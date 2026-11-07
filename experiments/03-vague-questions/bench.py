# /// script
# requires-python = ">=3.11"
# dependencies = ["tiktoken"]
# ///
"""Experiment 03: vague questions.

02 gave the model questions that name their fields. Here the same 20 questions are reworded so that none names a
column; the model still picks the fields in call 1, the harness builds the view, call 2 answers. The calls, the
pick parser and the two-call job are imported from ../02-picked-fields/bench.py (and through it 01's).

  uv run bench.py check  --data ~/Projects/repos.toml
  uv run bench.py run    --data ~/Projects/repos.toml --model haiku --repeat 3 [--dry-run]
  uv run bench.py report runs/<file>.jsonl [--write]
"""
import argparse
import hashlib
import importlib.util
import json
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNS = HERE / "runs"
RESULTS = HERE / "results"
VIEWS = ["toml", "view", "picked"]

CHECK_COVER, CHECK_POINTS, CHECK_TOKENS = 0.90, 5, 0.40   # README: covers 90% of calls, within 5 points, under 40%
STOP_COVER, STOP_POINTS, STOP_TOKENS = 0.75, 10, 0.60     # README: under 75%, more than 10 points behind, 60% or more
TOML_VALID = 0.90                                         # README: below this the wording, not the pick, is suspect


