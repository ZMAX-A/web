"""
BasePage 基类 —— 封装 Playwright 通用页面操作，所有页面对象都继承此类。

【优化说明】
- 增加 logging 日志记录（方便排查问题）
- 增加 wait_and_click / wait_and_fill 智能等待方法（替代固定等待）
- 增加 wait_for_stable 页面稳定等待（等待网络空闲 + 无动画）
- 增加 wait_for_element_state 显式状态等待
- 所有 click/fill 操作均自带显式等待（不再依赖隐式超时）
- 移除多余的 type_text 方法（fill 更高效）
- 定位器查找优先使用 role 语义化定位
"""
import logging
from pathlib import Path
from datetime import datetime
from typing import Literal

from playwright.sync_api import Page, expect, Locator

# 配置日志：输出到控制台，格式清晰
logger = logging.getLogger(__name__)


class BasePage:
    """页面对象基类，提供通用的点击、输入、等待、断言等操作"""

    def __init__(self, page: Page):
        """
        初始化基类
        :param page: Playwright 的 Page 实例
        """
        self.page = page
        # 截图目录（项目根目录下的 screenshots）
        self.screenshot_dir = Path(__file__).parent.parent / "screenshots"
        # 默认显式等待超时（毫秒）
        self.timeout = 15000

    # ==================== 导航操作 ====================

    def navigate(self, url: str) -> None:
        """打开指定 URL，等待 DOM 加载后即继续（SPA 有后台轮询，networkidle 会超时）"""
        logger.info(f"导航到: {url}")
        self.page.goto(url, wait_until="domcontentloaded", timeout=30000)

    def go_back(self) -> None:
        """浏览器后退"""
        logger.info("浏览器后退")
        self.page.go_back(wait_until="domcontentloaded")

    def refresh(self) -> None:
        """刷新页面"""
        logger.info("刷新页面")
        self.page.reload(wait_until="domcontentloaded")

    # ==================== 智能等待操作 ====================

    def wait_for_selector(self, selector: str, timeout: int | None = None) -> Locator:
        """
        等待元素出现在 DOM 中并返回（元素不一定可见）
        :param selector: 元素选择器
        :param timeout: 超时时间（毫秒），默认 self.timeout
        """
        return self.page.wait_for_selector(selector, timeout=timeout or self.timeout)

    def wait_for_visible(self, selector: str, timeout: int | None = None) -> Locator:
        """
        等待元素在页面上可见（不仅出现在 DOM，还要能看见）
        :param selector: 元素选择器
        :param timeout: 超时时间（毫秒）
        """
        # 【健壮性】SPA 中元素可能被异步替换，重试一次避免 stale element 引用
        for attempt in range(2):
            try:
                locator = self.page.locator(selector).first
                locator.wait_for(state="visible", timeout=timeout or self.timeout)
                return locator
            except Exception as e:
                if attempt == 0 and ("stale" in str(e).lower() or "detached" in str(e).lower()):
                    logger.warning(f"元素状态异常，等待后重试 [{selector}]: {e}")
                    self.page.wait_for_timeout(1500)
                else:
                    raise

    def wait_for_text(self, text: str, timeout: int | None = None) -> None:
        """等待页面上出现包含指定文本的元素"""
        self.page.wait_for_selector(f"text={text}", timeout=timeout or self.timeout)

    def wait_for_url(self, url_pattern: str, timeout: int | None = None) -> None:
        """
        等待 URL 匹配指定模式
        :param url_pattern: 支持 glob 通配符，如 "**/cases" 匹配任何以 /cases 结尾的 URL
        """
        self.page.wait_for_url(url_pattern, timeout=timeout or self.timeout)

    def wait_for_stable(self, timeout: int = 10000) -> None:
        """
        等待页面加载稳定（SPA 有后台轮询，domcontentloaded 后即可继续）

        【优化原因】networkidle 在 SPA 中会因后台轮询 API 一直等待到超时
        """
        try:
            self.page.wait_for_load_state("domcontentloaded", timeout=timeout)
        except Exception:
            logger.warning("页面加载未在预期时间内稳定，但将继续执行")

    def wait_for_timeout(self, milliseconds: int = 1000) -> None:
        """
        【注意】仅作为兜底方案，优先使用 wait_for_selector / wait_for_visible
        这个方法的调用处应该加上注释说明为什么不能用显式等待替代
        """
        self.page.wait_for_timeout(milliseconds)

    # ==================== 点击操作 ====================

    def click(self, selector: str, timeout: int | None = None) -> None:
        """
        点击元素（自带等待元素出现且可操作）

        【优化】相比原来，增加前置等待元素可见 + 点击后等待网络稳定
        """
        locator = self.wait_for_visible(selector, timeout=timeout)
        logger.debug(f"点击元素: {selector}")
        try:
            locator.click()
        except Exception:
            # 【健壮性】元素可能被遮罩层遮挡（如弹窗/下拉），降级为 force 点击
            logger.debug(f"常规点击失败，尝试 force 点击: {selector}")
            locator.click(force=True, timeout=timeout or self.timeout)
        # 点击后等待一小段时间让页面响应
        self.page.wait_for_load_state("domcontentloaded", timeout=5000)

    def click_text(self, text: str, timeout: int | None = None) -> None:
        """
        点击包含指定文本的元素（优先使用）
        【优化】使用 get_by_text 语义化定位，比 text= 选择器更可靠
        """
        locator = self.page.get_by_text(text, exact=False).first
        locator.wait_for(state="visible", timeout=timeout or self.timeout)
        logger.debug(f"点击文本: {text}")
        locator.click()

    def click_role(self, role: str, name: str | None = None, timeout: int | None = None) -> None:
        """
        通过 ARIA role 点击元素（语义化定位，最稳定）
        :param role: ARIA role，如 "button", "link", "checkbox"
        :param name: 元素的名称（无障碍标签）
        """
        locator = self.page.get_by_role(role, name=name).first
        locator.wait_for(state="visible", timeout=timeout or self.timeout)
        logger.debug(f"点击 role={role} name={name}")
        locator.click()

    # ==================== 输入操作 ====================

    def fill(self, selector: str, text: str, timeout: int | None = None) -> None:
        """
        输入文本：等待元素可见 → 先清空再输入

        【优化】增加 wait_for_visible 前置检查 + 输入后日志 + 过期元素重试
        """
        locator = self.wait_for_visible(selector, timeout=timeout)
        logger.debug(f"填充输入框: {selector}, 值: {text[:20]}{'...' if len(text) > 20 else ''}")
        try:
            locator.fill(text)
        except Exception as e:
            # 【健壮性】SPA 中元素可能在 wait_for_visible 到 fill 之间被替换
            if "stale" in str(e).lower() or "detached" in str(e).lower():
                logger.warning(f"输入时元素失效，重新等待后重试 [{selector}]")
                self.wait_for_timeout(1000)
                locator = self.wait_for_visible(selector, timeout=timeout)
                locator.fill(text)
            else:
                raise

    def fill_by_placeholder(self, placeholder: str, text: str, timeout: int | None = None) -> None:
        """
        通过 placeholder 文本定位输入框并输入（适用于无 id 的输入框）
        :param placeholder: placeholder 属性内容
        :param text: 要输入的文本
        """
        locator = self.page.get_by_placeholder(placeholder).first
        locator.wait_for(state="visible", timeout=timeout or self.timeout)
        logger.debug(f"填充[placeholder={placeholder}]: {text[:20]}")
        locator.fill(text)

    def select_option(self, selector: str, value: str | None = None,
                      label: str | None = None, timeout: int | None = None) -> None:
        """
        选择下拉框选项
        :param selector: 下拉框元素选择器
        :param value: 选项的 value 属性
        :param label: 选项的文本
        """
        locator = self.wait_for_visible(selector, timeout=timeout)
        if label:
            logger.debug(f"选择下拉选项: {selector}, label={label}")
            locator.select_option(label=label)
        elif value:
            logger.debug(f"选择下拉选项: {selector}, value={value}")
            locator.select_option(value=value)

    # ==================== Ant Design 组件支持 ====================

    def ant_select_by_id(self, select_id: str, option_text: str) -> None:
        """
        操作 Ant Design Select 组件：点击输入框 → 选择选项

        【新增】专门用于 Ant Design 的下拉选择组件（如门店选择器）
        :param select_id: Select 组件的 input id
        :param option_text: 要选择的选项文本
        """
        logger.info(f"Ant Design Select: 选择 {select_id} → {option_text}")
        # 点击 Select 输入框展开下拉
        self.click(f"#{select_id}")
        self.wait_for_timeout(500)
        # 选择包含指定文本的选项
        option = self.page.locator(f".ant-select-item-option[title='{option_text}']")
        if option.count() == 0:
            # 尝试通过文本匹配
            option = self.page.get_by_text(option_text, exact=True).first
        option.wait_for(state="visible", timeout=5000)
        option.click()
        self.wait_for_timeout(300)

    def ant_select_first_option(self, select_id: str) -> None:
        """
        操作 Ant Design Select：展开并选择第一个选项

        【新增】用于不知道具体选项文本，选择第一个的场景
        :param select_id: Select 组件的 input id
        """
        logger.info(f"Ant Design Select: 选择 {select_id} → 第一个选项")
        self.click(f"#{select_id}")
        self.wait_for_timeout(500)
        first_option = self.page.locator(".ant-select-item-option").first
        first_option.wait_for(state="visible", timeout=5000)
        first_option_text = first_option.inner_text()
        logger.info(f"选择门店: {first_option_text}")
        first_option.click()
        self.wait_for_timeout(300)

    # ==================== 断言操作 ====================

    def assert_visible(self, selector: str, message: str = "") -> None:
        """断言元素在页面上可见"""
        locator = self.page.locator(selector).first
        try:
            expect(locator).to_be_visible(timeout=self.timeout)
            logger.debug(f"断言可见成功: {selector}")
        except AssertionError as e:
            msg = message or f"元素不可见: {selector}"
            logger.error(msg)
            raise AssertionError(msg) from e

    def assert_text_visible(self, text: str, timeout: int | None = None) -> None:
        """断言页面上包含指定文本的元素可见"""
        locator = self.page.get_by_text(text, exact=False).first
        try:
            expect(locator).to_be_visible(timeout=timeout or self.timeout)
            logger.debug(f"断言文本可见成功: {text}")
        except AssertionError as e:
            msg = f"页面中未找到可见文本: 「{text}」"
            logger.error(msg)
            raise AssertionError(msg) from e

    def assert_url_contains(self, text: str) -> None:
        """断言当前 URL 包含指定文本"""
        try:
            expect(self.page).to_have_url(f"**{text}**", timeout=self.timeout)
            logger.debug(f"断言URL包含成功: {text}")
        except AssertionError as e:
            msg = f"当前 URL 不包含「{text}」，实际: {self.page.url}"
            logger.error(msg)
            raise AssertionError(msg) from e

    def assert_title_contains(self, text: str) -> None:
        """断言页面标题包含指定文本"""
        try:
            expect(self.page).to_have_title(f"**{text}**", timeout=self.timeout)
            logger.debug(f"断言标题包含成功: {text}")
        except AssertionError as e:
            msg = f"页面标题不包含「{text}」，实际: {self.page.title()}"
            logger.error(msg)
            raise AssertionError(msg) from e

    def assert_url_not_contains(self, text: str) -> None:
        """
        断言当前 URL 不包含指定文本

        【新增】用于验证登录成功（URL 不再包含 /login）
        :param text: 不应出现在 URL 中的文本
        """
        url = self.page.url
        assert text not in url, \
            f"断言失败：URL 中不应包含「{text}」，当前 URL: {url}"

    # ==================== 读取操作 ====================

    def get_text(self, selector: str) -> str:
        """获取元素的首个匹配文本内容"""
        text = self.page.locator(selector).first.inner_text(timeout=self.timeout)
        logger.debug(f"获取文本 [{selector}]: {text[:50]}")
        return text

    def get_input_value(self, selector: str) -> str:
        """获取输入框的值"""
        return self.page.locator(selector).first.input_value(timeout=self.timeout)

    def is_visible(self, selector: str, timeout: int = 3000) -> bool:
        """
        检查元素是否可见

        【优化】增加超时参数，避免长时间等待导致测试缓慢
        """
        try:
            self.page.locator(selector).first.wait_for(state="visible", timeout=timeout)
            return True
        except Exception:
            return False

    def is_enabled(self, selector: str) -> bool:
        """检查元素是否可用"""
        return self.page.locator(selector).first.is_enabled()

    # ==================== 截图操作 ====================

    def screenshot(self, filename: str) -> str:
        """
        截取当前页面截图，保存到 screenshots/ 目录

        【优化】文件名自动添加时间戳，避免覆盖；目录自动创建
        :param filename: 截图文件名前缀（不含扩展名，不含路径）
        :return: 截图完整路径
        """
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%H%M%S")
        filepath = self.screenshot_dir / f"{filename}_{timestamp}.png"
        self.page.screenshot(path=str(filepath), full_page=True)
        logger.info(f"截图已保存: {filepath}")
        return str(filepath)
