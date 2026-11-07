# /// script
# requires-python = ">=3.11"
# dependencies = ["tiktoken"]
# ///
"""Experiment 04: value hints.

03 was killed because a names-only pick missed `platform` when the question said "area". Here call 1 also gets the
distinct values of six few-valued columns (no repo names, no free text). Everything else is 03's: the 20 reworded
questions, the machine checks, the two-call job (and through it 02's `ask`, `parse_pick` and 01's views and scoring).
Only the pick prompt and the report are new.

  uv run bench.py check  --data ~/Projects/repos.toml
  uv run bench.py run    --data ~/Projects/repos.toml --model haiku --repeat 3 [--dry-run]
  uv run bench.py report runs/<file>.jsonl [--write]
"""
import argparse
import hashlib
import importlib.util
import json
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNS = HERE / "runs"
RESULTS = HERE / "results"
VIEWS = ["toml", "view", "picked"]

HINT_COLUMNS = ["status", "kind", "platform", "readme", "merge_policy", "sweep"]
FREE_TEXT = ["name", "path", "remote", "note", "check", "stop", "status_note"]
MAX_VALUES, MAX_CHARS, MAX_WORDS = 12, 24, 2
KNOWN_NAME_COLLISION = {("readme", "research")}   # a documentation template that is also a repo name (README)

CHECK_COVER, CHECK_POINTS, CHECK_TOKENS, CHECK_CALL1 = 0.90, 5, 0.40, 1500   # README check
STOP_COVER, STOP_POINTS, STOP_CALL1 = 0.75, 10, 1800                          # README stop
TOML_VALID = 0.90                                                              # below it the wording is suspect

# From 03's summary (results/2026-11-07-summary.md): the run this one is compared with.
B03_MISSED = {"q03": 3, "q06": 3, "q12": 3}   # uncovered picks per question; every other question 3 of 3 covered
B03 = dict(covered=51, picks=60, call1_tokens=1329, picked_ok=47, toml_ok=57)


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


b3 = _load(HERE.parent / "03-vague-questions" / "bench.py", "bench03")
b2, b1 = b3.b2, b3.b1


# ---- the pick prompt with value lists --------------------------------------------------------------------

ORIG_PICK_SYSTEM = b2.PICK_SYSTEM
HINT_SYSTEM = b2.PICK_SYSTEM.replace(
    "Name the columns that must be read",
    "For columns that have few distinct values, the user also lists all their values. "
    "Name the columns that must be read", 1)
assert HINT_SYSTEM != b2.PICK_SYSTEM, "02's pick prompt changed; fix the sentence this experiment adds"


def values(rows, col):
    seen = {b1.cell(r[col]) for r in rows if r.get(col) not in (None, "")}
    return sorted(seen)


def hint_block(rows):
    return ("Columns with few distinct values, with all their values:\n"
            + "\n".join(f"{c}: {' | '.join(values(rows, c))}" for c in HINT_COLUMNS))


def pick_user(cols, block, question):
    return f"Columns: {', '.join(cols)}\n{block}\n\nQuestion: {question}"


ORIG_ASK = b2.ask


def install(rows, orig=None):
    """Make 02's `job` (called by 03's) use the new system prompt and send the lists in call 1.
    Returns a counter of pick calls that carried the lists."""
    block, orig, sent = hint_block(rows), orig or ORIG_ASK, Counter()

    def ask(a, system, user):
        if system == HINT_SYSTEM:
            head, sep, tail = user.partition("\n\nQuestion: ")
            if not sep or "\nColumns with few" in head:
                raise RuntimeError("unexpected pick prompt shape; the lists were not added")
            user = f"{head}\n{block}{sep}{tail}"
            sent["pick"] += 1
        return orig(a, system, user)

    b2.PICK_SYSTEM = HINT_SYSTEM
    b2.ask = ask
    return sent


def probe(rows, cols):
    """Before any model call: the pick call must differ from 03's and carry every list, and an answer call must not."""
    got = []
    install(rows, orig=lambda a, system, user: got.append((system, user)) or {})
    b2.ask(None, b2.PICK_SYSTEM, f"Columns: {', '.join(cols)}\n\nQuestion: Q")
    b2.ask(None, b1.SYSTEM, "data and question")
    system, user = got[0]
    if (system == ORIG_PICK_SYSTEM or user != pick_user(cols, hint_block(rows), "Q")
            or got[1] != (b1.SYSTEM, "data and question")):
        sys.exit("guard: the pick prompt is 03's or the answer prompt changed; no model call made")


# ---- machine checks ----------------------------------------------------------------------------------------

def parse_block(block):
    """(column, [values]) pairs read back from the text the model will see."""
    lines = block.splitlines()[1:]
    return [(l.split(": ", 1)[0], l.split(": ", 1)[1].split(" | ")) for l in lines]


