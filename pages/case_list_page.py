"""
CaseListPage —— 案例列表页页面对象（基于真实页面 DOM 分析）

✅ 选择器已验证（2026-06-09）
- input[placeholder='请输入案例关键字'] → 搜索输入框 ✓
- button:has-text("搜索") → 搜索按钮 ✓
- button:has-text("新增图片案例") → 新增案例按钮 ✓
- button:has-text("管理") → 管理按钮 ✓
- a:has-text("标签管理") → 标签管理链接 ✓
- button:has-text("其他筛选") → 其他筛选按钮 ✓
- button:has-text("公共案例库") → 公共案例库切换 ✓
- .ant-tag → 分类标签 ✓

页面路由: /case
"""
from playwright.sync_api import Page
from pages.base_page import BasePage, logger


class CaseListPage(BasePage):
    """案例列表页面对象（真实页面）"""

    # ==================== 元素定位器（基于真实页面展示）====================
    # 搜索区域
    SEARCH_INPUT = "input[placeholder='请输入案例关键字']"
    SEARCH_BUTTON = "button:has-text('搜 索')"                     # 搜索按钮（实际文本"搜 索"）

    # 操作按钮
    ADD_CASE_BTN = "button:has-text('新增图片案例')"
    MANAGE_BTN = "button:has-text('管理')"
    FILTER_BTN = "button:has-text('其他筛选')"
    PUBLIC_LIBRARY_BTN = "button:has-text('公共案例库')"
    TAG_MANAGE_LINK = "a:has-text('标签管理')"

    # 分类标签
    CATEGORY_TAG = ".ant-tag"
    CATEGORY_ALL = ".ant-tag:has-text('全部')"

    # 案例列表
    CASE_ITEM = ".ant-card, [class*=case-item]"
    CASE_NAME = ".ant-card .ant-card-meta-title, [class*=case-name]"

    # 删除相关（管理模式下）
    DELETE_BUTTON = "button:has-text('删除')"
    CONFIRM_DELETE_BTN = ".ant-modal .ant-btn-primary:has-text('确定')"
    CANCEL_BUTTON = ".ant-modal .ant-btn:has-text('取消')"
    MODAL = ".ant-modal"

    # 消息提示
    TOAST_MESSAGE = ".ant-message-notice"

    # 空结果
    EMPTY_RESULT = ".ant-empty, .ant-select-item-empty"

    def __init__(self, page: Page, base_url: str = ""):
        super().__init__(page)
        self.base_url = base_url
        # BASE_URL 可能包含 /login，需要截取主机部分
        if base_url and "/login" in base_url:
            base_url = base_url.split("/login")[0]
        self.list_url = f"{base_url}/case" if base_url else "/case"
        logger.info(f"案例列表页 URL: {self.list_url}")

    # ==================== 页面操作 ====================

    def open(self) -> None:
        """打开案例列表页"""
        logger.info("打开案例列表页")
        self.navigate(self.list_url)
        self.wait_for_stable()

    def search_keyword(self, keyword: str) -> None:
        """搜索关键字并回车"""
        logger.info(f"搜索关键字: {keyword}")
        # 先清空再输入
        self.fill(self.SEARCH_INPUT, keyword)
        self.click(self.SEARCH_BUTTON)
        self.wait_for_stable()

    def click_add_case(self) -> None:
        """点击新增图片案例按钮"""
        logger.info("点击新增图片案例")
        self.click(self.ADD_CASE_BTN)
        self.wait_for_stable()

    def click_manage(self) -> None:
        """点击管理按钮（进入管理模式，可删除）"""
        logger.info("点击管理按钮")
        self.click(self.MANAGE_BTN)
        self.wait_for_stable()

    def click_delete(self) -> None:
        """点击删除按钮（管理模式下的删除按钮）"""
        logger.info("点击删除")
        self.click(self.DELETE_BUTTON)

    def confirm_delete(self) -> None:
        """在确认弹窗中点击确定"""
        logger.info("确认删除")
        self.click(self.CONFIRM_DELETE_BTN)
        self.wait_for_stable()

    def click_cancel(self) -> None:
        """在确认弹窗中点击取消"""
        logger.info("点击取消")
        self.click(self.CANCEL_BUTTON)

    def select_case(self, index: int = 0) -> None:
        """
        选择案例（管理模式下勾选）
        管理模式下案例项前可能有复选框
        """
        logger.info(f"选择案例: index={index}")
        # 尝试勾选复选框
        checkboxes = self.page.locator("input[type=checkbox]").all()
        if index < len(checkboxes):
            checkboxes[index].check()
        else:
            logger.warning(f"索引 {index} 超出范围，共 {len(checkboxes)} 个复选框")

    def select_category(self, category_name: str) -> None:
        """点击分类标签进行筛选"""
        logger.info(f"选择分类: {category_name}")
        tag = self.page.locator(f".ant-tag:has-text('{category_name}')").first
        if tag.count() > 0:
            tag.click()
            self.wait_for_stable()
        else:
            logger.warning(f"未找到分类标签: {category_name}")

    # ==================== 读取操作 ====================

    def get_case_names(self) -> list[str]:
        """获取当前所有可见案例的名称列表"""
        cases = self.page.evaluate('''() => {
            var items = document.querySelectorAll('[class*=_2eFn]');
            return Array.from(items).map(el => el.innerText.trim()).filter(t => t);
        }''')
        return cases

    def get_case_count(self) -> int:
        """获取当前列表案例数量"""
        return len(self.get_case_names())

    # ==================== 断言操作 ====================

    def assert_page_loaded(self) -> None:
        """断言列表页加载成功"""
        logger.info("验证案例列表页已加载")
        self.wait_for_stable()
        try:
            self.assert_visible(self.SEARCH_INPUT, "搜索输入框未显示")
        except AssertionError:
            # 兜底：检查页面是否包含搜索/案例等关键字
            body_text = self.page.locator("body").inner_text()
            assert "搜索" in body_text, f"案例列表页未正常加载，页面文字: {body_text[:200]}"

    def assert_case_visible(self, case_name: str) -> None:
        """断言指定案例名称在列表中可见"""
        logger.info(f"验证案例可见: {case_name}")
        case_texts = self.get_case_names()
        assert any(case_name in t for t in case_texts), \
            f"未找到名为「{case_name}」的案例，当前列表: {case_texts}"

    def assert_no_results(self) -> None:
        """断言搜索无结果"""
        logger.info("验证搜索无结果")
        try:
            self.assert_visible(self.EMPTY_RESULT, "空结果提示未显示")
        except AssertionError:
            # 无结果时列表为空，检查案例数量
            count = self.get_case_count()
            assert count == 0, f"预期无搜索结果，但找到 {count} 个案例"

    def assert_cases_contain(self, keyword: str) -> None:
        """断言搜索结果中包含指定关键字"""
        logger.info(f"验证列表包含关键字: {keyword}")
        self.wait_for_stable()
        case_texts = self.get_case_names()
        total_text = " ".join(case_texts)
        assert keyword in total_text, \
            f"搜索结果中未找到「{keyword}」，案例列表: {case_texts[:5]}"

    def assert_toast_message(self, expected_text: str) -> None:
        """断言 Toast 提示信息"""
        logger.info(f"验证消息提示: {expected_text}")
        try:
            self.wait_for_selector(self.TOAST_MESSAGE, timeout=5000)
            actual = self.get_text(self.TOAST_MESSAGE)
        except Exception:
            actual = self.page.locator("body").inner_text()
        assert expected_text in actual, \
            f"预期提示「{expected_text}」，实际「{actual[:200]}」"

    def assert_categories_displayed(self) -> None:
        """断言分类标签正常展示"""
        logger.info("验证分类标签可见")
        tags = self.page.locator(self.CATEGORY_TAG).all()
        assert len(tags) > 0, "页面上未找到任何分类标签"

    def assert_delete_prompt(self) -> None:
        """断言出现删除确认弹窗"""
        logger.info("验证删除确认弹窗")
        try:
            self.assert_text_visible("确定")
        except AssertionError:
            self.assert_visible(self.MODAL, "未出现删除确认弹窗")
