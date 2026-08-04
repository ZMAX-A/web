"""
步骤执行器 —— 读取 Excel 中的「操作类型」「元素定位器」「输入数据」并执行

支持的操作类型：
- input   输入文本
- click   点击元素
- select  下拉选择
- verify  验证元素可见
- hover   鼠标悬停
- scroll  滚动页面
- upload  上传文件
- download 下载文件
- wait    等待
- nav     导航到URL

Allure 集成：
- 每一步操作在 Allure 报告中显示为嵌套步骤
"""
import re
import logging
import allure
from playwright.sync_api import Page, TimeoutError as PwTimeout

logger = logging.getLogger("step_executor")


class StepExecutionError(RuntimeError):
    """Excel 步骤无法完成时抛出的明确异常，防止测试静默继续。"""


class StepExecutor:
    """执行 Excel 中定义的测试步骤"""

    def __init__(self, page: Page, base_url: str = "", timeout_ms: int = 5000):
        self.page = page
        self.timeout_ms = max(int(timeout_ms), 1)
        # 提取纯域名作为 base_url（去掉 /login 等路径部分）
        _m = re.match(r"(https?://[^/]+)", base_url)
        self.base_url = _m.group(1) if _m else base_url.rstrip("/")

    @staticmethod
    def _step_error(operation: str, locator: str, detail: str) -> StepExecutionError:
        location = f"，定位器={locator}" if locator else ""
        return StepExecutionError(f"步骤执行失败：{operation}{location}；{detail}")

    @allure.step("执行操作步骤")
    def execute(self, locators_str: str, operations_str: str, data_str: str) -> None:
        """按 Excel 中的顺序执行一组操作，任何未知或失败步骤都会终止用例。"""
        if not operations_str or not str(operations_str).strip():
            raise self._step_error("execute", "", "操作类型为空")

        locators = [item.strip() for item in str(locators_str).split(",")] if locators_str else []
        operations = [item.strip() for item in str(operations_str).split(",")]
        if not isinstance(data_str, str):
            data_str = str(data_str) if data_str else ""
        data_parts = [item.strip() for item in data_str.split("|")] if data_str else []

        data_idx = 0
        for index, operation in enumerate(operations):
            locator = locators[index] if index < len(locators) else ""
            logger.info("  执行步骤[%s]: %s | 定位器=%s", index, operation, locator[:50])

            if operation == "input":
                data = data_parts[data_idx] if data_idx < len(data_parts) else ""
                data_idx += 1
                self._do_input(locator, data)
            elif operation == "input_enter":
                data = data_parts[data_idx] if data_idx < len(data_parts) else ""
                data_idx += 1
                self._do_input(locator, data, press_enter=True)
            elif operation == "click":
                self._do_click(locator)
            elif operation == "select":
                data = data_parts[data_idx] if data_idx < len(data_parts) else ""
                data_idx += 1
                self._do_select(locator, data)
            elif operation == "verify":
                self._do_verify(locator)
            elif operation == "hover":
                self._do_hover(locator)
            elif operation == "scroll":
                self._do_scroll(locator)
            elif operation == "wait":
                try:
                    seconds = float(locator) if locator else 1.0
                except (TypeError, ValueError) as exc:
                    raise self._step_error("wait", locator, "等待时间必须是数字（秒）") from exc
                if seconds < 0:
                    raise self._step_error("wait", locator, "等待时间不能为负数")
                self.page.wait_for_timeout(round(seconds * 1000))
            elif operation == "nav":
                data_target = data_parts[data_idx] if data_idx < len(data_parts) else ""
                data_idx += 1
                target = data_target or locator
                if not target:
                    raise self._step_error("nav", locator, "缺少目标 URL")
                if not target.startswith("http") and self.base_url:
                    target = self.base_url + target
                self.page.goto(target, wait_until="domcontentloaded", timeout=max(self.timeout_ms, 30000))
            elif operation == "find_click":
                self._do_find_click(locator)
            elif operation == "upload":
                data = data_parts[data_idx] if data_idx < len(data_parts) else ""
                data_idx += 1
                self._do_upload(locator, data)
            elif operation in ("daterange", "date_range"):
                data = data_parts[data_idx] if data_idx < len(data_parts) else ""
                data_idx += 1
                self._do_daterange(locator, data)
            elif operation == "switch_tab":
                self._do_switch_tab(locator)
            else:
                raise self._step_error(operation or "<空操作>", locator, "不支持的操作类型")
    @allure.step("输入文本 → {locator}")
    def _do_input(self, locator: str, text: str, press_enter: bool = False) -> None:
        """输入文本，短暂重试后仍失败则终止当前用例。"""
        if not locator:
            raise self._step_error("input", locator, "缺少定位器")

        last_error = None
        for attempt in range(2):
            try:
                element = self.page.locator(locator).first
                element.wait_for(state="visible", timeout=self.timeout_ms)
                element.fill(text)
                if press_enter:
                    element.press("Enter")
                logger.info("    → 输入: %s", text[:30])
                return
            except Exception as exc:
                last_error = exc
                if attempt == 0:
                    logger.warning("    → 输入失败，等待后重试 [%s]: %s", locator, exc)
                    self.page.wait_for_timeout(1000)

        raise self._step_error("input", locator, f"重试后仍无法输入: {last_error}") from last_error
    @allure.step("点击元素: {locator}")
    def _do_click(self, locator: str) -> None:
        """点击元素；常规点击重试后仅做一次受控 force 兜底。"""
        if not locator:
            raise self._step_error("click", locator, "缺少定位器")

        last_error = None
        for attempt in range(2):
            try:
                element = self.page.locator(locator).first
                element.wait_for(state="visible", timeout=self.timeout_ms)
                element.click(timeout=self.timeout_ms)
                logger.info("    → 点击成功")
                self._after_click(locator)
                return
            except Exception as exc:
                last_error = exc
                if attempt == 0:
                    logger.warning("    → 点击失败，关闭遮罩后重试 [%s]: %s", locator, exc)
                    try:
                        self.page.keyboard.press("Escape")
                    except Exception:
                        pass
                    self.page.wait_for_timeout(500)

        # 部分 Ant Design 控件会被透明容器挡住，保留一次有日志的 force 兜底。
        try:
            logger.warning("    → 常规点击均失败，尝试 force 点击 [%s]", locator)
            element = self.page.locator(locator).first
            element.click(force=True, timeout=self.timeout_ms)
            self._after_click(locator)
            return
        except Exception as exc:
            last_error = exc

        raise self._step_error("click", locator, f"重试后仍无法点击: {last_error}") from last_error

    def _after_click(self, locator: str) -> None:
        """等待点击后的可观察状态，并处理门店下拉。"""
        self.page.wait_for_timeout(300)
        try:
            self.page.wait_for_load_state("domcontentloaded", timeout=self.timeout_ms)
        except PwTimeout:
            logger.debug("点击后 DOM 状态等待超时，将继续检查页面元素")

        try:
            spinner = self.page.locator(".ant-spin-spinning")
            if spinner.count() > 0 and spinner.first.is_visible(timeout=500):
                spinner.first.wait_for(state="hidden", timeout=max(self.timeout_ms * 3, 15000))
        except PwTimeout as exc:
            raise self._step_error("click", locator, "页面 loading 在超时后仍未消失") from exc

        if "store" in locator.lower():
            self.page.wait_for_timeout(500)
            options = self.page.locator(".ant-select-item-option")
            if options.count() > 0:
                option_text = options.first.inner_text()
                options.first.click(timeout=self.timeout_ms)
                logger.info("    → 选择门店: %s", option_text)
            else:
                self.page.keyboard.press("ArrowDown")
                self.page.keyboard.press("Enter")
            self.page.keyboard.press("Escape")
    @allure.step("查找有检测记录的顾客卡片: {locator}")
    def _do_find_click(self, locator: str) -> None:
        """
        在顾客列表中查找包含「共检测N次」(N>=1) 的卡片，点击其「详情」链接。

        卡片文本结构:
            姓名
            N岁
            详情
            手机号
            上次检测时间：
            日期/无
            共检测N次

        locator 参数通常为 "共检测"（仅用作识别标识，实际按文本结构查找）
        """
        if not locator:
            raise self._step_error("find_click", locator, "缺少定位器")
            return

        body = self.page.locator("body").inner_text()
        lines = body.split("\n")

        # locator 为"共检测"时用默认正则（N>=1）；传"共检测1次"等则精确匹配
        if locator and locator.strip() != "共检测":
            pattern = locator.strip()
        else:
            pattern = r'共检测([1-9]\d*)次'

        target_line = -1
        for i, line in enumerate(lines):
            if re.search(pattern, line):
                target_line = i
                break

        if target_line == -1:
            # 【健壮性】首次未找到 → 可能是多测试积累导致列表未刷新，
            # 直接导航到顾客列表页重新加载再试一次
            logger.warning("第一次未找到有检测记录的顾客，刷新顾客列表重试...")
            try:
                self.page.goto(f"{self.base_url}/customer", wait_until="domcontentloaded", timeout=15000)
                self.page.wait_for_timeout(2000)
            except Exception as e:
                logger.warning(f"刷新顾客列表页失败: {e}，尝试继续...")
            body = self.page.locator("body").inner_text()
            lines = body.split("\n")
            for i, line in enumerate(lines):
                if re.search(pattern, line):
                    target_line = i
                    logger.info("重试成功，已找到有检测记录的顾客")
                    break

        if target_line == -1:
            raise AssertionError(f"未找到匹配「{pattern}」的顾客卡片")

        # 从该行往回找最近的"详情"
        detail_idx = -1
        for j in range(target_line, max(target_line - 10, -1), -1):
            if "详情" in lines[j]:
                # 计算这个"详情"是第几个（从0开始）
                detail_idx = len([l for l in lines[:j] if "详情" in l])
                break

        if detail_idx == -1:
            raise AssertionError("找到检测记录但未找到对应的详情链接")

        details = self.page.locator("a:has-text('详情')")
        if details.count() <= detail_idx:
            raise AssertionError(f"详情链接数量不足: 需要第{detail_idx}个，实际{details.count()}个")

        details.nth(detail_idx).click()
        logger.info(f"    → 已点击第 {detail_idx} 个「详情」（有检测记录的顾客）")
        self.__body_text = self.page.locator("body").inner_text()
        self.page.wait_for_load_state("domcontentloaded", timeout=self.timeout_ms)

    @allure.step("下拉选择: {value} → {locator}")
    def _do_select(self, locator: str, value: str) -> None:
        """选择原生或 Ant Design 下拉项。"""
        if not locator:
            raise self._step_error("select", locator, "缺少定位器")

        native_error = None
        try:
            element = self.page.locator(locator).first
            element.wait_for(state="visible", timeout=self.timeout_ms)
            element.select_option(value=value) if value else element.select_option(index=0)
            logger.info("    → 选择: %s", value or "第一个选项")
            return
        except Exception as exc:
            native_error = exc

        try:
            self.page.locator(locator).first.click(timeout=self.timeout_ms)
            options = self.page.locator(".ant-select-item-option")
            options.first.wait_for(state="visible", timeout=self.timeout_ms)
            target = self.page.get_by_text(value, exact=True).last if value else options.first
            if value and target.count() == 0:
                raise self._step_error("select", locator, f"下拉中不存在选项「{value}」")
            target.click(timeout=self.timeout_ms)
            logger.info("    → Ant Design Select 选择: %s", value or "第一个选项")
        except Exception as exc:
            raise self._step_error(
                "select", locator, f"原生选择失败({native_error})，组件选择也失败({exc})"
            ) from exc
    @allure.step("验证元素可见: {locator}")
    def _do_verify(self, locator: str) -> None:
        """验证元素存在且可见。"""
        if not locator:
            raise self._step_error("verify", locator, "缺少定位器")

        last_error = None
        for attempt in range(2):
            try:
                element = self.page.locator(locator).first
                element.wait_for(state="visible", timeout=self.timeout_ms)
                logger.info("    → 元素可见: %s", locator[:40])
                return
            except Exception as exc:
                last_error = exc
                if attempt == 0:
                    self.page.wait_for_timeout(500)
        raise self._step_error("verify", locator, f"元素不可见: {last_error}") from last_error
    @allure.step("鼠标悬停: {locator}")
    def _do_hover(self, locator: str) -> None:
        """鼠标悬停。"""
        if not locator:
            raise self._step_error("hover", locator, "缺少定位器")
        try:
            self.page.locator(locator).first.hover(timeout=self.timeout_ms)
        except Exception as exc:
            raise self._step_error("hover", locator, str(exc)) from exc
    @allure.step("滚动到元素: {locator or '页面底部'}")
    def _do_scroll(self, locator: str) -> None:
        """滚动到目标元素；定位器为空时滚动到底部。"""
        try:
            if locator:
                self.page.locator(locator).first.scroll_into_view_if_needed(timeout=self.timeout_ms)
            else:
                self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        except Exception as exc:
            raise self._step_error("scroll", locator, str(exc)) from exc
    @allure.step("上传文件: {file_path} → {locator}")
    def _do_upload(self, locator: str, file_path: str) -> None:
        """上传文件。"""
        if not locator:
            raise self._step_error("upload", locator, "缺少定位器")
        if not file_path:
            raise self._step_error("upload", locator, "缺少文件路径")
        try:
            self.page.locator(locator).first.set_input_files(file_path, timeout=self.timeout_ms)
        except Exception as exc:
            raise self._step_error("upload", locator, str(exc)) from exc
    @staticmethod
    def _parse_date_range(data: str) -> tuple[str, str]:
        """解析两个完整日期，兼容 /、-、~、～、至作为分隔符。"""
        pattern = (
            r"^\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2})"
            r"\s*(?:~|～|至|-)\s*"
            r"(\d{4}[-/]\d{1,2}[-/]\d{1,2})\s*$"
        )
        match = re.fullmatch(pattern, data or "")
        if not match:
            raise ValueError(f"日期范围格式错误: {data}，示例: 2026/01/01-2026/06/28")

        def normalize(raw: str) -> str:
            year, month, day = (int(part) for part in re.split(r"[-/]", raw))
            # datetime.date 会同时验证月份和日期是否合法。
            from datetime import date
            value = date(year, month, day)
            return value.isoformat()

        return normalize(match.group(1)), normalize(match.group(2))

    @allure.step("日期范围选择: {data}")
    def _do_daterange(self, locator: str, data: str) -> None:
        """输入 Ant Design RangePicker 的开始和结束日期。"""
        if not locator:
            raise self._step_error("daterange", locator, "缺少日期输入框定位器")
        try:
            start_date, end_date = self._parse_date_range(data)
        except ValueError as exc:
            raise self._step_error("daterange", locator, str(exc)) from exc

        inputs = self.page.locator(locator)
        if inputs.count() < 2:
            raise self._step_error("daterange", locator, "定位器没有匹配到两个日期输入框")

        try:
            start_input = inputs.nth(0)
            end_input = inputs.nth(1)
            start_input.fill(start_date, timeout=self.timeout_ms)
            end_input.fill(end_date, timeout=self.timeout_ms)
            end_input.press("Enter")
            logger.info("    → 日期范围已应用: %s ~ %s", start_date, end_date)
        except Exception as exc:
            raise self._step_error("daterange", locator, str(exc)) from exc
    @allure.step("切换到标签页: {locator}")
    def _do_switch_tab(self, locator: str) -> None:
        """切换到指定页码；为空时切换到最新打开的标签页。"""
        try:
            pages = self.page.context.pages
            for _ in range(10):
                if len(pages) > 1:
                    break
                self.page.wait_for_timeout(500)
                pages = self.page.context.pages

            if locator and locator.strip():
                index = int(locator)
                if index < 0 or index >= len(pages):
                    raise IndexError(f"标签页索引 {index} 超出范围，当前共 {len(pages)} 页")
                target = pages[index]
            else:
                target = pages[-1]

            target.bring_to_front()
            target.wait_for_load_state("domcontentloaded", timeout=max(self.timeout_ms, 15000))
            self.page = target
            self._current_page = target
            logger.info("    → 已切换到标签页: %s", target.url[:80])
        except Exception as exc:
            raise self._step_error("switch_tab", locator, str(exc)) from exc
    def get_current_page(self):
        """获取当前操作的页面（可能在执行中切换了新标签页）"""
        return getattr(self, "_current_page", self.page)
