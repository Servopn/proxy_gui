#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
应用入口：解析参数、初始化日志、启动代理线程、构建主窗口与系统托盘，
并在退出时优雅关闭所有资源。
"""

import argparse
import base64
import datetime
import io
import os
import threading
import time
from pathlib import Path

import tkinter as tk
from tkinter import messagebox
from PIL import Image
import pystray

from claude_proxy import tray
from claude_proxy import config
from claude_proxy.config import get_app_dir
# 强制 import 所有子模块，确保 PyInstaller 打包时不会遗漏
import claude_proxy.gui.main_window  # noqa: F401
import claude_proxy.gui.channel_status  # noqa: F401
import claude_proxy.gui.proxy_auto  # noqa: F401
import claude_proxy.gui.config_window  # noqa: F401
import claude_proxy.gui.key_manager  # noqa: F401
import claude_proxy.gui.model_pool  # noqa: F401
import claude_proxy.gui.utils  # noqa: F401
from claude_proxy.gui.main_window import LogWindow
from claude_proxy.logger import log, set_log_file
from claude_proxy.proxy import create_proxy_server, run_proxy, stop_proxy
from claude_proxy.startup import (
    _acquire_startup_lock,
    _release_startup_lock,
    check_port_and_handle,
    disable_startup,
    enable_startup,
    find_existing_window,
    is_startup_enabled,
)


# 全局变量
log_window = None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18081)
    args = parser.parse_args()

    # 先检查是否有其他实例在运行
    if not _acquire_startup_lock():
        # 已有实例在运行，尝试激活已有窗口，静默退出
        time.sleep(0.3)
        find_existing_window()
        return

    port_check = check_port_and_handle(args.port)
    if port_check == "duplicate":
        _release_startup_lock()
        return
    if port_check == "exit":
        _release_startup_lock()
        return

    try:
        server = create_proxy_server(args.port)
    except OSError as exc:
        dialog_root = tk.Tk()
        dialog_root.withdraw()
        messagebox.showerror("启动失败", f"无法监听 127.0.0.1:{args.port}：{exc}")
        dialog_root.destroy()
        return

    # 日志写到 EXE/脚本运行目录下的 logs/ 子目录
    log_root = get_app_dir() / "logs"
    try:
        log_root.mkdir(parents=True, exist_ok=True)
    except OSError:
        log_root = get_app_dir()
    log_filename = datetime.datetime.now().strftime("claude_proxy_%Y%m%d_%H%M%S.log")
    set_log_file(str(log_root / log_filename))
    log(f"日志文件: {log_root / log_filename}")

    proxy_thread = threading.Thread(target=run_proxy, args=(server,), daemon=True)
    proxy_thread.start()

    try:
        from ttkthemes import ThemedTk
        root = ThemedTk(theme="arc")
    except (ImportError, tk.TclError):
        root = tk.Tk()

    try:
        import tempfile
        ico_data = base64.b64decode(tray.get_ico_base64())
        ico_img = Image.open(io.BytesIO(ico_data))
        temp_ico = os.path.join(tempfile.gettempdir(), "claude_proxy_icon.ico")
        ico_img.save(temp_ico, format="ICO", sizes=[
            (16, 16), (24, 24), (32, 32), (48, 48),
            (64, 64), (128, 128), (256, 256),
        ])
        root.iconbitmap(temp_ico)
        root.iconbitmap(default=temp_ico)
    except (OSError, ValueError, tk.TclError):
        pass

    root.withdraw()
    global log_window
    log_window = LogWindow(root, args.port)

    def on_show(icon, item):
        root.after(0, log_window.show)

    def on_hide(icon, item):
        root.after(0, log_window.hide)

    def on_quit(icon, item):
        root.after(0, log_window.quit_app)

    def on_toggle_startup(icon, item):
        if is_startup_enabled():
            disable_startup()
        else:
            enable_startup()
        icon.menu = build_menu()
        icon.update_menu()

    def build_menu():
        return tray.build_menu(
            args.port, on_show, on_hide, on_quit, on_toggle_startup
        )

    tray.tray_icon = pystray.Icon(
        "claude-proxy", tray.create_icon_image(), f"Claude Proxy ({args.port})", build_menu()
    )
    tray_thread = threading.Thread(target=tray.tray_icon.run, daemon=True)
    tray_thread.start()

    try:
        root.mainloop()
    finally:
        if tray.tray_icon is not None:
            try:
                tray.tray_icon.stop()
            except Exception:
                pass
            tray.tray_icon = None
        stop_proxy()


if __name__ == "__main__":
    main()
