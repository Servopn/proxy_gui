#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主日志窗口：统计卡片、实时日志、控制开关与各子窗口入口。
"""

import queue
import tkinter as tk
from tkinter import ttk, scrolledtext

from claude_proxy import config
from claude_proxy.config import (
    FORCE_PROXY_AUTO,
    set_force_proxy_auto,
)
from claude_proxy.logger import log_queue
from claude_proxy.proxy import stop_proxy
from claude_proxy.startup import _release_startup_lock
from claude_proxy.stats import pool


class LogWindow:
    def __init__(self, root, port):
        self.root = root
        self.root.title("Claude Proxy")
        self.root.geometry("1050x700")
        self.root.minsize(800, 500)
        self.root.protocol("WM_DELETE_WINDOW", self.hide)

        # 全局样式
        style = ttk.Style()
        style.configure(".", font=("Microsoft YaHei UI", 9))
        style.configure("Header.TLabel", font=("Microsoft YaHei UI", 16, "bold"))
        style.configure("Stats.TLabel", font=("Microsoft YaHei UI", 10))
        style.configure("Card.TFrame", relief="flat", borderwidth=0)
        style.configure("Btn.TButton", font=("Microsoft YaHei UI", 9), padding=6)

        # 顶部标题栏
        header = ttk.Frame(root)
        header.pack(fill=tk.X, padx=12, pady=(10, 0))
        ttk.Label(header, text="Claude Proxy", style="Header.TLabel").pack(side=tk.LEFT)
        ttk.Label(header, text=f"Port {port}", style="Stats.TLabel").pack(side=tk.LEFT, padx=10)

        # 统计卡片行
        stats_card = ttk.Frame(root, relief="groove", borderwidth=1)
        stats_card.pack(fill=tk.X, padx=12, pady=8)

        card_inner = ttk.Frame(stats_card)
        card_inner.pack(fill=tk.X, padx=10, pady=10)

        self.lbl_requests = ttk.Label(card_inner, text="0", font=("Microsoft YaHei UI", 18, "bold"))
        self.lbl_requests.pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(card_inner, text="请求  ", font=("Microsoft YaHei UI", 8)).pack(side=tk.LEFT, padx=(0, 16))

        self.lbl_errors = ttk.Label(card_inner, text="0", font=("Microsoft YaHei UI", 18, "bold"), foreground="#e74c3c")
        self.lbl_errors.pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(card_inner, text="错误  ", font=("Microsoft YaHei UI", 8)).pack(side=tk.LEFT, padx=(0, 16))

        self.lbl_input = ttk.Label(card_inner, text="0", font=("Microsoft YaHei UI", 18, "bold"))
        self.lbl_input.pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(card_inner, text="Input Token  ", font=("Microsoft YaHei UI", 8)).pack(side=tk.LEFT, padx=(0, 16))

        self.lbl_output = ttk.Label(card_inner, text="0", font=("Microsoft YaHei UI", 18, "bold"))
        self.lbl_output.pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(card_inner, text="Output Token  ", font=("Microsoft YaHei UI", 8)).pack(side=tk.LEFT, padx=(0, 16))

        self.lbl_channels = ttk.Label(card_inner, text=str(len(config.CHANNELS)), font=("Microsoft YaHei UI", 18, "bold"))
        self.lbl_channels.pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(card_inner, text="渠道  ", font=("Microsoft YaHei UI", 8)).pack(side=tk.LEFT, padx=(0, 16))

        self.lbl_mode = ttk.Label(card_inner, text="-", font=("Microsoft YaHei UI", 18, "bold"))
        self.lbl_mode.pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(card_inner, text="模式", font=("Microsoft YaHei UI", 8)).pack(side=tk.LEFT)

        # 控制栏
        ctrl_bar = ttk.Frame(root)
        ctrl_bar.pack(fill=tk.X, padx=12, pady=4)

        self.log_title = ttk.Label(ctrl_bar, text="实时日志", font=("Microsoft YaHei UI", 11, "bold"))
        self.log_title.pack(side=tk.LEFT)

        # 强制 ProxyAuto 开关
        auto_frame = ttk.Frame(ctrl_bar)
        auto_frame.pack(side=tk.RIGHT, padx=10)
        self.force_auto_var = tk.BooleanVar(value=FORCE_PROXY_AUTO)
        self.force_auto_check = ttk.Checkbutton(
            auto_frame, text="强制ProxyAuto", variable=self.force_auto_var,
            command=self._on_force_auto_change
        )
        self.force_auto_check.pack(side=tk.LEFT)

        # 日志区域
        log_frame = ttk.Frame(root, relief="sunken", borderwidth=1)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=4)
        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD,
                                                   font=('Cascadia Code', 9),
                                                   bg="#1e1e1e", fg="#d4d4d4",
                                                   insertbackground="white",
                                                   selectbackground="#264f78")
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        self.log_text.tag_config("error", foreground="#f44747")
        self.log_text.tag_config("success", foreground="#4ec9b0")
        self.log_text.tag_config("retry", foreground="#ce9178")
        self.log_text.tag_config("info", foreground="#569cd6")
        self.log_text.tag_config("model_name", foreground="#c586c0")

        # 底部按钮
        self.btn_frame = ttk.Frame(root)
        self.btn_frame.pack(fill=tk.X, padx=12, pady=6)

        ttk.Button(self.btn_frame, text="清空日志", command=self.clear_log, style="Btn.TButton").pack(side=tk.LEFT, padx=3)
        ttk.Button(self.btn_frame, text="隐藏到托盘", command=self.hide, style="Btn.TButton").pack(side=tk.LEFT, padx=3)
        ttk.Button(self.btn_frame, text="密钥管理", command=self.open_key_manager, style="Btn.TButton").pack(side=tk.LEFT, padx=3)
        ttk.Button(self.btn_frame, text="渠道状态", command=self.open_channel_status, style="Btn.TButton").pack(side=tk.LEFT, padx=3)
        ttk.Button(self.btn_frame, text="ProxyAuto", command=self.open_proxy_auto, style="Btn.TButton").pack(side=tk.LEFT, padx=3)
        ttk.Button(self.btn_frame, text="系统配置", command=self.open_config, style="Btn.TButton").pack(side=tk.LEFT, padx=3)
        ttk.Button(self.btn_frame, text="退出",  command=self.quit_app, style="Btn.TButton").pack(side=tk.RIGHT, padx=3)

        self.visible = False
        self.running = True
        self.log_line_count = 0
        self.update_log()

    def show(self):
        self.visible = True
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def hide(self):
        self.visible = False
        self.root.withdraw()

    def quit_app(self):
        self.running = False
        from claude_proxy.tray import tray_icon
        if tray_icon is not None:
            try:
                tray_icon.stop()
            except Exception:
                pass
            from claude_proxy import tray
            tray.tray_icon = None
        stop_proxy()
        _release_startup_lock()
        self.root.quit()
        self.root.destroy()

    def clear_log(self):
        self.log_text.delete(1.0, tk.END)

    def _on_force_auto_change(self):
        """强制 ProxyAuto 模式开关改变时的回调"""
        enabled = self.force_auto_var.get()
        set_force_proxy_auto(enabled)

    def open_key_manager(self):
        """打开密钥管理窗口"""
        from claude_proxy.gui.key_manager import KeyManagerWindow
        KeyManagerWindow(self.root)

    def open_channel_status(self):
        """打开渠道状态窗口"""
        from claude_proxy.gui.channel_status import ChannelStatusWindow
        ChannelStatusWindow(self.root)

    def open_proxy_auto(self):
        """打开ProxyAuto设置窗口"""
        from claude_proxy.gui.proxy_auto import ProxyAutoWindow
        ProxyAutoWindow(self.root)

    def open_config(self):
        """打开系统配置窗口"""
        from claude_proxy.gui.config_window import ConfigWindow
        ConfigWindow(self.root)

    def update_log(self):
        """从队列读取日志并显示"""
        if not self.running:
            return

        try:
            while True:
                line = log_queue.get_nowait()
                if line:
                    # 先插入文本
                    self.log_text.insert(tk.END, line + "\n")
                    # 获取插入行的行号（insert 之前 END 是空行，insert 之后 END 指向新行末尾）
                    # 使用 +1c -1l 定位到刚插入的行
                    line_start = self.log_text.index("end -1 lines")
                    line_end = self.log_text.index("end -1 lines lineend")

                    # 整行着色（基于文本内容）
                    tag = None
                    if "ERR" in line or "403" in line or "500" in line:
                        tag = "error"
                    elif "503" in line or "retry" in line or "SSL" in line or "429" in line:
                        tag = "retry"
                    elif "OK" in line:
                        tag = "success"
                    elif "TEST" in line:
                        tag = "info"
                    elif "REQ" in line:
                        tag = "info"
                    elif "AUTO" in line:
                        tag = "info"
                    elif "TRACE" in line:
                        tag = "error"
                    if tag:
                        self.log_text.tag_add(tag, line_start, line_end)
                        self.log_text.tag_raise(tag)

                    # 行内模型名着色（匹配 model=xxx 或 model=xxx->xxx）
                    import re
                    line_num = line_start.split(".")[0]
                    for m in re.finditer(r"model=([\w\-\.]+)", line):
                        start = f"{line_num}.{m.start(1)}"
                        end = f"{line_num}.{m.end(1)}"
                        self.log_text.tag_add("model_name", start, end)
                        self.log_text.tag_raise("model_name")

                    # 错误信息着色（匹配 ERR 后的具体错误描述）
                    for m in re.finditer(r"(ERR|ERROR|错误|失败|❌)(.*)", line):
                        start = f"{line_num}.{m.start(2)}"
                        end = f"{line_num}.{m.end(2)}"
                        self.log_text.tag_add("error", start, end)
                        self.log_text.tag_raise("error")

                    self.log_text.see(tk.END)

                    # 限制行数，避免每条日志都复制整个文本框内容。
                    self.log_line_count += 1
                    if self.log_line_count > 1000:
                        self.log_text.delete(1.0, "2.0")
                        self.log_line_count -= 1
        except queue.Empty:
            pass

        # 更新统计
        try:
            stats = pool.get_stats()
            self.lbl_requests.config(text=str(stats['total_requests']))
            self.lbl_errors.config(text=str(stats['total_errors']))
            self.lbl_input.config(text=str(stats['total_input_tokens']))
            self.lbl_output.config(text=str(stats['total_output_tokens']))
            self.lbl_channels.config(text=str(len(config.CHANNELS)))
            mode_text = "评分" if stats['mode'] == 'scoring' else "轮询"
            self.lbl_mode.config(text=mode_text,
                               foreground="#27ae60" if stats['mode'] == 'scoring' else "#2980b9")
        except (KeyError, tk.TclError):
            pass

        self.root.after(100, self.update_log)
