"""
CustomerDetailPage —— 顾客详情页面对象

⚠️ 选择器尚未验证（基于顾客列表页「详情」链接推断）
- 从顾客档案列表点击「详情」进入
- 预计包含顾客基本信息、检测记录、报告等模块

页面路由: /customer/{id}
"""
from pages.base_page import BasePage, logger


class CustomerDetailPage(BasePage):
    """顾客详情页面对象（骨架 — 仅页面识别，无操作逻辑）"""

    # ==================== 元素定位器（⚠️ 待验证）====================
    BACK_BUTTON = "button:has-text('返回'), a:has-text('返回')"  # 返回按钮

    def __init__(self, page, base_url: str = ""):
        super().__init__(page)
        self.base_url = base_url
        if base_url and "/login" in base_url:
            base_url = base_url.split("/login")[0]
        # 详情页路由动态包含顾客ID，此处只存储基础URL
        self.base_customer_url = f"{base_url}/customer" if base_url else "/customer"
        logger.info(f"顾客详情页基础 URL: {self.base_customer_url}")

    # ==================== 页面操作 ====================

    def open(self, customer_id: str = "") -> None:
        """
        打开顾客详情页面
        :param customer_id: 顾客ID，为空时仅为占位
        """
        url = f"{self.base_customer_url}/{customer_id}" if customer_id else self.base_customer_url
        logger.info(f"打开顾客详情页: {url}")
        self.navigate(url)
        self.wait_for_stable()

    # ==================== 断言操作 ====================

    def assert_page_loaded(self) -> None:
        """断言顾客详情页加载成功"""
        logger.info("验证顾客详情页已加载")
        self.wait_for_stable()
        assert "/customer/" in self.page.url, f"未在顾客详情页，当前: {self.page.url}"
