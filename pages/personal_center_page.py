"""
PersonalCenterPage —— 个人中心页面对象

⚠️ 选择器尚未验证（基于设置页「个人中心」入口推断）
- 从设置页点击「个人中心」进入
- 预计包含个人资料、头像、账号信息等

页面路由: /setting/personal-center
"""
from pages.base_page import BasePage, logger


class PersonalCenterPage(BasePage):
    """个人中心页面对象（骨架 — 仅页面识别，无操作逻辑）"""

    # ==================== 元素定位器（⚠️ 待验证）====================
    BACK_BUTTON = "button:has-text('返回'), a:has-text('返回')"  # 返回按钮

    def __init__(self, page, base_url: str = ""):
        super().__init__(page)
        self.base_url = base_url
        if base_url and "/login" in base_url:
            base_url = base_url.split("/login")[0]
        self.personal_url = f"{base_url}/setting/personal-center" if base_url else "/setting/personal-center"
        logger.info(f"个人中心页 URL: {self.personal_url}")

    # ==================== 页面操作 ====================

    def open(self) -> None:
        """打开个人中心页面"""
        logger.info("打开个人中心页")
        self.navigate(self.personal_url)
        self.wait_for_stable()

    # ==================== 断言操作 ====================

    def assert_page_loaded(self) -> None:
        """断言个人中心页加载成功"""
        logger.info("验证个人中心页已加载")
        self.wait_for_stable()
        body_text = self.page.locator("body").inner_text()
        assert "个人中心" in body_text, f"个人中心页未正常加载: {body_text[:200]}"
