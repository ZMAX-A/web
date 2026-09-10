# Dataset and baseline contract

Use `test_assets/vision_eval/cases.jsonl`. Each non-comment line is one labeled JSON object:

| Field | Type | Meaning |
|---|---|---|
| `id` | string | Unique evaluation sample ID |
| `case_id` | string | Business case whose baseline and Prompt focus apply |
| `current` | string | Project-relative PNG path used as the current image |
| `expected_pass` | boolean | Human-reviewed expected local Harness verdict |
| `focus` | string | Observable UI expectations, without hidden implementation claims |
| `locator` | string | Must equal the approved baseline `capture_locator` |
| `category` | string | Optional slice such as `positive`, `missing-button`, `loading`, or `error` |

Every baseline directory must contain `reference.png` and `reference.meta.json`. The metadata fixes the case ID, PNG hash and dimensions, screenshot locator, approval state/source, and allowed dynamic differences. Updating the PNG requires separate human review and a matching metadata update.

## Minimum useful coverage

The checked-in same-image positive sample is only a connection/control smoke case. Before reporting accuracy, add human-reviewed current screenshots covering at least:

- normal page with allowed dynamic customer/image content;
- missing or obscured critical buttons;
- blank, loading, network-error, and partially rendered image areas;
- clipped/overflowing layout at each supported viewport;
- a visually similar but wrong page;
- borderline cases that should become `uncertain` rather than pass.

Use at least 20 samples and include both expected passes and expected failures. Keep exact same files and labels when comparing `VISION_MODEL` or `PROMPT_VERSION`.

## Metric interpretation

- `false_pass`: an expected failure accepted by the Harness; highest-priority defect.
- `false_fail`: a valid page rejected; stability/usability problem.
- `defect_recall`: fraction of expected failures correctly rejected.
- `pass_precision`: fraction of accepted samples that truly should pass.
- `repeat_consistency_rate`: whether repeated uncached calls produce the same local verdict.
- schema/service error rates remain failed attempts and reduce total accuracy.

Inspect category slices as well as the aggregate. Do not tune the Prompt against evaluation failures and then report the same samples as an unbiased final benchmark; retain a separate holdout set.
