# 03 · vague questions

**Question.** When the question does not name its fields, can the agent still pick the ones it needs, and does the
two-call path keep its accuracy and its token saving?

**Why.** [02](../02-picked-fields/) picked every needed field 60 of 60, but each question named its fields
("status", "platform", "remote"), so the pick only had to copy words from the question. A real question says "which
repos are still being worked on". Now the pick has to map an everyday word to one of 16 column names, which is where
it can fail: a missing field makes the question unanswerable, and the answer is scored as it comes.

**Setup.** Same data, scoring, `claude -p` flags, two-call path and pick prompt as 02; the code is imported from 02's
`bench.py` and, through it, 01's.
- Data: `repos.toml` (read at run time, never committed). Questions and true answers are generated from it as before.
- 20 questions: the same 20 as 02, in the same order, with the same kind, true answer and list of needed fields. Only
  the wording changes. A reworded question never contains a column name; it may quote a value ("active", "oss") and
  use an everyday word for the concept ("area" for platform, "give up on" for stop). The meaning does not change.
- 3 views, Haiku 5.5, 3 passes, n = 60 per view, as in 02:
  - `toml`: the file as it is (control: can the whole file answer the reworded question at all).
  - `view`: 01's projected view with the needed fields given by the question generator (control: reading the view
    when the pick is right).
  - `picked`: call 1 gets the question and the 16 column names (no values, no descriptions) and replies
    `{"fields": [...]}`; the harness builds the view from it; call 2 answers from that view.
- A pick that misses a needed field is scored as it is: call 2 answers from what it was given. There is no fallback to
  the whole file. Names that are not columns are dropped and counted; an unusable reply goes on as `name` only.
- Tokens are Claude's own, from the usage report, as in 02; for `picked` the two calls are summed.

**Machine checks, before any model call** (`bench.py check`; `run` runs them first and stops if one fails):
1. The 20 reworded questions have the same id, kind, needed fields and true answer as 01's question of that id.
2. No reworded question contains a column name as a word (also with an `s`, `ed` or `ing` ending), once quoted
   values and repo names are set aside.

The wording is fixed before the first model call and is not edited after a result. A changed question is a new run;
the old one stays in `results/`.

**Prediction (before the run, starting values).** The pick covers every needed field in about 90% of calls. The
weak spots, guessed: the `readme` lookup ("documentation template"), `platform` ("area", which `kind` competes
with), and the `check` and `stop` lookups, where the everyday word sits far from the column name. Accuracy about 92%
against about 98% for `toml`. Tokens about 3,700, 25% of `toml` (02 measured 1,171 for call 1 and 2,432 for call 2),
a little more if picks add fields.

**Check (it works).** All three:
- the pick covers every needed field in at least 90% of calls (54 of 60);
- `picked` is within 5 points of `toml` on accuracy (3 answers at n = 60);
- `picked` uses under 40% of `toml`'s input tokens, both calls counted.

**Stop.** Any one:
- the pick covers every needed field in under 75% of calls (under 45 of 60);
- `picked` is more than 10 points behind `toml`;
- `picked` uses 60% or more of `toml`'s tokens (the same limit as 02).

Between the two, the experiment stays open. If `toml` itself scores under 90% (under 54 of 60), the reworded
questions are ambiguous even with the whole file, and the verdict says so instead of blaming the pick.

Also reported: which needed fields the pick missed most and what it picked instead, how often a question got extra
fields and which, accuracy when the pick did and did not cover the need, and seconds per question.

**Cost.** 240 calls (20 questions × 3 passes × `toml` 1 + `view` 1 + `picked` 2). 02's identical shape cost $0.14 at
list prices; so about $0.20 (a starting value, since vague picks may add fields; the run's `total_cost_usd`
replaces it). The runs use the Claude subscription.

**Known limits.**
- An everyday word is the mild end of vague: each question still maps one concept to one column. An indirect
  question ("what should I look at first?") is not tested here.
- The wording is mine, written knowing the schema. A user would phrase some of it differently.
- The pick sees column names only. A value-only question ("the repos marked parked") depends on the name `status`
  being a good guess for where "parked" lives.
- The two calls are separate `claude -p` processes, each paying about 870 tokens of overhead, as in 02.
- One file, 20 mechanical questions: a difference of one or two answers is noise.

**Reuse.** Imported from 02: `ask`, `parse_pick`, `job`, `PICK_SYSTEM`, `mean`, and through it 01's `load`,
`questions`, `to_view`, `columns`, `score`, `parse`. New in 03: the reworded questions, the two machine checks, `run`
and `report`. 02's `run` and `report` are tied to its own questions and thresholds, so they are written again here.
This is the third experiment on the same harness, so `kernel/` has a third consumer to be checked against; it still
waits for the language choice (Python, Rust or C# Native AOT).

**Run.**
```sh
uv run bench.py check  --data ~/Projects/repos.toml
uv run bench.py run    --data ~/Projects/repos.toml --model haiku --repeat 3 [--dry-run]
uv run bench.py report runs/<file>.jsonl --write               # aggregates to results/
```
`check`, `run` and `report` need only the standard library, so `python3 bench.py …` works too; `--dry-run` needs
`tiktoken`, so it needs `uv run`.

**Results.** See [results/](results/). The raw answers and picks stay in `runs/` (git-ignored) because they quote
the data.
