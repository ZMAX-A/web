import importlib.util
from pathlib import Path

import pytest

from utils.excel_handler import ExcelHandler


@pytest.mark.parametrize("scenario", ["登录成功", "登录失败-错误密码"])
def test_keyword_login_does_not_replace_real_store_response(monkeypatch, scenario):
    # 加载真实执行器，但不读取用户正在编辑的业务工作簿。
    monkeypatch.setattr(ExcelHandler, "detect_format", lambda self: "new")
    monkeypatch.setattr(ExcelHandler, "read_test_cases", lambda self: [])
    path = Path(__file__).resolve().parents[1] / "tests" / "test_core_cases.py"
    spec = importlib.util.spec_from_file_location("login_store_runtime", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class Page:
        def route(self, pattern, handler):
            raise AssertionError("普通关键字登录不得注入模拟接口响应")

        def wait_for_timeout(self, milliseconds):
            raise AssertionError("文本断言前不得固定等待，以免错过短暂提示")

    page = Page()
    operations = []
    assertions = []

    class Steps:
        vision_step_count = 0
        vision_step_failures = []

        def __init__(self, current_page, *args, **kwargs):
            assert current_page is page

        def execute(self, locators, types, data):
            operations.append((locators, types, data))

        def get_current_page(self):
            return page

    class Assertions:
        def __init__(self, current_page, **kwargs):
            assert current_page is page

        def assert_by_type(self, assertion_type, expected, locator):
            assertions.append((assertion_type, expected, locator))
            return True

    monkeypatch.setattr(module, "StepExecutor", Steps)
    monkeypatch.setattr(module, "AssertionExecutor", Assertions)
    runner = module.TestCoreCases()
    monkeypatch.setattr(runner, "_handle_preconditions", lambda *args: None)
    case = {
        "用例ID": "TC-LOGIN-007",
        "模块": "账号登录",
        "测试场景": scenario,
        "元素定位器": "#username,#password,#store,button[type='submit']",
        "操作类型": "input,input,click,click",
        "输入数据": "${TEST_USERNAME}|${TEST_PASSWORD}",
        "断言类型": "text_contains",
        "验证点": "测试断言",
    }

    runner._execute_new(case, page, None, "test-user", "test-password", "", "https://test.invalid/login")

    assert operations == [(case["元素定位器"], case["操作类型"], "test-user|test-password")]
    assert assertions == [("text_contains", "测试断言", "button[type='submit']")]
