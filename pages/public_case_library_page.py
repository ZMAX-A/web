"""
PublicCaseLibraryPage —— 公共案例库页面对象

⚠️ 选择器尚未验证（基于案例列表页「公共案例库」按钮推断）
- 从案例列表页切换至公共案例库视图
- 可能是独立页面或列表页的筛选模式

页面路由: /case/public
"""
from pages.base_page import BasePage, logger


class PublicCaseLibraryPage(BasePage):
    """公共案例库页面对象（骨架 — 仅页面识别，无操作逻辑）"""

    # ==================== 元素定位器（⚠️ 待验证）====================
    PAGE_TITLE = "text=公共案例库"

    def __init__(self, page, base_url: str = ""):
        super().__init__(page)
        self.base_url = base_url
        if base_url and "/login" in base_url:
            base_url = base_url.split("/login")[0]
        self.public_url = f"{base_url}/case/public" if base_url else "/case/public"
        logger.info(f"公共案例库页 URL: {self.public_url}")

    # ==================== 页面操作 ====================

    def open(self) -> None:
        """打开公共案例库页面"""
        logger.info("打开公共案例库页")
        self.navigate(self.public_url)
        self.wait_for_stable()

    # ==================== 断言操作 ====================

    def assert_page_loaded(self) -> None:
        """断言公共案例库页加载成功"""
        logger.info("验证公共案例库页已加载")
        self.wait_for_stable()
        body_text = self.page.locator("body").inner_text()
        assert "公共案例库" in body_text, f"公共案例库页未正常加载: {body_text[:200]}"
