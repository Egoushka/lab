# /// script
# requires-python = ">=3.11"
# dependencies = ["tiktoken"]
# ///
"""Experiment 01: agent views.

Asks the same 20 questions about a TOML manifest in four views (the file as it is, CSV, TOON, and a
projected view with only the fields the question needs) and scores correct answers per 1,000 tokens.
Questions and their true answers are generated from the data at run time, so no private data is committed.

  uv run bench.py tokens --data ~/Projects/repos.toml
  uv run bench.py run    --data ~/Projects/repos.toml --model haiku [--dry-run]
  uv run bench.py report runs/<file>.jsonl [--write]
"""
import argparse
import csv
import difflib
import io
import json
import re
import subprocess
import sys
import time
import tomllib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNS = HERE / "runs"
RESULTS = HERE / "results"
VIEWS = ["toml", "csv", "toon", "view"]
DEFAULT_REMOTE = "https://github.com/Egoushka/{name}.git"

SYSTEM = (
    "You answer one question about the data in the user's message. Use only that data. "
    'Reply with exactly one JSON object and nothing else: {"answer": X}. X is a number for "how many" '
    'questions, the exact value copied from the data for "what is" questions, or a JSON list of repo names '
    'for "list" questions ([] when none match). Repos are the [[repo]] entries or rows; nothing else counts.'
)


def load(path):
    raw = Path(path).expanduser().read_text()
    rows = json.loads(json.dumps(tomllib.loads(raw)["repo"], default=str))
    return raw, rows


def columns(rows):
    cols = []
    for r in rows:
        cols += [k for k in r if k not in cols]
    return cols


def cell(v):
    return "" if v is None else str(v).lower() if isinstance(v, bool) else str(v)


# ---- questions -------------------------------------------------------------------------------------------

def questions(rows):
    def pick(field, i):
        have = [r for r in rows if r.get(field) not in (None, "")]
        return have[i % len(have)]

    def names(pred):
        return [r["name"] for r in rows if pred(r)]

    def count(pred):
        return len(names(pred))

    def lookup(field, i):
        r = pick(field, i)
        return r["name"], cell(r[field])

    qs = [
        ("count", 'How many repos have status "active"?', ["status"], count(lambda r: r.get("status") == "active")),
        ("count", 'How many repos have kind "oss"?', ["kind"], count(lambda r: r.get("kind") == "oss")),
        ("count", 'How many repos have status "active" and platform "Money"?', ["status", "platform"],
         count(lambda r: r.get("status") == "active" and r.get("platform") == "Money")),
        ("count", "How many repos have sweep set to true?", ["sweep"], count(lambda r: r.get("sweep") is True)),
        ("count", 'How many repos have a path that starts with "personal/"?', ["path"],
         count(lambda r: str(r.get("path", "")).startswith("personal/"))),
        ("count", 'How many repos have status "active" and no platform?', ["status", "platform"],
         count(lambda r: r.get("status") == "active" and not r.get("platform"))),
    ]
    for field, i in [("check", 0), ("check", 3), ("stop", 1), ("note", 2), ("path", 10), ("platform", 5),
                     ("status", 20), ("readme", 7)]:
        name, value = lookup(field, i)
        qs.append(("lookup", f'What is the {field} of the repo named "{name}"?', [field], value))
    qs += [
        ("list", 'List the repos that have status "active" and no stop.', ["status", "stop"],
         names(lambda r: r.get("status") == "active" and not r.get("stop"))),
        ("list", 'List the repos with merge_policy "green".', ["merge_policy"],
         names(lambda r: r.get("merge_policy") == "green")),
        ("list", "List the repos whose remote is not on github.com.", ["remote"],
         names(lambda r: r.get("remote") and not r["remote"].startswith("https://github.com/"))),
        ("list", 'List the repos with status "parked" and platform "Phone".', ["status", "platform"],
         names(lambda r: r.get("status") == "parked" and r.get("platform") == "Phone")),
        ("list", 'List the repos with kind "sandbox".', ["kind"], names(lambda r: r.get("kind") == "sandbox")),
        ("list", "List the repos that have a due date.", ["due"], names(lambda r: r.get("due"))),
    ]
    return [dict(id=f"q{i:02d}", kind=k, text=t, fields=f, truth=a) for i, (k, t, f, a) in enumerate(qs, 1)]


