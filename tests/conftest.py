"""
pytest 全局配置文件 —— 提供 fixture 和 hook

【Allure 集成说明】
1. 测试报告改用 Allure（替代 pytest-html）
2. 自动为每条用例添加 Allure 特性/故事/用例ID 标签
3. 失败时自动截图附加到 Allure 报告
4. 环境信息写入 allure-results/environment.properties
5. Excel 结果回写增加异常处理，避免因回写失败导致测试中断
"""
import os
import sys
import logging
from pathlib import Path
from datetime import datetime

import pytest
import allure
from dotenv import load_dotenv

# 将项目根目录加入 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from pages.login_page import LoginPage
from pages.home_page import HomePage
from pages.case_list_page import CaseListPage
from pages.add_case_page import AddCasePage
from pages.customer_list_page import CustomerListPage
from pages.settings_page import SettingsPage
from pages.academy_page import AcademyPage
from pages.public_case_library_page import PublicCaseLibraryPage
from pages.customer_detail_page import CustomerDetailPage
from pages.watermark_settings_page import WatermarkSettingsPage
from pages.personal_center_page import PersonalCenterPage
from pages.recently_deleted_page import RecentlyDeletedPage
from pages.cloud_storage_page import CloudStoragePage
from utils.excel_handler import ExcelHandler

# ==================== 日志配置 ====================
# 【新增】统一的日志配置，测试运行时的所有日志都会显示
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pytest_conftest")

# ==================== 加载环境变量 ====================
load_dotenv()


# ==================== 环境变量 fixture ====================

@pytest.fixture(scope="session")
def base_url() -> str:
    """被测系统地址"""
    url = os.getenv("BASE_URL", "https://your-test-site.com")
    logger.info(f"BASE_URL = {url}")
    return url


@pytest.fixture(scope="session")
def test_username() -> str:
    """测试账号"""
    username = os.getenv("TEST_USERNAME", "")
    logger.info("TEST_USERNAME 已配置: %s", bool(username))
    return username


@pytest.fixture(scope="session")
def test_password() -> str:
    """测试密码"""
    password = os.getenv("TEST_PASSWORD", "")
    logger.info("TEST_PASSWORD = ******")
    return password


@pytest.fixture(scope="session")
def store_name() -> str:
    """登录门店名称；留空则默认选择第一个门店"""
    name = os.getenv("STORE_NAME", "").strip()
    logger.info(f"STORE_NAME = {name or '(未配置，默认第一个门店)'}")
    return name


# ==================== 页面对象 fixture ====================

@pytest.fixture
def login_page(page, base_url) -> LoginPage:
    """登录页对象"""
    return LoginPage(page, base_url)


@pytest.fixture
def case_list_page(page, base_url) -> CaseListPage:
    """案例列表页对象"""
    return CaseListPage(page, base_url)


@pytest.fixture
def add_case_page(page, base_url) -> AddCasePage:
    """新增案例页对象"""
    return AddCasePage(page, base_url)


@pytest.fixture
def home_page(page, base_url) -> HomePage:
    """首页页面对象"""
    return HomePage(page, base_url)


@pytest.fixture
def customer_list_page(page, base_url) -> CustomerListPage:
    """顾客档案列表页面对象"""
    return CustomerListPage(page, base_url)


@pytest.fixture
def settings_page(page, base_url) -> SettingsPage:
    """设置页面对象"""
    return SettingsPage(page, base_url)


@pytest.fixture
def academy_page(page, base_url) -> AcademyPage:
    """美际学院页面对象"""
    return AcademyPage(page, base_url)


@pytest.fixture
def public_case_library_page(page, base_url) -> PublicCaseLibraryPage:
    """公共案例库页面对象"""
    return PublicCaseLibraryPage(page, base_url)


@pytest.fixture
def customer_detail_page(page, base_url) -> CustomerDetailPage:
    """顾客详情页面对象"""
    return CustomerDetailPage(page, base_url)


@pytest.fixture
def watermark_settings_page(page, base_url) -> WatermarkSettingsPage:
    """水印设置页面对象"""
    return WatermarkSettingsPage(page, base_url)


@pytest.fixture
def personal_center_page(page, base_url) -> PersonalCenterPage:
    """个人中心页面对象"""
    return PersonalCenterPage(page, base_url)


