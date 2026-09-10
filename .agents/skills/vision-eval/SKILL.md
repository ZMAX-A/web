---
name: vision-eval
description: Evaluate this repository's visual-reference model and Harness using labeled PNG pairs, baseline metadata, deterministic pass/fail rules, repeatability metrics, and privacy-safe reports. Use when measuring visual accuracy, comparing model or Prompt versions, adding evaluation samples, or reviewing baseline quality; do not use for an ordinary single UI regression run.
---

# Vision Eval

Measure the visual system rather than assuming a passing smoke test proves accuracy. Keep the existing Python `VisionHarness` as the runtime oracle; this skill evaluates its model observations and local verdict together.

## Workflow

1. Inspect the current Git status, visual configuration, Prompt version, baseline metadata, and labeled manifest before changing anything. Preserve unrelated or user-owned changes.
2. Run the offline gate first:

   ```powershell
   .\.venv\Scripts\python.exe scripts\run_vision_eval.py
   ```

   This validates paths, PNGs, metadata hashes, dimensions, screenshot locators, approval state, and labels without calling the model.
3. Read [references/dataset-schema.md](references/dataset-schema.md) when adding samples, changing labels, comparing versions, or interpreting metrics.
4. Require explicit authorization immediately before a real run because approved images are sent to `VISION_BASE_URL`. Then run, for example:

   ```powershell
   .\.venv\Scripts\python.exe scripts\run_vision_eval.py --run-model --repeat 3
   ```

5. Compare models or Prompt versions only on the identical manifest. Preserve each generated `reports/vision-eval/<timestamp>/summary.json`; do not reuse cached model responses during repeatability checks.
6. Report accuracy, false-pass count, false-fail count, uncertainty, schema/service errors, repeat consistency, latency, dataset balance, and exclusions. A one-class or fewer-than-20-sample dataset is smoke evidence only.

## Non-negotiable boundaries

- Never create, replace, approve, or bulk-update a standard image from a normal test run. Baseline approval is a separate human action.
- Never infer `expected_pass` from the model output. Labels must come from human-reviewed expected behavior.
- Treat a false pass as higher risk than a false fail for customer-facing image pages. Do not hide model/schema/service errors inside the accuracy denominator.
- Do not persist screenshots in reports. Store relative paths, hashes, structured statuses, and sanitized errors only.
- Do not claim the model became more accurate from Prompt edits alone; require the same labeled dataset and compare metrics.
- Keep customer images on the approved company endpoint. If `VISION_BASE_URL` is non-local HTTP, flag the lack of transport encryption before real execution.