def hint_problems(rows):
    """The lists, as sent, hold only values of the six columns: no repo name, no free text."""
    found, cols = [], b1.columns(rows)
    names = {r["name"].lower() for r in rows}
    free = {c: {b1.cell(r[c]).lower() for r in rows if r.get(c) not in (None, "")}
            for c in FREE_TEXT if c != "name"}
    parsed = parse_block(hint_block(rows))
    if [c for c, _ in parsed] != HINT_COLUMNS:
        found.append(f"the lists cover {[c for c, _ in parsed]}, expected {HINT_COLUMNS}")
    for c, vs in parsed:
        if c not in cols:
            found.append(f"{c}: not a column")
        if not 1 <= len(vs) <= MAX_VALUES:
            found.append(f"{c}: {len(vs)} distinct values, expected 1 to {MAX_VALUES}")
        for v in vs:
            if len(v) > MAX_CHARS or len(v.split()) > MAX_WORDS:
                found.append(f"{c}: a value is over {MAX_CHARS} characters or {MAX_WORDS} words ({len(v)} characters)")
            if v.lower() in names and (c, v) not in KNOWN_NAME_COLLISION:
                found.append(f"{c}: value {v!r} is a repo name")
            for f, fv in free.items():
                if v.lower() in fv:
                    found.append(f"{c}: value {v!r} also appears in the free-text column {f}")
    return found


def few_valued_left_out(rows):
    return [c for c in b1.columns(rows) if c not in HINT_COLUMNS and 0 < len(values(rows, c)) <= MAX_VALUES]


def problems(rows):
    return b3.problems(rows) + hint_problems(rows)


def cmd_check(a):
    raw, rows = b1.load(a.data)
    found = problems(rows)
    if found:
        sys.exit("machine checks failed:\n  " + "\n  ".join(found))
    sizes = ", ".join(f"{c} {len(values(rows, c))}" for c in HINT_COLUMNS)
    print(f"ok: 03's checks pass (20 questions keep 01's id, kind, needed fields and true answer; none names a column); "
          f"the value lists come from {len(HINT_COLUMNS)} columns ({sizes} values), hold no repo name beyond the one "
          f"named exception and no free text. Other columns with at most {MAX_VALUES} values, left out: "
          f"{', '.join(few_valued_left_out(rows)) or 'none'}.")


# ---- run -----------------------------------------------------------------------------------------------

