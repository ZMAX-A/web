import base64
import hashlib
import json
import struct

import pytest

from utils import vision_client
from utils.assertion_executor import AssertionExecutor
from utils.case_validator import CaseValidationError, is_visual_assertion, validate_cases
from utils.vision_harness import (
    VisionAssertionMismatch,
    VisionHarness,
    VisionHarnessError,
    VisionSchemaError,
)


def _png_bytes(width=320, height=180, size=900):
    """构造满足 Harness 尺寸检查的 PNG 头；模型调用在测试中被替换。"""
    header = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR"
    header += struct.pack(">II", width, height)
    return header + b"\x00" * max(size - len(header), 0)


class _FakeLocator:
    def __init__(self, image_bytes):
        self.image_bytes = image_bytes
        self.wait_calls = []
        self.screenshot_calls = []

    @property
    def first(self):
        return self

    def wait_for(self, **kwargs):
        self.wait_calls.append(kwargs)

    def screenshot(self, **kwargs):
        self.screenshot_calls.append(kwargs)
        return self.image_bytes


class _FakePage:
    def __init__(self, image_bytes=None):
        self.target = _FakeLocator(image_bytes or _png_bytes())
        self.selectors = []
        self.comparison = _png_bytes(width=1640, height=1916, size=1500)
        self.evaluate_calls = []

    def locator(self, selector):
        self.selectors.append(selector)
        return self.target

    def evaluate(self, script, arg):
        self.evaluate_calls.append((script, arg))
        return "data:image/png;base64," + base64.b64encode(self.comparison).decode("ascii")


class _AnalyzeRecorder:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, image_bytes, prompt, **kwargs):
        self.calls.append((image_bytes, prompt, kwargs))
        return self.responses.pop(0)


class _CompareAnalyzeRecorder:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, image_bytes, prompt, **kwargs):
        self.calls.append((image_bytes, prompt, kwargs))
        return self.responses.pop(0)


@pytest.fixture(autouse=True)
def _clear_vision_cache(monkeypatch):
    VisionHarness.clear_cache()
    monkeypatch.setenv("VISION_MODEL", "unit-test-vision")
    monkeypatch.setenv("VISION_CACHE_ENABLED", "true")
    monkeypatch.setenv("VISION_ATTACH_SCREENSHOT", "false")
    monkeypatch.setenv("VISION_REQUIRE_BASELINE_METADATA", "false")


def test_vision_contains_crops_locator_and_passes_all_visible():
    response = json.dumps(
        {
            "task": "items",
            "checks": {"冷光": "visible", "毛孔": "visible"},
            "uncertain_reason": "",
        },
        ensure_ascii=False,
    )
    analyze = _AnalyzeRecorder(response)
    page = _FakePage()
    harness = VisionHarness(page, timeout_ms=9000, analyze_fn=analyze)

    assert harness.assert_contains("'冷光','毛孔'", "[data-testid='toolbar']") is True
    assert page.selectors == ["[data-testid='toolbar']"]
    assert page.target.wait_calls == [{"state": "visible", "timeout": 9000}]
    assert analyze.calls[0][2] == {"discipline": True, "json_mode": True}
    assert "冷光" in analyze.calls[0][1] and "毛孔" in analyze.calls[0][1]


def test_vision_contains_uncertain_is_fail_closed():
    response = json.dumps(
        {
            "task": "items",
            "checks": {"冷光": "visible", "毛孔": "uncertain"},
            "uncertain_reason": "右侧被截断",
        },
        ensure_ascii=False,
    )
    harness = VisionHarness(_FakePage(), analyze_fn=_AnalyzeRecorder(response))

    with pytest.raises(VisionAssertionMismatch, match="毛孔=uncertain"):
        harness.assert_contains("'冷光','毛孔'", "#toolbar")


def test_vision_schema_rejects_boolean_status_instead_of_silently_coercing():
    response = json.dumps(
        {
            "task": "items",
            "checks": {"冷光": True},
            "uncertain_reason": "",
        },
        ensure_ascii=False,
    )
    harness = VisionHarness(_FakePage(), analyze_fn=_AnalyzeRecorder(response))

    with pytest.raises(VisionSchemaError, match="visible/not_visible/uncertain"):
        harness.assert_contains("冷光", "#toolbar")


def test_vision_cache_reuses_same_image_prompt_and_model():
    response = json.dumps(
        {"task": "items", "checks": {"冷光": "visible"}, "uncertain_reason": ""},
        ensure_ascii=False,
    )
    analyze = _AnalyzeRecorder(response)
    harness = VisionHarness(_FakePage(), analyze_fn=analyze)

    assert harness.assert_contains("冷光", "#toolbar") is True
    assert harness.assert_contains("冷光", "#toolbar") is True
    assert len(analyze.calls) == 1


