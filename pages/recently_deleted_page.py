"""
RecentlyDeletedPage —— 最近删除页面对象

⚠️ 选择器尚未验证（基于设置页「最近删除」入口推断）
- 从设置页点击「最近删除」进入
- 预计包含已删除的案例/文件列表与恢复/彻底删除操作

页面路由: /setting/recent-delete
"""
from pages.base_page import BasePage, logger


class RecentlyDeletedPage(BasePage):
    """最近删除页面对象（骨架 — 仅页面识别，无操作逻辑）"""

    # ==================== 元素定位器（⚠️ 待验证）====================
    BACK_BUTTON = "button:has-text('返回'), a:has-text('返回')"  # 返回按钮

    def __init__(self, page, base_url: str = ""):
        super().__init__(page)
        self.base_url = base_url
        if base_url and "/login" in base_url:
            base_url = base_url.split("/login")[0]
        self.recent_url = f"{base_url}/setting/recent-delete" if base_url else "/setting/recent-delete"
        logger.info(f"最近删除页 URL: {self.recent_url}")

    # ==================== 页面操作 ====================

    def open(self) -> None:
        """打开最近删除页面"""
        logger.info("打开最近删除页")
        self.navigate(self.recent_url)
        self.wait_for_stable()

    # ==================== 断言操作 ====================

    def assert_page_loaded(self) -> None:
        """断言最近删除页加载成功"""
        logger.info("验证最近删除页已加载")
        self.wait_for_stable()
        body_text = self.page.locator("body").inner_text()
        assert "最近删除" in body_text, f"最近删除页未正常加载: {body_text[:200]}"
