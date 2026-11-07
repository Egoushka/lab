# lab

Public experiments repo. Read README.md for its rules; the ones agents break most:

- Never commit an experiment's inputs or raw model answers: they come from private files (`repos.toml`,
  transcripts). `runs/` is git-ignored; commit only `results/*.md` with aggregates.
- An experiment's README states hypothesis, check, stop and cost before its code lands.
- Python scripts carry their dependencies inline (PEP 723) and run with `uv run <script>`.
