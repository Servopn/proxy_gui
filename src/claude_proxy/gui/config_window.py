#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""系统配置窗口：可调整参数与只读参数分区展示。"""

import tkinter as tk
from tkinter import ttk, messagebox

from claude_proxy import config
from claude_proxy.config import (
    MAX_POOL_SIZE,
    MAX_RETRY_CHANNELS,
    set_max_retry_channels,
)
from claude_proxy.connection_pool import set_max_pool_size
from claude_proxy.gui.utils import _center_window
from claude_proxy.stats import model_pool


class ConfigWindow:
    """运行时系统配置窗口。"""
    def __init__(self, parent):
        self.window = tk.Toplevel(parent)
        self.window.title("系统配置")
        self.window.geometry("620x580")
        self.window.transient(parent)
        _center_window(self.window)

        ttk.Label(self.window, text="系统配置", font=("Arial", 14, "bold")).pack(pady=(12, 4))

        # === 可调整参数区域 ===
        editable = ttk.LabelFrame(self.window, text="可调整参数")
        editable.pack(fill=tk.BOTH, expand=True, padx=12, pady=(4, 2))

        # 用 Canvas + Scrollbar 包裹内层 Frame，支持滚动
        canvas = tk.Canvas(editable, highlightthickness=0)
        scrollbar = ttk.Scrollbar(editable, orient=tk.VERTICAL, command=canvas.yview)
        self._scroll_frame = ttk.Frame(canvas)

        self._scroll_frame.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self._scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4, pady=4)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 4), pady=4)

        # 鼠标滚轮支持
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        self.window.bind("<Destroy>", lambda e: canvas.unbind_all("<MouseWheel>"))

        # 参数定义：(键名, 标签, 最小值, 最大值, 步长, config属性名, 后缀)
        self._editable_params = [
            ("max_retry",   "最大重试渠道数",       1, len(config.CHANNELS), 1,  "MAX_RETRY_CHANNELS",     "个"),
            ("pool_size",   "连接池大小",            1, 100,  1,  "MAX_POOL_SIZE",          "个"),
            ("warmup",      "渠道评分预热请求数",    1, 500,  10, "WARMUP_REQUESTS",        "次"),
            ("min_ch",      "渠道最少样本数",        1, 100,  1,  "MIN_CHANNEL_REQUESTS",   "次"),
            ("score_th",    "评分模式最低平均分",    1, 100,  5,  "SCORE_THRESHOLD",        "%"),
            ("cooldown_ch", "渠道冷却上限",          1, 50,   1,  "COOLDOWN_CHANNELS",      "个"),
            ("model_warmup","模型评分预热请求数",    1, 200,  10, "MODEL_WARMUP_REQUESTS",  "次"),
            ("min_model",   "模型最少样本数",        1, 50,   1,  "MIN_MODEL_REQUESTS",     "次"),
            ("cooldown_sec","模型冷却时间",          5, 600,  10, "COOLDOWN_SECONDS",       "秒"),
        ]

        self._vars = {}
        for i, (key, label, lo, hi, step, attr, suffix) in enumerate(self._editable_params):
            row_frame = ttk.Frame(self._scroll_frame)
            row_frame.pack(fill=tk.X, padx=8, pady=2)

            ttk.Label(row_frame, text=label, width=22, anchor="w").pack(side=tk.LEFT)

            cur = getattr(config, attr)
            if isinstance(cur, float):
                display_val = int(cur * 100) if cur <= 1 else int(cur)
                self._vars[key] = tk.StringVar(value=str(display_val))
            else:
                self._vars[key] = tk.StringVar(value=str(cur))

            sp = ttk.Spinbox(row_frame, from_=lo, to=hi, textvariable=self._vars[key], width=6)
            sp.pack(side=tk.LEFT, padx=(4, 2))
            ttk.Label(row_frame, text=suffix, width=3, anchor="w").pack(side=tk.LEFT)

        # 应用按钮
        btn_frame = ttk.Frame(editable)
        btn_frame.pack(fill=tk.X, padx=12, pady=6)
        ttk.Button(btn_frame, text="应用更改", command=self._apply, width=15).pack(side=tk.RIGHT)

        # === 只读参数区域 ===
        readonly = ttk.LabelFrame(self.window, text="只读参数")
        readonly.pack(fill=tk.BOTH, padx=12, pady=(2, 12))

        columns = ("param", "value")
        self.tree = ttk.Treeview(readonly, columns=columns, show="headings", height=2)
        self.tree.heading("param", text="参数名")
        self.tree.heading("value", text="当前值")
        self.tree.column("param", width=120, anchor="w")
        self.tree.column("value", width=100, anchor="center")

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4, pady=4)

        self._load_config()

    def _load_config(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        rows = [
            ("总渠道数", len(config.CHANNELS)),
            ("模型池数量", len(model_pool.models)),
        ]
        for param, value in rows:
            self.tree.insert("", tk.END, values=(param, value))

    def _apply(self):
        try:
            set_max_retry_channels(int(self._vars["max_retry"].get()))
            set_max_pool_size(int(self._vars["pool_size"].get()))
            config.WARMUP_REQUESTS = int(self._vars["warmup"].get())
            config.MIN_CHANNEL_REQUESTS = int(self._vars["min_ch"].get())
            config.SCORE_THRESHOLD = float(self._vars["score_th"].get()) / 100.0
            config.COOLDOWN_CHANNELS = int(self._vars["cooldown_ch"].get())
            config.MODEL_WARMUP_REQUESTS = int(self._vars["model_warmup"].get())
            config.MIN_MODEL_REQUESTS = int(self._vars["min_model"].get())
            config.COOLDOWN_SECONDS = int(self._vars["cooldown_sec"].get())
        except ValueError:
            messagebox.showerror("错误", "配置值必须是整数")
            return

        # 持久化到 .env
        self._persist()
        self._load_config()
        messagebox.showinfo("成功", "运行时配置已应用并保存到 .env")

    def _persist(self):
        """将当前可调参数写入 .env"""
        from claude_proxy.config import ENV_FILE
        if not ENV_FILE.exists():
            return
        try:
            lines = ENV_FILE.read_text(encoding="utf-8-sig").splitlines()
            # 要更新的 key 列表
            update_keys = {
                "CLAUDE_PROXY_WARMUP_REQUESTS": str(config.WARMUP_REQUESTS),
                "CLAUDE_PROXY_MIN_CHANNEL_REQUESTS": str(config.MIN_CHANNEL_REQUESTS),
                "CLAUDE_PROXY_SCORE_THRESHOLD": str(config.SCORE_THRESHOLD),
                "CLAUDE_PROXY_COOLDOWN_CHANNELS": str(config.COOLDOWN_CHANNELS),
                "CLAUDE_PROXY_MODEL_WARMUP_REQUESTS": str(config.MODEL_WARMUP_REQUESTS),
                "CLAUDE_PROXY_MIN_MODEL_REQUESTS": str(config.MIN_MODEL_REQUESTS),
                "CLAUDE_PROXY_COOLDOWN_SECONDS": str(config.COOLDOWN_SECONDS),
                "CLAUDE_PROXY_MAX_RETRY_CHANNELS": str(config.MAX_RETRY_CHANNELS),
                "CLAUDE_PROXY_MAX_POOL_SIZE": str(config.MAX_POOL_SIZE),
            }
            # 移除旧 key
            kept = [l for l in lines
                    if not any(l.lstrip().startswith(k + "=") for k in update_keys)]
            for k, v in update_keys.items():
                import os
                os.environ[k] = v
                kept.append(f"{k}={v}")
            ENV_FILE.write_text("\n".join(kept) + "\n", encoding="utf-8")
        except OSError:
            pass