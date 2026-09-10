import hashlib
import json
import struct

import pytest

from scripts import run_vision_eval as vision_eval


def _png_bytes(width=320, height=180, size=900):
    header = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR"
    header += struct.pack(">II", width, height)
    return header + b"\x00" * max(size - len(header), 0)


def _prepare_dataset(tmp_path, monkeypatch, expected_pass=True):
    monkeypatch.setattr(vision_eval, "PROJECT_ROOT", tmp_path)
    baseline_root = tmp_path / "baselines"
    baseline_dir = baseline_root / "TC-IMAGE-006"
    baseline_dir.mkdir(parents=True)
    image_bytes = _png_bytes()
    (baseline_dir / "reference.png").write_bytes(image_bytes)
    metadata = {
        "schema_version": 1,
        "case_id": "TC-IMAGE-006",
        "reference_file": "reference.png",
        "image_sha256": hashlib.sha256(image_bytes).hexdigest(),
        "image_width": 320,
        "image_height": 180,
        "capture_locator": "body",
        "approved_for_visual_testing": True,
        "approval_source": "unit test",
        "allowed_dynamic_differences": [],
    }
    (baseline_dir / "reference.meta.json").write_text(
        json.dumps(metadata), encoding="utf-8"
    )
    current = tmp_path / "current.png"
    current.write_bytes(image_bytes)
    manifest = tmp_path / "cases.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "id": "sample-1",
                "case_id": "TC-IMAGE-006",
                "current": "current.png",
                "expected_pass": expected_pass,
                "focus": "页面正常",
                "locator": "body",
                "category": "smoke",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("VISION_BASELINE_DIR", str(baseline_root))
    monkeypatch.setenv("VISION_REQUIRE_BASELINE_METADATA", "true")
    return manifest


def test_load_cases_validates_images_and_baseline_metadata(tmp_path, monkeypatch):
    manifest = _prepare_dataset(tmp_path, monkeypatch)

    cases = vision_eval.load_cases(manifest)

    assert len(cases) == 1
    assert cases[0].id == "sample-1"
    assert cases[0].expected_pass is True
    assert any("异常页面样本" in warning for warning in vision_eval.dataset_warnings(cases))


def test_load_cases_rejects_path_outside_project(tmp_path, monkeypatch):
    manifest = _prepare_dataset(tmp_path, monkeypatch)
    record = json.loads(manifest.read_text(encoding="utf-8"))
    record["current"] = str(tmp_path.parent / "outside.png")
    manifest.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(vision_eval.VisionEvalConfigError, match="项目目录内"):
        vision_eval.load_cases(manifest)


def test_summary_counts_false_pass_and_errors(tmp_path, monkeypatch):
    manifest = _prepare_dataset(tmp_path, monkeypatch, expected_pass=False)
    case = vision_eval.load_cases(manifest)[0]
    records = [
        {
            "id": case.id,
            "status": "ok",
            "expected_pass": False,
            "actual_pass": True,
            "correct": False,
            "uncertain": False,
            "latency_ms": 100,
        },
        {
            "id": case.id,
            "status": "schema_error",
            "expected_pass": False,
            "actual_pass": None,
            "correct": False,
            "uncertain": False,
            "latency_ms": None,
        },
    ]

    summary = vision_eval.summarize_records([case], records, repeat=2)

    assert summary["accuracy"] == 0.0
    assert summary["confusion_matrix"]["false_pass"] == 1
    assert summary["schema_error_rate"] == 0.5
    assert summary["repeat_consistency_rate"] == 0.0