# ---- views ---------------------------------------------------------------------------------------------

def to_csv(rows, cols):
    b = io.StringIO()
    w = csv.writer(b, lineterminator="\n")
    w.writerow(cols)
    for r in rows:
        w.writerow([cell(r.get(c)) for c in cols])
    return b.getvalue()


def to_toon(rows, cols):
    def q(v):
        s = cell(v)
        return json.dumps(s) if any(ch in s for ch in ',:"\n') or s != s.strip() else s
    lines = [f"repo[{len(rows)}]{{{','.join(cols)}}}:"]
    lines += ["  " + ",".join(q(r[c]) if c in r else "" for c in cols) for r in rows]
    return "\n".join(lines) + "\n"


def to_view(rows, fields):
    """Only the fields the question needs, and derivable values dropped."""
    cols = ["name"] + [f for f in fields if f != "name"]
    out = []
    if "remote" in cols:
        out.append(f"# an empty remote means {DEFAULT_REMOTE}; a repo with no remote at all shows '-'")
        rows = [{**r, "remote": "" if r.get("remote") == DEFAULT_REMOTE.format(name=r["name"])
                 else r.get("remote", "-")} for r in rows]
    return "\n".join(out + [to_csv(rows, cols)])


def render(view, raw, rows, q):
    if view == "toml":
        return raw
    if view == "csv":
        return to_csv(rows, columns(rows))
    if view == "toon":
        return to_toon(rows, columns(rows))
    return to_view(rows, q["fields"])


def prompt(view, text, q):
    return f'<data format="{view}">\n{text}</data>\n\nQuestion: {q["text"]}'


# ---- scoring -------------------------------------------------------------------------------------------

def norm(s):
    return re.sub(r"\s+", " ", str(s)).strip().strip('"').lower()


def score(q, answer):
    try:
        if q["kind"] == "count":
            return int(answer) == q["truth"]
        if q["kind"] == "lookup":
            return difflib.SequenceMatcher(None, norm(answer), norm(q["truth"])).ratio() >= 0.9
        return {norm(x) for x in answer} == {norm(x) for x in q["truth"]}
    except (TypeError, ValueError):
        return False


