"""归档当前 Allure 报告到 reports/history/<时间戳>/，保留历史报告不被覆盖

用法（通常由 generate_allure_report.bat 在报告生成后自动调用）：
    python utils/archive_report.py
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

# 中文 Windows 控制台为 GBK 编码，emoji 输出到管道时会 UnicodeEncodeError
sys.stdout.reconfigure(errors="replace")
sys.stderr.reconfigure(errors="replace")

REPORT_DIR = Path(__file__).resolve().parent.parent / "reports" / "allure-report"
HISTORY_DIR = Path(__file__).resolve().parent.parent / "reports" / "history"


def main() -> int:
    if not REPORT_DIR.exists() or not (REPORT_DIR / "index.html").exists():
        print("❌ 未找到 reports/allure-report 报告，请先生成报告")
        return 1
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = HISTORY_DIR / stamp
    shutil.copytree(REPORT_DIR, target, dirs_exist_ok=True)
    print(f"✅ 报告已归档: {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