def test_vision_count_requires_consistent_evidence_and_exact_result():
    response = json.dumps(
        {
            "task": "count",
            "count": 3,
            "uncertain": False,
            "evidence": ["左侧缩略图", "中间缩略图", "右侧缩略图"],
        },
        ensure_ascii=False,
    )
    harness = VisionHarness(_FakePage(), analyze_fn=_AnalyzeRecorder(response))
    assert harness.assert_count("应显示3项", "#gallery") is True


def test_vision_count_rejects_inconsistent_evidence():
    response = json.dumps(
        {"task": "count", "count": 2, "uncertain": False, "evidence": ["只有一项"]},
        ensure_ascii=False,
    )
    harness = VisionHarness(_FakePage(), analyze_fn=_AnalyzeRecorder(response))

    with pytest.raises(VisionSchemaError, match="evidence 项数"):
        harness.assert_count("2项", "#gallery")


def test_page_state_and_canvas_ready_use_local_decisions():
    page_response = json.dumps(
        {
            "task": "page_state",
            "page_state": "image_viewer",
            "uncertain": False,
            "evidence": ["左侧工具栏", "中央影像画布"],
        },
        ensure_ascii=False,
    )
    canvas_response = json.dumps(
        {"task": "canvas", "canvas_state": "loaded", "uncertain": False, "error_texts": []},
        ensure_ascii=False,
    )
    harness = VisionHarness(
        _FakePage(),
        analyze_fn=_AnalyzeRecorder(page_response, canvas_response),
    )

    assert harness.assert_page_state("影像阅览页", "#viewer") is True
    assert harness.assert_canvas_ready("影像加载完成", "#canvas") is True


def test_canvas_error_never_passes():
    response = json.dumps(
        {
            "task": "canvas",
            "canvas_state": "error",
            "uncertain": False,
            "error_texts": ["网络不佳"],
        },
        ensure_ascii=False,
    )
    harness = VisionHarness(_FakePage(), analyze_fn=_AnalyzeRecorder(response))

    with pytest.raises(VisionAssertionMismatch, match="网络不佳"):
        harness.assert_canvas_ready("影像加载完成", "#canvas")