def parse(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        return json.loads(m.group(0))["answer"] if m else None
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


# ---- commands ------------------------------------------------------------------------------------------

def proxy_tokens():
    import tiktoken
    enc = tiktoken.get_encoding("o200k_base")
    return lambda s: len(enc.encode(s))


def cmd_tokens(a):
    raw, rows = load(a.data)
    qs, n = questions(rows), proxy_tokens()
    print(f"{len(rows)} repos, {len(qs)} questions; tokens are o200k_base (a proxy for Claude's tokenizer)")
    for v in VIEWS:
        t = [n(prompt(v, render(v, raw, rows, q), q)) for q in qs]
        print(f"  {v:5s} mean {sum(t) / len(t):7.0f}  total {sum(t):7d}")


def call(a, v, text, q):
    cmd = [a.claude, "-p", "--model", a.model, "--system-prompt", SYSTEM, "--tools", "", "--strict-mcp-config",
           "--setting-sources", "", "--no-session-persistence", "--output-format", "json"]
    t0 = time.time()
    p = subprocess.run(cmd, input=prompt(v, text, q), capture_output=True, text=True, timeout=300)
    try:
        out = json.loads(p.stdout)
    except json.JSONDecodeError:
        out = {"is_error": True, "result": (p.stdout + p.stderr)[-500:]}
    u = out.get("usage") or {}
    answer = parse(out.get("result"))
    return dict(q=q["id"], kind=q["kind"], view=v, models=sorted(out.get("modelUsage") or {}),
                ok=score(q, answer), answer=answer, truth=q["truth"],
                error=out.get("result") if out.get("is_error") else None,
                tokens=sum(u.get(k, 0) for k in ("input_tokens", "cache_creation_input_tokens",
                                                  "cache_read_input_tokens")),
                cost=out.get("total_cost_usd", 0), secs=round(time.time() - t0, 1))


def cmd_run(a):
    raw, rows = load(a.data)
    qs = questions(rows)
    jobs = [(v, render(v, raw, rows, q), q) for _ in range(a.repeat) for q in qs for v in a.views]
    if a.dry_run:
        n = proxy_tokens()
        total = sum(n(prompt(v, t, q)) for v, t, q in jobs)
        print(f"{len(jobs)} calls, about {total:,} input tokens (o200k proxy) before the system prompt")
        return
    RUNS.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = RUNS / f"{stamp}-{a.model}.jsonl"
    with ThreadPoolExecutor(a.jobs) as pool, path.open("w") as f:
        for i, rec in enumerate(pool.map(lambda j: call(a, *j), jobs), 1):
            f.write(json.dumps(rec) + "\n")
            f.flush()
            print(f"[{i}/{len(jobs)}] {rec['q']} {rec['view']:5s} {'ok' if rec['ok'] else 'MISS'}"
                  f"{'  error: ' + str(rec['error'])[:80] if rec['error'] else ''}", file=sys.stderr)
    print(path)
    report(path, write=False)


def report(path, write):
    recs = [json.loads(line) for line in Path(path).read_text().splitlines() if line]
    model = Path(path).stem.split("-", 1)[1]
    seen = sorted({m for r in recs for m in r.get("models") or ([r["model"]] if r.get("model") else [])})
    model += f" (calls used: {', '.join(seen)})" if seen else ""
    lines = [f"Run `{Path(path).name}`: {len(recs)} calls, model `{model}`, "
             f"cost ${sum(r['cost'] or 0 for r in recs):.2f}, errors {sum(1 for r in recs if r['error'])}.", "",
             "| View | Correct | Mean input tokens per call | Correct per 1k tokens | count | lookup | list |",
             "|---|---|---|---|---|---|---|"]
    for v in VIEWS:
        rs = [r for r in recs if r["view"] == v]
        if not rs:
            continue
        ok = sum(r["ok"] for r in rs)
        tok = sum(r["tokens"] for r in rs) / len(rs)
        by = {k: f"{sum(r['ok'] for r in rs if r['kind'] == k)}/{sum(1 for r in rs if r['kind'] == k)}"
              for k in ("count", "lookup", "list")}
        lines.append(f"| {v} | {ok}/{len(rs)} ({ok / len(rs):.0%}) | {tok:,.0f} | "
                     f"{1000 * ok / (tok * len(rs)) if tok else 0:.3f} | {by['count']} | {by['lookup']} | {by['list']} |")
    misses = sorted({(r["q"], r["view"]) for r in recs if not r["ok"]})
    lines += ["", "Misses (question, view): " + (", ".join(f"{q}/{v}" for q, v in misses) or "none")]
    text = "\n".join(lines) + "\n"
    print(text)
    if write:
        RESULTS.mkdir(exist_ok=True)
        out = RESULTS / f"{Path(path).stem}.md"
        out.write_text(text)
        print(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("tokens")
    t.add_argument("--data", required=True)
    r = sub.add_parser("run")
    r.add_argument("--data", required=True)
    r.add_argument("--model", default="haiku")
    r.add_argument("--views", nargs="+", default=VIEWS, choices=VIEWS)
    r.add_argument("--repeat", type=int, default=1)
    r.add_argument("--jobs", type=int, default=4)
    r.add_argument("--claude", default="claude")
    r.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("report")
    p.add_argument("run")
    p.add_argument("--write", action="store_true")
    a = ap.parse_args()
    {"tokens": cmd_tokens, "run": cmd_run, "report": lambda a: report(a.run, a.write)}[a.cmd](a)


if __name__ == "__main__":
    main()
