# 01 · agent views

**Question.** When an AI reads a structured file, does a cut-down *view* (only the fields the question needs,
derivable values dropped) beat a token-cheap *syntax* (CSV, TOON) on correct answers per token?

**Why.** Agents read manifests, issues and transcripts in every session. Published format benchmarks compare
syntaxes: TOON claims about 40% fewer tokens than JSON ([toonformat.dev](https://toonformat.dev/guide/benchmarks)),
and independent runs don't confirm it ([dev.to](https://dev.to/ikaganacar/toon-benchmarks-a-critical-analysis-of-different-results-5h66)).
A first count on my `repos.toml` (2026-11-07, `o200k_base` tokenizer as a stand-in for Claude's) found CSV only 13%
above the bare values, so no syntax can save much more than that. Leaving fields out can.

**Setup.**
- Data: my workspace manifest `repos.toml` (81 repos, 16 fields), read at run time and never committed.
- 20 questions generated from the data with their true answers: 6 counts, 8 lookups, 6 lists.
- 4 views:
  - `toml`: the file as it is.
  - `csv`: every field.
  - `toon`: every field, as a TOON table.
  - `view`: `name` plus the question's fields, with a remote dropped when a rule can rebuild it.
- The model runs through `claude -p` with no tools, no settings, no MCP servers and a short system prompt.
  Token counts come from the API's usage report, so they are Claude's own.
- Assumption to know: `view` is told which fields the question needs. In real use the agent would request the
  fields (like a SQL `SELECT`), so this measures the upper bound of projection, not the cost of choosing fields.

**Check (it works).** `view` keeps accuracy within 2 points of `toml` and uses under 40% of its tokens.
**Stop.** `view` loses more than 5 points of accuracy against `toml` on two models.
**Cost.** 80 calls, about 455k input tokens per model. Haiku 5.5 about $0.05, Sonnet 5.5 about $1 at API
prices from third-party trackers (2026-11-07). The runs here used the Claude subscription.

**Run.**
```sh
uv run bench.py tokens --data ~/Projects/repos.toml            # token counts only, offline
uv run bench.py run    --data ~/Projects/repos.toml --model haiku
uv run bench.py report runs/<file>.jsonl --write               # aggregates to results/
```

**Results.** See [results/](results/). The raw answers stay in `runs/` (git-ignored) because they quote the data.
