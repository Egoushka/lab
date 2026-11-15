# 08 · lint4sg on implock's generator

**Question.** What does lint4sg say about a source generator that works, and how many of the findings are worth acting on?

**Hypothesis.** It reports a handful of findings on a hand-written generator and most are real performance or
correctness points, not noise.

**Check.** Copy of implock `src/Implock.Generator` (git archive of commit ae87abb, 893 lines). Add `lint4sg` 0.1.7, build
Release, list distinct diagnostics by rule, and mark each by hand as perf/correctness or style. One reviewer (me); the
marks are a judgement, not a measurement.

**Stop.** More than half the findings are false positives, or the package changes anything outside `obj/`: kill.

**Cost.** No model calls. The "let a model write a generator" half of the cheapest test is not run here. Tool: NuGet
`lint4sg` 0.1.7 (Apache-2.0; its `buildTransitive` target only writes one file under `obj/`).

Result: [results/2026-11-15.md](results/2026-11-15.md).
