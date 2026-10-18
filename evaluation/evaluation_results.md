# Evaluation Results Summary

## Summary Overview

- **Date of Evaluation:** 2026-10-18
- **Model Evaluated:** `qwen3:8b` (text classification path). The vision model (`moondream`) was not exercised in this round, because all 16 test cases were text only.
- **Total Test Cases Executed:** 16
- **Passed:** 14
- **Failed:** 0
- **Partial:** 2
- **Pass Rate:** 88% (14/16 automatically graded as correct; the remaining 2 are marked `partial`, because they ran without error but need human judgment rather than a scripted pass or fail, see below)
- **Previous round:** 2026-09-26, 12 cases, 9 passed, 0 failed, 3 partial.

## Performance by Category

| Category | Total Cases | Passed | Failed | Pass Rate |
| :--- | :---: | :---: | :---: | :--- |
| Successful Cases | 10 | 10 | 0 | 100% |
| Difficult Cases | 3 | 1 | 0 | 33% (2 marked `partial`, not `fail`, see notes) |
| Failure / Edge Cases | 3 | 3 | 0 | 100% |

*Note on `partial`: two cases have no single objectively correct answer, so `run_evaluation.py` did not attempt to grade them as pass or fail. It recorded the real output and left the case for manual review instead. This is a deliberate part of the evaluation design, not a scoring gap.*

## Key Findings and Failure Analysis

### What worked well

- All 10 successful cases were classified correctly (100%), including the four cases added after the first round (bricks, grass clippings, electric kettle and cereal box). This confirms that the grounding pipeline works reliably for clear, everyday inputs and that the later added categories are recognised.
- The fallback logic performed as designed: "broken ceramic mug" (case-07) is not listed under any category, and the system correctly fell back to Mixed / miscellaneous waste instead of matching it to Glass.
- Input validation worked: both empty (case-10) and whitespace-only (case-11) input were caught before reaching the model, and the friendly guidance message was returned without a model call or a crash.
- Out-of-scope input (case-12) is now handled correctly. In the first round, "What is the capital of France?" was forced into Mixed waste. After the off topic option was added to the classification prompt, the question receives a polite redirect back to waste sorting.

### Observed limitations

- **Contamination nuance (case-08):** a heavily soiled, smelly pizza box was classified as Cardboard / Carton in this round, whereas the first round classified it as Mixed waste. According to the notes in the reference dataset, badly soiled cardboard should not go to cardboard recycling, so the present answer is not the ideal one. The difference between the two rounds shows that the answer for a borderline item can change, either because of the later changes to the classification prompt or because of variation in the model's output. WasteBuddy also gives one single label per item, so it cannot express "recycle the clean part, dispose of the dirty part". The case remains `partial`.
- **Non-English input (case-09):** "vaatteet" (Finnish for "clothes") was classified correctly as Textiles, as in the first round, even though WasteBuddy is deliberately scoped as English first. This is a side effect of the model's own multilingual training and not a supported feature, so it should not be relied on. The case remains `partial`.
- **Sample size:** 16 cases is a small sample, so the results do not prove that every possible input is handled correctly.
