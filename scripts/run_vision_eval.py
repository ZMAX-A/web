"""Validate and score the project's visual-reference model on labeled image pairs.

The default mode is offline and never calls the vision endpoint. Use --run-model
only after the image set is approved for transmission to the configured service.
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import math
import os
import statistics
import struct
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.vision_client import VisionError  # noqa: E402
from utils.vision_harness import (  # noqa: E402
    PROMPT_VERSION,
    VisionHarness,
    VisionHarnessError,
    VisionSchemaError,
)


DEFAULT_MANIFEST = PROJECT_ROOT / "test_assets" / "vision_eval" / "cases.jsonl"
DEFAULT_REPORT_ROOT = PROJECT_ROOT / "reports" / "vision-eval"


class VisionEvalConfigError(ValueError):
    """The labeled dataset is missing, unsafe, or internally inconsistent."""


@dataclass(frozen=True)
class EvalCase:
    id: str
    case_id: str
    current_path: Path
    current_relative: str
    expected_pass: bool
    focus: str
    locator: str
    category: str


def _project_path(raw: str, label: str) -> Path:
    value = str(raw or "").strip()
    if not value:
        raise VisionEvalConfigError(f"{label} 不能为空")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path = path.resolve()
    try:
        path.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise VisionEvalConfigError(f"{label} 必须位于项目目录内: {value}") from exc
    return path


def _png_info(path: Path) -> tuple[bytes, int, int, str]:
    try:
        image_bytes = path.read_bytes()
    except FileNotFoundError as exc:
        raise VisionEvalConfigError(f"评测图片不存在: {path.relative_to(PROJECT_ROOT)}") from exc
    except OSError as exc:
        raise VisionEvalConfigError(f"评测图片读取失败: {path}: {exc}") from exc
    if len(image_bytes) < 512 or not image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        raise VisionEvalConfigError(f"评测图片必须是有效且非空的 PNG: {path.relative_to(PROJECT_ROOT)}")
    width, height = struct.unpack(">II", image_bytes[16:24])
    if width < 24 or height < 24 or width > 4096 or height > 4096:
        raise VisionEvalConfigError(
            f"评测图片尺寸必须在 24..4096 像素内: {path.relative_to(PROJECT_ROOT)}={width}x{height}"
        )
    return image_bytes, width, height, hashlib.sha256(image_bytes).hexdigest()


def load_cases(manifest_path: Path, selected_case_id: str = "") -> list[EvalCase]:
    path = manifest_path.resolve()
    try:
        path.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise VisionEvalConfigError("评测清单必须位于项目目录内") from exc
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise VisionEvalConfigError(f"评测清单不存在: {path.relative_to(PROJECT_ROOT)}") from exc

    cases: list[EvalCase] = []
    seen_ids: set[str] = set()
    allowed = {"id", "case_id", "current", "expected_pass", "focus", "locator", "category"}
    required = allowed - {"category"}
    for line_number, raw_line in enumerate(lines, start=1):
        text = raw_line.strip()
        if not text or text.startswith("#"):
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise VisionEvalConfigError(f"评测清单第 {line_number} 行不是合法 JSON: {exc.msg}") from exc
        if not isinstance(data, dict):
            raise VisionEvalConfigError(f"评测清单第 {line_number} 行必须是 JSON 对象")
        if set(data) - allowed or not required.issubset(data):
            missing = sorted(required - set(data))
            extra = sorted(set(data) - allowed)
            raise VisionEvalConfigError(
                f"评测清单第 {line_number} 行字段错误: 缺少={missing}, 多余={extra}"
            )
        item_id = str(data["id"] or "").strip()
        case_id = str(data["case_id"] or "").strip()
        if not item_id or item_id in seen_ids:
            raise VisionEvalConfigError(f"评测清单第 {line_number} 行 id 为空或重复: {item_id!r}")
        seen_ids.add(item_id)
        if selected_case_id and case_id != selected_case_id:
            continue
        expected_pass = data["expected_pass"]
        if type(expected_pass) is not bool:
            raise VisionEvalConfigError(f"评测清单第 {line_number} 行 expected_pass 必须是 boolean")
        current_path = _project_path(str(data["current"]), f"第 {line_number} 行 current")
        relative = current_path.relative_to(PROJECT_ROOT).as_posix()
        focus = str(data["focus"] or "").strip()
        locator = str(data["locator"] or "").strip()
        category = str(data.get("category") or "unclassified").strip()
        if not case_id or not focus or not locator or not category:
            raise VisionEvalConfigError(
                f"评测清单第 {line_number} 行 case_id/focus/locator/category 不能为空"
            )
        _png_info(current_path)
        VisionHarness.load_baseline(case_id, locator)
        cases.append(
            EvalCase(
                id=item_id,
                case_id=case_id,
                current_path=current_path,
                current_relative=relative,
                expected_pass=expected_pass,
                focus=focus,
                locator=locator,
                category=category,
            )
        )
    if not cases:
        suffix = f"（case_id={selected_case_id}）" if selected_case_id else ""
        raise VisionEvalConfigError(f"评测清单没有可执行样本{suffix}")
    return cases


def dataset_warnings(cases: list[EvalCase]) -> list[str]:
    positive = sum(case.expected_pass for case in cases)
    negative = len(cases) - positive
    warnings: list[str] = []
    if not positive:
        warnings.append("缺少 expected_pass=true 的正常页面样本，无法评估误拒绝")
    if not negative:
        warnings.append("缺少 expected_pass=false 的异常页面样本，无法评估漏报")
    if len(cases) < 20:
        warnings.append("样本少于 20 条，只能作为连通性/冒烟证据，不能声称模型准确率")
    return warnings


def _record_error(case: EvalCase, repeat_index: int, exc: Exception) -> dict[str, Any]:
    if isinstance(exc, VisionSchemaError):
        status = "schema_error"
    elif isinstance(exc, (VisionError, VisionHarnessError)):
        status = "service_or_harness_error"
    else:
        status = "runtime_error"
    return {
        "id": case.id,
        "case_id": case.case_id,
        "category": case.category,
        "current": case.current_relative,
        "expected_pass": case.expected_pass,
        "repeat": repeat_index,
        "status": status,
        "actual_pass": None,
        "correct": False,
        "uncertain": False,
        "latency_ms": None,
        "image_sha256": None,
        "reference_sha256": None,
        "layout_status": None,
        "critical_elements_status": None,
        "page_usability": None,
        "unexpected_error_visible": None,
        "critical_differences": [],
        "uncertain_reason": "",
        "failure_reasons": [],
        "error": str(exc)[:500],
    }


def _run_case(page: Any, case: EvalCase, repeat_index: int) -> dict[str, Any]:
    image_bytes, width, height, image_hash = _png_info(case.current_path)
    image_url = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
    page.set_viewport_size({"width": width, "height": height})
    page.set_content(
        "<style>html,body{margin:0;padding:0;overflow:hidden;background:#fff}"
        f"body{{width:{width}px;height:{height}px}}"
        f"img{{display:block;width:{width}px;height:{height}px}}</style>"
        f'<img id="current" alt="approved evaluation image" src="{image_url}">',
        wait_until="load",
    )
    page.locator("#current").wait_for(state="visible", timeout=30_000)
    harness = VisionHarness(page, timeout_ms=60_000, case_id=case.case_id)
    inspection = harness.inspect_reference_compare(case.focus, case.locator)
    observation = inspection.observation
    failures = harness.reference_compare_failures(observation)
    actual_pass = not failures
    uncertain = "uncertain" in {
        observation["layout_status"],
        observation["critical_elements_status"],
        observation["page_usability"],
    } or bool(observation["uncertain_reason"])
    return {
        "id": case.id,
        "case_id": case.case_id,
        "category": case.category,
        "current": case.current_relative,
        "expected_pass": case.expected_pass,
        "repeat": repeat_index,
        "status": "ok",
        "actual_pass": actual_pass,
        "correct": actual_pass is case.expected_pass,
        "uncertain": uncertain,
        "latency_ms": inspection.latency_ms,
        "image_sha256": image_hash,
        "reference_sha256": inspection.reference_sha256,
        "layout_status": observation["layout_status"],
        "critical_elements_status": observation["critical_elements_status"],
        "page_usability": observation["page_usability"],
        "unexpected_error_visible": observation["unexpected_error_visible"],
        "critical_differences": observation["critical_differences"],
        "uncertain_reason": observation["uncertain_reason"],
        "failure_reasons": failures,
        "error": "",
    }


def run_model(cases: list[EvalCase], repeat: int) -> list[dict[str, Any]]:
    from playwright.sync_api import sync_playwright

    records: list[dict[str, Any]] = []
    previous_cache = os.environ.get("VISION_CACHE_ENABLED")
    os.environ["VISION_CACHE_ENABLED"] = "false"
    VisionHarness.clear_cache()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            try:
                for case in cases:
                    for repeat_index in range(1, repeat + 1):
                        try:
                            records.append(_run_case(page, case, repeat_index))
                        except Exception as exc:  # Each labeled sample must remain visible in the report.
                            records.append(_record_error(case, repeat_index, exc))
            finally:
                browser.close()
    finally:
        if previous_cache is None:
            os.environ.pop("VISION_CACHE_ENABLED", None)
        else:
            os.environ["VISION_CACHE_ENABLED"] = previous_cache
    return records


def summarize_records(cases: list[EvalCase], records: list[dict[str, Any]], repeat: int) -> dict[str, Any]:
    total = len(records)
    ok_records = [record for record in records if record["status"] == "ok"]
    tp = sum(record["expected_pass"] and record["actual_pass"] for record in ok_records)
    tn = sum(not record["expected_pass"] and not record["actual_pass"] for record in ok_records)
    fp = sum(not record["expected_pass"] and record["actual_pass"] for record in ok_records)
    fn = sum(record["expected_pass"] and not record["actual_pass"] for record in ok_records)
    latencies = [record["latency_ms"] for record in ok_records if record["latency_ms"] is not None]
    consistency_values: list[bool] = []
    if repeat > 1:
        for case in cases:
            values = [
                record["actual_pass"]
                for record in records
                if record["id"] == case.id and record["status"] == "ok"
            ]
            consistency_values.append(len(values) == repeat and len(set(values)) == 1)

    def ratio(numerator: int, denominator: int) -> float | None:
        return round(numerator / denominator, 4) if denominator else None

    return {
        "attempts": total,
        "successful_responses": len(ok_records),
        "correct": sum(bool(record["correct"]) for record in records),
        "accuracy": ratio(sum(bool(record["correct"]) for record in records), total),
        "pass_precision": ratio(tp, tp + fp),
        "pass_recall": ratio(tp, tp + fn),
        "defect_recall": ratio(tn, tn + fp),
        "confusion_matrix": {"true_pass": tp, "true_fail": tn, "false_pass": fp, "false_fail": fn},
        "schema_error_rate": ratio(sum(record["status"] == "schema_error" for record in records), total),
        "service_or_harness_error_rate": ratio(
            sum(record["status"] == "service_or_harness_error" for record in records), total
        ),
        "uncertain_rate": ratio(sum(bool(record["uncertain"]) for record in ok_records), len(ok_records)),
        "repeat_consistency_rate": ratio(sum(consistency_values), len(consistency_values)),
        "median_latency_ms": round(statistics.median(latencies)) if latencies else None,
        "p95_latency_ms": (
            sorted(latencies)[max(0, math.ceil(0.95 * len(latencies)) - 1)]
            if latencies
            else None
        ),
    }


def write_report(
    output_dir: Path,
    manifest_path: Path,
    cases: list[EvalCase],
    records: list[dict[str, Any]],
    repeat: int,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=False)
    warnings = dataset_warnings(cases)
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": os.getenv("VISION_MODEL", "unknown"),
        "prompt_version": PROMPT_VERSION,
        "manifest": manifest_path.relative_to(PROJECT_ROOT).as_posix(),
        "repeat": repeat,
        "sample_count": len(cases),
        "coverage_ready": not warnings,
        "warnings": warnings,
        "metrics": summarize_records(cases, records, repeat),
        "records": records,
    }
    summary_path = output_dir / "summary.json"
    summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with (output_dir / "records.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = [
            "id", "case_id", "category", "current", "expected_pass", "repeat", "status",
            "actual_pass", "correct", "uncertain", "latency_ms", "layout_status",
            "critical_elements_status", "page_usability", "unexpected_error_visible",
            "failure_reasons", "error",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            row = dict(record)
            row["failure_reasons"] = " | ".join(record["failure_reasons"])
            writer.writerow(row)
    return summary_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="校验并评测视觉基线 Harness 的准确率与稳定性")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="项目内 JSONL 评测清单")
    parser.add_argument("--case-id", default="", help="只评测指定业务用例ID")
    parser.add_argument("--run-model", action="store_true", help="真实调用公司视觉模型；默认仅离线校验")
    parser.add_argument("--repeat", type=int, default=1, help="每个样本真实调用次数，范围 1..20")
    parser.add_argument("--output-dir", default="", help="真实评测报告目录；默认按时间生成")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    load_dotenv(PROJECT_ROOT / ".env")
    args = parse_args(argv)
    if args.repeat < 1 or args.repeat > 20:
        print("ERROR: --repeat 必须在 1..20 之间", file=sys.stderr)
        return 2
    try:
        manifest_path = _project_path(args.manifest, "manifest")
        cases = load_cases(manifest_path, args.case_id.strip())
    except VisionEvalConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    positive = sum(case.expected_pass for case in cases)
    print(f"数据集校验通过: {len(cases)} 条（正常={positive}，异常={len(cases) - positive}）")
    for warning in dataset_warnings(cases):
        print(f"WARNING: {warning}")
    if not args.run_model:
        print("离线模式完成：未调用视觉模型，未生成评测报告。")
        return 0

    records = run_model(cases, args.repeat)
    stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    try:
        output_dir = _project_path(args.output_dir, "output-dir") if args.output_dir else DEFAULT_REPORT_ROOT / stamp
        summary_path = write_report(output_dir, manifest_path, cases, records, args.repeat)
    except (OSError, VisionEvalConfigError) as exc:
        print(f"ERROR: 评测报告写入失败: {exc}", file=sys.stderr)
        return 2
    metrics = summarize_records(cases, records, args.repeat)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print(f"评测报告: {summary_path.relative_to(PROJECT_ROOT)}")
    return 0 if metrics["correct"] == metrics["attempts"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
