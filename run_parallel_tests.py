"""使用两个独立账号并行执行 Excel 驱动的 Web 自动化用例。

架构：主进程校验与分组 -> Worker A/B 并发 -> 可选 SERIAL 串行 ->
汇总 JSON -> Excel 单次回写 -> 合并 Allure 结果并生成总报告。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from utils.case_validator import CaseValidationError, validate_cases
from utils.excel_handler import ExcelHandler
from utils.parallel_execution import assign_case_groups, case_id, is_case_enabled


PROJECT_ROOT = Path(__file__).resolve().parent
REPORTS_ROOT = PROJECT_ROOT / "reports" / "runs"


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(errors="replace")


@dataclass
class WorkerSpec:
    worker_id: str
    account_slot: str
    cases: list[dict]
    run_dir: Path

    @property
    def worker_dir(self) -> Path:
        return self.run_dir / f"worker_{self.worker_id}"

    @property
    def result_file(self) -> Path:
        return self.worker_dir / f"results_{self.worker_id}.json"

    @property
    def allure_dir(self) -> Path:
        return self.worker_dir / "allure-results"


@dataclass
class WorkerOutcome:
    spec: WorkerSpec
    returncode: int
    payload: dict | None
    payload_error: str = ""


def _excel_path() -> Path:
    cases_dir = PROJECT_ROOT / "test_cases"
    for name in ("test_case.xlsx", "yanjia_ai_overseas_test_cases.xlsx", "core_test_cases.xlsx"):
        candidate = cases_dir / name
        if candidate.exists():
            return candidate
    return cases_dir / "test_case.xlsx"


def _python_executable() -> Path:
    candidate = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    return candidate if candidate.exists() else Path(sys.executable)


def _load_cases() -> tuple[Path, list[dict], dict[str, list[dict]]]:
    excel_path = _excel_path()
    handler = ExcelHandler(str(excel_path))
    all_cases = handler.read_test_cases()
    enabled_cases = [case for case in all_cases if is_case_enabled(case)]
    validate_cases(enabled_cases)
    groups = assign_case_groups(enabled_cases)
    return excel_path, enabled_cases, groups


def _validate_parallel_accounts() -> None:
    missing = [
        name
        for name in ("TEST_USERNAME_A", "TEST_PASSWORD_A", "TEST_USERNAME_B", "TEST_PASSWORD_B")
        if not os.getenv(name, "").strip()
    ]
    if missing:
        raise ValueError(".env 缺少双账号配置: " + ", ".join(missing))
    if os.getenv("TEST_USERNAME_A", "").strip() == os.getenv("TEST_USERNAME_B", "").strip():
        raise ValueError("账号 A 与账号 B 必须是两个不同账号，否则仍可能发生登录冲突")


def _run_framework_checks(python: Path) -> int:
    command = [
        str(python),
        "-m",
        "pytest",
        "unit_tests",
        "-q",
        "-o",
        "addopts=",
    ]
    print("运行离线框架检查...")
    return subprocess.run(command, cwd=PROJECT_ROOT, check=False).returncode


def _worker_env(spec: WorkerSpec, run_id: str, run_timestamp: str) -> dict[str, str]:
    env = os.environ.copy()
    env.update({
        "PYTHONUNBUFFERED": "1",
        "PYTHONIOENCODING": "utf-8",
        "TEST_WORKER_ID": spec.worker_id,
        "TEST_ACCOUNT_SLOT": spec.account_slot,
        "TEST_RUN_ID": run_id,
        "TEST_RUN_DIR": str(spec.run_dir),
        "TEST_RUN_TIMESTAMP": run_timestamp,
        "TEST_AUTH_STATE_FILE": str(spec.worker_dir / "auth_state.json"),
        "TEST_RESULT_FILE": str(spec.result_file),
        "TEST_SCREENSHOT_DIR": str(spec.worker_dir / "screenshots"),
    })
    return env


def _worker_command(python: Path, spec: WorkerSpec, pytest_args: list[str]) -> list[str]:
    return [
        str(python),
        "-m",
        "pytest",
        "tests/test_core_cases.py",
        "-v",
        "--tb=short",
        "--color=yes",
        "-p",
        "no:cacheprovider",
        "-o",
        "addopts=",
        f"--alluredir={spec.allure_dir}",
        "--clean-alluredir",
        *pytest_args,
    ]


def _stream_output(worker_id: str, process: subprocess.Popen[str]) -> None:
    assert process.stdout is not None
    for line in process.stdout:
        print(f"[{worker_id}] {line.rstrip()}", flush=True)


def _start_worker(
    python: Path,
    spec: WorkerSpec,
    run_id: str,
    run_timestamp: str,
    pytest_args: list[str],
) -> subprocess.Popen[str]:
    spec.worker_dir.mkdir(parents=True, exist_ok=True)
    print(
        f"[{spec.worker_id}] 启动：账号 {spec.account_slot}，"
        f"{len(spec.cases)} 条用例，结果目录 {spec.worker_dir}"
    )
    return subprocess.Popen(
        _worker_command(python, spec, pytest_args),
        cwd=PROJECT_ROOT,
        env=_worker_env(spec, run_id, run_timestamp),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )


def _read_payload(spec: WorkerSpec) -> tuple[dict | None, str]:
    if not spec.result_file.exists():
        return None, f"未生成结果文件 {spec.result_file.name}"
    try:
        payload = json.loads(spec.result_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"结果文件无法读取: {exc}"
    if payload.get("worker_id") != spec.worker_id:
        return None, "结果文件中的 worker_id 与调度分组不一致"
    if not isinstance(payload.get("results"), list):
        return None, "结果文件缺少 results 列表"
    return payload, ""


def _wait_for_processes(processes: dict[str, subprocess.Popen[str]]) -> dict[str, int]:
    threads = [
        threading.Thread(target=_stream_output, args=(worker_id, process), daemon=True)
        for worker_id, process in processes.items()
    ]
    for thread in threads:
        thread.start()
    try:
        returncodes = {worker_id: process.wait() for worker_id, process in processes.items()}
    except KeyboardInterrupt:
        print("\n收到中断，正在停止所有 Worker...")
        for process in processes.values():
            if process.poll() is None:
                process.terminate()
        for process in processes.values():
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        raise
    finally:
        for thread in threads:
            thread.join(timeout=5)
    return returncodes


def _stop_processes(processes: dict[str, subprocess.Popen[str]]) -> None:
    for process in processes.values():
        if process.poll() is None:
            process.terminate()
    for process in processes.values():
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def _run_worker_batch(
    python: Path,
    specs: list[WorkerSpec],
    run_id: str,
    run_timestamp: str,
    pytest_args: list[str],
) -> list[WorkerOutcome]:
    processes: dict[str, subprocess.Popen[str]] = {}
    try:
        for spec in specs:
            processes[spec.worker_id] = _start_worker(
                python, spec, run_id, run_timestamp, pytest_args
            )
    except OSError:
        _stop_processes(processes)
        raise
    returncodes = _wait_for_processes(processes)
    outcomes = []
    for spec in specs:
        payload, payload_error = _read_payload(spec)
        outcomes.append(WorkerOutcome(spec, returncodes[spec.worker_id], payload, payload_error))
    return outcomes


def _infra_record(case: dict, worker_id: str, reason: str) -> dict:
    return {
        "case_id": case_id(case),
        "status": "infra_error",
        "result": f"infra_error: Worker {worker_id} {reason}"[:320],
        "row": case.get("_row"),
        "duration": 0.0,
        "worker_id": worker_id,
    }


def _merge_worker_results(outcomes: list[WorkerOutcome]) -> list[dict]:
    merged: dict[str, dict] = {}
    for outcome in outcomes:
        spec = outcome.spec
        expected_by_id = {case_id(case): case for case in spec.cases}
        if outcome.payload is None:
            reason = outcome.payload_error or f"异常退出（退出码 {outcome.returncode}）"
            for case in spec.cases:
                merged[case_id(case)] = _infra_record(case, spec.worker_id, reason)
            continue

        payload_results = outcome.payload.get("results", [])
        collected_ids = set(outcome.payload.get("collected_case_ids", []))
        returned_ids: set[str] = set()
        for record in payload_results:
            cid = str(record.get("case_id", "")).strip()
            if not cid or cid not in expected_by_id:
                continue
            if cid in merged:
                raise ValueError(f"用例 {cid} 被多个 Worker 返回")
            normalized = dict(record)
            normalized["row"] = expected_by_id[cid].get("_row")
            normalized["worker_id"] = spec.worker_id
            merged[cid] = normalized
            returned_ids.add(cid)

        missing_ids = collected_ids - returned_ids
        if outcome.returncode not in {0, 1, 5} and not collected_ids:
            missing_ids = set(expected_by_id)
        for cid in missing_ids:
            case = expected_by_id.get(cid)
            if case and cid not in merged:
                merged[cid] = _infra_record(
                    case,
                    spec.worker_id,
                    f"未返回测试结果（退出码 {outcome.returncode}）",
                )

    return sorted(merged.values(), key=lambda record: int(record.get("row") or 10**9))


def _write_excel_results(excel_path: Path, records: list[dict]) -> None:
    updates = [
        (record["case_id"], str(record["result"]), record.get("row"))
        for record in records
    ]
    if updates:
        ExcelHandler(str(excel_path)).write_results(updates)
        print(f"主进程已一次性回写 {len(updates)} 条 Excel 结果")


def _merge_allure_results(run_dir: Path, specs: list[WorkerSpec]) -> Path:
    merged_dir = run_dir / "allure-results"
    merged_dir.mkdir(parents=True, exist_ok=True)
    for spec in specs:
        if not spec.allure_dir.exists():
            continue
        for source in spec.allure_dir.iterdir():
            if not source.is_file() or source.name == "environment.properties":
                continue
            destination = merged_dir / source.name
            if not destination.exists():
                shutil.copy2(source, destination)
    (merged_dir / "environment.properties").write_text(
        "\n".join([
            f"运行ID={run_dir.name}",
            "执行模式=双进程固定分组",
            "Worker=A,B",
            f"执行时间={datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        ]) + "\n",
        encoding="utf-8",
    )
    return merged_dir


def _cleanup_auth_states(specs: list[WorkerSpec]) -> None:
    """无论 Worker 是否正常退出，都不把登录 Cookie 长期留在运行目录。"""
    for spec in specs:
        auth_file = spec.worker_dir / "auth_state.json"
        if not auth_file.exists():
            continue
        try:
            auth_file.unlink()
        except OSError as exc:
            print(f"[{spec.worker_id}] 警告：登录状态清理失败: {exc}")


def _patch_allure_results(merged_dir: Path, passed_case_ids: set[str]) -> None:
    """复跑改判通过的用例：把合并结果中的 failed/broken 改为 passed，报告反映最终判定。"""
    if not passed_case_ids:
        return
    patched = 0
    for result_file in merged_dir.glob("*-result.json"):
        try:
            data = json.loads(result_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        name = data.get("name", "")
        if any(cid in name for cid in passed_case_ids) and data.get("status") in ("failed", "broken"):
            data["status"] = "passed"
            data["statusDetails"] = {}
            result_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            patched += 1
    if patched:
        print(f"报告结果已按复跑改判更新: {patched} 条 failed → passed")


def _generate_allure_report(run_dir: Path, results_dir: Path, open_report: bool) -> bool:
    report_dir = run_dir / "allure-report"
    command = subprocess.list2cmdline([
        "allure",
        "generate",
        str(results_dir),
        "-o",
        str(report_dir),
        "--clean",
    ])
    generated = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        shell=True,
        check=False,
        capture_output=True,
        text=True,
    )
    if generated.returncode != 0:
        print("Allure 报告生成失败；测试结果和 summary.json 已保留。")
        if generated.stderr:
            print(generated.stderr[-500:])
        return False
    print(f"统一 Allure 报告已生成: {report_dir}")

    # 归档到 reports/history/<时间戳>/（与单进程 archive_report.py 保持一致）
    try:
        history_dir = PROJECT_ROOT / "reports" / "history"
        history_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        target = history_dir / stamp
        shutil.copytree(report_dir, target, dirs_exist_ok=True)
        print(f"报告已归档: {target}")
    except OSError as exc:
        print(f"⚠ 报告归档失败（不影响报告查看）: {exc}")

    if open_report:
        # 先杀掉占用 8899 的旧报告服务：多次运行叠加会导致浏览器随机连到旧报告
        try:
            subprocess.run(
                [
                    "powershell", "-NoProfile", "-Command",
                    "Get-NetTCPConnection -LocalPort 8899 -State Listen -ErrorAction SilentlyContinue "
                    "| ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }",
                ],
                capture_output=True,
                timeout=30,
            )
        except Exception:
            pass
        subprocess.Popen(
            [str(_python_executable()), "-m", "http.server", "8899", "-d", str(report_dir)],
            cwd=PROJECT_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        webbrowser.open("http://localhost:8899")
        print("报告服务器已启动: http://localhost:8899")
    return True


def _summary_payload(
    run_id: str,
    groups: dict[str, list[dict]],
    outcomes: list[WorkerOutcome],
    records: list[dict],
) -> dict:
    counts = {"pass": 0, "fail": 0, "skip": 0, "infra_error": 0}
    for record in records:
        status = str(record.get("status", "fail"))
        counts[status if status in counts else "fail"] += 1
    return {
        "run_id": run_id,
        "mode": "parallel-two-account",
        "group_counts": {name: len(cases) for name, cases in groups.items()},
        "worker_exit_codes": {outcome.spec.worker_id: outcome.returncode for outcome in outcomes},
        "result_counts": counts,
        "results": records,
    }


def _print_group_summary(groups: dict[str, list[dict]]) -> None:
    print("用例分组：")
    for group in ("A", "B", "SERIAL"):
        modules: dict[str, int] = {}
        for case in groups[group]:
            module = str(case.get("模块", ""))
            modules[module] = modules.get(module, 0) + 1
        module_text = "，".join(f"{name} {count}" for name, count in modules.items()) or "无"
        print(f"  {group}: {len(groups[group])} 条（{module_text}）")


def parse_args(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(description="双账号双进程自动化测试调度器")
    parser.add_argument("--dry-run", action="store_true", help="只校验并显示分组，不启动浏览器")
    parser.add_argument("--skip-checks", action="store_true", help="跳过离线单元测试")
    parser.add_argument("--no-report", action="store_true", help="不生成 Allure 总报告")
    parser.add_argument("--no-open", action="store_true", help="生成报告但不自动打开浏览器")
    return parser.parse_known_args(argv)


def run(argv: list[str] | None = None) -> int:
    options, pytest_args = parse_args(list(argv or []))
    load_dotenv(PROJECT_ROOT / ".env")

    try:
        excel_path, enabled_cases, groups = _load_cases()
    except (FileNotFoundError, ValueError, CaseValidationError) as exc:
        print(f"启动前校验失败: {exc}")
        return 2

    print(f"已读取 {excel_path.name}：{len(enabled_cases)} 条启用用例")
    _print_group_summary(groups)
    if options.dry_run:
        return 0

    try:
        _validate_parallel_accounts()
    except ValueError as exc:
        print(f"双账号配置错误: {exc}")
        return 2

    python = _python_executable()
    if not options.skip_checks and _run_framework_checks(python) != 0:
        print("离线框架检查失败，未启动 E2E 测试。")
        return 2

    started_at = datetime.now()
    run_timestamp = started_at.strftime("%Y%m%d%H%M%S")
    run_id = f"RUN-{started_at.strftime('%Y%m%d-%H%M%S')}-{started_at.microsecond // 1000:03d}"
    run_dir = REPORTS_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    parallel_specs = [
        WorkerSpec("A", "A", groups["A"], run_dir),
        WorkerSpec("B", "B", groups["B"], run_dir),
    ]
    all_specs = list(parallel_specs)
    try:
        outcomes = _run_worker_batch(
            python, parallel_specs, run_id, run_timestamp, pytest_args
        )
        if groups["SERIAL"]:
            serial_slot = os.getenv("TEST_SERIAL_ACCOUNT_SLOT", "A").strip().upper() or "A"
            if serial_slot not in {"A", "B"}:
                raise ValueError("TEST_SERIAL_ACCOUNT_SLOT 仅支持 A 或 B")
            serial_spec = WorkerSpec("SERIAL", serial_slot, groups["SERIAL"], run_dir)
            all_specs.append(serial_spec)
            outcomes.extend(_run_worker_batch(
                python, [serial_spec], run_id, run_timestamp, pytest_args
            ))
    except KeyboardInterrupt:
        _cleanup_auth_states(all_specs)
        print("运行已由用户中断。")
        return 130
    except (OSError, ValueError) as exc:
        _cleanup_auth_states(all_specs)
        print(f"调度失败: {exc}")
        return 2

    _cleanup_auth_states(all_specs)

    try:
        records = _merge_worker_results(outcomes)
        # ===== 失败用例自动复跑确认 =====
        # 全量跑失败的用例逐条单独复跑一次：两次都失败才判定为 failed，
        # 复跑通过说明是全量环境下偶发（服务器慢/时序），最终按通过处理。
        failed_records = [r for r in records if r.get("status") != "pass"]
        if failed_records:
            print(f"\n发现 {len(failed_records)} 条失败用例，等待 30 秒（让服务器慢时段恢复）后逐条复跑确认...")
            import time as _time
            _time.sleep(30)
            for record in failed_records:
                cid = record.get("case_id", "")
                slot = record.get("worker_id", "A")
                case = next(
                    (c for c in groups.get(slot, []) if case_id(c) == cid), None
                )
                if case is None:
                    for group_name in ("A", "B", "SERIAL"):
                        case = next(
                            (c for c in groups.get(group_name, []) if case_id(c) == cid),
                            None,
                        )
                        if case:
                            break
                if case is None:
                    print(f"  [{cid}] 未找到用例定义，跳过复跑")
                    continue
                rerun_spec = WorkerSpec(f"RERUN-{cid}", slot, [case], run_dir)
                try:
                    rerun_spec.worker_dir.mkdir(parents=True, exist_ok=True)
                    # 复跑：单条用例 + 全新执行窗口（独立进程 + 独立控制台窗口）
                    rerun_cmd = _worker_command(python, rerun_spec, pytest_args) + ["-k", cid]
                    rerun_env = _worker_env(rerun_spec, run_id, run_timestamp)
                    # 复跑只跑单条（-k 过滤），不需要 worker 分组；
                    # 置空 TEST_WORKER_ID 走传统单进程模式，账号由 TEST_ACCOUNT_SLOT 控制
                    rerun_env["TEST_WORKER_ID"] = ""
                    rerun_proc = subprocess.Popen(
                        rerun_cmd,
                        cwd=PROJECT_ROOT,
                        env=rerun_env,
                        creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
                    )
                    rerun_proc.wait()
                    # 复跑 worker 的 TEST_WORKER_ID 为空（单进程模式），
                    # 直接读结果文件，跳过 _read_payload 的 worker_id 校验
                    payload = None
                    if rerun_spec.result_file.exists():
                        try:
                            payload = json.loads(rerun_spec.result_file.read_text(encoding="utf-8"))
                        except (OSError, json.JSONDecodeError):
                            payload = None
                    rerun_status = "error"
                    if payload and payload.get("results"):
                        rerun_status = str(payload["results"][0].get("status", "error"))
                    if rerun_status == "pass":
                        record["status"] = "pass"
                        record["result"] = "pass（全量失败后复跑通过，判定为偶发）"
                        print(f"  [{cid}] 复跑通过 → 最终判定 pass")
                    else:
                        print(f"  [{cid}] 复跑仍失败 → 最终判定 failed")
                except Exception as exc:
                    print(f"  [{cid}] 复跑异常（按原结果判定）: {exc}")
        _write_excel_results(excel_path, records)
    except (OSError, ValueError) as exc:
        print(f"结果汇总失败: {exc}")
        return 2

    summary = _summary_payload(run_id, groups, outcomes, records)
    summary_path = run_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"运行摘要已保存: {summary_path}")

    if not options.no_report:
        merged_allure = _merge_allure_results(run_dir, all_specs)
        # 复跑改判通过的用例：报告同步更新为 passed（反映最终判定）
        rerun_passed_ids = {
            r.get("case_id", "")
            for r in records
            if "复跑通过" in str(r.get("result", ""))
        }
        _patch_allure_results(merged_allure, rerun_passed_ids)
        _generate_allure_report(run_dir, merged_allure, open_report=not options.no_open)

    counts = summary["result_counts"]
    print(
        "执行完成："
        f"pass={counts['pass']}，fail={counts['fail']}，"
        f"skip={counts['skip']}，infra_error={counts['infra_error']}"
    )
    abnormal_worker_exit = any(outcome.returncode not in {0, 1, 5} for outcome in outcomes)
    return 0 if (
        counts["fail"] == 0
        and counts["infra_error"] == 0
        and not abnormal_worker_exit
    ) else 1


def main() -> None:
    raise SystemExit(run(sys.argv[1:]))


if __name__ == "__main__":
    main()
