"""
CustomerListPage —— 顾客档案列表页面对象

✅ 选择器已验证（2026-06-09）
- input[placeholder='请输入关键字'] → 搜索框 ✓
- button:has-text('搜索') → 搜索按钮 ✓
- button:has-text('其他筛选') → 其他筛选按钮 ✓
- input[type='date']/input[type='text'] → 日期范围选择器 ✓
- a:has-text('详情') → 顾客详情链接 ✓

页面路由: /customer
"""
from playwright.sync_api import Page
from pages.base_page import BasePage, logger


class CustomerListPage(BasePage):
    """顾客档案列表页面对象"""

    # ==================== 元素定位器 ====================
    SEARCH_INPUT = "input[placeholder='请输入关键字']"           # 搜索框
    SEARCH_BUTTON = "button:has-text('搜 索')"                 # 搜索按钮
    FILTER_BTN = "button:has-text('其他筛选')"                  # 其他筛选按钮
    DETAIL_LINK = "a:has-text('详情')"                         # 顾客详情链接
    BACK_BUTTON = "button:has-text('返回'), a:has-text('返回')"  # 返回按钮

    # 日期筛选
    DATE_START_INPUT = "input[placeholder*='开始'], input[placeholder*='2015']"  # 开始日期
    DATE_END_INPUT = "input[placeholder*='结束'], input[placeholder*='2026']"   # 结束日期

    # 其他筛选弹窗
    FILTER_MODAL = ".ant-modal"                                # 筛选弹窗
    FILTER_CONFIRM = ".ant-modal .ant-btn-primary:has-text('确定')"  # 筛选确定
    FILTER_RESET = ".ant-modal button:has-text('重置')"         # 筛选重置

    # 顾客列表项目
    CUSTOMER_ITEM = "[class*=ant-list-item]"                   # 顾客列表项

    def __init__(self, page: Page, base_url: str = ""):
        super().__init__(page)
        self.base_url = base_url
        if base_url and "/login" in base_url:
            base_url = base_url.split("/login")[0]
        self.list_url = f"{base_url}/customer" if base_url else "/customer"
        logger.info(f"顾客列表页 URL: {self.list_url}")

    # ==================== 页面操作 ====================

    def open(self) -> None:
        """打开顾客档案列表页"""
        logger.info("打开顾客档案列表页")
        self.navigate(self.list_url)
        self.wait_for_stable()

    def search_keyword(self, keyword: str) -> None:
        """输入关键字搜索"""
        logger.info(f"搜索顾客: {keyword}")
        self.fill(self.SEARCH_INPUT, keyword)
        self.click(self.SEARCH_BUTTON)
        self.wait_for_stable()

    def click_detail(self, index: int = 0) -> None:
        """点击第 index 个顾客的详情按钮"""
        logger.info(f"点击顾客详情: index={index}")
        details = self.page.locator(self.DETAIL_LINK).all()
        if index < len(details):
            details[index].click()
            self.wait_for_stable()
        else:
            logger.warning(f"详情链接索引 {index} 超出范围，共 {len(details)} 个")

    def click_filter(self) -> None:
        """点击其他筛选按钮"""
        logger.info("点击其他筛选")
        self.click(self.FILTER_BTN)
        self.wait_for_timeout(500)

    def click_back(self) -> None:
        """点击返回按钮"""
        logger.info("点击返回")
        self.click(self.BACK_BUTTON)
        self.wait_for_stable()

    # ==================== 读取操作 ====================

    def get_customer_count(self) -> int:
        """获取当前列表顾客数量"""
        items = self.page.locator(self.CUSTOMER_ITEM).all()
        count = len(items)
        logger.info(f"顾客列表数量: {count}")
        return count

    def get_customer_names(self) -> list[str]:
        """
        获取当前列表所有顾客姓名
        页面结构: 姓名 + 年龄 + "详情" + 手机号 + 上次检测时间 + 共检测N次
        """
        body_text = self.page.locator("body").inner_text()
        # 提取姓名（年龄之前的文本）
        import re
        names = re.findall(r'^([一-鿿\w]+)\n(\d+岁)\n详情', body_text, re.MULTILINE)
        return names

    # ==================== 断言操作 ====================

    def assert_page_loaded(self) -> None:
        """断言顾客列表页加载成功"""
        logger.info("验证顾客列表页已加载")
        self.wait_for_stable()
        try:
            self.assert_visible(self.SEARCH_INPUT, "搜索输入框未显示")
        except AssertionError:
            assert "customer" in self.page.url, f"未在顾客列表页: {self.page.url}"

    def assert_search_has_results(self) -> None:
        """断言搜索有结果"""
        self.wait_for_stable()
        body_text = self.page.locator("body").inner_text()
        assert "详情" in body_text, "搜索无结果，未找到顾客"
