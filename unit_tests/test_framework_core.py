from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

from utils.assertion_executor import AssertionExecutor
from utils.case_validator import CaseValidationError, validate_cases
from utils.excel_handler import ExcelHandler
from utils.step_executor import StepExecutionError, StepExecutor
from utils.vision_harness import VisionAssertionMismatch, VisionHarnessError


class WaitPage:
    def __init__(self):
        self.waited = []

    def wait_for_timeout(self, milliseconds):
        self.waited.append(milliseconds)


class ViewportAndHiddenPage(WaitPage):
    def __init__(self):
        super().__init__()
        self.viewport = None
        self.hidden_wait = None

    def set_viewport_size(self, size):
        self.viewport = size

    def locator(self, _locator):
        return self

    @property
    def first(self):
        return self

    def wait_for(self, **kwargs):
        self.hidden_wait = kwargs


def test_fractional_wait_uses_milliseconds():
    page = WaitPage()
    StepExecutor(page).execute("0.5", "wait", "")
    assert page.waited == [500]


def test_visual_viewport_and_loading_wait_are_explicit_steps():
    page = ViewportAndHiddenPage()
    StepExecutor(page, timeout_ms=60000).execute(
        "2561x1398,text=正在努力下载资源",
        "set_viewport,wait_hidden",
        "",
    )
    assert page.viewport == {"width": 2561, "height": 1398}
    assert page.waited == [500]
    assert page.hidden_wait == {"state": "hidden", "timeout": 60000}


def test_step_visual_compare_runs_in_sequence_and_preserves_explicit_wait():
    class FakeVisionHarness:
        def __init__(self):
            self.calls = []

        def assert_step_reference(self, reference_key, locator):
            self.calls.append((reference_key, locator))
            return True

    page = WaitPage()
    vision = FakeVisionHarness()
    executor = StepExecutor(page, case_id="TC-IMAGE-042", vision_harness=vision)
    executor.execute(
        "body,1,body",
        "vision_compare_step,wait,vision_compare_step",
        "TC-IMAGE-006/step_013_FenPing.png|TC-IMAGE-006/step_014_JingXiang.png",
    )

    assert page.waited == [1000]
    assert vision.calls == [
        ("TC-IMAGE-006/step_013_FenPing.png", "body"),
        ("TC-IMAGE-006/step_014_JingXiang.png", "body"),
    ]
    assert executor.vision_step_count == 2
    assert executor.vision_step_failures == []


def test_step_visual_mismatch_is_collected_and_later_steps_continue():
    class FakeVisionHarness:
        def __init__(self):
            self.calls = []

        def assert_step_reference(self, reference_key, locator):
            self.calls.append((reference_key, locator))
            if reference_key == "TC-IMAGE-006/step_005_ChongZhi.png":
                raise VisionAssertionMismatch("关键布局不一致")
            return True

    vision = FakeVisionHarness()
    executor = StepExecutor(WaitPage(), case_id="TC-IMAGE-042", vision_harness=vision)
    executor.execute(
        "body,body",
        "vision_compare_step,vision_compare_step",
        "TC-IMAGE-006/step_005_ChongZhi.png|TC-IMAGE-006/step_006_GuanBiao.png",
    )

    assert [call[0] for call in vision.calls] == [
        "TC-IMAGE-006/step_005_ChongZhi.png",
        "TC-IMAGE-006/step_006_GuanBiao.png",
    ]
    assert executor.vision_step_count == 2
    assert len(executor.vision_step_failures) == 1
    assert "step_005_ChongZhi.png" in executor.vision_step_failures[0]


def test_step_visual_infrastructure_error_still_stops_immediately():
    class BrokenVisionHarness:
        def assert_step_reference(self, _reference_key, _locator):
            raise VisionHarnessError("模型服务不可用")

    executor = StepExecutor(
        WaitPage(), case_id="TC-IMAGE-042", vision_harness=BrokenVisionHarness()
    )
    with pytest.raises(VisionHarnessError, match="模型服务不可用"):
        executor.execute(
            "body,body",
            "vision_compare_step,vision_compare_step",
            "TC-IMAGE-006/step_005_ChongZhi.png|TC-IMAGE-006/step_006_GuanBiao.png",
        )
    assert executor.vision_step_count == 0
    assert executor.vision_step_failures == []


