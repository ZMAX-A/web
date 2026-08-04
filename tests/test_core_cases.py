"""
通用测试用例 —— 数据驱动执行

核心逻辑：
1. 自动检测 Excel 格式（新版16列 / 旧版10列）
2. 新版格式：直接用 StepExecutor 执行操作 + AssertionExecutor 执行断言
3. 旧版格式：走 if/elif 路由到对应页面对象方法

Allure 集成：
- 每条测试用例自动添加 feature（模块）、story（场景）、testcase（用例ID）标签
"""
import sys
import re
import logging
from pathlib import Path

import pytest
import allure

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.excel_handler import ExcelHandler
from utils.step_executor import StepExecutor
from utils.assertion_executor import AssertionExecutor

logger = logging.getLogger("test_core_cases")


# ==================== 加载测试用例 ====================

def _load_test_cases() -> list[dict]:
    cases_dir = Path(__file__).parent.parent / "test_cases"
    for fname in ["test_case.xlsx", "yanjia_ai_overseas_test_cases.xlsx", "core_test_cases.xlsx"]:
        path = cases_dir / fname
        if path.exists():
            handler = ExcelHandler(str(path))
            fmt = handler.detect_format()
            logger.info(f"已加载: {fname} (格式: {fmt})")
            return handler.read_test_cases()
    raise FileNotFoundError("test_cases/ 目录下没有可用的 Excel 文件")

ALL_TEST_CASES = _load_test_cases()
IS_NEW_FORMAT = bool(ALL_TEST_CASES and "用例ID" in ALL_TEST_CASES[0])
logger.info(f"共 {len(ALL_TEST_CASES)} 条用例，格式: {'新版关键字驱动' if IS_NEW_FORMAT else '旧版'}")


# ==================== 旧版用常量 ====================

MOCK_STORE_RESPONSE = '''{"code":0,"msg":"success","data":[{"access":"mock","organization_id":1,"organization_name":"默认门店","organization_icon":""}]}'''


# ==================== 测试 ID 生成 ====================

def _make_test_id(case: dict) -> str:
    if IS_NEW_FORMAT:
        cid = case.get("用例ID", "")
        scene = case.get("测试场景", "")
        return f"[{cid}] {scene}" if scene else str(cid)
    else:
        cid = case.get("编号", "")
        feature = case.get("功能点", "")
        mod = case.get("模块", "")
        return f"[{cid}] {mod}-{feature}" if feature else str(cid)


# ==================== 数据驱动测试 ====================

