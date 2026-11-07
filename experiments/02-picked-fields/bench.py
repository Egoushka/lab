# /// script
# requires-python = ">=3.11"
# dependencies = ["tiktoken"]
# ///
"""Experiment 02: picked fields.

01 gave the projected view the fields each question needs. Here the model picks them: call 1 sees the question
and the field names and returns a field list, the harness builds the view from it, call 2 answers from that
view. Both calls' tokens are counted and compared with the whole file and with 01's hand-fed view.
Questions, views, scoring and parsing are imported from ../01-agent-views/bench.py.

  uv run bench.py run    --data ~/Projects/repos.toml --model haiku --repeat 3 [--dry-run]
  uv run bench.py report runs/<file>.jsonl [--write]
"""
import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNS = HERE / "runs"
RESULTS = HERE / "results"
VIEWS = ["toml", "view", "picked"]

CHECK_POINTS, CHECK_TOKENS = 2, 0.40   # README: within 2 points of toml, under 40% of its tokens
STOP_POINTS, STOP_TOKENS = 5, 0.60     # README: more than 5 points behind toml, or 60% of its tokens or more

PICK_SYSTEM = (
    "You choose columns. The user gives the column names of a table of repos and a question about the table. "
    "Name the columns that must be read to answer the question, and no others. The column `name` is always "
    'included. Reply with exactly one JSON object and nothing else: {"fields": ["column", ...]}.'
)


