"""Excel 用例静态校验：在启动浏览器前发现拼写和步骤配置问题。"""
from __future__ import annotations

from collections.abc import Iterable

from utils.parallel_execution import normalize_execution_group


SUPPORTED_OPERATIONS = {
    "input", "input_enter", "click", "select", "verify", "hover", "scroll", "wait", "nav",
    "find_click", "upload", "daterange", "date_range", "switch_tab",
    "retry_report",
}
SUPPORTED_ASSERTIONS = {
    "text_equals", "text_contains", "text_visible", "text_hidden", "text_not_empty",
    "value_equals", "element_visible", "element_disabled", "element_count", "attr_equals",
    "url_contains",
    "url_matches", "empty_list", "list_contains", "date_in_range",
    "value_in_range", "file_verify", "age_in_range", "date_format",
    "text_optional",
}
ASSERTION_ALIASES = {"visible_text": "text_visible"}
OPERATIONS_REQUIRING_LOCATOR = {
    "input", "input_enter", "click", "select", "verify", "hover", "find_click", "upload",
    "daterange", "date_range", "retry_report",
}
ASSERTIONS_REQUIRING_LOCATOR = {
    "text_not_empty", "value_equals", "element_visible", "element_disabled", "element_count",
    "attr_equals",
    "list_contains", "date_in_range", "value_in_range", "date_format",
    "text_optional",
}
DATA_OPERATIONS = {"input", "input_enter", "select", "nav", "upload", "daterange", "date_range"}


class CaseValidationError(ValueError):
    """一个或多个 Excel 用例不满足执行约定。"""


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def validate_cases(cases: Iterable[dict]) -> None:
    """校验关键字驱动用例；发现任何错误时一次性给出全部位置。"""
    cases = list(cases)
    if not cases:
        raise CaseValidationError("Excel 中没有可执行用例")

    errors: list[str] = []
    seen_ids: set[str] = set()
    for position, case in enumerate(cases, start=2):
        row = case.get("_row") or position
        case_id = _text(case.get("用例ID") or case.get("编号"))
        prefix = f"第{row}行[{case_id or '无用例ID'}]"

        # 标记「是否执行=否」的用例跳过校验
        run_flag = _text(case.get("是否执行"))
        if run_flag and run_flag not in ("是", "1", "Y", "y", "True", "true"):
            continue

        if not case_id:
            errors.append(f"{prefix}: 用例ID为空")
        elif case_id in seen_ids:
            errors.append(f"{prefix}: 用例ID重复")
        seen_ids.add(case_id)

        # 旧版用例由页面对象路由执行，仅检查 ID；以下规则只适用于关键字格式。
        if "用例ID" not in case:
            continue

        try:
            normalize_execution_group(case.get("执行分组", "AUTO"))
        except ValueError as exc:
            errors.append(f"{prefix}: {exc}")

        operations_raw = _text(case.get("操作类型"))
        locators_raw = _text(case.get("元素定位器"))
        data_raw = _text(case.get("输入数据"))
        operations = [item.strip() for item in operations_raw.split(",")] if operations_raw else []
        locators = [item.strip() for item in locators_raw.split(",")] if locators_raw else []
        data_parts = [item.strip() for item in data_raw.split("|")] if data_raw else []

        if not operations:
            errors.append(f"{prefix}: 操作类型为空")
            continue
        if len(locators) > len(operations) + 1:
            errors.append(
                f"{prefix}: 定位器数量({len(locators)})超过操作数量({len(operations)})太多，"
                "请把断言定位器放入独立列"
            )

        data_index = 0
        for index, operation in enumerate(operations):
            locator = locators[index] if index < len(locators) else ""
            if not operation:
                errors.append(f"{prefix}: 第{index + 1}个操作为空")
                continue
            if operation not in SUPPORTED_OPERATIONS:
                errors.append(f"{prefix}: 不支持的操作类型「{operation}」")
                continue
            if operation in OPERATIONS_REQUIRING_LOCATOR and not locator:
                errors.append(f"{prefix}: 操作「{operation}」缺少定位器")
            if operation == "wait":
                try:
                    seconds = float(locator or "1")
                    if seconds < 0:
                        raise ValueError
                except ValueError:
                    errors.append(f"{prefix}: wait 定位器必须是非负秒数，实际为「{locator}」")

            data_value = data_parts[data_index] if data_index < len(data_parts) else ""
            if operation in DATA_OPERATIONS:
                data_index += 1
            if operation == "nav" and not (data_value or locator):
                errors.append(f"{prefix}: nav 缺少 URL（定位器和输入数据均为空）")
            if operation in {"upload", "daterange", "date_range"} and not data_value:
                errors.append(f"{prefix}: 操作「{operation}」缺少输入数据")

        assert_type = _text(case.get("断言类型"))
        assert_type = ASSERTION_ALIASES.get(assert_type, assert_type)
        if not assert_type:
            errors.append(f"{prefix}: 断言类型为空")
        elif assert_type not in SUPPORTED_ASSERTIONS:
            errors.append(f"{prefix}: 不支持的断言类型「{assert_type}」")

        assertion_locator = _text(case.get("断言定位器"))
        if not assertion_locator:
            assertion_locator = next((item for item in reversed(locators) if item), "")
        if assert_type in ASSERTIONS_REQUIRING_LOCATOR and not assertion_locator:
            errors.append(f"{prefix}: 断言「{assert_type}」缺少定位器")

        timeout = _text(case.get("超时(秒)"))
        if timeout:
            try:
                if float(timeout) <= 0:
                    raise ValueError
            except ValueError:
                errors.append(f"{prefix}: 超时(秒)必须为正数，实际为「{timeout}」")

    if errors:
        details = "\n".join(f"- {message}" for message in errors)
        raise CaseValidationError(f"Excel 用例校验失败，共 {len(errors)} 项：\n{details}")
