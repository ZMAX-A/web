"""
SettingsPage —— 设置页面对象

✅ 选择器已验证（2026-06-09）
- li:has-text("语言") → 语言设置列表项 ✓
- .ant-select → 语言下拉选择器 ✓
- li:has-text("报告解读模块默认收起") → 报告解读收起设置 ✓
- li:has-text("水印设置") → 水印设置入口 ✓
- li:has-text("个人中心") → 个人中心入口 ✓
- li:has-text("最近删除") → 最近删除入口 ✓
- li:has-text("云存储管理") → 云存储管理入口 ✓
- button:has-text("退出登录") → 退出登录按钮 ✓

页面路由: /setting
"""
from playwright.sync_api import Page
from pages.base_page import BasePage, logger


class SettingsPage(BasePage):
    """设置页面对象"""

    # ==================== 元素定位器 ====================
    LANGUAGE_ITEM = "li:has-text('语言')"                          # 语言设置列表项
    LANGUAGE_SELECT = ".ant-select"                                # 语言下拉选择器
    REPORT_TOGGLE_ITEM = "li:has-text('报告解读模块默认收起')"       # 报告解读收起
    WATERMARK_ITEM = "li:has-text('水印设置')"                     # 水印设置
    PERSONAL_CENTER_ITEM = "li:has-text('个人中心')"                # 个人中心
    RECENT_DELETE_ITEM = "li:has-text('最近删除')"                  # 最近删除
    CLOUD_STORAGE_ITEM = "li:has-text('云存储管理')"                # 云存储管理
    LOGOUT_BUTTON = "button:has-text('退出登录')"                  # 退出登录按钮
    BACK_BUTTON = "button:has-text('返回'), a:has-text('返回')"    # 返回按钮

    # 弹窗确认
    CONFIRM_BTN = ".ant-btn-primary:has-text('确定')"
    CANCEL_BTN = ".ant-btn:has-text('取消')"
    MODAL = ".ant-modal"

    def __init__(self, page: Page, base_url: str = ""):
        super().__init__(page)
        self.base_url = base_url
        if base_url and "/login" in base_url:
            base_url = base_url.split("/login")[0]
        self.settings_url = f"{base_url}/setting" if base_url else "/setting"
        logger.info(f"设置页 URL: {self.settings_url}")

    # ==================== 页面操作 ====================

    def open(self) -> None:
        """打开设置页面"""
        logger.info("打开设置页")
        self.navigate(self.settings_url)
        self.wait_for_stable()

    def click_language(self) -> None:
        """点击语言设置"""
        logger.info("点击语言设置")
        self.click(self.LANGUAGE_ITEM)
        self.wait_for_timeout(500)

    def select_language(self, language: str = "English") -> None:
        """
        切换语言
        :param language: 语言名称，如 "中文"、"English"
        """
        logger.info(f"切换语言为: {language}")
        self.click_language()
        # Ant Design Select 下拉选项
        option = self.page.get_by_text(language, exact=True).first
        if option.count() > 0:
            option.click()
            self.wait_for_timeout(500)
        else:
            logger.warning(f"未找到语言选项: {language}")

    def click_report_toggle(self) -> None:
        """点击报告解读模块默认收起"""
        logger.info("点击报告解读模块默认收起")
        self.click(self.REPORT_TOGGLE_ITEM)
        self.wait_for_stable()

    def click_watermark(self) -> None:
        """点击水印设置"""
        logger.info("点击水印设置")
        self.click(self.WATERMARK_ITEM)
        self.wait_for_stable()

    def click_personal_center(self) -> None:
        """点击个人中心"""
        logger.info("点击个人中心")
        self.click(self.PERSONAL_CENTER_ITEM)
        self.wait_for_stable()

    def click_recent_delete(self) -> None:
        """点击最近删除"""
        logger.info("点击最近删除")
        self.click(self.RECENT_DELETE_ITEM)
        self.wait_for_stable()

    def click_cloud_storage(self) -> None:
        """点击云存储管理"""
        logger.info("点击云存储管理")
        self.click(self.CLOUD_STORAGE_ITEM)
        self.wait_for_stable()

    def click_logout(self) -> None:
        """点击退出登录"""
        logger.info("点击退出登录")
        self.click(self.LOGOUT_BUTTON)

    def confirm_logout(self) -> None:
        """确认退出登录"""
        logger.info("确认退出登录")
        self.click(self.CONFIRM_BTN)
        self.wait_for_stable()

    def cancel_logout(self) -> None:
        """取消退出登录"""
        logger.info("取消退出登录")
        self.click(self.CANCEL_BTN)

    # ==================== 断言操作 ====================

    def assert_page_loaded(self) -> None:
        """断言设置页加载成功"""
        logger.info("验证设置页已加载")
        self.wait_for_stable()
        try:
            self.assert_visible(self.LOGOUT_BUTTON, "退出登录按钮未显示")
        except AssertionError:
            body_text = self.page.locator("body").inner_text()
            assert "设置" in body_text, f"设置页未正常加载: {body_text[:200]}"

    def assert_logout_success(self) -> None:
        """断言退出登录成功（回到登录页）"""
        self.wait_for_stable(timeout=8000)
        assert "/login" in self.page.url, f"退出登录失败，当前: {self.page.url}"
        logger.info("✅ 已退出登录，返回登录页")