def _bench02():
    spec = importlib.util.spec_from_file_location("bench02", HERE.parent / "02-picked-fields" / "bench.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


b2 = _bench02()
b1 = b2.b1


# ---- questions -------------------------------------------------------------------------------------------
# Fixed before the first model call. A change is a new run (README). No text here may contain a column name;
# `check` enforces it. "area" is the everyday word for platform, "give up on" for stop, and so on.

VAGUE = {
    "q01": 'How many repos are marked "active"?',
    "q02": 'How many repos are classed as "oss"?',
    "q03": 'How many repos are "active" and belong to the "Money" area?',
    "q04": "How many repos does the cleanup job cover?",
    "q05": 'How many repos live under the folder "personal/"?',
    "q06": 'How many "active" repos belong to no area?',
    "q15": 'List the "active" repos that have no give-up condition.',
    "q16": 'List the repos whose pull requests merge on "green".',
    "q17": "List the repos that are hosted somewhere other than github.com.",
    "q18": 'List the "parked" repos in the "Phone" area.',
    "q19": 'List the repos classed as "sandbox".',
    "q20": "List the repos that have a deadline.",
}
LOOKUP = {   # by the one field the question needs; {n} is the repo name
    "check": 'What counts as success for the repo named "{n}"?',
    "stop": 'What would make us give up on the repo named "{n}"?',
    "note": 'What comment is attached to the repo named "{n}"?',
    "path": 'Where does the repo named "{n}" live, relative to the workspace root?',
    "platform": 'Which area does the repo named "{n}" belong to?',
    "status": 'What lifecycle state is the repo named "{n}" in?',
    "readme": 'What documentation template applies to the repo named "{n}"?',
}


def vague_questions(rows):
    """01's questions with the same id, kind, needed fields and true answer, and a wording that names no column."""
    out = []
    for q in b1.questions(rows):
        if q["kind"] == "lookup":
            name = re.search(r'named "(.*)"\?$', q["text"]).group(1)
            text = LOOKUP[q["fields"][0]].format(n=name)
        else:
            text = VAGUE[q["id"]]
        out.append({**q, "text": text})
    return out


def leaks(text, cols):
    """Columns the text names as a word (also with an s, es, ed or ing ending), quoted values set aside.
    `name` is skipped: every view includes it, so naming it gives nothing away."""
    bare = re.sub(r'"[^"]*"', " ", text.lower())
    return [c for c in cols if c != "name"
            and any(re.search(rf"\b{re.escape(c.replace('_', ' '))}{e}\b", bare.replace("_", " "))
                    for e in ("", "s", "es", "ed", "ing"))]


def problems(rows):
    cols, old, new = b1.columns(rows), b1.questions(rows), vague_questions(rows)
    found = [] if len(old) == len(new) == 20 else [f"{len(old)} questions in 01, {len(new)} reworded, expected 20"]
    for o, n in zip(old, new):
        found += [f"{n['id']}: {k} differs from 01" for k in ("id", "kind", "fields", "truth") if o[k] != n[k]]
        if o["text"] == n["text"]:
            found.append(f"{n['id']}: wording unchanged")
        if leaks(n["text"], cols):
            found.append(f"{n['id']}: names {', '.join(leaks(n['text'], cols))}")
        if not leaks(o["text"], cols):
            found.append(f"{n['id']}: the detector does not see a column in 01's wording, so it cannot be trusted")
    return found


def cmd_check(a):
    raw, rows = b1.load(a.data)
    found = problems(rows)
    if found:
        sys.exit("machine checks failed:\n  " + "\n  ".join(found))
    print(f"ok: {len(vague_questions(rows))} questions keep 01's id, kind, needed fields and true answer; none names a "
          f"column; the detector flags all {len(vague_questions(rows))} of 01's wordings")


# ---- run -----------------------------------------------------------------------------------------------

def job(a, raw, rows, cols, q, v):
    rec = b2.job(a, raw, rows, cols, q, v)
    if rec["pick"]:
        rec["pick"]["needed_fields"] = q["fields"]   # which fields were needed, for the report
    return rec


def cmd_run(a):
    raw, rows = b1.load(a.data)
    found = problems(rows)
    if found:
        sys.exit("machine checks failed:\n  " + "\n  ".join(found))
    cols, qs = b1.columns(rows), vague_questions(rows)
    jobs = [(q, v) for _ in range(a.repeat) for q in qs for v in a.views]
    if a.dry_run:
        n = b1.proxy_tokens()
        total = 0
        for q, v in jobs:
            if v == "picked":
                total += n(f"{b2.PICK_SYSTEM}\nColumns: {', '.join(cols)}\n\nQuestion: {q['text']}")
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


# ---- report --------------------------------------------------------------------------------------------

def fields(names):
    return ", ".join(f"`{n}`" for n in names) or "nothing"


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
    acc = {v: b2.mean(r["ok"] for r in rs) for v, rs in by.items()}
    tok = {v: b2.mean(r["tokens"] for r in rs) for v, rs in by.items()}
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
                     f"{kinds['list']} | {b2.mean(r['secs'] for r in rs):.1f} |")
    pk = by["picked"]
    cover = 0
    if pk:
        good = [r for r in pk if r["pick"]["sufficient"]]
        bad = [r for r in pk if not r["pick"]["sufficient"]]
        cover = len(good) / len(pk)
        need, miss, extras = Counter(), Counter(), Counter()
        for r in pk:
            p = r["pick"]
            for f in p["needed_fields"]:
                need[f] += 1
                miss[f] += f not in p["fields"]
            extras.update(set(p["fields"]) - set(p["needed_fields"]) - {"name"})
        with_extra = [r for r in pk if r["pick"]["extra"]]
        lines += ["", "**Picked, by call** (mean input tokens, mean output tokens)", "",
                  "| Call | Input tokens | Output tokens |", "|---|---|---|",
                  f"| 1 · pick | {b2.mean(r['pick_tokens'] or 0 for r in pk):,.0f} | "
                  f"{b2.mean(r['pick_out'] or 0 for r in pk):.0f} |",
                  f"| 2 · answer | {b2.mean(r['answer_tokens'] or 0 for r in pk):,.0f} | "
                  f"{b2.mean(r['answer_out'] or 0 for r in pk):.0f} |",
                  "", "**The pick**", "",
                  f"- Covers every needed field: {len(good)}/{len(pk)} ({cover:.0%}); field by field: "
                  f"{sum(need.values()) - sum(miss.values())}/{sum(need.values())} needed fields found.",
                  f"- Needed fields the pick missed (missed/needed): "
                  + (", ".join(f"`{f}` {n}/{need[f]}" for f, n in miss.most_common() if n) or "none") + ".",
                  f"- Extra fields (picked, not needed, `name` aside): {len(with_extra)}/{len(pk)} picks "
                  f"({len(with_extra) / len(pk):.0%}), {b2.mean(r['pick']['extra'] for r in pk):.2f} per pick. "
                  + ("Most often: " + ", ".join(f"`{f}` ×{n}" for f, n in extras.most_common(5)) + "."
                     if extras else "None."),
                  f"- Answer correct when the pick covered the need: {sum(r['ok'] for r in good)}/{len(good)}; "
                  f"when it did not: {sum(r['ok'] for r in bad)}/{len(bad)}.",
                  f"- Replies that were no field list: {sum(1 for r in pk if not r['pick']['parsed'])}; "
                  f"names that are not columns: {sum(r['pick']['unknown'] for r in pk)}."]
        per = {}
        for r in bad:
            p = r["pick"]
            gap = (tuple(f for f in p["needed_fields"] if f not in p["fields"]),
                   tuple(sorted(set(p["fields"]) - set(p["needed_fields"]) - {"name"})))
            per.setdefault(r["q"], Counter())[gap] += 1
        lines.append("- Picks that missed a field, by question (× passes):"
                     + ("" if per else " none."))
        for q in sorted(per):
            for (m, e), n in per[q].items():
                lines.append(f"  - {q} ×{n}: missed {fields(m)}; picked {fields(e)} beyond the need.")
    if tok.get("toml") and pk:
        lost = 100 * (acc["toml"] - acc["picked"])
        share = tok["picked"] / tok["toml"]
        c_cov, c_acc, c_tok = cover >= CHECK_COVER - 1e-9, lost <= CHECK_POINTS + 1e-9, share < CHECK_TOKENS
        s_cov, s_acc, s_tok = cover < STOP_COVER - 1e-9, lost > STOP_POINTS + 1e-9, share >= STOP_TOKENS
        yes = lambda b: "yes" if b else "no"
        hit = [n for n, b in (("coverage", s_cov), ("accuracy", s_acc), ("tokens", s_tok)) if b]
        lines += ["", f"**Verdict.** Check {'met' if c_cov and c_acc and c_tok else 'not met'}: "
                  f"coverage {cover:.0%} (≥ {CHECK_COVER:.0%}) {yes(c_cov)}; "
                  f"`picked` {lost:+.1f} points behind `toml` (≤ {CHECK_POINTS}) {yes(c_acc)}; "
                  f"{share:.0%} of `toml`'s tokens (< {CHECK_TOKENS:.0%}) {yes(c_tok)}. "
                  f"Stop {'HIT (' + ', '.join(hit) + ')' if hit else 'not hit'} "
                  f"(coverage < {STOP_COVER:.0%}, > {STOP_POINTS} points behind, ≥ {STOP_TOKENS:.0%} of tokens). "
                  f"`view`, hand-fed, is {acc['view']:.0%} at {tok['view'] / tok['toml']:.0%} of the tokens.",
                  f"Control: `toml` scored {acc['toml']:.0%}; " + (
                      "the reworded questions can be answered from the whole file."
                      if acc["toml"] >= TOML_VALID - 1e-9 else
                      f"below {TOML_VALID:.0%}, so the wording is ambiguous even with the whole file and this run "
                      "does not test the pick.")]
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
    c = sub.add_parser("check")
    c.add_argument("--data", required=True)
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
    {"check": cmd_check, "run": cmd_run, "report": lambda a: report(a.run, a.write)}[a.cmd](a)


if __name__ == "__main__":
    main()