def test_unknown_operation_fails_instead_of_passing():
    with pytest.raises(StepExecutionError, match="不支持的操作类型"):
        StepExecutor(None).execute("", "clik", "")


class _InputPage:
    """记录 input 步骤最终填入的内容"""

    def __init__(self):
        self.filled = None

    def locator(self, _selector):
        return self

    @property
    def first(self):
        return self

    def wait_for(self, **kwargs):
        return None

    def fill(self, text):
        self.filled = text

    def wait_for_timeout(self, _ms):
        pass


def test_retry_report_locator_uses_pipe_separator():
    """retry_report 的定位器用 | 分隔三个部分，逗号分割后必须保持为一个定位器项"""
    locator = "text=查看报告|text=完 成|.ant-checkbox-group .ant-image"
    locs = [item.strip() for item in locator.split(",")]
    assert len(locs) == 1
    parts = [p.strip() for p in locs[0].split("|")]
    assert len(parts) == 3
    assert parts[0] == "text=查看报告" and parts[1] == "text=完 成"


def test_find_click_validation_locator_stays_single_item():
    """find_click 的「共检测|验证定位器」格式在逗号分割后必须保持为一个定位器项"""
    locs = [item.strip() for item in "共检测|.ant-image + div .anticon".split(",")]
    assert locs == ["共检测|.ant-image + div .anticon"]


def test_space_only_input_is_not_stripped_to_empty():
    """纯空格输入应保留为空格，而不是被 strip 成空串（TC-DETAIL-019 空格标签）"""
    page = _InputPage()
    StepExecutor(page).execute("input[placeholder='请输入标签内容']", "input", " ")
    assert page.filled == " "


def test_empty_input_still_fills_empty_string():
    page = _InputPage()
    StepExecutor(page).execute("input[placeholder='请输入标签内容']", "input", "")
    assert page.filled == ""


def test_date_range_parser_supports_slash_and_iso_dates():
    assert StepExecutor._parse_date_range("2026/1/2-2026/6/28") == (
        "2026-01-02",
        "2026-06-28",
    )
    assert StepExecutor._parse_date_range("2026-01-02~2026-06-28") == (
        "2026-01-02",
        "2026-06-28",
    )


def test_unknown_assertion_fails_instead_of_passing():
    with pytest.raises(AssertionError, match="未知断言类型"):
        AssertionExecutor(None).assert_by_type("visible_tex", "任意文本")


def test_vision_step_sequence_requires_all_expected_comparisons():
    assert (
        AssertionExecutor(None, vision_step_count=10).assert_by_type(
            "vision_step_sequence", "共10次步骤视觉比较"
        )
        is True
    )
    with pytest.raises(AssertionError, match="期望 10，实际 9"):
        AssertionExecutor(None, vision_step_count=9).assert_by_type(
            "vision_step_sequence", "10"
        )
    with pytest.raises(AssertionError, match="存在 1 个不一致"):
        AssertionExecutor(
            None,
            vision_step_count=10,
            vision_step_failures=["step_006_GuanBiao.png: 关键布局不一致"],
        ).assert_by_type("vision_step_sequence", "10")


def test_visible_text_alias_uses_real_text_assertion():
    executor = AssertionExecutor(None)
    called = []
    executor._text_visible = lambda expected: called.append(expected) or True
    assert executor.assert_by_type("visible_text", "请输入账号") is True
    assert called == ["请输入账号"]


def test_text_hidden_dispatches_to_hidden_assertion():
    executor = AssertionExecutor(None)
    called = []
    executor._text_hidden = lambda expected: called.append(expected) or True
    assert executor.assert_by_type("text_hidden", "不显示'自动化标签测试1'标签") is True
    assert called == ["不显示'自动化标签测试1'标签"]


def test_element_disabled_dispatches_to_disabled_assertion():
    executor = AssertionExecutor(None)
    called = []
    executor._element_disabled = lambda locator: called.append(locator) or True
    assert executor.assert_by_type("element_disabled", "提交按钮禁用", "button.ant-btn-primary") is True
    assert called == ["button.ant-btn-primary"]


