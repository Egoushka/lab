# 09 · quotamax trend vs subgate

**Question.** Does `quotamax trend` agree with the numbers subgate keeps, and can an agent ask it for capacity advice?

**Hypothesis.** Both read the same plan meter and agree within a few percent.

**Check.** Read-only: `quotamax trend` and `agent`, compared with subgate's recorded numbers.

**Stop.** The tool sends the credential anywhere except Anthropic's usage endpoint: kill. A check that needs the
owner's OAuth token cannot run in this session: report instead.

**Cost.** No model calls. Tool: quotamax 0.5.0 (MIT, source read). It reads the Claude OAuth token from
`~/.claude/.credentials.json` and sends it to `api.anthropic.com/api/oauth/usage`.

Result: [results/2026-11-15.md](results/2026-11-15.md).