def _reference_response(**overrides):
    payload = {
        "task": "reference_compare",
        "layout_status": "match",
        "critical_elements_status": "match",
        "page_usability": "usable",
        "unexpected_error_visible": False,
        "critical_differences": [],
        "evidence": ["主工具栏位置一致", "影像画布已显示"],
        "uncertain_reason": "",
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


def test_reference_compare_automatically_loads_case_baseline(tmp_path, monkeypatch):
    baseline = _png_bytes(width=640, height=360, size=1200)
    current = _png_bytes(width=640, height=360, size=1300)
    baseline_path = tmp_path / "TC-IMAGE-006" / "reference.png"
    baseline_path.parent.mkdir(parents=True)
    baseline_path.write_bytes(baseline)
    monkeypatch.setenv("VISION_BASELINE_DIR", str(tmp_path))
    compare = _CompareAnalyzeRecorder(_reference_response())
    page = _FakePage(current)
    harness = VisionHarness(
        page,
        case_id="TC-IMAGE-006",
        compare_analyze_fn=compare,
    )

    assert harness.assert_reference_compare("页面结构正常", "#image-viewer") is True
    comparison, prompt, kwargs = compare.calls[0]
    assert comparison == page.comparison
    assert "上半部分标记 REFERENCE / STANDARD" in prompt
    assert "页面结构正常" in prompt
    assert kwargs == {"discipline": True, "json_mode": True}
    assert page.selectors == ["#image-viewer"]
    assert len(page.evaluate_calls) == 1
    evaluate_arg = page.evaluate_calls[0][1]
    assert evaluate_arg["referenceUrl"].startswith("data:image/png;base64,")
    assert evaluate_arg["currentUrl"].startswith("data:image/png;base64,")


def _write_baseline_metadata(path, image_bytes, **overrides):
    width, height = struct.unpack(">II", image_bytes[16:24])
    payload = {
        "schema_version": 1,
        "case_id": "TC-IMAGE-006",
        "reference_file": "reference.png",
        "image_sha256": hashlib.sha256(image_bytes).hexdigest(),
        "image_width": width,
        "image_height": height,
        "capture_locator": "#image-viewer",
        "approved_for_visual_testing": True,
        "approval_source": "unit test",
        "allowed_dynamic_differences": ["时间"],
    }
    payload.update(overrides)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_step_metadata(path, image_bytes, filename="step_005_page_loaded.png", **overrides):
    width, height = struct.unpack(">II", image_bytes[16:24])
    payload = {
        "schema_version": 1,
        "case_id": "TC-IMAGE-006",
        "capture_locator": "body",
        "approved_for_visual_testing": True,
        "approval_source": "unit test",
        "allowed_dynamic_differences": ["轻微颜色差异"],
        "references": {
            filename: {
                "image_sha256": hashlib.sha256(image_bytes).hexdigest(),
                "image_width": width,
                "image_height": height,
                "crop_box": [10, 10, width - 20, height - 20],
                "current_crop_box": [10, 10, width - 20, height - 20],
            }
        },
    }
    payload.update(overrides)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_step_reference_uses_manifest_crop_and_local_verdict(tmp_path, monkeypatch):
    baseline = _png_bytes(width=640, height=360, size=1200)
    current = _png_bytes(width=640, height=360, size=1300)
    reference_crop = _png_bytes(width=620, height=340, size=1100)
    current_crop = _png_bytes(width=620, height=340, size=1150)
    comparison = _png_bytes(width=620, height=720, size=1500)
    steps_dir = tmp_path / "TC-IMAGE-006" / "steps"
    steps_dir.mkdir(parents=True)
    filename = "step_005_page_loaded.png"
    (steps_dir / filename).write_bytes(baseline)
    _write_step_metadata(steps_dir / "steps.meta.json", baseline, filename)
    monkeypatch.setenv("VISION_BASELINE_DIR", str(tmp_path))
    crop_calls = []

    def crop_pair(reference_bytes, current_bytes, crop_box):
        crop_calls.append((reference_bytes, current_bytes, crop_box))
        return reference_crop, current_crop

    compare = _CompareAnalyzeRecorder(_reference_response())
    harness = VisionHarness(
        _FakePage(current),
        case_id="TC-IMAGE-042",
        compare_analyze_fn=compare,
        crop_fn=crop_pair,
        compose_fn=lambda _reference, _current: comparison,
    )

    assert harness.assert_step_reference(f"TC-IMAGE-006/{filename}", "body") is True
    assert crop_calls == [(baseline, current, [10, 10, 620, 340])]
    assert compare.calls[0][0] == comparison
    assert filename in compare.calls[0][1]
    assert "轻微颜色差异" in compare.calls[0][1]


def test_step_reference_can_use_separate_current_crop_box(tmp_path, monkeypatch):
    baseline = _png_bytes(width=640, height=360, size=1200)
    current_full = _png_bytes(width=640, height=360, size=1300)
    reference_crop = _png_bytes(width=620, height=340, size=1100)
    discarded_current_crop = _png_bytes(width=620, height=340, size=1150)
    discarded_reference_crop = _png_bytes(width=600, height=320, size=1125)
    current_crop = _png_bytes(width=600, height=320, size=1175)
    comparison = _png_bytes(width=620, height=720, size=1500)
    steps_dir = tmp_path / "TC-IMAGE-006" / "steps"
    steps_dir.mkdir(parents=True)
    filename = "step_012_GY.png"
    (steps_dir / filename).write_bytes(baseline)
    _write_step_metadata(
        steps_dir / "steps.meta.json",
        baseline,
        filename,
        references={
            filename: {
                "image_sha256": hashlib.sha256(baseline).hexdigest(),
                "image_width": 640,
                "image_height": 360,
                "crop_box": [10, 10, 620, 340],
                "current_crop_box": [20, 20, 600, 320],
            }
        },
    )
    monkeypatch.setenv("VISION_BASELINE_DIR", str(tmp_path))
    crop_calls = []

    def crop_pair(reference_bytes, current_bytes, crop_box):
        crop_calls.append((reference_bytes, current_bytes, crop_box))
        if crop_box == [10, 10, 620, 340]:
            return reference_crop, discarded_current_crop
        return discarded_reference_crop, current_crop

    compare = _CompareAnalyzeRecorder(_reference_response())
    harness = VisionHarness(
        _FakePage(current_full),
        case_id="TC-IMAGE-042",
        compare_analyze_fn=compare,
        crop_fn=crop_pair,
        compose_fn=lambda reference, current: (
            comparison
            if (reference, current) == (reference_crop, current_crop)
            else b"unexpected"
        ),
    )

    assert harness.assert_step_reference(f"TC-IMAGE-006/{filename}", "body") is True
    assert crop_calls == [
        (baseline, current_full, [10, 10, 620, 340]),
        (baseline, current_full, [20, 20, 600, 320]),
    ]
    assert compare.calls[0][0] == comparison


def test_step_reference_rejects_ambiguous_current_crop_config(tmp_path, monkeypatch):
    baseline = _png_bytes(width=640, height=360, size=1200)
    steps_dir = tmp_path / "TC-IMAGE-006" / "steps"
    steps_dir.mkdir(parents=True)
    filename = "step_012_GY.png"
    (steps_dir / filename).write_bytes(baseline)
    _write_step_metadata(
        steps_dir / "steps.meta.json",
        baseline,
        filename,
        references={
            filename: {
                "image_sha256": hashlib.sha256(baseline).hexdigest(),
                "image_width": 640,
                "image_height": 360,
                "crop_box": [10, 10, 620, 340],
                "current_crop_box": [20, 20, 600, 320],
                "current_capture": {
                    "locator": "canvas",
                    "ancestor_levels": 0,
                    "required_texts": ["光影增强"],
                },
            }
        },
    )
    monkeypatch.setenv("VISION_BASELINE_DIR", str(tmp_path))
    harness = VisionHarness(_FakePage(baseline), case_id="TC-IMAGE-042")

    with pytest.raises(
        VisionHarnessError,
        match="current_capture 与 current_crop_box 不能同时配置",
    ):
        harness.inspect_step_reference(f"TC-IMAGE-006/{filename}", "body")


def test_step_reference_requires_explicit_current_capture_strategy(tmp_path, monkeypatch):
    baseline = _png_bytes(width=640, height=360, size=1200)
    steps_dir = tmp_path / "TC-IMAGE-006" / "steps"
    steps_dir.mkdir(parents=True)
    filename = "step_012_GY.png"
    (steps_dir / filename).write_bytes(baseline)
    _write_step_metadata(
        steps_dir / "steps.meta.json",
        baseline,
        filename,
        references={
            filename: {
                "image_sha256": hashlib.sha256(baseline).hexdigest(),
                "image_width": 640,
                "image_height": 360,
                "crop_box": [10, 10, 620, 340],
            }
        },
    )
    monkeypatch.setenv("VISION_BASELINE_DIR", str(tmp_path))
    harness = VisionHarness(_FakePage(baseline), case_id="TC-IMAGE-042")

    with pytest.raises(
        VisionHarnessError,
        match="STEP_CURRENT_CAPTURE_STRATEGY_MISSING",
    ):
        harness.inspect_step_reference(f"TC-IMAGE-006/{filename}", "body")


def test_step_reference_can_capture_current_component_dynamically(tmp_path, monkeypatch):
    class HierarchyLocator(_FakeLocator):
        def __init__(self, image_bytes, text, parent=None):
            super().__init__(image_bytes)
            self.text = text
            self.parent = parent
            self.parent_calls = []

        def locator(self, selector):
            self.parent_calls.append(selector)
            assert selector == "xpath=.."
            assert self.parent is not None
            return self.parent

        def inner_text(self, **_kwargs):
            return self.text

    class DynamicPage(_FakePage):
        def __init__(self, full_bytes, component_bytes):
            super().__init__(full_bytes)
            panel_text = "视角回正 0° R45° L45° R90° L90°"
            self.panel = HierarchyLocator(component_bytes, panel_text)
            self.header = HierarchyLocator(component_bytes, "视角回正", self.panel)
            self.label = HierarchyLocator(component_bytes, "视角回正", self.header)

        def locator(self, selector):
            self.selectors.append(selector)
            if selector == "text=视角回正":
                return self.label
            return self.target

    baseline = _png_bytes(width=640, height=360, size=1200)
    current_full = _png_bytes(width=640, height=360, size=1300)
    reference_crop = _png_bytes(width=220, height=300, size=1100)
    discarded_coordinate_crop = _png_bytes(width=220, height=300, size=1150)
    component_crop = _png_bytes(width=104, height=241, size=1050)
    comparison = _png_bytes(width=620, height=720, size=1500)
    steps_dir = tmp_path / "TC-IMAGE-006" / "steps"
    steps_dir.mkdir(parents=True)
    filename = "step_006_view_reset.png"
    (steps_dir / filename).write_bytes(baseline)
    _write_step_metadata(
        steps_dir / "steps.meta.json",
        baseline,
        filename,
        references={
            filename: {
                "image_sha256": hashlib.sha256(baseline).hexdigest(),
                "image_width": 640,
                "image_height": 360,
                "crop_box": [10, 10, 620, 340],
                "current_capture": {
                    "locator": "text=视角回正",
                    "ancestor_levels": 2,
                    "required_texts": ["视角回正", "0°", "R45°", "L45°", "R90°", "L90°"],
                },
            }
        },
    )
    monkeypatch.setenv("VISION_BASELINE_DIR", str(tmp_path))
    crop_calls = []

    def crop_pair(reference_bytes, current_bytes, crop_box):
        crop_calls.append((reference_bytes, current_bytes, crop_box))
        return reference_crop, discarded_coordinate_crop

    compare = _CompareAnalyzeRecorder(_reference_response())
    page = DynamicPage(current_full, component_crop)
    harness = VisionHarness(
        page,
        case_id="TC-IMAGE-042",
        compare_analyze_fn=compare,
        crop_fn=crop_pair,
        compose_fn=lambda reference, current: (
            comparison
            if (reference, current) == (reference_crop, component_crop)
            else b"unexpected"
        ),
    )

    assert harness.assert_step_reference(f"TC-IMAGE-006/{filename}", "body") is True
    assert crop_calls == [(baseline, current_full, [10, 10, 620, 340])]
    assert page.selectors == ["body", "text=视角回正"]
    assert page.label.parent_calls == ["xpath=.."]
    assert page.header.parent_calls == ["xpath=.."]
    assert page.panel.screenshot_calls == [
        {
            "type": "png",
            "animations": "disabled",
            "caret": "hide",
            "timeout": 5000,
        }
    ]
    assert compare.calls[0][0] == comparison


def test_step_dynamic_capture_fails_closed_when_required_text_is_missing(
    tmp_path, monkeypatch
):
    class MissingTextLocator(_FakeLocator):
        def __init__(self, image_bytes, parent=None):
            super().__init__(image_bytes)
            self.parent = parent

        def locator(self, _selector):
            return self.parent

        def inner_text(self, **_kwargs):
            return "视角回正 0° R45°"

    class MissingTextPage(_FakePage):
        def __init__(self, image_bytes):
            super().__init__(image_bytes)
            panel = MissingTextLocator(image_bytes)
            header = MissingTextLocator(image_bytes, panel)
            self.label = MissingTextLocator(image_bytes, header)

        def locator(self, selector):
            if selector == "text=视角回正":
                return self.label
            return self.target

    baseline = _png_bytes(width=640, height=360, size=1200)
    steps_dir = tmp_path / "TC-IMAGE-006" / "steps"
    steps_dir.mkdir(parents=True)
    filename = "step_006_view_reset.png"
    (steps_dir / filename).write_bytes(baseline)
    _write_step_metadata(
        steps_dir / "steps.meta.json",
        baseline,
        filename,
        references={
            filename: {
                "image_sha256": hashlib.sha256(baseline).hexdigest(),
                "image_width": 640,
                "image_height": 360,
                "crop_box": [10, 10, 620, 340],
                "current_capture": {
                    "locator": "text=视角回正",
                    "ancestor_levels": 2,
                    "required_texts": ["视角回正", "L90°"],
                },
            }
        },
    )
    monkeypatch.setenv("VISION_BASELINE_DIR", str(tmp_path))
    harness = VisionHarness(
        MissingTextPage(_png_bytes(width=640, height=360, size=1300)),
        case_id="TC-IMAGE-042",
        crop_fn=lambda _reference, _current, _box: (
            _png_bytes(width=620, height=340, size=1100),
            _png_bytes(width=620, height=340, size=1150),
        ),
    )

    with pytest.raises(VisionHarnessError, match="STEP_CURRENT_CAPTURE_TEXT_MISSING"):
        harness.inspect_step_reference(f"TC-IMAGE-006/{filename}", "body")


def test_step_reference_rejects_changed_hash_and_viewport(tmp_path, monkeypatch):
    baseline = _png_bytes(width=640, height=360, size=1200)
    steps_dir = tmp_path / "TC-IMAGE-006" / "steps"
    steps_dir.mkdir(parents=True)
    filename = "step_005_page_loaded.png"
    (steps_dir / filename).write_bytes(baseline)
    _write_step_metadata(
        steps_dir / "steps.meta.json",
        baseline,
        filename,
        references={
            filename: {
                "image_sha256": "0" * 64,
                "image_width": 640,
                "image_height": 360,
                "crop_box": [10, 10, 620, 340],
            }
        },
    )
    monkeypatch.setenv("VISION_BASELINE_DIR", str(tmp_path))
    harness = VisionHarness(_FakePage(), case_id="TC-IMAGE-042")
    with pytest.raises(VisionHarnessError, match="STEP_BASELINE_HASH_MISMATCH"):
        harness.assert_step_reference(f"TC-IMAGE-006/{filename}", "body")

    _write_step_metadata(steps_dir / "steps.meta.json", baseline, filename)
    harness = VisionHarness(_FakePage(_png_bytes(width=800, height=600)), case_id="TC-IMAGE-042")
    with pytest.raises(VisionHarnessError, match="STEP_VIEWPORT_MISMATCH"):
        harness.assert_step_reference(f"TC-IMAGE-006/{filename}", "body")


def test_reference_compare_validates_metadata_and_adds_dynamic_rules(tmp_path, monkeypatch):
    baseline = _png_bytes(width=640, height=360, size=1200)
    baseline_dir = tmp_path / "TC-IMAGE-006"
    baseline_dir.mkdir(parents=True)
    (baseline_dir / "reference.png").write_bytes(baseline)
    _write_baseline_metadata(baseline_dir / "reference.meta.json", baseline)
    monkeypatch.setenv("VISION_BASELINE_DIR", str(tmp_path))
    monkeypatch.setenv("VISION_REQUIRE_BASELINE_METADATA", "true")
    compare = _CompareAnalyzeRecorder(_reference_response())
    harness = VisionHarness(
        _FakePage(),
        case_id="TC-IMAGE-006",
        compare_analyze_fn=compare,
    )

    inspection = harness.inspect_reference_compare("页面结构正常", "#image-viewer")

    assert inspection.observation["layout_status"] == "match"
    assert VisionHarness.reference_compare_failures(inspection.observation) == []
    assert "允许以下动态差异" in compare.calls[0][1]
    assert "时间" in compare.calls[0][1]


def test_reference_compare_rejects_changed_baseline_hash(tmp_path, monkeypatch):
    baseline = _png_bytes(width=640, height=360, size=1200)
    baseline_dir = tmp_path / "TC-IMAGE-006"
    baseline_dir.mkdir(parents=True)
    (baseline_dir / "reference.png").write_bytes(baseline)
    _write_baseline_metadata(
        baseline_dir / "reference.meta.json",
        baseline,
        image_sha256="0" * 64,
    )
    monkeypatch.setenv("VISION_BASELINE_DIR", str(tmp_path))
    monkeypatch.setenv("VISION_REQUIRE_BASELINE_METADATA", "true")

    with pytest.raises(VisionHarnessError, match="BASELINE_HASH_MISMATCH"):
        VisionHarness(_FakePage(), case_id="TC-IMAGE-006").inspect_reference_compare(
            "页面结构正常", "#image-viewer"
        )


def test_reference_compare_requires_metadata_when_enabled(tmp_path, monkeypatch):
    baseline_dir = tmp_path / "TC-IMAGE-006"
    baseline_dir.mkdir(parents=True)
    (baseline_dir / "reference.png").write_bytes(_png_bytes())
    monkeypatch.setenv("VISION_BASELINE_DIR", str(tmp_path))
    monkeypatch.setenv("VISION_REQUIRE_BASELINE_METADATA", "true")

    with pytest.raises(VisionHarnessError, match="BASELINE_METADATA_MISSING"):
        VisionHarness(_FakePage(), case_id="TC-IMAGE-006").inspect_reference_compare(
            "页面结构正常", "#image-viewer"
        )


def test_reference_compare_missing_baseline_fails_without_model_call(tmp_path, monkeypatch):
    monkeypatch.setenv("VISION_BASELINE_DIR", str(tmp_path))
    compare = _CompareAnalyzeRecorder(_reference_response())
    harness = VisionHarness(
        _FakePage(),
        case_id="TC-IMAGE-006",
        compare_analyze_fn=compare,
    )

    with pytest.raises(VisionHarnessError, match="BASELINE_MISSING"):
        harness.assert_reference_compare("页面结构正常", "#image-viewer")
    assert compare.calls == []


def test_reference_compare_rejects_critical_difference(tmp_path, monkeypatch):
    baseline_path = tmp_path / "TC-IMAGE-006" / "reference.png"
    baseline_path.parent.mkdir(parents=True)
    baseline_path.write_bytes(_png_bytes())
    monkeypatch.setenv("VISION_BASELINE_DIR", str(tmp_path))
    compare = _CompareAnalyzeRecorder(
        _reference_response(
            critical_elements_status="mismatch",
            critical_differences=["查看报告按钮缺失"],
        )
    )
    harness = VisionHarness(
        _FakePage(),
        case_id="TC-IMAGE-006",
        compare_analyze_fn=compare,
    )

    with pytest.raises(VisionAssertionMismatch, match="查看报告按钮缺失"):
        harness.assert_reference_compare("按钮完整", "#image-viewer")


def test_reference_compare_rejects_schema_drift(tmp_path, monkeypatch):
    baseline_path = tmp_path / "TC-IMAGE-006" / "reference.png"
    baseline_path.parent.mkdir(parents=True)
    baseline_path.write_bytes(_png_bytes())
    monkeypatch.setenv("VISION_BASELINE_DIR", str(tmp_path))
    response = json.loads(_reference_response())
    response["pass"] = True
    harness = VisionHarness(
        _FakePage(),
        case_id="TC-IMAGE-006",
        compare_analyze_fn=_CompareAnalyzeRecorder(json.dumps(response, ensure_ascii=False)),
    )

    with pytest.raises(VisionSchemaError, match="多余=.*pass"):
        harness.assert_reference_compare("页面正常", "#image-viewer")


def test_reference_compare_accepts_missing_reason_when_result_is_determinate(tmp_path, monkeypatch):
    baseline_path = tmp_path / "TC-IMAGE-006" / "reference.png"
    baseline_path.parent.mkdir(parents=True)
    baseline_path.write_bytes(_png_bytes())
    monkeypatch.setenv("VISION_BASELINE_DIR", str(tmp_path))
    response = json.loads(_reference_response())
    response.pop("uncertain_reason")
    harness = VisionHarness(
        _FakePage(),
        case_id="TC-IMAGE-006",
        compare_analyze_fn=_CompareAnalyzeRecorder(json.dumps(response, ensure_ascii=False)),
    )

    assert harness.assert_reference_compare("页面正常", "#image-viewer") is True


def test_reference_compare_requires_reason_for_uncertain_result(tmp_path, monkeypatch):
    baseline_path = tmp_path / "TC-IMAGE-006" / "reference.png"
    baseline_path.parent.mkdir(parents=True)
    baseline_path.write_bytes(_png_bytes())
    monkeypatch.setenv("VISION_BASELINE_DIR", str(tmp_path))
    response = json.loads(_reference_response(layout_status="uncertain"))
    response.pop("uncertain_reason")
    harness = VisionHarness(
        _FakePage(),
        case_id="TC-IMAGE-006",
        compare_analyze_fn=_CompareAnalyzeRecorder(json.dumps(response, ensure_ascii=False)),
    )

    with pytest.raises(VisionSchemaError, match="uncertain_reason"):
        harness.assert_reference_compare("页面正常", "#image-viewer")


def test_reference_compare_rejects_unsafe_case_id(tmp_path, monkeypatch):
    monkeypatch.setenv("VISION_BASELINE_DIR", str(tmp_path))
    harness = VisionHarness(_FakePage(), case_id="../secret")
    with pytest.raises(VisionHarnessError, match="不安全字符"):
        harness.assert_reference_compare("页面正常", "#image-viewer")


def test_vision_client_sends_two_labeled_images_in_one_request(monkeypatch):
    monkeypatch.setenv("VISION_API_KEY", "unit-key")
    monkeypatch.setenv("VISION_BASE_URL", "https://vision.test/api")
    monkeypatch.setenv("VISION_MODEL", "unit-test-vision")
    monkeypatch.setenv("VISION_THINKING_BUDGET", "0")
    monkeypatch.delenv("VISION_ENABLE_THINKING", raising=False)
    captured = {}

    class Response:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {"choices": [{"message": {"content": "{}"}}]}

    def fake_post(url, json, headers, timeout):
        captured.update(url=url, payload=json, headers=headers, timeout=timeout)
        return Response()

    monkeypatch.setattr(vision_client.requests, "post", fake_post)
    result = vision_client.analyze_images(
        [_png_bytes(size=1000), _png_bytes(size=1100)],
        "比较两张图片",
        image_labels=["标准截图", "当前截图"],
        json_mode=True,
    )

    assert result == "{}"
    content = captured["payload"]["messages"][-1]["content"]
    assert [item["type"] for item in content] == [
        "text", "text", "image_url", "text", "image_url",
    ]
    assert content[1]["text"] == "【标准截图】"
    assert content[3]["text"] == "【当前截图】"
    assert "valid json object" in content[0]["text"]
    assert captured["payload"]["response_format"] == {"type": "json_object"}


def test_vision_client_uses_dashscope_top_level_thinking_switch(monkeypatch):
    monkeypatch.setenv("VISION_API_KEY", "unit-key")
    monkeypatch.setenv("VISION_BASE_URL", "https://workspace.example.com/compatible-mode/v1")
    monkeypatch.setenv("VISION_MODEL", "qwen3.8-27b")
    monkeypatch.setenv("VISION_THINKING_BUDGET", "16384")
    monkeypatch.setenv("VISION_ENABLE_THINKING", "false")
    captured = {}

    class Response:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {"choices": [{"message": {"content": "{}"}}]}

    def fake_post(url, json, headers, timeout):
        captured.update(payload=json)
        return Response()

    monkeypatch.setattr(vision_client.requests, "post", fake_post)
    vision_client.analyze_images([_png_bytes()], "比较图片", json_mode=True)

    assert captured["payload"]["enable_thinking"] is False
    assert "thinking_budget" not in captured["payload"]
    assert "chat_template_kwargs" not in captured["payload"]


def test_vision_client_suppresses_network_exception_context(monkeypatch):
    monkeypatch.setenv("VISION_API_KEY", "unit-secret-key")
    monkeypatch.setenv("VISION_BASE_URL", "https://vision.test/api")
    monkeypatch.setenv("VISION_MODEL", "unit-test-vision")
    monkeypatch.setattr(
        vision_client.requests,
        "post",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            vision_client.requests.ReadTimeout("read timed out")
        ),
    )

    with pytest.raises(vision_client.VisionError) as caught:
        vision_client.analyze_images([_png_bytes()], "比较图片")

    assert caught.value.__suppress_context__ is True
    assert "unit-secret-key" not in str(caught.value)