def cmd_run(a):
    raw, rows = b1.load(a.data)
    found = problems(rows)
    if found:
        sys.exit("machine checks failed:\n  " + "\n  ".join(found))
    cols, qs = b1.columns(rows), b3.vague_questions(rows)
    jobs = [(q, v) for _ in range(a.repeat) for q in qs for v in a.views]
    block = hint_block(rows)
    if a.dry_run:
        n = b1.proxy_tokens()
        total = pick1 = npick = 0
        for q, v in jobs:
            if v == "picked":
                npick += 1
                c1 = n(f"{HINT_SYSTEM}\n{pick_user(cols, block, q['text'])}")
                pick1 += c1
                total += c1
                total += n(b1.prompt("view", b1.to_view(rows, q["fields"]), q))
            else:
                total += n(b1.prompt(v, b1.render(v, raw, rows, q), q))
        calls = sum(2 if v == "picked" else 1 for _, v in jobs)
        without = sum(n(f"{b2.PICK_SYSTEM}\nColumns: {', '.join(cols)}\n\nQuestion: {q['text']}")
                      for q, v in jobs if v == "picked")
        print(f"{calls} calls, about {total:,} input tokens (o200k proxy; picked counted with the true fields). "
              f"Call 1 with the lists: {pick1 / max(npick, 1):,.0f} tokens on average, "
              f"{(pick1 - without) / max(npick, 1):+.0f} against 03's prompt.")
        return
    probe(rows, cols)
    sent = install(rows)
    RUNS.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = RUNS / f"{stamp}-{a.model}.jsonl"
    meta = dict(date=stamp[:8], model=a.model, repos=len(rows), fields=len(cols), questions=len(qs),
                passes=a.repeat, data_sha256=hashlib.sha256(raw.encode()).hexdigest()[:8],
                hint_columns=HINT_COLUMNS, hint_values=sum(len(values(rows, c)) for c in HINT_COLUMNS),
                pick_prompt_sha256=hashlib.sha256((HINT_SYSTEM + block).encode()).hexdigest()[:8])
    path.with_suffix(".meta.json").write_text(json.dumps(meta))
    with ThreadPoolExecutor(a.jobs) as pool, path.open("w") as f:
        for i, rec in enumerate(pool.map(lambda j: b3.job(a, raw, rows, cols, *j), jobs), 1):
            f.write(json.dumps(rec) + "\n")
            f.flush()
            print(f"[{i}/{len(jobs)}] {rec['q']} {rec['view']:6s} {'ok' if rec['ok'] else 'MISS'}"
                  f"{'  error: ' + str(rec['error'])[:80] if rec['error'] else ''}", file=sys.stderr)
    expected = sum(1 for _, v in jobs if v == "picked")
    if sent["pick"] != expected:
        sys.exit(f"guard: {sent['pick']} pick calls carried the lists, expected {expected}; do not use {path}")
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
             f"sha256 {meta.get('data_sha256', '?')}. Value lists: {len(meta.get('hint_columns', []))} columns, "
             f"{meta.get('hint_values', '?')} values, pick prompt sha256 {meta.get('pick_prompt_sha256', '?')}.", "",
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
    cover = call1 = 0
    if pk:
        good = [r for r in pk if r["pick"]["sufficient"]]
        bad = [r for r in pk if not r["pick"]["sufficient"]]
        cover = len(good) / len(pk)
        call1 = b2.mean(r["pick_tokens"] or 0 for r in pk)
        need, miss, extras = Counter(), Counter(), Counter()
        for r in pk:
            p = r["pick"]
            for f in p["needed_fields"]:
                need[f] += 1
                miss[f] += f not in p["fields"]
            extras.update(set(p["fields"]) - set(p["needed_fields"]) - {"name"})
        with_extra = [r for r in pk if r["pick"]["extra"]]
        lines += ["", "**Picked, by call** (mean input tokens, mean output tokens; 03 in brackets)", "",
                  "| Call | Input tokens | Output tokens |", "|---|---|---|",
                  f"| 1 · pick | {call1:,.0f} [{B03['call1_tokens']:,}] | {b2.mean(r['pick_out'] or 0 for r in pk):.0f} [121] |",
                  f"| 2 · answer | {b2.mean(r['answer_tokens'] or 0 for r in pk):,.0f} [2,687] | "
                  f"{b2.mean(r['answer_out'] or 0 for r in pk):.0f} [375] |",
                  "", "**The pick**", "",
                  f"- Covers every needed field: {len(good)}/{len(pk)} ({cover:.0%}); 03: "
                  f"{B03['covered']}/{B03['picks']} ({B03['covered'] / B03['picks']:.0%}). Field by field: "
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
        covered = Counter(r["q"] for r in good)
        total = Counter(r["q"] for r in pk)
        diff = [q for q in sorted(total) if covered[q] != total[q] or B03_MISSED.get(q)]
        lines.append("- Coverage by question, 04 against 03 (covered picks of " +
                     f"{max(total.values())}); only questions where either run missed:" + ("" if diff else " none."))
        for q in diff:
            lines.append(f"  - {q}: {covered[q]}/{total[q]} against {total[q] - B03_MISSED.get(q, 0)}/{total[q]}.")
        per = {}
        for r in bad:
            p = r["pick"]
            gap = (tuple(f for f in p["needed_fields"] if f not in p["fields"]),
                   tuple(sorted(set(p["fields"]) - set(p["needed_fields"]) - {"name"})))
            per.setdefault(r["q"], Counter())[gap] += 1
        lines.append("- Picks that missed a field, by question (× passes):" + ("" if per else " none."))
        for q in sorted(per):
            for (m, e), n in per[q].items():
                lines.append(f"  - {q} ×{n}: missed {fields(m)}; picked {fields(e)} beyond the need.")
    if tok.get("toml") and pk:
        lost = 100 * (acc["toml"] - acc["picked"])
        share = tok["picked"] / tok["toml"]
        c_cov, c_acc, c_tok, c_c1 = (cover >= CHECK_COVER - 1e-9, lost <= CHECK_POINTS + 1e-9,
                                     share < CHECK_TOKENS, call1 < CHECK_CALL1)
        s_cov, s_acc, s_c1 = cover < STOP_COVER - 1e-9, lost > STOP_POINTS + 1e-9, call1 > STOP_CALL1
        yes = lambda b: "yes" if b else "no"
        hit = [n for n, b in (("coverage", s_cov), ("accuracy", s_acc), ("call 1 tokens", s_c1)) if b]
        met = c_cov and c_acc and c_tok and c_c1
        lines += ["", f"**Verdict.** Check {'met' if met else 'not met'}: "
                  f"coverage {cover:.0%} (≥ {CHECK_COVER:.0%}) {yes(c_cov)}; "
                  f"`picked` {lost:+.1f} points behind `toml` (≤ {CHECK_POINTS}) {yes(c_acc)}; "
                  f"{share:.0%} of `toml`'s tokens (< {CHECK_TOKENS:.0%}) {yes(c_tok)}; "
                  f"call 1 {call1:,.0f} input tokens (< {CHECK_CALL1:,}) {yes(c_c1)}. "
                  f"Stop {'HIT (' + ', '.join(hit) + ')' if hit else 'not hit'} "
                  f"(coverage < {STOP_COVER:.0%}, > {STOP_POINTS} points behind, call 1 > {STOP_CALL1:,}). "
                  f"State by the rules: {'killed' if hit else 'open'}. "
                  f"Hypothesis (coverage ≥ 95%): {'yes' if cover >= 0.95 - 1e-9 else 'no'}. "
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
