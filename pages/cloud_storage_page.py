"""
CloudStoragePage —— 云存储管理页面对象

⚠️ 选择器尚未验证（基于设置页「云存储管理」入口推断）
- 从设置页点击「云存储管理」进入
- 预计包含存储使用量、上传/下载管理、套餐信息等

页面路由: /setting/cloud-storage
"""
from pages.base_page import BasePage, logger


class CloudStoragePage(BasePage):
    """云存储管理页面对象（骨架 — 仅页面识别，无操作逻辑）"""

    # ==================== 元素定位器（⚠️ 待验证）====================
    BACK_BUTTON = "button:has-text('返回'), a:has-text('返回')"  # 返回按钮

    def __init__(self, page, base_url: str = ""):
        super().__init__(page)
        self.base_url = base_url
        if base_url and "/login" in base_url:
            base_url = base_url.split("/login")[0]
        self.storage_url = f"{base_url}/setting/cloud-storage" if base_url else "/setting/cloud-storage"
        logger.info(f"云存储管理页 URL: {self.storage_url}")

    # ==================== 页面操作 ====================

    def open(self) -> None:
        """打开云存储管理页面"""
        logger.info("打开云存储管理页")
        self.navigate(self.storage_url)
        self.wait_for_stable()

    # ==================== 断言操作 ====================

    def assert_page_loaded(self) -> None:
        """断言云存储管理页加载成功"""
        logger.info("验证云存储管理页已加载")
        self.wait_for_stable()
        body_text = self.page.locator("body").inner_text()
        assert "云存储" in body_text, f"云存储管理页未正常加载: {body_text[:200]}"
