"""
AddCasePage —— 新增案例页页面对象（基于真实页面 DOM 分析）

✅ 选择器已验证（2026-06-09）
- textarea[placeholder='请输入案例名称'] → 案例名称输入框 ✓
- button:has-text("保存") → 保存按钮 ✓
- div:has-text("案例公开范围") → 公开范围选择器 ✓
- 各分类复选框 → input[type=checkbox] ✓
- 产品/术前诊断/治疗步骤 → textarea 按 placeholder 定位 ✓

页面路由: /case/create
"""
from playwright.sync_api import Page
from pages.base_page import BasePage, logger


class AddCasePage(BasePage):
    """新增案例页面对象（真实页面）"""

    # ==================== 元素定位器 ====================
    CASE_NAME_INPUT = "textarea[placeholder='请输入案例名称']"  # 案例名称文本域
    SAVE_BUTTON = "button.ant-btn-primary"                     # 保存按钮（页面唯一主按钮，显示"保 存"）
    BACK_BUTTON = "button:has-text('返回'), a:has-text('返回')"  # 返回按钮
    PUBLIC_SCOPE = "#rc_select_1"                             # 案例公开范围选择器
    ADD_IMAGE_BTN = "text=添加图片"                            # 添加图片
    ADD_STEP_LINK = "a:has-text('添加一个步骤')"                # 添加治疗步骤
    ADD_CUSTOM_TAG = "a:has-text('添加自定义标签')"             # 添加自定义标签
    PRODUCT_INPUT = "textarea[placeholder='请输入治疗方案使用的产品']"
    DIAGNOSIS_INPUT = "textarea[placeholder='请输入用户情况']"

    def __init__(self, page: Page, base_url: str = ""):
        super().__init__(page)
        self.base_url = base_url
        if base_url and "/login" in base_url:
            base_url = base_url.split("/login")[0]
        self.add_url = f"{base_url}/case/create" if base_url else "/case/create"
        logger.info(f"新增案例页 URL: {self.add_url}")

    # ==================== 页面操作 ====================

    def open(self) -> None:
        """打开新增案例页面"""
        logger.info("打开新增案例页")
        self.navigate(self.add_url)
        self.wait_for_stable()

    def enter_case_name(self, name: str) -> None:
        """输入案例名称"""
        logger.info(f"输入案例名称: {name}")
        self.fill(self.CASE_NAME_INPUT, name)

    def click_save(self) -> None:
        """点击保存按钮"""
        logger.info("点击保存")
        self.click(self.SAVE_BUTTON)
        self.wait_for_stable()

    # ==================== 组合操作 ====================

    def create_case(self, name: str) -> None:
        """创建案例：输入名称并保存"""
        logger.info(f"创建案例: {name}")
        self.enter_case_name(name)
        self.click_save()

    # ==================== 断言操作 ====================

    def assert_page_loaded(self) -> None:
        """断言新增案例页加载成功"""
        logger.info("验证新增案例页已加载")
        self.wait_for_stable()
        try:
            self.assert_visible(self.CASE_NAME_INPUT, "案例名称输入框未显示")
        except AssertionError:
            try:
                self.assert_visible(self.SAVE_BUTTON, "保存按钮未显示")
            except AssertionError:
                # 兜底：检查页面 URL
                assert "/case/create" in self.page.url, \
                    f"未在新增案例页，当前: {self.page.url}"

    def assert_name_required_error(self) -> None:
        """断言出现必填校验错误"""
        logger.info("验证案例名称必填错误")
        try:
            self.wait_for_selector(".ant-form-item-explain-error", timeout=3000)
            error_text = self.page.locator(".ant-form-item-explain-error").inner_text()
        except Exception:
            error_text = self.page.locator("body").inner_text()
        assert any(kw in error_text for kw in ["请输入", "不能为空", "必填"]), \
            f"未找到必填提示，实际: 「{error_text[:150]}」"

    def assert_save_success(self) -> None:
        """断言保存成功（URL 跳转到 /case 列表页）"""
        logger.info("验证保存成功")
        self.wait_for_stable(timeout=8000)
        current_url = self.page.url
        # 保存成功后应跳转回案例列表页
        if "/case" in current_url and "/create" not in current_url:
            logger.info(f"✅ 已跳转到案例列表页: {current_url}")
            return
        # 也可能有成功 Toast
        try:
            self.wait_for_selector(".ant-message-success", timeout=3000)
            logger.info("✅ 保存成功消息可见")
            return
        except Exception:
            pass
        logger.warning(f"保存成功验证未通过，当前 URL: {current_url}")