@pytest.fixture
def recently_deleted_page(page, base_url) -> RecentlyDeletedPage:
    """最近删除页面对象"""
    return RecentlyDeletedPage(page, base_url)


@pytest.fixture
def cloud_storage_page(page, base_url) -> CloudStoragePage:
    """云存储管理页面对象"""
    return CloudStoragePage(page, base_url)


# ==================== 登录状态复用（全量测试加速）====================

@pytest.fixture(scope="session")
def auth_state_file() -> Path:
    """登录状态缓存文件路径，用于跨测试用例复用登录态。"""
    return Path(__file__).parent.parent / ".auth_state.json"


@pytest.fixture(scope="session", autouse=True)
def clean_auth_state(auth_state_file):
    """测试前后都清理登录缓存，避免 Cookie/LocalStorage 长期落盘。"""
    if auth_state_file.exists():
        auth_state_file.unlink()
        logger.info("已清理旧的登录状态缓存")
    try:
        yield
    finally:
        if auth_state_file.exists():
            auth_state_file.unlink()
            logger.info("测试结束，已删除登录状态缓存")


@pytest.fixture(scope="function")
def browser_context_args(auth_state_file):
    """
    覆写 playwright 的 browser_context_args 注入已保存的登录状态。
    首个「已登录」用例会执行真实登录并保存 state，后续用例自动复用。
    """
    if auth_state_file.exists():
        logger.info("▸ 复用已保存的登录状态，跳过登录流程")
        return {"storage_state": str(auth_state_file)}
    return {}


# ==================== 公共登录 fixture（测试隔离）====================

@pytest.fixture
def common_login(page, base_url, test_username, test_password, login_page, home_page, store_name):
    """
    公共登录 fixture：每个测试用例独立使用，避免状态污染。

    使用方法：
        def test_xxx(self, common_login):
            home_page = common_login['home_page']
            # 此时已登录并关闭了弹窗，可直接操作首页
    """
    # 执行登录（STORE_NAME 留空时自动选第一个门店）
    login_page.open()
    login_page.login(test_username, test_password, select_store=True, store_name=store_name)
    login_page.assert_login_success()

    # 关闭可能出现的续费弹窗
    home_page.close_modal_if_present()

    return {
        'page': page,
        'login_page': login_page,
        'home_page': home_page,
    }


# ==================== 获取 Excel 路径 ====================

def _get_excel_path() -> str:
    """按优先级查找可用的 Excel 文件"""
    base = Path(__file__).parent.parent / "test_cases"
    for fname in ["test_case.xlsx", "yanjia_ai_overseas_test_cases.xlsx", "core_test_cases.xlsx"]:
        path = base / fname
        if path.exists():
            return str(path)
    return str(base / "test_case.xlsx")


# ==================== 测试结果收集 Hook ====================

@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """
    拦截每个测试阶段的执行结果，保存到 item 对象上供后续使用。
    """
    outcome = yield
    rep = outcome.get_result()
    setattr(item, "rep_" + rep.when, rep)


def _case_data_from_item(item) -> dict | None:
    """从参数化 pytest item 中取得 Excel 用例。"""
    if not hasattr(item, "callspec"):
        return None
    return item.callspec.params.get("test_case")