def test_visual_assertion_refuses_missing_roi_locator():
    harness = VisionHarness(_FakePage(), analyze_fn=_AnalyzeRecorder("{}"))
    with pytest.raises(VisionHarnessError, match="断言定位器"):
        harness.assert_contains("冷光", "")


def test_assertion_executor_dispatches_visual_assertions():
    class FakeVisionHarness:
        def __init__(self):
            self.called = []

        def assert_contains(self, expected, locator):
            self.called.append((expected, locator))
            return True

        def assert_reference_compare(self, expected, locator):
            self.called.append(("reference", expected, locator))
            return True

    fake = FakeVisionHarness()
    executor = AssertionExecutor(None, vision_harness=fake)
    assert executor.assert_by_type("vision_contains", "'冷光'", "#toolbar") is True
    assert executor.assert_by_type("vision_compare_reference", "页面正常", "#viewer") is True
    assert fake.called == [
        ("'冷光'", "#toolbar"),
        ("reference", "页面正常", "#viewer"),
    ]


def _valid_visual_case(**overrides):
    case = {
        "用例ID": "TC-VISION-001",
        "操作类型": "wait",
        "元素定位器": "0.1",
        "输入数据": "",
        "断言类型": "vision_contains",
        "断言定位器": "#toolbar",
        "验证点": "'冷光'",
        "超时(秒)": "10",
        "_row": 2,
    }
    case.update(overrides)
    return case


