from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

from utils.assertion_executor import AssertionExecutor
from utils.case_validator import CaseValidationError, validate_cases
from utils.excel_handler import ExcelHandler
from utils.step_executor import StepExecutionError, StepExecutor


class WaitPage:
    def __init__(self):
        self.waited = []

    def wait_for_timeout(self, milliseconds):
        self.waited.append(milliseconds)


def test_fractional_wait_uses_milliseconds():
    page = WaitPage()
    StepExecutor(page).execute("0.5", "wait", "")
    assert page.waited == [500]


def test_unknown_operation_fails_instead_of_passing():
    with pytest.raises(StepExecutionError, match="不支持的操作类型"):
        StepExecutor(None).execute("", "clik", "")


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


def test_visible_text_alias_uses_real_text_assertion():
    executor = AssertionExecutor(None)
    called = []
    executor._text_visible = lambda expected: called.append(expected) or True
    assert executor.assert_by_type("visible_text", "请输入账号") is True
    assert called == ["请输入账号"]


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
    workbook.close()