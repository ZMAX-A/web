"""
WatermarkSettingsPage —— 水印设置页面对象

⚠️ 选择器尚未验证（基于设置页「水印设置」入口推断）
- 从设置页点击「水印设置」进入
- 预计包含水印开关、样式配置等选项

页面路由: /setting/watermark
"""
from pages.base_page import BasePage, logger


class WatermarkSettingsPage(BasePage):
    """水印设置页面对象（骨架 — 仅页面识别，无操作逻辑）"""

    # ==================== 元素定位器（⚠️ 待验证）====================
    BACK_BUTTON = "button:has-text('返回'), a:has-text('返回')"  # 返回按钮

    def __init__(self, page, base_url: str = ""):
        super().__init__(page)
        self.base_url = base_url
        if base_url and "/login" in base_url:
            base_url = base_url.split("/login")[0]
        self.watermark_url = f"{base_url}/setting/watermark" if base_url else "/setting/watermark"
        logger.info(f"水印设置页 URL: {self.watermark_url}")

    # ==================== 页面操作 ====================

    def open(self) -> None:
        """打开水印设置页面"""
        logger.info("打开水印设置页")
        self.navigate(self.watermark_url)
        self.wait_for_stable()

    # ==================== 断言操作 ====================

    def assert_page_loaded(self) -> None:
        """断言水印设置页加载成功"""
        logger.info("验证水印设置页已加载")
        self.wait_for_stable()
        body_text = self.page.locator("body").inner_text()
        assert "水印" in body_text, f"水印设置页未正常加载: {body_text[:200]}"
