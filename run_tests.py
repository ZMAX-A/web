"""
先运行离线框架检查，再执行 Web 自动化测试

使用方法：
    python run_tests.py [可选的 pytest 参数]

示例：
    python run_tests.py                    # 运行所有测试
    python run_tests.py -k "login"         # 运行包含 "login" 的测试
    python run_tests.py --maxfail=5        # 最多允许5个失败
"""
import os
import subprocess
import sys
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent

def run_tests(args=None):
    """运行离线检查和 pytest E2E 测试。"""
    if args is None:
        args = []

    # E2E 前先验证框架解析、严格失败和 Excel 批量回写逻辑。
    check_cmd = [
        str(PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"),
        "-m", "pytest", "unit_tests", "-q", "-o", "addopts=",
    ]
    check_result = subprocess.run(check_cmd, cwd=PROJECT_ROOT)
    if check_result.returncode != 0:
        print("离线框架检查失败，未启动 E2E 测试。")
        return check_result.returncode

    # 构建 pytest 命令
    pytest_cmd = [
        str(PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"),
        "-m", "pytest",
        "tests/",
        "-v",
        "--tb=short",
    ] + args

    print("=" * 60)
    print("运行测试...")
    print("=" * 60)

    # 运行测试
    result = subprocess.run(pytest_cmd, cwd=PROJECT_ROOT)

    print()
    print("=" * 60)

    if result.returncode == 0:
        print("测试完成 - 全部通过!")
    else:
        print(f"测试完成 - 退出码: {result.returncode}")

    print("=" * 60)

    # 失败用例自动复跑确认：复跑通过则判定为偶发（全量环境下服务器慢/时序导致）
    _rerun_failed_cases()

    # 生成 Allure 报告 + 归档 + 启动报告服务器（与 run_tests.bat 行为一致）
    _generate_report_and_serve()

    return result.returncode


def _rerun_failed_cases() -> None:
    """全量跑完后，逐条复跑失败的用例；复跑结果由 conftest 自动回写 Excel。"""
    cases_dir = PROJECT_ROOT / "test_cases"
    excel_path = next(
        (cases_dir / name for name in
         ("test_case.xlsx", "yanjia_ai_overseas_test_cases.xlsx", "core_test_cases.xlsx")
         if (cases_dir / name).exists()),
        cases_dir / "test_case.xlsx",
    )
    try:
        from utils.excel_handler import ExcelHandler
        cases = ExcelHandler(str(excel_path)).read_test_cases()
    except Exception as exc:
        print(f"读取 Excel 失败，跳过失败用例复跑: {exc}")
        return
    failed_ids = [
        str(c.get("用例ID", "") or c.get("编号", "")).strip()
        for c in cases
        if str(c.get("实际结果", "")).startswith("fail")
        # 只复跑启用的用例；「是否执行=否」的用例不参与运行，历史 fail 结果忽略
        and str(c.get("是否执行", "是")).strip() not in ("否", "N", "n")
    ]
    failed_ids = [cid for cid in failed_ids if cid]
    if not failed_ids:
        return
    print(f"\n发现 {len(failed_ids)} 条失败用例，等待 30 秒（让服务器慢时段恢复）后逐条复跑确认...")
    import time as _time
    _time.sleep(30)
    python = str(PROJECT_ROOT / ".venv" / "Scripts" / "python.exe")
    for cid in failed_ids:
        print(f"  复跑 [{cid}] ...")
        # 复跑：每条用例打开全新的执行窗口（独立进程 + 独立控制台窗口）
        subprocess.run(
            [
                python, "-m", "pytest", "tests/test_core_cases.py",
                "-k", cid, "-q", "-o", "addopts=",
            ],
            cwd=PROJECT_ROOT,
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
        )


def _find_java_home() -> str | None:
    """环境变量缺失时自动探测 JDK 常见安装路径。"""
    current = os.getenv("JAVA_HOME", "").strip()
    if current and Path(current).joinpath("bin", "java.exe").exists():
        return current
    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "Eclipse Adoptium",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "Java",
    ]
    for base in candidates:
        if not base.exists():
            continue
        for jdk in sorted(base.iterdir(), reverse=True):
            if jdk.joinpath("bin", "java.exe").exists():
                return str(jdk)
    return None


def _generate_report_and_serve() -> None:
    """生成 Allure 报告、归档到 history/，并启动 8899 报告服务器。"""
    # JAVA_HOME 缺失时自动探测，避免在旧终端（无环境变量）里静默失败
    java_home = _find_java_home()
    env = os.environ.copy()
    if java_home:
        env["JAVA_HOME"] = java_home
        env["PATH"] = str(Path(java_home) / "bin") + os.pathsep + env.get("PATH", "")

    print("生成 Allure 报告...")
    gen = subprocess.run(
        # shell=True：Windows 下 allure 是 .cmd 命令，需经 shell 解析
        "allure generate reports/allure-results -o reports/allure-report --clean",
        cwd=PROJECT_ROOT,
        shell=True,
        capture_output=True,
        text=True,
        env=env,
    )
    if gen.returncode != 0:
        print("⚠ 报告生成失败：")
        if not java_home:
            print("  未找到 Java（JAVA_HOME 未设置且未探测到 JDK），请安装 JDK 17")
        print("  请安装 Allure CLI: npm install -g allure-commandline")
        print((gen.stderr or gen.stdout or "")[-500:])
        return
    print("报告已生成: reports/allure-report")

    print("归档本次报告...")
    subprocess.run(
        [str(PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"), "utils/archive_report.py"],
        cwd=PROJECT_ROOT,
    )

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

    # 启动报告服务器（8899）
    subprocess.Popen(
        [str(PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"), "-m", "http.server", "8899", "-d", "reports/allure-report"],
        cwd=PROJECT_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    import time
    import webbrowser
    # 等服务真正就绪再打开浏览器，避免打开空白页
    for _ in range(20):
        time.sleep(0.5)
        try:
            if __import__("urllib.request").request.urlopen(
                "http://localhost:8899/index.html", timeout=1
            ).status == 200:
                break
        except Exception:
            continue
    webbrowser.open("http://localhost:8899")
    print("报告服务器已启动: http://localhost:8899")


def main():
    """主函数"""
    # 获取命令行参数
    args = sys.argv[1:]

    # 运行测试
    exit_code = run_tests(args)

    # 双击运行时防止窗口瞬间关闭（脚本/管道调用时自动跳过）
    if sys.stdin is not None and sys.stdin.isatty():
        try:
            input("\n运行结束，按回车键退出...")
        except EOFError:
            pass

    # 返回退出码
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
