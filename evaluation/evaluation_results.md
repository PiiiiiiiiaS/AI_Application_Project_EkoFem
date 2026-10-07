# Evaluation Results Summary

Document your team's evaluation results below.

> **Note (pending re-run):** the figures below predate the off-topic-handling
> and memory updates. Case-12 in particular is expected to change from
> `partial` to an automatic `pass`, since WasteBuddy no longer forces a
> nonsensical classification onto out-of-scope input (see Action Items
> below and `docs/architecture.md`). Run `python -m evaluation.run_evaluation`
> after pulling these changes and update this file with the real numbers
> rather than assuming the outcome.

## Summary Overview

- **Date of Evaluation:** 2026-09-26
- **Model Evaluated:** `qwen3:8b` (text classification path). The vision model (`moondream`) was not exercised in this round -- all 12 test cases were text-only.
- **Total Test Cases Executed:** 12
- **Passed:** 9
- **Failed:** 0
- **Pass Rate:** 75% (9/12 automatically graded as correct; the remaining 3 are marked `partial` -- they ran without error but need human judgment rather than a scripted pass/fail, see below)

## Performance by Category

| Category | Total Cases | Passed | Failed | Pass Rate |
| :--- | :---: | :---: | :---: | :---: |
| Successful Cases | 6 | 6 | 0 | 100% |
| Difficult Cases | 3 | 1 | 0 | 33% (2 marked `partial`, not `fail` -- see notes) |
| Failure / Edge Cases | 3 | 2 | 0 | 67% (1 marked `partial`, not `fail` -- see notes) |

*Note on `partial`: three cases have no single objectively correct answer, so `run_evaluation.py` did not attempt to auto-grade them as pass/fail -- it recorded the real output and left the case for manual review instead. That is a deliberate part of the evaluation design, not a scoring gap.*

## Key Findings & Failure Analysis

### What worked well
- All 6 successful-case (typical) items were classified correctly (100%), confirming the core grounding pipeline -- the model only picks a category label, and all disposal facts come from `data/finland_waste_categories.json` -- works reliably for clear, everyday inputs.
- The fallback logic performed exactly as designed: "broken ceramic mug" (case-07) is not listed under any category's `belongs` list, and the system correctly fell back to Mixed / miscellaneous waste rather than mistakenly matching it to Glass just because ceramic is breakable and glass-like.
- Input validation worked flawlessly: both empty (case-10) and whitespace-only (case-11) input were caught before ever reaching the model, returning the friendly guidance message immediately, with no wasted model call and no crash.

### Observed failure modes / limitations
- **Contamination nuance (case-08):** a heavily soiled, smelly pizza box was classified as Mixed waste. On manual review this is actually the right call per the dataset's own notes (badly soiled cardboard should be rejected from recycling) -- but it also reveals a limitation: WasteBuddy gives one single label per item, so it cannot express "recycle the clean part, bin the dirty part" the way a human sorter would.
- **Non-English input (case-09):** "vaatteet" (Finnish for "clothes") was still classified correctly as Textiles, even though WasteBuddy was deliberately scoped as English-first. This is a side effect of the underlying model's own multilingual training, not a supported feature -- it should not be relied on, and full Finnish support remains a deferred, intentional scope decision.
- **Out-of-scope input (case-12):** "What is the capital of France?" was not rejected as irrelevant -- WasteBuddy still forced a classification ("Mixed waste") onto it. This is the clearest genuine gap found in this evaluation round: the system has no way to recognize that a question is unrelated to waste sorting, so an off-topic query produces a confusing, nonsensical answer instead of a clear "I can't help with that."
