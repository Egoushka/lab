# 05 · skillgate audit

**Question.** Does `skillgate audit` (zero-config, read-only) say anything useful about a folder of agent skills?

**Hypothesis.** The audit runs without touching the folder and its secrets gate fires on a planted key. Its defaults
(`npm test`, `src/**/*.{ts,js}`) fit a code repo, so on `skills/` most gates pass by matching nothing.

**Check.** On a copy of `skills/` (23 skills): exit code, per-gate status, files written. Control: a copy of one skill
with a fake `ghp_` token in a `.md` file must fail `no-secrets`.

**Stop.** The audit writes into the folder, or the control does not fail: kill.

**Cost.** No model calls. About 6 s per run. Tool: `@reneza/skillgate@0.16.0` (MIT, source read: `git`, `spawn` of the
spec's own commands, no network in `audit`), run with `npx` from a throwaway directory.

Result: [results/2026-11-15.md](results/2026-11-15.md).