def test_case_validator_accepts_visual_assertion_with_explicit_locator():
    validate_cases([_valid_visual_case()])


def test_case_validator_rejects_visual_assertion_without_explicit_locator():
    with pytest.raises(CaseValidationError, match="视觉断言必须填写独立"):
        validate_cases([_valid_visual_case(**{"断言定位器": ""})])


def test_visual_assertion_type_is_identified_for_rerun_policy():
    assert is_visual_assertion({"断言类型": "vision_canvas_ready"}) is True
    assert is_visual_assertion({"断言类型": "vision_compare_reference"}) is True
    assert is_visual_assertion({"操作类型": "click,vision_compare_step"}) is True
    assert is_visual_assertion({"断言类型": "text_visible"}) is False


def test_case_validator_accepts_step_visual_sequence_without_assertion_locator():
    validate_cases(
        [
            {
                "用例ID": "TC-IMAGE-042",
                "操作类型": "vision_compare_step",
                "元素定位器": "body",
                "输入数据": "TC-IMAGE-006/step_005_page_loaded.png",
                "断言类型": "vision_step_sequence",
                "验证点": "1",
                "超时(秒)": "60",
                "_row": 99,
            }
        ]
    )


def test_case_validator_rejects_step_visual_without_reference():
    with pytest.raises(CaseValidationError, match="缺少步骤标准图引用"):
        validate_cases(
            [
                {
                    "用例ID": "TC-IMAGE-042",
                    "操作类型": "vision_compare_step",
                    "元素定位器": "body",
                    "输入数据": "",
                    "断言类型": "vision_step_sequence",
                    "验证点": "1",
                    "_row": 99,
                }
            ]
        )
