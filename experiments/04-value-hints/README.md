# 04 · value hints

**Question.** If call 1 also sees the distinct values of the columns that have only a few, does the pick stop missing
the column that an everyday word stands for?

**Why.** [03](../03-vague-questions/) was killed by one word. With 16 column names and no values, the pick missed
`platform` in 9 of its 12 needed appearances because the questions said "area"; every other needed field was found in
all 60 calls. The value list of a few-valued column is cheap and shows what the column holds: `platform` holds
`Money`, `Phone` and three more. The pick may read those as "areas". This tests whether that is enough.

**Hypothesis.** Coverage (the pick names every needed field) returns to 95% or more, and call 1 grows by a few dozen
tokens (measured with the o200k proxy before the run: +92).

**Setup.** Same data, questions, scoring, `claude -p` flags, controls and two-call path as 03. The code is imported
from 03's `bench.py` and, through it, 02's and 01's. The only change is call 1.
- Data: `repos.toml` (read at run time, never committed).
- Questions: the same 20 reworded questions as 03, imported by path, not copied. The wording is not edited.
- 3 views, Haiku 5.5, 3 passes, n = 60 per view, as in 03:
  - `toml`: the file as it is (control).
  - `view`: 01's projected view with the needed fields given by the question generator (control).
  - `picked`: call 1 gets the question, the 16 column names **and, for six columns, the list of their values**, and
    replies `{"fields": [...]}`; the harness builds the view from it; call 2 answers from that view.
- The six columns are fixed: `status`, `kind`, `platform`, `readme`, `merge_policy`, `sweep`. Each has at most 12
  distinct values (4, 5, 5, 8, 2 and 2; empty is not a value). Four more columns also have at most 12 and are left out
  on purpose: `nuget` (set on one repo), `card` (five repos), `due` (three dates; 03 found it every time without a
  list) and `status_note` (free text). Nothing else is added to the prompt. The system prompt gets one sentence saying
  that some columns come with all their values; it does not say how to use them.
- Only call 1 changes. Call 2, the controls and the scoring are 03's, so a difference in the answer is the pick's.

**Machine checks, before any model call** (`bench.py check`; `run` runs them first and stops if one fails):
1. 03's two: the 20 questions keep 01's id, kind, needed fields and true answer; none names a column.
2. New: the value lists hold only values, never repo names or free text.
   - they come from exactly the six columns, each with 1 to 12 distinct values;
   - every value is at most 24 characters and two words;
   - no value equals a repo name. One coincidence is known and named in `bench.py`: the `readme` value `research` is
     also a repo name. It is a documentation template there. It stays, because `readme` is one of the six, and the
     check fails on any other collision;
   - no value of a free-text column (`name`, `path`, `remote`, `note`, `check`, `stop`, `status_note`) appears in a
     list.

A guard, not a data check: the harness stops if the pick prompt it builds is the same as 03's, so a run cannot go
through without the lists.

**Prediction (before the run, starting values).** Coverage about 93% (56 of 60). `Money` is a value of `platform`,
so q03 should be fixed. q06 and q12 carry no value ("belong to no area", "which area does the repo belong to"), so the
lists help only if the model reads `Agent work, Box, Memory, Money, Phone` as areas; I guess half of those six calls.
Accuracy about 90% against 95% for `toml`. Call 1 about 1,420 input tokens (03 measured 1,329, plus 92 from the
proxy), call 2 about 2,690, total about 27% of `toml`'s. The lists may also change picks that were fine in 03; the
report compares coverage per question with 03's.

**Check (it works).** All four:
- the pick covers every needed field in at least 90% of calls (54 of 60);
- `picked` is within 5 points of `toml` on accuracy (3 answers at n = 60);
- `picked` uses under 40% of `toml`'s input tokens, both calls counted;
- call 1 uses under 1,500 input tokens on average.

**Stop.** Any one:
- the pick covers every needed field in under 75% of calls (under 45 of 60);
- `picked` is more than 10 points behind `toml`;
- call 1 uses over 1,800 input tokens on average.

Between the two, the experiment stays open. The stop line of 02 and 03 ("`picked` uses 60% of `toml`'s tokens or
more") is not carried over: call 1 is the only cost this experiment changes, so its limit is the stop. If `toml` itself scores under 90% (under 54 of
60), the questions are ambiguous even with the whole file, and the verdict says so instead of blaming the pick.

Also reported: coverage per question next to 03's, which needed fields the pick missed and what it picked instead,
extra fields, accuracy when the pick did and did not cover the need, and seconds per question.

**Cost.** 240 calls (20 questions × 3 passes × `toml` 1 + `view` 1 + `picked` 2). 03's identical shape cost $0.16 at
list prices; about $0.16 again, a few cents more at most (a starting value; the run's `total_cost_usd` replaces it).
The runs use the Claude subscription.

**Known limits.**
- One wording per field, as in 03. "Area" for `platform` is still one word chosen by me; this run says whether the
  lists rescue that word, not whether they rescue any word.
- Of the three questions that failed in 03, only q03 quotes a value. If q03 is fixed and q06 and q12 are not, the
  lists work by value matching, not by describing the column, and the verdict says that.
- q15 ("active" repos with no give-up condition) fails in all three views in 03, 9 of 9. It costs `toml`, `view` and
  `picked` the same 3 answers, so it does not move the gap to `toml`; the best `picked` can score is about 95%.
- The comparison with 03 is across two runs on the same file and wording (the data hash is recorded in both). A
  difference of one or two answers is noise.
- The lists are bounded by the 12-value rule. A column with 12 values costs more than these six together; this run
  does not price that.
- The two calls are separate `claude -p` processes, each paying about 870 tokens of overhead, as in 02 and 03.

**Reuse.** Imported from 03: the 20 questions (`vague_questions`), the first machine checks (`problems`) and `job`;
through it 02's `ask`, `parse_pick`, `PICK_SYSTEM`, `mean` and 01's `load`, `columns`, `to_view`, `score`. New in 04:
the pick prompt with the lists, the list check, `run` and `report`. `run` and `report` are written again because
03's write to 03's folder and apply 03's thresholds. This is the fourth experiment on the same harness; `kernel/` still
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
