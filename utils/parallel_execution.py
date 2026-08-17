"""双进程执行的分组、账号和运行目录约定。

该模块不启动子进程，只提供可复用且易于单元测试的纯逻辑。Pytest Worker
和主调度器必须同时使用这里的规则，避免同一条用例在两边得到不同分组。
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parent.parent

GROUP_A_MODULES = frozenset({"顾客详情", "影像阅览", "首页搜索"})
GROUP_B_MODULES = frozenset({"账号登录", "顾客列表", "首页", "首页跳转", "案例库", "个人中心"})
VALID_EXECUTION_GROUPS = frozenset({"A", "B", "SERIAL", "AUTO"})


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def case_id(case: dict) -> str:
    """返回新旧两种 Excel 格式中的用例 ID。"""
    return _text(case.get("用例ID") or case.get("编号"))


def is_case_enabled(case: dict) -> bool:
    """与现有执行器保持一致：否/N/n 表示禁用，其余值默认启用。"""
    return _text(case.get("是否执行") or "是") not in {"否", "N", "n"}


def normalize_execution_group(value: object) -> str:
    """规范化 Excel 中的执行分组；空值等同 AUTO。"""
    raw = _text(value).upper()
    aliases = {
        "": "AUTO",
        "自动": "AUTO",
        "串行": "SERIAL",
        "WORKER_A": "A",
        "WORKER_B": "B",
    }
    group = aliases.get(raw, raw)
    if group not in VALID_EXECUTION_GROUPS:
        raise ValueError(f"不支持的执行分组「{value}」，仅支持 A/B/SERIAL/AUTO")
    return group


def assign_case_groups(cases: Iterable[dict]) -> dict[str, list[dict]]:
    """把用例稳定地分到 A、B、SERIAL。

    优先级：Excel 显式分组 > 已约定模块分组 > AUTO 动态平衡。动态平衡只
    用于尚未纳入模块映射的新用例，并按 Excel 行顺序分配，结果可重复。
    """
    groups: dict[str, list[dict]] = {"A": [], "B": [], "SERIAL": []}
    unresolved: list[dict] = []

    for case in cases:
        if not is_case_enabled(case):
            continue
        group = normalize_execution_group(case.get("执行分组", "AUTO"))
        if group in {"A", "B", "SERIAL"}:
            groups[group].append(case)
            continue

        module = _text(case.get("模块"))
        if module in GROUP_A_MODULES:
            groups["A"].append(case)
        elif module in GROUP_B_MODULES:
            groups["B"].append(case)
        else:
            unresolved.append(case)

    for case in unresolved:
        target = "A" if len(groups["A"]) <= len(groups["B"]) else "B"
        groups[target].append(case)

    return groups


def cases_for_worker(cases: Iterable[dict], worker_id: str | None = None) -> list[dict]:
    """返回指定 Worker 的用例；无 Worker 环境时保持单进程全量兼容。"""
    selected_worker = normalize_worker_id(worker_id or os.getenv("TEST_WORKER_ID", ""))
    case_list = [case for case in cases if is_case_enabled(case)]
    if not selected_worker:
        return case_list
    return assign_case_groups(case_list)[selected_worker]


def normalize_worker_id(value: object) -> str:
    """只接受调度器支持的 Worker 标识，空值代表传统单进程模式。"""
    worker = _text(value).upper()
    if not worker:
        return ""
    if worker not in {"A", "B", "SERIAL"}:
        raise ValueError(f"不支持的 Worker「{value}」")
    return worker


def current_worker_id() -> str:
    return normalize_worker_id(os.getenv("TEST_WORKER_ID", ""))


def current_account_slot() -> str:
    """SERIAL 默认使用账号 A，也可由 TEST_ACCOUNT_SLOT 显式覆盖。"""
    configured = _text(os.getenv("TEST_ACCOUNT_SLOT", "")).upper()
    if configured:
        if configured not in {"A", "B"}:
            raise ValueError("TEST_ACCOUNT_SLOT 仅支持 A 或 B")
        return configured
    worker = current_worker_id()
    return worker if worker in {"A", "B"} else "A" if worker == "SERIAL" else ""


def account_env_value(base_name: str, default: str = "") -> str:
    """读取当前 Worker 账号配置，并兼容原单账号环境变量。"""
    slot = current_account_slot()
    if slot:
        slot_value = os.getenv(f"{base_name}_{slot}", "")
        if slot_value:
            return slot_value
    legacy_value = os.getenv(base_name, "")
    if legacy_value:
        return legacy_value
    if not slot:
        return os.getenv(f"{base_name}_A", default)
    return default


def _path_from_env(name: str) -> Path | None:
    raw = _text(os.getenv(name, ""))
    return Path(raw).resolve() if raw else None


def auth_state_path() -> Path:
    explicit = _path_from_env("TEST_AUTH_STATE_FILE")
    if explicit:
        return explicit
    return PROJECT_ROOT / ".auth_state.json"


def screenshot_dir() -> Path:
    explicit = _path_from_env("TEST_SCREENSHOT_DIR")
    if explicit:
        return explicit
    return PROJECT_ROOT / "screenshots"


def result_file_path() -> Path | None:
    return _path_from_env("TEST_RESULT_FILE")


def runtime_timestamp() -> str:
    """用于 ${TIMESTAMP}，调度运行内保持一致。"""
    configured = _text(os.getenv("TEST_RUN_TIMESTAMP", ""))
    return configured or datetime.now().strftime("%Y%m%d%H%M%S")


def substitute_runtime_tokens(value: object) -> str:
    """替换双进程业务数据隔离占位符。"""
    text = "" if value is None else str(value)
    worker = current_worker_id() or "LOCAL"
    return text.replace("${WORKER_ID}", worker).replace("${TIMESTAMP}", runtime_timestamp())
