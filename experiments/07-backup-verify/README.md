# 07 · backup-verify, one plan

**Question.** Does `backup-verify` turn "we have a backup" into a restore that fails loudly when the backup is bad?

**Hypothesis.** A plan with a restic fetch, a Postgres load and two checks passes on a good backup and fails on (a) a
wrong row floor and (b) a truncated dump, and writes a history line either way.

**Check.** `run.sh`: throwaway Postgres (5,000 rows) → `pg_dump` → throwaway restic repo → three plans against a second
throwaway Postgres. Expected exits: 0, 1, non-zero.

**Stop.** A bad backup passes, or a run writes outside its workdir: kill.

**Cost.** No model calls. Devbox has no Docker, so the plan runs in the tool's documented in-place mode (no
`restore.image`). restic 0.19.1 and the Postgres of the `pgserver` wheel, both under a throwaway directory. Tool: commit
9d4727f (Apache-2.0, source read).

Result: [results/2026-11-15.md](results/2026-11-15.md).
