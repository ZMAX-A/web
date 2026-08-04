"""
先运行离线框架检查，再执行 Web 自动化测试

使用方法：
    python run_tests.py [可选的 pytest 参数]

示例：
    python run_tests.py                    # 运行所有测试
    python run_tests.py -k "login"         # 运行包含 "login" 的测试
    python run_tests.py --maxfail=5        # 最多允许5个失败
"""
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

    return result.returncode


def main():
    """主函数"""
    # 获取命令行参数
    args = sys.argv[1:]

    # 运行测试
    exit_code = run_tests(args)

    # 返回退出码
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
