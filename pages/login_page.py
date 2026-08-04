"""
LoginPage —— 登录页页面对象（基于真实页面 DOM 分析）

✅ 选择器已验证（2026-06-09 针对 yanjia-ai.xiaofutech.com）
- #username      → 账号输入框 ✓
- #password      → 密码输入框 ✓
- .ant-select-selector → 门店选择器（点父级而非 #store 避免遮挡）✓
- button[type='submit'] → 登录按钮（通过 JS 点击绕过遮罩层）✓
- img[alt='logo'] → 页面 Logo ✓
- .ant-form-item-explain-error → 表单校验错误提示 ✓
- .ant-message-notice → 全局消息通知 ✓
- .ant-select-selection-item → 门店已选中的回显文本 ✓
"""
import os
import time
from playwright.sync_api import Page, TimeoutError as PwTimeout
from pages.base_page import BasePage, logger


class LoginPage(BasePage):
    """登录页面对象"""

    # ==================== 元素定位器 ====================
    USERNAME_INPUT = "#username"                      # 账号输入框
    PASSWORD_INPUT = "#password"                      # 密码输入框
    STORE_SELECTOR = ".ant-select-selector"            # 门店选择器（点父级而非 input）
    LOGIN_BUTTON = "button[type='submit']"            # 登录按钮
    ERROR_MESSAGE = ".ant-form-item-explain-error"    # 表单校验错误
    LOGO_IMAGE = "img[alt='logo']"                   # 页面 Logo
    TOAST_NOTICE = ".ant-message-notice"              # 全局消息通知
    STORE_SELECTED = ".ant-select-selection-item"     # 门店已选中的回显

    def __init__(self, page: Page, base_url: str = ""):
        super().__init__(page)
        self.base_url = base_url
        if base_url and "/login" in base_url:
            self.login_url = base_url
        else:
            self.login_url = f"{base_url}/login" if base_url else "/login"
        logger.info(f"登录页 URL: {self.login_url}")

    # ==================== 页面操作 ====================

    def open(self) -> None:
        """打开登录页面"""
        logger.info("打开登录页")
        self.navigate(self.login_url)

    def enter_username(self, username: str) -> None:
        """输入账号"""
        logger.info("输入登录账号（内容已隐藏）")
        self.fill(self.USERNAME_INPUT, username)

    def enter_password(self, password: str) -> None:
        """输入密码"""
        logger.info("输入密码")
        self.fill(self.PASSWORD_INPUT, password)

    def click_login(self) -> None:
        """
        点击登录按钮
        在等待稳定前先快速捕获可能出现的 Toast 消息（Ant Design 消息 3 秒后消失）
        """
        logger.info("点击登录按钮")
        try:
            self.page.evaluate('document.querySelector("button[type=\'submit\']").click()')
        except Exception:
            # 【健壮性】JS 点击失败时（如页面未完全加载），降级为 Playwright 原生点击
            logger.warning("JS 点击失败，降级为原生点击")
            try:
                self.click(self.LOGIN_BUTTON)
            except Exception:
                self.page.locator(self.LOGIN_BUTTON).click(force=True, timeout=5000)
        # 立即等待一小段让 Toast 渲染出来
        self.wait_for_timeout(500)
        # 捕获可能出现的 Toast 消息
        toast = self.page.locator(self.TOAST_NOTICE)
        self._toast_text = toast.inner_text() if toast.count() > 0 else ""
        # 等待页面加载（SPA有后台轮询，用domcontentloaded代替networkidle避免超时）
        try:
            self.page.wait_for_load_state("domcontentloaded", timeout=3000)
        except Exception:
            pass
        # 再捕获一次（以防上面太早）
        if not self._toast_text:
            toast = self.page.locator(self.TOAST_NOTICE)
            self._toast_text = toast.inner_text() if toast.count() > 0 else ""
        if self._toast_text:
            logger.info(f"捕获到 Toast: {self._toast_text}")

    def get_last_toast(self) -> str:
        """获取最近一次点击登录后捕获的 Toast 消息"""
        return getattr(self, "_toast_text", "")

    # ==================== 门店选择 ====================

    def select_first_store(self) -> str:
        """
        展开门店下拉并选择第一个可用门店
        使用多次重试 + Playwright 原生定位，确保 Ant Design Select 正确触发
        """
        logger.info("选择门店（第一个可用门店）")

        # 步骤1：重试点击展开下拉（最多 3 次）
        option_text = None
        for attempt in range(3):
            try:
                self.page.locator(self.STORE_SELECTOR).first.click(timeout=5000)
                self.wait_for_timeout(500)

                # 用 Playwright 原生轮询方式等待下拉选项出现
                option_text = self.page.evaluate('''() => {
                    return new Promise((resolve) => {
                        var check = setInterval(function() {
                            var items = document.querySelectorAll('.ant-select-item-option');
                            if (items.length > 0) {
                                clearInterval(check);
                                resolve(items[0].innerText);
                            }
                            setTimeout(function() { clearInterval(check); resolve(null); }, 5000);
                        }, 100);
                    });
                }''')

                if option_text:
                    logger.info(f"门店选项: {option_text}（第 {attempt+1} 次尝试）")
                    break
                else:
                    logger.warning(f"门店下拉选项为空，第 {attempt+1} 次尝试，重试...")
                    # 先关闭可能残留的下拉再重试
                    self.page.keyboard.press("Escape")
                    self.wait_for_timeout(500)
            except Exception as e:
                logger.warning(f"门店点击异常（第 {attempt+1} 次）: {e}")

        # 步骤2：用 Playwright 原生 get_by_text 点击选项
        if option_text:
            target = self.page.get_by_text(option_text, exact=True).first
            if target.count() > 0:
                target.click()
            else:
                self.page.locator(".ant-select-item-option").first.click()
        else:
            logger.error("门店下拉始终未找到选项，尝试直接输入值")
            # 兜底：用 dispatchEvent 修改输入值
            self.page.evaluate('''() => {
                var input = document.querySelector('#store');
                if (input) {
                    var nativeSetter = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, 'value'
                    ).set;
                    nativeSetter.call(input, 'zwf新原彩');
                    input.dispatchEvent(new Event('input', {bubbles: true}));
                    input.dispatchEvent(new Event('change', {bubbles: true}));
                }
            }''')

        # 关闭下拉
        self.wait_for_timeout(500)
        self.page.keyboard.press("Escape")
        self.wait_for_timeout(300)

        return option_text or "未知门店"

    def select_store_by_name(self, store_name: str) -> None:
        """按名称选择指定门店"""
        logger.info(f"选择门店: {store_name}")
        self.page.locator(self.STORE_SELECTOR).first.click()
        self.wait_for_timeout(1500)

        option = self.page.get_by_text(store_name, exact=True)
        if option.count() > 0:
            option.first.click()
        else:
            logger.warning(f"未找到门店: {store_name}")
            self.page.keyboard.press("Escape")

        self.wait_for_timeout(500)
        self.page.keyboard.press("Escape")
        self.wait_for_timeout(300)

    # ==================== 组合操作 ====================

    def login(self, username: str, password: str, select_store: bool = True, store_name: str = "") -> None:
        """执行完整登录流程（含门店选择）

        :param store_name: 指定门店名称；为空时读取环境变量 STORE_NAME，
                           仍未配置则默认选择第一个门店
        """
        logger.info("开始执行完整登录流程")
        self.enter_username(username)
        self.enter_password(password)
        if select_store:
            name = store_name or os.getenv("STORE_NAME", "").strip()
            if name:
                self.select_store_by_name(name)
            else:
                self.select_first_store()
        self.click_login()

    # ==================== 断言操作 ====================

    def assert_page_loaded(self) -> None:
        """断言登录页加载成功"""
        try:
            self.assert_visible(self.LOGO_IMAGE, "页面 Logo 未显示")
            logger.info("登录页加载成功：Logo 可见")
        except AssertionError:
            self.assert_title_contains("颜佳AI")

    def assert_error_message(self, expected_text: str) -> None:
        """
        断言出现错误提示
        优先使用 click_login 时捕获的 Toast 文本（因为消息 3 秒后自动消失）
        """
        logger.info(f"断言错误提示: {expected_text}")

        # 方案一：使用 click_login 时捕获的 Toast
        toast_text = self.get_last_toast()
        if toast_text:
            logger.info(f"已捕获的 Toast: {toast_text}")
            if expected_text in toast_text:
                return

        # 方案二：尝试从 DOM 中立即读取 Toast
        toast = self.page.locator(self.TOAST_NOTICE)
        if toast.count() > 0:
            txt = toast.inner_text()
            logger.info(f"DOM 中的 Toast: {txt}")
            if expected_text in txt:
                return

        # 方案三：表单校验错误（可能有多个，取第一个有内容的）
        form_errors = self.page.locator(self.ERROR_MESSAGE)
        if form_errors.count() > 0:
            for i in range(form_errors.count()):
                txt = form_errors.nth(i).inner_text()
                logger.info(f"表单校验错误[{i}]: {txt}")
                if expected_text in txt:
                    return

        # 方案四：页面全部文本
        body_text = self.page.locator("body").inner_text()
        if expected_text in body_text:
            return

        # 都找不到
        logger.error(f"页面完整文本: {body_text[:500]}")
        raise AssertionError(
            f"预期错误「{expected_text}」在页面上任何位置都找不到\n"
            f"Toast: {toast_text[:100]}"
        )

    def assert_login_success(self) -> None:
        """断言登录成功（轮询等待 URL 跳离 /login）"""
        logger.info("验证登录是否成功...")
        # 轮询等待 URL 不再是 /login（最长 15 秒）
        start = time.time()
        while time.time() - start < 15:
            current_url = self.page.url
            if "/login" not in current_url and current_url != "about:blank":
                logger.info(f"✅ 登录成功 - URL: {current_url}")
                return
            self.wait_for_timeout(500)
        raise AssertionError(f"登录失败，仍在登录页: {self.page.url}")

    def assert_toast_message(self, expected_text: str, timeout: int = 5000) -> None:
        """断言全局消息提示包含指定文本"""
        logger.info(f"断言消息提示: {expected_text}")
        self.wait_for_selector(self.TOAST_NOTICE, timeout=timeout)
        toast_text = self.get_text(self.TOAST_NOTICE)
        assert expected_text in toast_text, \
            f"预期消息「{expected_text}」，实际「{toast_text}」"
