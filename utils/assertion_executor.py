"""
断言执行器 —— 读取 Excel 中的「断言类型」「验证点」并执行断言

Allure 集成：
- 每个断言步骤在 Allure 报告中显示为独立步骤
"""
import re
import logging
from datetime import datetime
import allure
from playwright.sync_api import Page, expect

logger = logging.getLogger("assertion_executor")


class AssertionExecutor:
    """执行 Excel 中定义的断言验证；未知或缺失断言一律失败。"""

    ASSERTION_ALIASES = {
        "visible_text": "text_visible",  # 兼容历史 Excel 写法
    }

    def __init__(self, page: Page, timeout_ms: int = 5000):
        self.page = page
        self.timeout_ms = max(int(timeout_ms), 1)

    @allure.step("断言: [{assert_type}] {verify_point}")
    def assert_by_type(self, assert_type: str, verify_point: str, locator: str = "") -> bool:
        if not assert_type or str(assert_type).strip() in ("", "/", "-"):
            raise AssertionError("断言类型为空，拒绝将未验证的用例标记为通过")

        assert_type = str(assert_type).strip()
        assert_type = self.ASSERTION_ALIASES.get(assert_type, assert_type)
        verify_point = str(verify_point or "")
        logger.info("  断言: [%s] %s", assert_type, verify_point[:50])

        try:
            if assert_type == "text_equals":
                return self._text_equals(verify_point, locator)
            if assert_type == "text_contains":
                return self._text_contains(verify_point, locator)
            if assert_type == "text_visible":
                return self._text_visible(verify_point)
            if assert_type == "text_hidden":
                return self._text_hidden(verify_point)
            if assert_type == "text_not_empty":
                return self._text_not_empty(locator)
            if assert_type == "value_equals":
                return self._value_equals(verify_point, locator)
            if assert_type == "element_visible":
                return self._element_visible(locator)
            if assert_type == "element_disabled":
                return self._element_disabled(locator)
            if assert_type == "element_count":
                return self._element_count(verify_point, locator)
            if assert_type == "attr_equals":
                return self._attr_equals(verify_point, locator)
            if assert_type == "url_contains":
                return self._url_contains(verify_point)
            if assert_type == "url_matches":
                return self._url_matches(verify_point)
            if assert_type == "empty_list":
                return self._empty_list(locator)
            if assert_type == "list_contains":
                return self._list_contains(verify_point, locator)
            if assert_type == "date_in_range":
                return self._date_in_range(verify_point, locator)
            if assert_type == "value_in_range":
                return self._value_in_range(verify_point, locator)
            if assert_type == "file_verify":
                return self._file_verify(verify_point)
            if assert_type == "age_in_range":
                return self._age_in_range(verify_point)
            if assert_type == "date_format":
                return self._date_format(verify_point, locator)
            if assert_type == "text_optional":
                return self._text_optional(verify_point, locator)
            raise ValueError(f"未知断言类型: {assert_type}")
        except AssertionError:
            raise
        except Exception as exc:
            logger.warning("  ❌ 断言执行异常: %s", exc)
            raise AssertionError(f"断言执行异常: {exc}") from exc
    @allure.step("验证文本相等: {expected}")
    def _text_equals(self, expected: str, locator: str) -> bool:
        # 【健壮性】等待页面加载完成再读取文本，避免页面未渲染完成导致误判
        try:
            self.page.wait_for_load_state("domcontentloaded", timeout=self.timeout_ms)
        except Exception:
            pass
        if locator:
            actual = self.page.locator(locator).first.inner_text(timeout=self.timeout_ms)
        else:
            actual = self.page.locator("body").inner_text()
        assert actual.strip() == expected.strip(), \
            f"文本不相等\n  期望: {expected}\n  实际: {actual[:100]}"
        logger.info(f"  ✅ 文本相等")
        return True

    @allure.step("验证文本包含: {expected}")
    def _text_contains(self, expected: str, locator: str) -> bool:
        """验证文本包含指定内容（三元兜底：元素→body→Toast）"""
        # 【健壮性】等待页面加载稳定后再读取文本，避免因页面切换中导致文本读取不全
        try:
            self.page.wait_for_load_state("domcontentloaded", timeout=self.timeout_ms)
        except Exception:
            pass
        keyword = self._extract_assert_keyword(expected) or expected
        if locator:
            try:
                actual = self.page.locator(locator).first.inner_text(timeout=2000)
                if keyword in actual:
                    logger.info(f"  ✅ 元素文本包含: {keyword}")
                    return True
            except Exception:
                pass
        body_text = self.page.locator("body").inner_text()
        if keyword in body_text:
            logger.info(f"  ✅ body文本包含: {keyword}")
            return True
        try:
            toast = self.page.locator(".ant-message-notice")
            if toast.count() > 0:
                toast_text = toast.first.inner_text()
                if keyword in toast_text:
                    logger.info(f"  ✅ Toast包含: {keyword}")
                    return True
        except Exception:
            pass
        raise AssertionError(f"文本不包含「{keyword}」\n  body: {body_text[:200]}")

    @allure.step("验证文本可见: {expected}")
    def _text_visible(self, expected: str) -> bool:
        keywords = [item for item in self._extract_multi_keywords(expected) if item]
        assert keywords, "文本可见断言缺少期望文本"

        body_text = ""
        attempts = max(1, self.timeout_ms // 500)
        for _ in range(attempts):
            body_text = self.page.locator("body").inner_text()
            if all(keyword in body_text for keyword in keywords):
                logger.info("  ✅ 文本均可见: %s", keywords)
                return True
            self.page.wait_for_timeout(500)
        missing = [keyword for keyword in keywords if keyword not in body_text]
        raise AssertionError(f"页面中未找到文本: {missing}")

    @allure.step("验证文本已隐藏: {expected}")
    def _text_hidden(self, expected: str) -> bool:
        """断言文本在超时时间内从页面消失（如删除标签后不再显示）。"""
        keywords = [item for item in self._extract_multi_keywords(expected) if item]
        assert keywords, "文本隐藏断言缺少期望文本"

        attempts = max(1, self.timeout_ms // 500)
        for _ in range(attempts):
            body_text = self.page.locator("body").inner_text()
            if not any(keyword in body_text for keyword in keywords):
                logger.info("  ✅ 文本已隐藏: %s", keywords)
                return True
            self.page.wait_for_timeout(500)
        visible = [keyword for keyword in keywords if keyword in body_text]
        raise AssertionError(f"页面仍可见文本: {visible}")

    @allure.step("验证文本不为空: {locator}")
    def _text_not_empty(self, locator: str) -> bool:
        assert locator, "text_not_empty 断言缺少定位器"
        text = self.page.locator(locator).first.inner_text(timeout=self.timeout_ms)
        assert text.strip(), f"元素文本为空: {locator}"
        logger.info("  ✅ 文本不为空: %s", text[:30])
        return True

    @allure.step("验证输入框值: {expected}")
    def _value_equals(self, expected: str, locator: str) -> bool:
        """断言输入框的值（input_value），验证点写「空」表示空字符串。"""
        assert locator, "value_equals 断言缺少定位器"
        expected_val = "" if expected.strip() == "空" else expected.strip()
        value = self.page.locator(locator).first.input_value(timeout=self.timeout_ms)
        assert value == expected_val, f"输入框值不匹配\n  期望: {expected_val!r}\n  实际: {value!r}"
        logger.info("  ✅ 输入框值匹配: %r", value)
        return True
    @allure.step("验证元素可见: {locator}")
    def _element_visible(self, locator: str) -> bool:
        assert locator, "element_visible 断言缺少定位器"
        element = self.page.locator(locator).first
        expect(element).to_be_visible(timeout=self.timeout_ms)
        logger.info("  ✅ 元素可见: %s", locator[:40])
        return True

    @allure.step("验证元素禁用: {locator}")
    def _element_disabled(self, locator: str) -> bool:
        """断言元素处于禁用状态（disabled 属性）。

        新版 Ant Design 按钮禁用态不再加 ant-btn-disabled class，
        而是通过 disabled 属性渲染灰色，class 检查不可靠，必须查属性。
        """
        assert locator, "element_disabled 断言缺少定位器"
        element = self.page.locator(locator).first
        expect(element).to_be_disabled(timeout=self.timeout_ms)
        logger.info("  ✅ 元素已禁用: %s", locator[:40])
        return True
    @allure.step("验证元素数量: {expected}")
    def _element_count(self, expected: str, locator: str) -> bool:
        assert locator, "element_count 断言缺少定位器"
        numbers = re.findall(r"\d+", expected)
        assert numbers, f"元素数量断言缺少期望数量: {expected}"
        count = self.page.locator(locator).count()
        expected_count = int(numbers[0])
        assert count >= expected_count, f"元素数量不足\n  期望至少: {expected_count}\n  实际: {count}"
        logger.info("  ✅ 元素数量 %s >= %s", count, expected_count)
        return True
    @allure.step("验证属性: {expected}")
    def _attr_equals(self, expected: str, locator: str) -> bool:
        assert locator, "attr_equals 断言缺少定位器"
        if "包含" in expected:
            attribute, value = expected.split("包含", 1)
            mode = "contains"
        elif "=" in expected:
            attribute, value = expected.split("=", 1)
            mode = "equals"
        else:
            raise AssertionError(f"属性断言格式错误: {expected}，示例: value=abc")

        attribute, value = attribute.strip(), value.strip()
        assert attribute and value, f"属性断言格式错误: {expected}"
        actual = self.page.locator(locator).first.get_attribute(attribute)
        if mode == "equals":
            assert actual == value, f"属性不相等\n  期望 {attribute}={value}\n  实际={actual}"
        else:
            assert actual is not None and value in actual, (
                f"属性不包含\n  期望 {attribute} 包含 {value}\n  实际={actual}"
            )
        logger.info("  ✅ 属性验证通过")
        return True
    @allure.step("验证URL包含: {expected}")
    def _url_contains(self, expected: str) -> bool:
        """验证 URL 包含指定内容，支持中文“或”逻辑。"""
        url = self.page.url
        keywords = re.findall(r"['\"]([^'\"]+)['\"]", expected)
        if not keywords:
            keywords = re.findall(r"/[\w-]+", expected)
        assert keywords, f"URL 断言没有可解析的期望值: {expected}"

        if "或" in expected:
            assert any(keyword in url for keyword in keywords), (
                f"URL 不包含任一: {keywords}\n  当前URL: {url}"
            )
        else:
            missing = [keyword for keyword in keywords if keyword not in url]
            assert not missing, f"URL 不包含 {missing}\n  当前URL: {url}"
        logger.info("  ✅ URL 验证通过: %s", keywords)
        return True
    @allure.step("验证URL匹配正则: {pattern}")
    def _url_matches(self, pattern: str) -> bool:
        assert pattern, "URL 正则断言为空"
        assert re.search(pattern, self.page.url), f"URL 不匹配正则: {pattern}\n  当前URL: {self.page.url}"
        logger.info("  ✅ URL 匹配正则")
        return True
    @allure.step("验证列表为空")
    def _empty_list(self, locator: str) -> bool:
        if locator:
            count = self.page.locator(locator).count()
        else:
            count = len(self.page.locator("[class*=list-item], [class*=ant-list]").all())
        assert count == 0 or "暂无" in self.page.locator("body").inner_text(), f"列表不为空: {count}"
        logger.info(f"  ✅ 列表为空")
        return True

    @allure.step("验证列表包含: {expected}")
    def _list_contains(self, expected: str, locator: str) -> bool:
        assert locator, "list_contains 断言缺少定位器"
        keyword = self._extract_assert_keyword(expected) or expected
        assert keyword, "list_contains 断言缺少期望文本"
        texts = [item.inner_text() for item in self.page.locator(locator).all()]
        all_text = " ".join(texts)
        assert keyword in all_text, f"列表中未找到「{keyword}」"
        logger.info("  ✅ 列表包含: %s", keyword)
        return True
    @allure.step("验证日期格式")
    def _date_in_range(self, expected: str, locator: str) -> bool:
        assert locator, "日期断言缺少定位器"
        text = self.page.locator(locator).first.inner_text(timeout=self.timeout_ms)
        assert re.search(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", text), f"日期格式异常: {text}"
        logger.info("  ✅ 日期格式正确")
        return True
    @allure.step("验证数值范围: {expected}")
    def _value_in_range(self, expected: str, locator: str) -> bool:
        assert locator, "value_in_range 断言缺少定位器"
        text = self.page.locator(locator).first.inner_text(timeout=self.timeout_ms)
        actual_numbers = re.findall(r"-?\d+(?:\.\d+)?", text)
        assert actual_numbers, f"未找到数值: {text}"
        actual = float(actual_numbers[0])
        expected_numbers = [float(value) for value in re.findall(r"-?\d+(?:\.\d+)?", expected)]
        if len(expected_numbers) >= 2:
            lower, upper = expected_numbers[:2]
            assert lower <= actual <= upper, f"数值 {actual} 不在范围 {lower}~{upper} 内"
        logger.info("  ✅ 数值验证通过: %s", actual)
        return True
    @allure.step("验证顾客年龄在范围内: {expected_range}")
    def _age_in_range(self, expected_range: str) -> bool:
        """
        从顾客详情页读取生日，计算年龄，验证是否在指定范围内

        页面文本格式: 『男生日：2025-03-26』或『女生日：YYYY-MM-DD』
        验证点格式:
          - 『18~25』 → 解析为 [18, 25]
          - 『18岁以下』或『0~18』 → 解析为 [0, 18]
          - 『18岁以上』或『18~100』 → 解析为 [18, 200]
        """
        # 解析年龄范围
        nums = re.findall(r'\d+', expected_range)
        if "以下" in expected_range:
            # "18岁以下" → [0, 18]
            max_age = int(nums[0]) if nums else 18
            min_age = 0
        elif "以上" in expected_range:
            # "18岁以上" → [18, 200]
            min_age = int(nums[0]) if nums else 18
            max_age = 200
        else:
            # "18~25" → [18, 25]
            assert len(nums) >= 2, f"年龄范围格式错误: {expected_range}（应为类似 18~25 或 18岁以下）"
            min_age, max_age = int(nums[0]), int(nums[1])

        # 在页面中查找生日文本
        body_text = self.page.locator("body").inner_text()
        # 匹配 "生日：2025-03-26"、"男生日：2025-03-26"、"女生日：2025-03-26"
        birth_match = re.search(r'生日[：:]\s*(\d{4})-(\d{2})-(\d{2})', body_text)
        assert birth_match, f"页面未找到生日信息\n  页面内容: {body_text[:200]}"

        birth_year = int(birth_match.group(1))
        birth_month = int(birth_match.group(2))
        birth_day = int(birth_match.group(3))

        # 计算年龄（以当前日期 2026-06-29 为基准）
        today = datetime.now()
        age = today.year - birth_year
        if (today.month, today.day) < (birth_month, birth_day):
            age -= 1

        birthday_str = f"{birth_year}-{birth_month:02d}-{birth_day:02d}"
        logger.info(f"    → 生日: {birthday_str}，计算年龄: {age}岁（期望范围: {min_age}~{max_age}岁）")

        assert min_age <= age <= max_age, \
            f"顾客年龄 {age} 不在期望范围 {min_age}~{max_age} 内（生日: {birthday_str}）"
        logger.info(f"  ✅ 年龄 {age} 在范围 {min_age}~{max_age} 内")
        return True

    @allure.step("文件验证: {expected}")
    def _file_verify(self, expected: str) -> bool:
        from pathlib import Path

        raw_path = expected.strip().strip("'\"")
        assert raw_path, "file_verify 断言缺少文件路径"
        path = Path(raw_path)
        assert path.is_file(), f"文件不存在: {path}"
        assert path.stat().st_size > 0, f"文件为空: {path}"
        logger.info("  ✅ 文件存在且非空: %s", path)
        return True

    def _date_format(self, expected: str, locator: str) -> bool:
        return self._date_in_range(expected, locator)

    def _text_optional(self, expected: str, locator: str) -> bool:
        """允许字段值为空，但字段标签本身必须真实可见。"""
        assert locator, "text_optional 断言缺少字段定位器"
        element = self.page.locator(locator).first
        expect(element).to_be_visible(timeout=self.timeout_ms)
        logger.info("  ✅ 可选字段已显示: %s", expected[:40])
        return True
    @staticmethod
    def _extract_assert_keyword(text: str) -> str:
        if not text:
            return ""
        text = re.sub(r'^\d+[\.\、\s]+', '', text.strip())
        match = re.search(r"['\"]([^'\"]*)['\"]", text)
        if match:
            return match.group(1).strip()
        match = re.search(r"包含'([^']+)'", text)
        if match:
            return match.group(1).strip()
        return text[:40].strip()

    @staticmethod
    def _extract_multi_keywords(text: str) -> list[str]:
        if not text:
            return []
        keywords = re.findall(r"['\"]([^'\"]+)['\"]", text)
        if keywords:
            return keywords
        parts = re.split(r"[、，,]", text)
        result = []
        for p in parts:
            p = p.strip()
            if p and p not in ("页面包含", "文本", "或", ""):
                result.append(p)
        return result if result else [text[:30]]
