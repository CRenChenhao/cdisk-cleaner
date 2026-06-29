#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
C 盘清理工具 v2.0 - 桌面版（嵌入式浏览器 GUI）
使用 pywebview 在桌面窗口中渲染 Web 版 UI
"""

import os
import sys
import threading
import time
import socket
import subprocess
import webview

# 禁止控制台窗口弹出
NO_WINDOW = subprocess.CREATE_NO_WINDOW

# 把 app.py 当作模块加载，复用后端逻辑
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app import app
app.config['APP_VERSION'] = "v2.0"  # 覆盖版本标识（通过 Flask config，PyInstaller 打包后也可靠）

PORT = 18080

def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0

def kill_port_process(port):
    """杀掉占用指定端口的进程"""
    try:
        subprocess.run(
            ["powershell", "-Command",
             f"Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue | "
             "ForEach-Object {{ Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }}"],
            capture_output=True, timeout=10, creationflags=NO_WINDOW
        )
        time.sleep(1.5)
    except:
        pass

def start_flask():
    app.run(host="127.0.0.1", port=PORT, debug=False, use_reloader=False)

def main():
    # 如果上次退出不干净，端口可能还被占用
    if is_port_in_use(PORT):
        kill_port_process(PORT)

    # 启动 Flask 后台服务
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()
    time.sleep(1.5)

    # 创建桌面窗口，嵌入 1.0 版精美 Web UI
    window = webview.create_window(
        title="C 盘清理工具 v2.0",
        url=f"http://127.0.0.1:{PORT}",
        width=960,
        height=720,
        min_size=(780, 560),
        resizable=True,
    )
    webview.start(gui='edgechromium')

    # 窗口关闭后，强制退出所有线程，确保端口释放
    os._exit(0)

if __name__ == "__main__":
    main()
