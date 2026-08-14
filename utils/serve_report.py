"""启动简易 HTTP 服务器查看 Allure 报告"""
import json, http.server, socketserver, webbrowser, sys, os
from pathlib import Path

# 中文 Windows 控制台为 GBK 编码，emoji 输出到管道时会 UnicodeEncodeError
sys.stdout.reconfigure(errors="replace")
sys.stderr.reconfigure(errors="replace")

PORT = 8899
REPORT_DIR = Path(__file__).resolve().parent.parent / "reports" / "allure-report"
RESULTS_DIR = Path(__file__).resolve().parent.parent / "reports" / "allure-results"

def build_simple_report():
    """从 allure-results JSON 生成简易 HTML 报告"""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    test_cases = list(RESULTS_DIR.glob("*-result.json"))
    passed = sum(1 for f in test_cases if json.loads(f.read_text("utf-8")).get("status") == "passed")
    failed = len(test_cases) - passed

    rows = ""
    for f in sorted(test_cases, key=lambda p: p.name):
        data = json.loads(f.read_text("utf-8"))
        name = data.get("name", "Unknown")
        status = data.get("status", "unknown")
        story = ""
        for label in data.get("labels", []):
            if label.get("name") == "story":
                story = f" - {label['value']}"
        color = "green" if status == "passed" else "red"
        rows += f'<tr><td>{name}{story}</td><td style="color:{color};font-weight:bold">{status}</td></tr>\n'

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>颜佳AI 测试报告</title>
<style>
body {{ font-family: -apple-system, sans-serif; max-width: 960px; margin: 0 auto; padding: 24px; background: #f5f5f5; }}
.summary {{ display: flex; gap: 16px; margin: 20px 0; }}
.card {{ flex: 1; padding: 20px; border-radius: 10px; text-align: center; font-size: 26px; font-weight: bold; }}
.card span {{ display: block; font-size: 14px; font-weight: normal; margin-bottom: 4px; }}
.pass {{ background: #d3f0df; color: #1a7f37; }}
.fail {{ background: #ffe0e0; color: #b60205; }}
.total {{ background: #e0e0e0; color: #333; }}
table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; }}
th, td {{ padding: 10px 14px; text-align: left; border-bottom: 1px solid #eee; }}
th {{ background: #f0f2f5; }}
tr:hover td {{ background: #fafafa; }}
</style></head>
<body>
<h1>📊 颜佳AI 测试报告</h1>
<div class="summary">
<div class="card total"><span>总用例</span>{len(test_cases)}</div>
<div class="card pass"><span>通过</span>{passed}</div>
<div class="card fail"><span>失败</span>{failed}</div>
</div>
<table><tr><th>用例</th><th>结果</th></tr>{rows}</table>
<div class="footer">数据来源: reports/allure-results</div>
</body></html>"""
    (REPORT_DIR / "index.html").write_text(html, "utf-8")
    return len(test_cases), passed, failed


def main():
    # 标准 Allure 报告存在时（allure generate 生成，含 widgets/ 结构）直接展示，
    # 不做任何覆盖；只有没有标准报告时才生成简易版，避免把标准报告换成简单表格。
    rich_marker = REPORT_DIR / "widgets"
    if rich_marker.exists():
        print("✅ 找到 Allure 标准报告，直接展示")
    else:
        if not RESULTS_DIR.exists():
            print("❌ 找不到测试结果 (reports/allure-results)")
            print("   请先运行 run_tests.bat 执行测试")
            sys.exit(1)
        total, passed, failed = build_simple_report()
        print(f"✅ 已从当前 {total} 条测试数据生成简易报告 (通过 {passed}, 失败 {failed})")

    # 3. 启动 HTTP 服务器
    os.chdir(str(REPORT_DIR))
    webbrowser.open(f"http://localhost:{PORT}")
    print(f"\n🌐 报告地址: http://localhost:{PORT}")
    print("   关闭此窗口即可停止服务器\n")

    handler = http.server.SimpleHTTPRequestHandler

    # 禁止日志输出（保持终端干净）
    class QuietHandler(handler):
        def log_message(self, format, *args):
            pass

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), QuietHandler) as httpd:
        httpd.serve_forever()


if __name__ == "__main__":
    main()