@pytest.mark.parametrize(
    "test_case",
    ALL_TEST_CASES,
    ids=[_make_test_id(c) for c in ALL_TEST_CASES],
)
class TestCoreCases:
    """通用测试用例：新版自动执行 + 旧版路由兼容"""

    @allure.step("执行数据驱动测试")
    def test_execute(
        self,
        test_case: dict,
        page,
        login_page,
        home_page,
        case_list_page,
        add_case_page,
        customer_list_page,
        settings_page,
        base_url,
        test_username,
        test_password,
    ):
        if IS_NEW_FORMAT:
            self._execute_new(test_case, page, login_page, test_username, test_password)
        else:
            self._execute_old(
                test_case, page, login_page, home_page, case_list_page,
                add_case_page, customer_list_page, settings_page,
                base_url, test_username, test_password,
            )

    # ==================== 新版：Excel 规范直接驱动 ====================

    @allure.step("新版关键字驱动执行")
    def _execute_new(self, test_case, page, login_page, test_username, test_password):
        case_id = test_case.get("用例ID", "")
        module = test_case.get("模块", "")
        scenario = test_case.get("测试场景", "")
        preconditions = test_case.get("前置条件", "")
        locators_str = test_case.get("元素定位器", "")
        operations_str = test_case.get("操作类型", "")
        data_str = str(test_case.get("输入数据", "") or "")
        data_str = data_str.replace("${TEST_USERNAME}", test_username)
        data_str = data_str.replace("${TEST_PASSWORD}", test_password)
        expected = test_case.get("期望结果", "")
        verify_point = test_case.get("验证点", "")
        assert_type = test_case.get("断言类型", "")

        logger.info(f"执行 [{case_id}] {module} - {scenario}")

        # 如果定位器包含 #store，mock 门店 API 避免假账号无法加载
        if "#store" in locators_str:
            call_count = [0]
            def store_or_login(route):
                call_count[0] += 1
                if call_count[0] == 1:
                    # 第一次：返回门店数据（用真实access格式让前端正确解析）
                    route.fulfill(status=200, content_type="application/json",
                        body='{"code":0,"msg":"success","data":[{"access":"eyJpdiI6IkFLUEtaQ0ltWjA3aUQrTk5oaDRsQXc9PSIsInZhbHVlIjoiVnJ5cFZaTjQrS1RoNlJnYmk4S3E5Uk5uaGpCdjYwWnpRcTd1WWxIOVJkTUt5UFRpcGJSa1JONkNhOGRjYnBJSUtIWFU4d1ZKWUF0eVhhRjZmaXYxYUE9PSIsIm1hYyI6IjQ4YjFkNzE3MjU0MmQ1MWUxNmE2ZTQ2MmM2ZWY5Mjk3Yjg1NTU4NTkxZWIwOTJkY2Q2MjY3MTAwYjY4NWE3ZDAiLCJ0YWciOiIifQ==","organization_id":1,"organization_name":"默认门店","organization_icon":""}]}')
                else:
                    # 第二次及以后：透传到真实 API（登录验证）
                    route.continue_()
            page.route("**/accesses", store_or_login)

        # 处理前置条件
        self._handle_preconditions(preconditions, page, login_page, test_username, test_password)

        # 执行操作步骤
        executor = StepExecutor(page)
        executor.execute(locators_str, operations_str, data_str)

        # 执行断言
        # 【健壮性】locators_str 可能为空，split 前做空值保护
        locator_list = [l.strip() for l in locators_str.split(",") if l.strip()] if locators_str else []
        last_locator = locator_list[-1] if locator_list else ""
        # 等待页面稳定后再断言（Toast 消息需要时间渲染）
        page.wait_for_timeout(2000)
        assertion = AssertionExecutor(page)
        assertion.assert_by_type(assert_type, verify_point or expected, last_locator)

        logger.info(f"[{case_id}] ✅ 完成")

    @allure.step("处理前置条件: {preconditions}")
    def _handle_preconditions(self, preconditions, page, login_page, test_username, test_password):
        if not preconditions:
            return
        pc = preconditions.strip()
        if "已登录" in pc or "登录成功" in pc:
            login_page.open()
            login_page.login(test_username, test_password, select_store=True)
            login_page.assert_login_success()
            # 【健壮性】「知道了」按钮可能出现延迟，重试 2 次确保点击成功
            for _ in range(2):
                try:
                    page.get_by_text("知道了").click()
                    page.wait_for_timeout(1000)
                    break
                except Exception:
                    page.wait_for_timeout(500)
        elif "打开登录" in pc or "未登录" in pc:
            login_page.open()

    # ==================== 旧版：路由兼容 ====================

    @allure.step("旧版兼容模式执行")
    def _execute_old(
        self, test_case, page, login_page, home_page, case_list_page,
        add_case_page, customer_list_page, settings_page,
        base_url, test_username, test_password
    ):
        """兼容旧版10列格式的 if/elif 路由逻辑"""
        module = test_case.get("模块", "")
        feature = test_case.get("功能点", "")
        action = test_case.get("输入动作", "")
        input_data_str = test_case.get("输入数据", "")
        expected = test_case.get("期望结果", "")
        case_id = test_case.get("编号", "")

        data = self._parse_input_data(input_data_str)
        logger.info(f"执行 [{case_id}] {module} - {feature}")

        if module == "登录":
            self._test_login_old(login_page, feature, data, test_username, test_password, expected)
        elif "公共案例库" in module:
            pytest.skip("「新增公共案例库」模块待实现")
        elif "声光联合" in module:
            pytest.skip("「新增声光联合报告」模块待实现")
        elif "数字工牌" in module:
            pytest.skip("「新增数字工牌功能」模块待实现")
        elif "检测报告单" in module:
            pytest.skip("「检测报告单」模块待实现")
        elif "新增" in module or "图片" in module or "上传" in module:
            self._test_add_case_old(login_page, case_list_page, add_case_page, feature, action, data, test_username, test_password, expected)
        elif "案例" in module:
            self._test_case_list_old(login_page, case_list_page, feature, action, data, test_username, test_password, expected)
        elif "首页" in module:
            self._test_home_old(home_page, login_page, feature, action, data, test_username, test_password, expected)
        elif "顾客" in module or "档案" in module:
            self._test_customer_list_old(login_page, home_page, customer_list_page, feature, action, data, test_username, test_password, expected)
        elif "设置" in module:
            self._test_settings_old(login_page, home_page, settings_page, feature, action, data, test_username, test_password, expected)
        else:
            pytest.skip(f"未配置模块「{module}」跳过")
        logger.info(f"[{case_id}] ✅ 完成")

    # ---- 旧版子方法 ----

    def _parse_input_data(self, input_data: str) -> dict:
        if not input_data or input_data.strip() in ("/", "-", ""):
            return {}
        result = {}
        parts = re.split(r"[，,\n]", input_data)
        for part in parts:
            part = part.strip()
            if not part:
                continue
            if "：" in part:
                key, val = part.split("：", 1)
                result[key.strip()] = val.strip()
            elif ":" in part:
                key, val = part.split(":", 1)
                result[key.strip()] = val.strip()
        return result

    @allure.step("公共登录")
    def _ensure_logged_in(self, login_page, username, password, page=None):
        login_page.open()
        login_page.login(username, password, select_store=True)
        login_page.assert_login_success()
        if page:
            # 【健壮性】「知道了」按钮可能出现延迟，重试 2 次确保点击成功
            for _ in range(2):
                try:
                    page.get_by_text("知道了").click()
                    page.wait_for_timeout(1000)
                    break
                except Exception:
                    page.wait_for_timeout(500)
        logger.info("✅ 已登录")

    @allure.step("登录模块旧版测试: {feature}")
    def _test_login_old(self, login_page, feature, data, test_username, test_password, expected):
        login_page.open()
        login_page.assert_page_loaded()
        assert_key = self._extract_assert_keyword(expected)

        if "不存在的账号" in feature:
            api_count = [0]
            def mock_then_real(route):
                api_count[0] += 1
                if api_count[0] == 1:
                    route.fulfill(status=200, content_type="application/json", body=MOCK_STORE_RESPONSE)
                else:
                    route.continue_()
            login_page.page.route("**/accesses", mock_then_real)
            login_page.enter_username("test123")
            login_page.enter_password(test_password)
            login_page.select_first_store()
            login_page.click_login()
            login_page.assert_error_message(assert_key or "登录失败")

        elif "错误的密码" in feature:
            api_count = [0]
            def mock_then_real(route):
                api_count[0] += 1
                if api_count[0] == 1:
                    route.fulfill(status=200, content_type="application/json", body=MOCK_STORE_RESPONSE)
                else:
                    route.continue_()
            login_page.page.route("**/accesses", mock_then_real)
            login_page.enter_username(test_username)
            login_page.enter_password("wrong123")
            login_page.select_first_store()
            login_page.click_login()
            login_page.assert_error_message(assert_key or "登录失败")

        elif "不输入账号密码" in feature:
            login_page.click_login()
            try:
                login_page.assert_error_message(assert_key or "请输入")
            except AssertionError:
                login_page.assert_error_message("请选择")

        elif "正常登录" in feature:
            username = data.get("账号", "")
            password = data.get("密码", "")
            has_chinese = bool(re.search(r'[一-鿿]', username + password))
            if has_chinese or not username:
                username = test_username
                password = test_password
            login_page.login(username, password, select_store=True)
            login_page.assert_login_success()

        elif "记住我" in feature:
            logger.warning("页面无「记住我」功能，降级为普通登录")
            login_page.login(test_username, test_password, select_store=True)
            login_page.assert_login_success()
        else:
            login_page.assert_page_loaded()

    @allure.step("案例列表旧版测试: {feature}")
    def _test_case_list_old(self, login_page, case_list_page, feature, action, data, test_username, test_password, expected):
        self._ensure_logged_in(login_page, test_username, test_password)
        case_list_page.open()
        case_list_page.assert_page_loaded()
        if "不存在的关键词" in feature or "不存在" in feature:
            case_list_page.search_keyword(data.get("关键词", "xxxxyyyy"))
            case_list_page.assert_no_results()
        elif "部分关键词" in feature:
            case_list_page.search_keyword(data.get("关键词", "测试"))
            case_list_page.assert_cases_contain("测试")
        elif "全部关键词" in feature or "全关键词" in feature:
            case_list_page.search_keyword(data.get("关键词", "测试"))
            case_list_page.assert_cases_contain("测试")
        elif "删除" in feature and "未选中" in feature:
            case_list_page.click_manage()
            case_list_page.click_delete()
            case_list_page.assert_toast_message("请选择")
        elif "删除" in feature and "选中" in feature and "确认" not in feature:
            case_list_page.click_manage()
            case_list_page.select_case(0)
            case_list_page.click_delete()
            case_list_page.assert_delete_prompt()
        elif "取消" in feature:
            case_list_page.click_manage()
            case_list_page.select_case(0)
            case_list_page.click_delete()
            case_list_page.click_cancel()
            case_list_page.assert_page_loaded()
        elif "删除" in feature:
            case_list_page.click_manage()
            case_list_page.select_case(0)
            case_list_page.click_delete()
            case_list_page.confirm_delete()
            case_list_page.assert_toast_message("删除成功")
        elif "分类" in feature:
            case_list_page.assert_categories_displayed()
        else:
            case_list_page.assert_page_loaded()

    @allure.step("新增案例旧版测试: {feature}")
    def _test_add_case_old(self, login_page, case_list_page, add_case_page, feature, action, data, test_username, test_password, expected):
        self._ensure_logged_in(login_page, test_username, test_password)
        if "不填写" in action or "不填" in action:
            add_case_page.open()
            add_case_page.assert_page_loaded()
            add_case_page.click_save()
            add_case_page.wait_for_stable()
            assert "case" in add_case_page.page.url, f"保存后异常: {add_case_page.page.url}"
        elif "填写" in action and "保存" in action:
            add_case_page.open()
            add_case_page.assert_page_loaded()
            add_case_page.create_case(data.get("案例名称", "自动化测试案例"))
            add_case_page.assert_save_success()
        elif "列表" in action or "查看" in action:
            case_list_page.open()
            case_list_page.assert_page_loaded()
        elif "搜索" in action:
            case_list_page.open()
            case_list_page.assert_page_loaded()
            case_list_page.search_keyword("u")
            case_list_page.wait_for_stable()
        else:
            case_list_page.open()
            case_list_page.click_add_case()
            add_case_page.assert_page_loaded()

    @allure.step("首页旧版测试: {feature}")
    def _test_home_old(self, home_page, login_page, feature, action, data, test_username, test_password, expected):
        self._ensure_logged_in(login_page, test_username, test_password)
        home_page.open()
        home_page.close_modal_if_present()
        home_page.assert_page_loaded()
        if "不存在" in feature:
            home_page.search_patient(data.get("关键字", "不存在的用户xxxx"))
        elif "存在" in feature or "搜索" in feature:
            home_page.search_patient(data.get("关键字", "咨询01"))
        elif "数量" in feature or "档案" in feature:
            home_page.assert_patient_card_visible()
            home_page.get_patient_count_text()
        else:
            home_page.assert_page_loaded()

    @allure.step("顾客档案旧版测试: {feature}")
    def _test_customer_list_old(self, login_page, home_page, customer_list_page, feature, action, data, test_username, test_password, expected):
        self._ensure_logged_in(login_page, test_username, test_password)
        customer_list_page.open()
        customer_list_page.assert_page_loaded()
        if "不存在" in feature:
            customer_list_page.search_keyword(data.get("关键字", "不存在的用户xxxx"))
        elif "存在" in feature or "搜索" in feature:
            customer_list_page.search_keyword(data.get("关键字", "ZWG"))
            customer_list_page.assert_search_has_results()
        elif "手机号" in feature:
            customer_list_page.search_keyword(data.get("关键字", "188"))
            customer_list_page.assert_search_has_results()
        else:
            customer_list_page.assert_page_loaded()

    @allure.step("设置模块旧版测试: {feature}")
    def _test_settings_old(self, login_page, home_page, settings_page, feature, action, data, test_username, test_password, expected):
        self._ensure_logged_in(login_page, test_username, test_password)
        settings_page.open()
        settings_page.assert_page_loaded()
        if "语言" in feature:
            settings_page.click_language()
        elif "水印" in feature:
            settings_page.click_watermark()
        elif "个人中心" in feature:
            settings_page.click_personal_center()
        elif "最近删除" in feature:
            settings_page.click_recent_delete()
        elif "退出登录" in feature or "退出" in feature:
            settings_page.click_logout()
            settings_page.confirm_logout()
            settings_page.assert_logout_success()
        elif "报告解读" in feature:
            settings_page.click_report_toggle()
        elif "云存储" in feature:
            settings_page.click_cloud_storage()
        else:
            settings_page.assert_page_loaded()

    @staticmethod
    def _extract_assert_keyword(text: str) -> str:
        if not text:
            return ""
        text = re.sub(r'^\d+[\.\、\s]+', '', text.strip())
        match = re.search(r'提示[\s:]*[“”"\']?([^“”"\']*)[“”"\']?', text)
        if match:
            return match.group(1).strip()
        return text[:30].strip()
