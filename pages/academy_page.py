"""
AcademyPage —— 美际学院页面对象

⚠️ 选择器尚未验证（基于首页导航推断）
- 从首页「美际学院」卡片进入
- 预计包含课程列表、学习资料等模块

页面路由: /academy
"""
from pages.base_page import BasePage, logger


class AcademyPage(BasePage):
    """美际学院页面对象（骨架 — 仅页面识别，无操作逻辑）"""

    # ==================== 元素定位器（⚠️ 待验证）====================
    PAGE_TITLE = "text=美际学院"

    def __init__(self, page, base_url: str = ""):
        super().__init__(page)
        self.base_url = base_url
        if base_url and "/login" in base_url:
            base_url = base_url.split("/login")[0]
        self.academy_url = f"{base_url}/academy" if base_url else "/academy"
        logger.info(f"美际学院页 URL: {self.academy_url}")

    # ==================== 页面操作 ====================

    def open(self) -> None:
        """打开美际学院页面"""
        logger.info("打开美际学院页")
        self.navigate(self.academy_url)
        self.wait_for_stable()

    # ==================== 断言操作 ====================

    def assert_page_loaded(self) -> None:
        """断言美际学院页加载成功"""
        logger.info("验证美际学院页已加载")
        self.wait_for_stable()
        body_text = self.page.locator("body").inner_text()
        assert "美际学院" in body_text, f"美际学院页未正常加载: {body_text[:200]}"