def _bench01():
    spec = importlib.util.spec_from_file_location("bench01", HERE.parent / "01-agent-views" / "bench.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


b1 = _bench01()


# ---- calls ---------------------------------------------------------------------------------------------

def ask(a, system, user):
    cmd = [a.claude, "-p", "--model", a.model, "--system-prompt", system, "--tools", "", "--strict-mcp-config",
           "--setting-sources", "", "--no-session-persistence", "--output-format", "json"]
    t0 = time.time()
    try:
        p = subprocess.run(cmd, input=user, capture_output=True, text=True, timeout=300)
        out = json.loads(p.stdout)
    except (json.JSONDecodeError, subprocess.TimeoutExpired) as e:
        out = {"is_error": True, "result": f"{type(e).__name__}: {e}"[-500:]}
    u = out.get("usage") or {}
    return dict(text=out.get("result"), error=str(out.get("result")) if out.get("is_error") else None,
                models=sorted(out.get("modelUsage") or {}),
                tokens=sum(u.get(k, 0) for k in ("input_tokens", "cache_creation_input_tokens",
                                                  "cache_read_input_tokens")),
                out_tokens=u.get("output_tokens", 0), cost=out.get("total_cost_usd", 0),
                secs=round(time.time() - t0, 1))


def parse_pick(text, cols):
    """The picked column names that exist, and how many names did not. None when the reply is no field list."""
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        raw = json.loads(m.group(0))["fields"] if m else None
    except (json.JSONDecodeError, KeyError, TypeError):
        raw = None
    if not isinstance(raw, list):
        return None, 0
    known = {c.lower(): c for c in cols}
    picked, unknown = [], 0
    for f in raw:
        c = known.get(str(f).strip().lower())
        if c is None:
            unknown += 1
        elif c not in picked:
            picked.append(c)
    return picked, unknown


def job(a, raw, rows, cols, q, v):
    pick = pick_call = None
    if v == "picked":
        pick_call = ask(a, PICK_SYSTEM, f"Columns: {', '.join(cols)}\n\nQuestion: {q['text']}")
        fields, unknown = parse_pick(pick_call["text"], cols)
        picked = fields or []   # a reply that is no field list goes on as an empty pick: `name` only
        pick = dict(fields=picked, parsed=fields is not None, unknown=unknown, needed=len(q["fields"]),
                    sufficient=set(q["fields"]) <= set(picked),
                    extra=len(set(picked) - set(q["fields"]) - {"name"}))
        if pick_call["error"]:
            calls, answer_call = [pick_call], None
        else:
            answer_call = ask(a, b1.SYSTEM, b1.prompt("view", b1.to_view(rows, picked), q))
            calls = [pick_call, answer_call]
    else:
        answer_call = ask(a, b1.SYSTEM, b1.prompt(v, b1.render(v, raw, rows, q), q))
        calls = [answer_call]
    answer = b1.parse(answer_call["text"]) if answer_call else None
    return dict(q=q["id"], kind=q["kind"], view=v, models=sorted({m for c in calls for m in c["models"]}),
                ok=b1.score(q, answer), answer=answer, truth=q["truth"],
                error=next((c["error"] for c in calls if c["error"]), None),
                tokens=sum(c["tokens"] for c in calls), out_tokens=sum(c["out_tokens"] for c in calls),
                pick_tokens=pick_call["tokens"] if pick_call else None,
                pick_out=pick_call["out_tokens"] if pick_call else None,
                answer_tokens=answer_call["tokens"] if answer_call else None,
                answer_out=answer_call["out_tokens"] if answer_call else None,
                cost=sum(c["cost"] or 0 for c in calls), secs=round(sum(c["secs"] for c in calls), 1), pick=pick)


# ---- commands ------------------------------------------------------------------------------------------

def cmd_run(a):
    raw, rows = b1.load(a.data)
    cols, qs = b1.columns(rows), b1.questions(rows)
    jobs = [(q, v) for _ in range(a.repeat) for q in qs for v in a.views]
    if a.dry_run:
        n = b1.proxy_tokens()
        total = 0
        for q, v in jobs:
            if v == "picked":
                total += n(f"{PICK_SYSTEM}\nColumns: {', '.join(cols)}\n\nQuestion: {q['text']}")
                total += n(b1.prompt("view", b1.to_view(rows, q["fields"]), q))
            else:
                total += n(b1.prompt(v, b1.render(v, raw, rows, q), q))
        calls = sum(2 if v == "picked" else 1 for _, v in jobs)
        print(f"{calls} calls, about {total:,} input tokens (o200k proxy; picked counted with the true fields)")
        return
    RUNS.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = RUNS / f"{stamp}-{a.model}.jsonl"
    meta = dict(date=stamp[:8], model=a.model, repos=len(rows), fields=len(cols), questions=len(qs),
                passes=a.repeat, data_sha256=hashlib.sha256(raw.encode()).hexdigest()[:8])
    path.with_suffix(".meta.json").write_text(json.dumps(meta))
    with ThreadPoolExecutor(a.jobs) as pool, path.open("w") as f:
        for i, rec in enumerate(pool.map(lambda j: job(a, raw, rows, cols, *j), jobs), 1):
            f.write(json.dumps(rec) + "\n")
            f.flush()
            print(f"[{i}/{len(jobs)}] {rec['q']} {rec['view']:6s} {'ok' if rec['ok'] else 'MISS'}"
                  f"{'  error: ' + str(rec['error'])[:80] if rec['error'] else ''}", file=sys.stderr)
    print(path)
    report(path, write=False)


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0


def report(path, write):
    path = Path(path)
    recs = [json.loads(line) for line in path.read_text().splitlines() if line]
    meta_path = path.with_suffix(".meta.json")
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    seen = sorted({m for r in recs for m in r.get("models") or []})
    lines = [f"Run `{path.name}`: {len(recs)} questions asked, model `{path.stem.split('-', 1)[1]}`"
             f"{' (calls used: ' + ', '.join(seen) + ')' if seen else ''}, "
             f"cost ${sum(r['cost'] or 0 for r in recs):.2f}, errors {sum(1 for r in recs if r['error'])}.",
             f"Data: {meta.get('repos', '?')} repos, {meta.get('fields', '?')} fields, "
             f"{meta.get('questions', '?')} questions × {meta.get('passes', '?')} passes, "
             f"sha256 {meta.get('data_sha256', '?')}.", "",
             "| View | Correct | Mean input tokens per question | vs toml | Correct per 1k tokens | count | lookup | list "
             "| Mean seconds |", "|---|---|---|---|---|---|---|---|---|"]
    by = {v: [r for r in recs if r["view"] == v] for v in VIEWS}
    acc = {v: mean(r["ok"] for r in rs) for v, rs in by.items()}
    tok = {v: mean(r["tokens"] for r in rs) for v, rs in by.items()}
    for v in VIEWS:
        rs = by[v]
        if not rs:
            continue
        ok = sum(r["ok"] for r in rs)
        kinds = {k: f"{sum(r['ok'] for r in rs if r['kind'] == k)}/{sum(1 for r in rs if r['kind'] == k)}"
                 for k in ("count", "lookup", "list")}
        vs = f"{tok[v] / tok['toml']:.0%}" if tok.get("toml") else "n/a"
        lines.append(f"| {v} | {ok}/{len(rs)} ({acc[v]:.0%}) | {tok[v]:,.0f} | {vs} | "
                     f"{1000 * ok / (tok[v] * len(rs)) if tok[v] else 0:.3f} | {kinds['count']} | {kinds['lookup']} | "
                     f"{kinds['list']} | {mean(r['secs'] for r in rs):.1f} |")
    pk = by["picked"]
    if pk:
        good = [r for r in pk if r["pick"]["sufficient"]]
        bad = [r for r in pk if not r["pick"]["sufficient"]]
        exact = [r for r in pk if r["pick"]["sufficient"] and r["pick"]["extra"] == 0]
        lines += ["", "**Picked, by call** (mean input tokens, mean output tokens)", "",
                  "| Call | Input tokens | Output tokens |", "|---|---|---|",
                  f"| 1 · pick | {mean(r['pick_tokens'] or 0 for r in pk):,.0f} | "
                  f"{mean(r['pick_out'] or 0 for r in pk):.0f} |",
                  f"| 2 · answer | {mean(r['answer_tokens'] or 0 for r in pk):,.0f} | "
                  f"{mean(r['answer_out'] or 0 for r in pk):.0f} |",
                  "", "**The pick**", "",
                  f"- Covers every needed field: {len(good)}/{len(pk)} ({len(good) / len(pk):.0%}); "
                  f"exactly the needed fields: {len(exact)}/{len(pk)}.",
                  f"- Fields picked per question (name aside): {mean(len(set(r['pick']['fields']) - {'name'}) for r in pk):.1f}, "
                  f"needed {mean(r['pick']['needed'] for r in pk):.1f}, extra {mean(r['pick']['extra'] for r in pk):.2f}.",
                  f"- Answer correct when the pick covered the need: {sum(r['ok'] for r in good)}/{len(good)}; "
                  f"when it did not: {sum(r['ok'] for r in bad)}/{len(bad)}.",
                  f"- Replies that were no field list: {sum(1 for r in pk if not r['pick']['parsed'])}; "
                  f"names that are not fields: {sum(r['pick']['unknown'] for r in pk)}."]
        short = {}
        for r in bad:
            short[r["q"]] = short.get(r["q"], 0) + 1
        lines.append("- Questions whose pick missed a needed field (× passes): "
                     + (", ".join(f"{q} ×{n}" for q, n in sorted(short.items())) or "none") + ".")
    if tok.get("toml") and pk:
        lost = 100 * (acc["toml"] - acc["picked"])
        share = tok["picked"] / tok["toml"]
        check = lost <= CHECK_POINTS + 1e-9 and share < CHECK_TOKENS
        stop = lost > STOP_POINTS + 1e-9 or share >= STOP_TOKENS
        lines += ["", f"**Verdict.** `picked` is {lost:+.1f} points behind `toml` and uses {share:.0%} of its tokens "
                  f"(`view`, hand-fed: {tok['view'] / tok['toml']:.0%}). "
                  f"Check (≤ {CHECK_POINTS} points behind, < {CHECK_TOKENS:.0%} of tokens): {'passed' if check else 'not met'}. "
                  f"Stop (> {STOP_POINTS} points behind, or ≥ {STOP_TOKENS:.0%} of tokens): "
                  f"{'HIT' if stop else 'not hit'}."]
    misses = sorted({(r["q"], r["view"]) for r in recs if not r["ok"]})
    lines += ["", "Misses (question, view): " + (", ".join(f"{q}/{v}" for q, v in misses) or "none")]
    text = "\n".join(lines) + "\n"
    print(text)
    if write:
        RESULTS.mkdir(exist_ok=True)
        out = RESULTS / f"{path.stem}.md"
        out.write_text(text)
        print(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
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
    {"run": cmd_run, "report": lambda a: report(a.run, a.write)}[a.cmd](a)


if __name__ == "__main__":
    main()
