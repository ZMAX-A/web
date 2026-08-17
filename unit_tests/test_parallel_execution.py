import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from run_parallel_tests import WorkerOutcome, WorkerSpec, _merge_worker_results
from utils.case_validator import CaseValidationError, validate_cases
from utils.parallel_execution import (
    account_env_value,
    assign_case_groups,
    auth_state_path,
    cases_for_worker,
    normalize_execution_group,
    substitute_runtime_tokens,
)


def _case(case_id: str, module: str, group: str = "AUTO", row: int = 2) -> dict:
    return {
        "用例ID": case_id,
        "模块": module,
        "执行分组": group,
        "是否执行": "是",
        "_row": row,
    }


def test_fixed_module_groups_match_parallel_design():
    cases = [
        _case("A-1", "顾客详情"),
        _case("A-2", "影像阅览"),
        _case("A-3", "首页搜索"),
        _case("B-1", "账号登录"),
        _case("B-2", "顾客列表"),
        _case("B-3", "首页"),
        _case("B-4", "首页跳转"),
        _case("B-5", "案例库"),
        _case("B-6", "个人中心"),
    ]
    groups = assign_case_groups(cases)
    assert [case["用例ID"] for case in groups["A"]] == ["A-1", "A-2", "A-3"]
    assert [case["用例ID"] for case in groups["B"]] == [
        "B-1", "B-2", "B-3", "B-4", "B-5", "B-6"
    ]


def test_explicit_groups_override_module_and_auto_balances_unknowns():
    cases = [
        _case("X-1", "顾客详情", "B"),
        _case("X-2", "未知模块", "SERIAL"),
        _case("X-3", "未知模块"),
        _case("X-4", "未知模块"),
    ]
    groups = assign_case_groups(cases)
    assert [case["用例ID"] for case in groups["B"]] == ["X-1"]
    assert [case["用例ID"] for case in groups["SERIAL"]] == ["X-2"]
    assert [case["用例ID"] for case in groups["A"]] == ["X-3", "X-4"]


def test_invalid_execution_group_is_rejected():
    with pytest.raises(ValueError, match="仅支持 A/B/SERIAL/AUTO"):
        normalize_execution_group("C")


def test_worker_filter_and_account_slot(monkeypatch):
    monkeypatch.setenv("TEST_WORKER_ID", "B")
    monkeypatch.setenv("TEST_USERNAME_B", "worker-b")
    monkeypatch.setenv("TEST_USERNAME", "legacy")
    cases = [_case("A-1", "顾客详情"), _case("B-1", "账号登录")]
    assert [case["用例ID"] for case in cases_for_worker(cases)] == ["B-1"]
    assert account_env_value("TEST_USERNAME") == "worker-b"


def test_runtime_paths_and_business_tokens_are_worker_isolated(monkeypatch, tmp_path: Path):
    state = tmp_path / "worker_B" / "auth.json"
    monkeypatch.setenv("TEST_WORKER_ID", "B")
    monkeypatch.setenv("TEST_AUTH_STATE_FILE", str(state))
    monkeypatch.setenv("TEST_RUN_TIMESTAMP", "20260814143000")
    assert auth_state_path() == state.resolve()
    assert substitute_runtime_tokens("顾客-${WORKER_ID}-${TIMESTAMP}") == (
        "顾客-B-20260814143000"
    )


def test_case_validator_reports_invalid_execution_group():
    case = {
        "用例ID": "TC-DEMO-001",
        "执行分组": "C",
        "操作类型": "wait",
        "元素定位器": "0.1",
        "断言类型": "url_contains",
        "验证点": "/home",
        "_row": 2,
    }
    with pytest.raises(CaseValidationError, match="不支持的执行分组"):
        validate_cases([case])


def test_missing_worker_payload_marks_only_that_group_as_infra_error(tmp_path: Path):
    spec = WorkerSpec("A", "A", [_case("A-1", "顾客详情", row=9)], tmp_path)
    records = _merge_worker_results([
        WorkerOutcome(spec=spec, returncode=2, payload=None, payload_error="未生成结果文件")
    ])
    assert records == [{
        "case_id": "A-1",
        "status": "infra_error",
        "result": "infra_error: Worker A 未生成结果文件",
        "row": 9,
        "duration": 0.0,
        "worker_id": "A",
    }]


def test_worker_json_result_uses_excel_row_from_assignment(tmp_path: Path):
    spec = WorkerSpec("B", "B", [_case("B-1", "账号登录", row=12)], tmp_path)
    payload = {
        "worker_id": "B",
        "collected_case_ids": ["B-1"],
        "results": [{
            "case_id": "B-1",
            "status": "pass",
            "result": "pass",
            "row": 999,
            "duration": 1.25,
        }],
    }
    records = _merge_worker_results([WorkerOutcome(spec, 0, payload)])
    assert records[0]["row"] == 12
    assert records[0]["worker_id"] == "B"


def test_pytest_worker_writes_json_instead_of_excel(monkeypatch, tmp_path: Path):
    from tests import conftest

    result_file = tmp_path / "worker_A" / "results_A.json"
    auth_file = tmp_path / "worker_A" / "auth_state.json"
    monkeypatch.setenv("TEST_WORKER_ID", "A")
    monkeypatch.setenv("TEST_ACCOUNT_SLOT", "A")
    monkeypatch.setenv("TEST_RUN_ID", "RUN-TEST")
    monkeypatch.setenv("TEST_RESULT_FILE", str(result_file))
    monkeypatch.setenv("TEST_AUTH_STATE_FILE", str(auth_file))

    report = SimpleNamespace(
        failed=False,
        skipped=False,
        passed=True,
        duration=1.25,
        longrepr=None,
    )
    item = SimpleNamespace(
        callspec=SimpleNamespace(params={
            "test_case": {"用例ID": "TC-A", "_row": 7},
        }),
        rep_call=report,
    )
    session = SimpleNamespace(
        items=[item],
        config=SimpleNamespace(option=SimpleNamespace(collectonly=False)),
    )

    conftest.pytest_sessionfinish(session, 0)

    payload = json.loads(result_file.read_text(encoding="utf-8"))
    assert payload["worker_id"] == "A"
    assert payload["results"] == [{
        "case_id": "TC-A",
        "status": "pass",
        "result": "pass",
        "row": 7,
        "duration": 1.25,
    }]
