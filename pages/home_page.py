"""
HomePage —— 首页仪表盘页面对象

✅ 选择器已验证（2026-06-09）
- input[placeholder='请输入关键字'] → 患者搜索输入框 ✓
- button:has-text('搜索') → 搜索按钮 ✓
- text=顾客档案 → 顾客档案卡片入口 ✓
- text=美际学院 → 美际学院卡片入口 ✓
- text=案例库 → 案例库卡片入口 ✓
- text=设置 → 设置卡片入口 ✓
- .ant-modal → 续费/通知弹窗 ✓
- button:has-text('知道了') → 关闭弹窗按钮 ✓

页面路由: /
"""
from playwright.sync_api import Page
from pages.base_page import BasePage, logger


class HomePage(BasePage):
    """首页仪表盘页面对象"""

    # ==================== 元素定位器 ====================
    SEARCH_INPUT = "input[placeholder='请输入关键字']"           # 患者搜索输入框
    SEARCH_BUTTON = "button:has-text('搜 索')"                 # 搜索按钮
    MODAL = ".ant-modal"                                        # 弹窗（续费/通知）
    MODAL_CLOSE_BTN = "button:has-text('知道了')"               # 关闭弹窗按钮
    MODAL_BUY_BTN = "button:has-text('去购买')"                 # 弹窗购买按钮

    # 四个功能卡片入口
    PATIENT_CARD = "text=顾客档案"                                # 顾客档案卡片
    ACADEMY_CARD = "text=美际学院"                                # 美际学院卡片
    CASE_CARD = "text=案例库"                                     # 案例库卡片
    SETTINGS_CARD = "text=设置"                                   # 设置卡片

    # 首页关键数据
    PATIENT_COUNT_TEXT = "已为"                                   # 顾客档案数量（如"已为163位顾客生成3D影像"）

    def __init__(self, page: Page, base_url: str = ""):
        super().__init__(page)
        self.base_url = base_url
        if base_url and "/login" in base_url:
            base_url = base_url.split("/login")[0]
        self.home_url = base_url if base_url else "/"
        logger.info(f"首页 URL: {self.home_url}")

    # ==================== 页面操作 ====================

    def open(self) -> None:
        """打开首页"""
        logger.info("打开首页")
        self.navigate(self.home_url)
        self.wait_for_stable()

    def close_modal_if_present(self) -> bool:
        """
        关闭可能出现的续费弹窗

        每次登录后可能出现「云服务即将进入缴费期」弹窗，
        需要在操作其他元素前关闭它。
        :return: 是否关闭了弹窗
        """
        try:
            modal = self.page.locator(self.MODAL)
            if modal.count() > 0 and modal.first.is_visible(timeout=2000):
                logger.info("检测到弹窗，尝试关闭")
                close_btn = self.page.locator(self.MODAL_CLOSE_BTN)
                if close_btn.count() > 0:
                    close_btn.click()
                    self.wait_for_timeout(1000)
                    logger.info("弹窗已关闭")
                    return True
        except Exception:
            pass
        return False

    def search_patient(self, keyword: str) -> None:
        """搜索患者（姓名或手机号）"""
        logger.info(f"搜索患者: {keyword}")
        self.fill(self.SEARCH_INPUT, keyword)
        self.click(self.SEARCH_BUTTON)
        self.wait_for_stable()

    def click_patient_card(self) -> None:
        """点击「顾客档案」卡片进入顾客列表页"""
        logger.info("点击顾客档案卡片")
        self.click(self.PATIENT_CARD)
        self.wait_for_stable()

    def click_academy_card(self) -> None:
        """点击「美际学院」卡片"""
        logger.info("点击美际学院卡片")
        self.click(self.ACADEMY_CARD)
        self.wait_for_stable()

    def click_case_card(self) -> None:
        """点击「案例库」卡片进入案例管理页"""
        logger.info("点击案例库卡片")
        self.click(self.CASE_CARD)
        self.wait_for_stable()

    def click_settings_card(self) -> None:
        """点击「设置」卡片进入设置页"""
        logger.info("点击设置卡片")
        self.click(self.SETTINGS_CARD)
        self.wait_for_stable()

    # ==================== 读取操作 ====================

    def get_patient_count_text(self) -> str:
        """获取顾客档案数量描述文本"""
        body_text = self.page.locator("body").inner_text()
        # 提取包含"已为"的行，如"已为163位顾客生成3D影像"
        import re
        match = re.search(r'已为(\d+)位顾客生成3D影像', body_text)
        if match:
            logger.info(f"顾客档案数量: {match.group(1)} 位")
            return match.group(1)
        return ""

    def get_case_count_text(self) -> str:
        """获取案例库数量描述文本"""
        body_text = self.page.locator("body").inner_text()
        import re
        match = re.search(r'已积累(\d+)个治疗案例', body_text)
        if match:
            logger.info(f"案例数量: {match.group(1)} 个")
            return match.group(1)
        return ""

    # ==================== 断言操作 ====================

    def assert_page_loaded(self) -> None:
        """断言首页加载成功"""
        logger.info("验证首页已加载")
        self.wait_for_stable()
        try:
            self.assert_visible(self.SEARCH_INPUT, "搜索输入框未显示")
        except AssertionError:
            body_text = self.page.locator("body").inner_text()
            assert "搜索" in body_text, f"首页未正常加载: {body_text[:200]}"

    def assert_patient_card_visible(self) -> None:
        """断言顾客档案卡片可见"""
        self.assert_visible(self.PATIENT_CARD, "顾客档案卡片未显示")

    def assert_search_result_visible(self, keyword: str) -> None:
        """断言搜索结果中包含指定关键字"""
        self.wait_for_stable()
        body_text = self.page.locator("body").inner_text()
        assert keyword in body_text, \
            f"搜索结果中未找到「{keyword}」"