def test_value_equals_dispatches_to_value_assertion():
    executor = AssertionExecutor(None)
    called = []
    executor._value_equals = lambda expected, locator: called.append((expected, locator)) or True
    assert executor.assert_by_type("value_equals", "空", "input[placeholder='请输入家庭住址']") is True
    assert called == [("空", "input[placeholder='请输入家庭住址']")]


def _valid_case(**overrides):
    case = {
        "用例ID": "TC-DEMO-001",
        "操作类型": "wait",
        "元素定位器": "0.5",
        "输入数据": "",
        "断言类型": "url_contains",
        "验证点": "'/home'",
        "超时(秒)": "5",
        "_row": 2,
    }
    case.update(overrides)
    return case


def test_case_validator_rejects_invalid_wait_and_assertion():
    with pytest.raises(CaseValidationError) as exc_info:
        validate_cases([_valid_case(**{"元素定位器": "later", "断言类型": "unknown"})])
    message = str(exc_info.value)
    assert "wait 定位器必须是非负秒数" in message
    assert "不支持的断言类型" in message


def test_excel_reader_keeps_real_rows_and_batch_writes(tmp_path: Path):
    path = tmp_path / "cases.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "自动化测试用例"
    sheet.append(["用例ID", "模块", "实际结果"])
    sheet.append(["TC-A", "登录", ""])
    sheet.append([None, None, None])
    sheet.append(["TC-B", "首页", ""])
    workbook.save(path)
    workbook.close()

    handler = ExcelHandler(str(path))
    cases = handler.read_test_cases()
    assert [case["_row"] for case in cases] == [2, 4]

    handler.write_results([("TC-A", "pass", 2), ("TC-B", "fail: demo", 4)])
    workbook = load_workbook(path, read_only=True)
    sheet = workbook.active
    assert sheet.cell(2, 3).value == "pass"
    assert sheet.cell(4, 3).value == "fail: demo"
    # 失败用例应标红（浅红背景），通过用例不标红
    assert sheet.cell(4, 3).fill.start_color.rgb == "FFFFC7CE"
    assert sheet.cell(2, 3).fill.start_color.rgb != "FFFFC7CE"
    workbook.close()


def test_excel_result_writes_visual_failure_step_to_note_and_clears_it_on_pass(
    tmp_path: Path,
):
    path = tmp_path / "visual-cases.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "自动化测试用例"
    sheet.append(["用例ID", "备注", "实际结果"])
    sheet.append(["TC-IMAGE-042", "标准图只读", ""])
    workbook.save(path)
    workbook.close()

    handler = ExcelHandler(str(path))
    handler.write_results([
        (
            "TC-IMAGE-042",
            "fail: 视觉不一致",
            2,
            "步骤13（step_013_FenPing.png）、步骤14（step_014_JingXiang.png）",
        )
    ])
    workbook = load_workbook(path, read_only=True)
    sheet = workbook.active
    assert sheet.cell(2, 2).value == (
        "标准图只读\n【自动化失败步骤】"
        "步骤13（step_013_FenPing.png）、步骤14（step_014_JingXiang.png）"
    )
    workbook.close()

    handler.write_results([("TC-IMAGE-042", "pass", 2, "")])
    workbook = load_workbook(path, read_only=True)
    sheet = workbook.active
    assert sheet.cell(2, 2).value == "标准图只读"
    assert sheet.cell(2, 3).value == "pass"
    workbook.close()


def test_visual_failure_note_extracts_and_deduplicates_failed_steps():
    from tests.conftest import _visual_failure_note

    reason = (
        "步骤视觉比较存在 2 个不一致：\n"
        "- TC-IMAGE-006/step_013_FenPing.png: 布局=mismatch\n"
        "- TC-IMAGE-006/step_014_JingXiang.png: 关键元素=mismatch\n"
        "重复引用 step_013_FenPing.png"
    )
    assert _visual_failure_note(reason) == (
        "步骤13（step_013_FenPing.png）、步骤14（step_014_JingXiang.png）"
    )
