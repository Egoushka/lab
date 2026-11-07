# lab

A playground for experiments with code, agents and data, kept apart from my everyday tools on purpose:
here it's fine for things to break.

Every experiment is a folder in `experiments/` with a claim it tests, a result that counts as working,
a result that stops it, and its cost. An experiment ends in one of three states: **kept** (it graduates into
a real project), **killed** (the stop rule hit) or **open**.

| # | Experiment | Question | State |
|---|---|---|---|
| 01 | [agent-views](experiments/01-agent-views/) | Does a cut-down view of a file beat a token-cheap syntax (CSV, TOON) for AI reading? | open |
| 02 | [picked-fields](experiments/02-picked-fields/) | Does the view still win when the agent picks its own fields, counting both calls? | open |
| 03 | [vague-questions](experiments/03-vague-questions/) | Does the pick still work when the question does not name its fields? | killed |
| 04 | [value-hints](experiments/04-value-hints/) | Does giving the pick the values of few-valued columns fix 03's miss? | open |

## Rules

- **No personal or employer data in git.** Experiments read private inputs from a path at run time and
  commit only aggregate results (scores, token counts), never the inputs or the model's answers.
- **Numbers carry their source:** a script, a commit and the date of the run.
- Shared code moves into `kernel/` only once two experiments use it. Until then each experiment owns its code.

MIT licensed.
