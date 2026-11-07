# 02 · picked fields

**Question.** When the agent chooses the fields itself, does a projected view still beat the whole file, once the
tokens of both calls are counted?

**Why.** [01](../01-agent-views/) gave the view the fields the question needs, so it measured the upper bound of
projection. A real agent has to ask for them. That can fail two ways: a missing field makes the question
unanswerable, and the pick is a call of its own. A bare `claude -p` call carries about 870 input tokens before any
data (measured 2026-11-07: a one-line prompt came back as 872).

**Setup.** Same data, questions, scoring and `claude -p` flags as 01; the code is imported from 01's `bench.py`.
- Data: `repos.toml` (read at run time, never committed). It has changed since 01, so the questions and their true
  answers are regenerated, and the controls below run in the same run.
- 20 questions: 6 counts, 8 lookups, 6 lists. Each question names the fields it needs, so picking is the easy case.
- 3 views, Haiku 5.5, 3 passes, n = 60 per view:
  - `toml`: the file as it is (control).
  - `view`: 01's projected view with the fields given by the question generator (control, the upper bound).
  - `picked`: **call 1** gets the question and the 16 field names (no values, no descriptions) and replies
    `{"fields": [...]}`. The harness builds the view from that list with 01's `to_view`, the same projection and
    remote rule; `name` is always included. **Call 2** reads that view and the question, as in 01.
- Names that are not fields are dropped and counted. There is no fallback to the full file: a bad pick stays bad.
  An empty pick, or a reply that is no field list, goes on as `name` only.
- Tokens are Claude's own, from the usage report: input tokens as in 01 (new, cache write and cache read added),
  output tokens counted apart. For `picked`, the two calls are summed.

**Prediction (before the run, starting values).** The pick covers the needed fields in 95% of calls or more. Call 1
is about 1,050 tokens (872 of overhead plus the prompt) and call 2 about 2,030 (01's `view`), so `picked` totals
about 3,100 tokens: 22% of `toml`.

**Check (it works).** `picked` keeps accuracy within 2 points of `toml` and uses under 40% of its input tokens,
both calls counted.
**Stop.** `picked` loses more than 5 points of accuracy against `toml`, or uses 60% or more of its tokens.

Also reported: how often the pick covers every needed field, the fields picked beyond need, accuracy when the pick
was or wasn't enough, and the seconds a `picked` question takes against a `view` one.

**Cost.** 240 calls (20 questions × 3 passes × `toml` 1 + `view` 1 + `picked` 2). 01's Haiku runs cost $0.23 for 160
calls and $0.26 for 80, at list prices, and `toml` dominates; so about $0.30 (a starting value; the run's
`total_cost_usd` replaces it). The runs use the Claude subscription.

**Known limits.**
- The questions name their fields, so this does not test a vague question. That is a harder run, not this one.
- The two calls are separate `claude -p` processes, each paying the ~870-token overhead. In one live agent
  conversation the second step continues the first and pays it once. This measures the stateless worst case.
- One file, 20 mechanical questions: a difference of one or two answers is noise.

**Reuse.** Imported from 01: `load`, `questions`, `to_view`, `columns`, `score`, `parse`, `prompt`, `SYSTEM`. New in
02: the pick call, the two-call job and the report. The `claude -p` invocation is written again, because 01's
`call` is tied to its four views. This is the first reuse that #35's check counts, so `kernel/` starts after the
language choice (Python, Rust or C# Native AOT) is made.

**Run.**
```sh
uv run bench.py run    --data ~/Projects/repos.toml --model haiku --repeat 3 [--dry-run]
uv run bench.py report runs/<file>.jsonl --write               # aggregates to results/
```

**Results.** See [results/](results/). The raw answers and picks stay in `runs/` (git-ignored) because they quote
the data.
