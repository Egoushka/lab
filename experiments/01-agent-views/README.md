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

## Part 2 · code views (`codeview/`)

**Hypothesis.** The same idea works on source code: an agent that reads a cut-down view of a C# or TypeScript
file (types, signatures, doc comments, bodies elided behind a marker that keeps the original line range) sees
every public symbol at its real line, for about half the tokens of the full file.

**Tool.** `codeview view FILE` prints the view; `codeview bench REPO...` measures it over the git-tracked
files of each repo. Each kept line carries a gutter `N| ` with its original line number; an elided body becomes
`{ /*…14-18*/ }`. Interfaces, enums and type aliases are kept whole. Blank lines are dropped. If braces do not
balance the tool returns an error and the caller reads the full file.

Language: Go. One static binary with no dependencies, starts in about a millisecond (the agent calls it per
file), and the standard library is enough. Rust would be as good; C# would need a runtime or AOT for the same
start time and would be a bigger tool for a lexer and a brace matcher. It is a lexer, not a parser: comments,
strings and regex literals are masked first, then braces are matched, so it needs no Roslyn or TypeScript
compiler and does not check that the code compiles.

**Check (it works).** On every repo and language measured, the view uses at most 55% of the original tokens
(pieces proxy, gutter included) and 99% or more of the public symbols are found at the same line in the view.
Those thresholds were set after a first run showed about 50% for C#, not before it; the first pre-registered
number was "about half".
**Stop.** Symbol recall under 95%, or more than 80% of the tokens kept, on any repo.
**Cost.** $0. No model is called.

**How measured.** `go run . bench REPO...` from `codeview/`, on the tracked `.cs`, `.ts` and `.tsx` files
(`.d.ts` excluded).
- Tokens: no offline Claude tokenizer exists, so two proxies are shown. `pieces` splits identifiers at case
  changes, digit runs, punctuation runs and whitespace runs; `bytes/4` is the common rule of thumb. Absolute
  counts are not Claude's; the kept ratio is what matters. The Part 1 note applies: Claude's tokenizer counts
  more than the proxy, and more so on code, so treat the ratios as approximate.
- Correctness proxy, no model: a symbol extractor lists public, protected and internal declarations in C# (including indexers,
  operators and every name in `const int K = 1, L = 2`), and in TypeScript `export` declarations and lists,
  `export default`, and non-private members of top-level classes (with or without `public`), as (name, line) pairs. It runs on the original file
  and on the view (lines read from the gutter). "Found in view" is the share of original pairs also in the
  view. "Exact files" is the share of files whose two sets are identical. A second check confirms every
  gutter line is the start of the original line with that number.
- Limitation: the extractor and the view share one lexer, so a mask bug could hide in both. The check proves
  the cut does not drop declarations; it does not prove a model answers better with the view. Part 1 is
  the only evidence on accuracy.
- What the score covers: declarations named as above, at the right line, plus signatures and import/export
  lists left whole ("Cut signatures", from the view text alone). It does not cover: members of classes nested
  in functions or namespaces (not public API, skipped on both sides), return-type object literals
  (`): Promise<{ ... }> {` may still be elided), a C# `a < b` inside a field initializer (confuses the comma
  split), or anything about body content. The signature check shares its import/export pattern with the cut,
  so it is not fully independent of it.

**Result (2026-11-11, lab `4062de7` plus the review fixes; repos at chargehand `d9e29ac`, workspace `1a8225b`,
personal-website `bc769d7`).**

| Repo | Lang | Files | Tokens kept (pieces) | Tokens kept (bytes/4) | Symbols | Found in view | Exact files | Cut signatures |
|---|---|---|---|---|---|---|---|---|
| chargehand | C# | 1019 | 50.7% | 45.4% | 10124 | 100.00% | 100.0% | 0 |
| chargehand | TS | 256 | 32.0% | 26.8% | 1198 | 100.00% | 100.0% | 0 |
| workspace | C# | 15 | 44.0% | 37.4% | 221 | 100.00% | 100.0% | 0 |
| workspace | TS | 4 | 42.0% | 39.1% | 9 | 100.00% | 100.0% | 0 |
| personal-website | TS | 119 | 35.0% | 31.3% | 332 | 100.00% | 100.0% | 0 |

No file fell back to the full text. All gutter lines match the original (about 60,000). Viewing all of
chargehand's C# takes about 0.3 s. The first version of this table (extractor covering only explicit
`public` members, `export` declarations, and no signature check) also read 100% while the cut elided
multi-line signatures and import/export lists in 11 TS files; the extractor was widened and the
"Cut signatures" column added, and the cut fixed.

**Verdict.** The check passed (worst row 50.7%, recall 100% and no cut signatures everywhere) and the stop was not hit. The 100% is
a statement about declarations, not about answers: a model still has to be tested on the view, which needs
paid calls and is a separate session. C# keeps more than TS because of attributes, expression-bodied members
and one-line bodies that stay inline.

**Run.**
```sh
cd codeview && go test ./... && go run . bench ~/work/chargehand ~/work/workspace
```
