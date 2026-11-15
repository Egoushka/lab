# 06 · agent-readiness vs levelset

**Question.** On the same live site, does `@canonry/agent-readiness` find things levelset does not, and is its agent
output specific enough to act on?

**Hypothesis.** The two overlap on `llms.txt` and `robots.txt` and differ elsewhere: agent-readiness scores content and
schema (16 factors), levelset scores WebMCP, MCP, x402 and discovery. Different scores, not a ranking.

**Check.** One run each on `https://hrabovskyi.online`: score, the findings both report, the findings only one reports,
and whether each `--format agent` issue carries a concrete fix.

**Stop.** The tool sends anything but requests to the audited site, or crashes on a plain static site: kill.

**Cost.** No model calls, no key (the optional PageSpeed call needs `PAGESPEED_API_KEY`, unset). Tools:
`@canonry/agent-readiness@8.2.0` (MIT, source read: no telemetry), levelset at its main checkout run with
`--no-browser`.

Result: [results/2026-11-15.md](results/2026-11-15.md).