@pytest.fixture(autouse=True)
def auto_result_handler(request, page):
    """设置 Allure 标签，并在 setup/call 失败时保存现场截图。"""
    test_case_data = _case_data_from_item(request.node)
    if test_case_data:
        case_id = test_case_data.get("用例ID", "") or test_case_data.get("编号", "")
        module = test_case_data.get("模块", "")
        scenario = test_case_data.get("测试场景", "") or test_case_data.get("功能点", "")
        if case_id:
            allure.dynamic.testcase(case_id)
            allure.dynamic.title(f"[{case_id}] {scenario}" if scenario else case_id)
        if module:
            allure.dynamic.feature(module)
            allure.dynamic.label("module", module)
        if scenario:
            allure.dynamic.story(scenario)

    yield

    if not test_case_data:
        return
    reports = [
        getattr(request.node, "rep_setup", None),
        getattr(request.node, "rep_call", None),
    ]
    failed_report = next((report for report in reports if report and report.failed), None)
    if not failed_report:
        return

    case_id = test_case_data.get("用例ID", "") or test_case_data.get("编号", "") or request.node.name
    fail_reason = str(failed_report.longrepr)[:300] if failed_report.longrepr else "未知失败"
    try:
        page.title()  # 页面上下文关闭时会在这里失败，避免重复报错。
        screenshot_bytes = page.screenshot(full_page=True)
        if len(screenshot_bytes) <= 10000:
            logger.warning("截图太小（%s字节），可能为空白页，跳过保存", len(screenshot_bytes))
        else:
            allure.attach(
                screenshot_bytes,
                name=f"{case_id}_失败截图",
                attachment_type=allure.attachment_type.PNG,
            )
            screenshot_dir = Path(__file__).parent.parent / "screenshots"
            screenshot_dir.mkdir(parents=True, exist_ok=True)
            safe_name = str(case_id).replace("/", "_").replace("\\", "_").replace(":", "_")
            timestamp = datetime.now().strftime("%m%d_%H%M%S")
            screenshot_path = screenshot_dir / f"{safe_name}_{timestamp}.png"
            screenshot_path.write_bytes(screenshot_bytes)
            logger.info("失败截图已保存: %s", screenshot_path)
    except Exception as exc:
        logger.warning("截图失败（不影响测试结论）: %s", exc)

    allure.attach(
        fail_reason,
        name=f"{case_id}_失败原因",
        attachment_type=allure.attachment_type.TEXT,
    )


def pytest_sessionfinish(session, exitstatus):
    """所有 teardown 完成后一次性把 setup/call/teardown 的最终结果写回 Excel。"""
    updates: list[tuple[str, str, int | None]] = []
    for item in session.items:
        test_case_data = _case_data_from_item(item)
        if not test_case_data:
            continue
        case_id = test_case_data.get("用例ID", "") or test_case_data.get("编号", "")
        if not case_id:
            continue
        reports = [
            getattr(item, "rep_setup", None),
            getattr(item, "rep_call", None),
            getattr(item, "rep_teardown", None),
        ]
        if not any(reports):
            continue  # --collect-only 不应覆盖上次执行结果。
        failed_report = next((report for report in reports if report and report.failed), None)
        skipped_report = next((report for report in reports if report and report.skipped), None)
        call_report = getattr(item, "rep_call", None)
        if failed_report:
            reason = str(failed_report.longrepr)[:300] if failed_report.longrepr else "未知失败"
            result = f"fail: {reason}"
        elif skipped_report:
            reason = str(skipped_report.longrepr)[:200] if skipped_report.longrepr else "跳过"
            result = f"skip: {reason}"
        elif call_report and call_report.passed:
            result = "pass"
        else:
            result = "fail: 用例未进入执行阶段"
        updates.append((case_id, result, test_case_data.get("_row")))

    try:
        if updates:
            ExcelHandler(_get_excel_path()).write_results(updates)
            logger.info("已批量回写 %s 条 Excel 结果", len(updates))
    except Exception as exc:
        logger.error("Excel 结果批量回写失败（不改变 pytest 退出码）: %s", exc)
    finally:
        auth_path = Path(__file__).parent.parent / ".auth_state.json"
        if not session.config.option.collectonly and auth_path.exists():
            try:
                auth_path.unlink()
            except OSError as exc:
                logger.warning("测试结束后删除登录状态失败: %s", exc)

# ==================== Allure 报告配置 Hook ====================

def pytest_configure(config):
    """配置 pytest，将环境信息写入 Allure"""
    # 写入 Allure 环境信息（将在 Allure 报告的 Environment 页显示）
    allure_dir = getattr(config.option, "alluredir", None) or "reports/allure-results"
    env_path = Path(allure_dir) / "environment.properties"
    env_path.parent.mkdir(parents=True, exist_ok=True)
    with open(env_path, "w", encoding="utf-8") as f:
        f.write(f"测试环境={os.getenv('ENV', 'Test')}\n")
        f.write(f"测试人员={os.getenv('TESTER', 'QA Team')}\n")
        f.write(f"测试系统={os.getenv('BASE_URL', 'https://your-test-site.com')}\n")
        f.write(f"Python版本={sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}\n")
        f.write(f"pytest版本={pytest.__version__}\n")
        f.write(f"操作系统={os.name}\n")
        f.write(f"浏览器=Chromium\n")
        f.write(f"执行时间={datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_teardown(item, nextitem):
    """确保测试资源正确释放"""
    outcome = yield
