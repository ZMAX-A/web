"""查看历史归档报告：选择时间戳后用 HTTP 服务器打开（file:// 直接打开会因浏览器限制报错）

用法：
    python utils/serve_archive.py            # 交互式选择归档
    python utils/serve_archive.py 20260810   # 直接指定归档名（前缀匹配）
"""
import http.server
import os
import socketserver
import sys
import webbrowser
from pathlib import Path

# 中文 Windows 控制台为 GBK 编码，emoji 输出到管道时会 UnicodeEncodeError
sys.stdout.reconfigure(errors="replace")
sys.stderr.reconfigure(errors="replace")

PORT = 8891
HISTORY_DIR = Path(__file__).resolve().parent.parent / "reports" / "history"


def main() -> int:
    archives = sorted([d for d in HISTORY_DIR.iterdir() if d.is_dir()])
    if not archives:
        print("❌ reports/history 下没有归档报告")
        return 1

    # 命令行参数直接指定
    if len(sys.argv) > 1:
        key = sys.argv[1]
        matches = [d for d in archives if d.name.startswith(key)]
        if not matches:
            print(f"❌ 未找到以 {key} 开头的归档")
            return 1
        target = matches[0]
    else:
        print("可用的归档报告：")
        for i, d in enumerate(archives):
            print(f"  [{i}] {d.name}")
        choice = input("输入序号查看: ").strip()
        if not choice.isdigit() or int(choice) >= len(archives):
            print("❌ 无效序号")
            return 1
        target = archives[int(choice)]

    os.chdir(str(target))
    socketserver.TCPServer.allow_reuse_address = True

    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

    with socketserver.TCPServer(("", PORT), QuietHandler) as httpd:
        print(f"🌐 正在查看归档: {target.name}")
        print(f"   报告地址: http://localhost:{PORT}")
        webbrowser.open(f"http://localhost:{PORT}")
        print("   关闭此窗口即可停止服务器")
        httpd.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
