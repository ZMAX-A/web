"""
列出 test_case.xlsx 中所有可用的用例ID（供 run_one_case.bat 调用）
"""
import sys
from pathlib import Path

# 项目根目录
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))

from utils.excel_handler import ExcelHandler

xlsx = root / "test_cases" / "test_case.xlsx"
if not xlsx.exists():
    print("❌ 找不到 test_cases/test_case.xlsx")
    sys.exit(1)

handler = ExcelHandler(str(xlsx))
fmt = handler.detect_format()
all_cases = handler.read_test_cases()

print(f"\n可用用例列表 (共 {len(all_cases)} 条, 格式: {fmt})\n")

if fmt == "new" or "用例ID" in (all_cases[0] if all_cases else {}):
    key = "用例ID"
    scene_key = "测试场景"
else:
    key = "编号"
    scene_key = "功能点"

for c in all_cases:
    cid = c.get(key, "?")
    scene = c.get(scene_key, "")
    print(f"  {cid:20s}  {scene}")

print()
