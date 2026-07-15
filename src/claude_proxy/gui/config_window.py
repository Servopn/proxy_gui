#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""系统配置窗口：可调整参数与只读参数分区展示。"""

import tkinter as tk
from tkinter import ttk, messagebox

from claude_proxy import config
from claude_proxy.config import (
    MAX_RETRY_CHANNELS,
    set_max_retry_channels,
)
from claude_proxy.connection_pool import MAX_POOL_SIZE, set_max_pool_size
from claude_proxy.gui.utils import _center_window
from claude_proxy.stats import ChannelPool, model_pool


class ConfigWindow:
    """运行时系统配置窗口。"""
    def __init__(self, parent):
        self.window = tk.Toplevel(parent)
        self.window.title("系统配置")
        self.window.geometry("600x500")
        self.window.transient(parent)
        _center_window(self.window)

        ttk.Label(self.window, text="系统配置参数", font=("Arial", 14, "bold")).pack(pady=10)

        # === 可调整参数区域 ===
        editable = ttk.LabelFrame(self.window, text="可调整参数")
        editable.pack(fill=tk.X, padx=12, pady=6)

        self.retry_var = tk.StringVar(value=str(MAX_RETRY_CHANNELS))
        self.pool_var = tk.StringVar(value=str(MAX_POOL_SIZE))

        ttk.Label(editable, text="最大重试渠道数").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        self.retry_spin = ttk.Spinbox(editable, from_=1, to=len(config.CHANNELS),
                                      textvariable=self.retry_var, width=8)
        self.retry_spin.grid(row=0, column=1, padx=8)

        ttk.Label(editable, text="连接池大小").grid(row=1, column=0, sticky="w", padx=8, pady=6)
        self.pool_spin = ttk.Spinbox(editable, from_=1, to=100,
                                     textvariable=self.pool_var, width=8)
        self.pool_spin.grid(row=1, column=1, padx=8)

        ttk.Button(editable, text="应用", command=self._apply).grid(row=0, column=2, rowspan=2, padx=12)

        # === 只读参数区域 ===
        readonly = ttk.LabelFrame(self.window, text="只读参数")
        readonly.pack(fill=tk.BOTH, expand=True, padx=12, pady=6)

        columns = ("param", "value", "description")
        self.tree = ttk.Treeview(readonly, columns=columns, show="headings", height=8)
        self.tree.heading("param", text="参数名")
        self.tree.heading("value", text="当前值")
        self.tree.heading("description", text="说明")
        self.tree.column("param", width=190)
        self.tree.column("value", width=80, anchor="center")
        self.tree.column("description", width=250)

        tree_scroll = ttk.Scrollbar(readonly, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 2))
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self._load_config()

    def _load_config(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        rows = [
            ("WARMUP_REQUESTS", ChannelPool.WARMUP_REQUESTS, "尝试达到此数量后启用评分"),
            ("MIN_CHANNEL_REQUESTS", ChannelPool.MIN_CHANNEL_REQUESTS, "单渠道最少样本数"),
            ("SCORE_THRESHOLD", ChannelPool.SCORE_THRESHOLD, "评分模式最低平均分"),
            ("COOLDOWN_CHANNELS", ChannelPool.COOLDOWN_CHANNELS, "过多冷却时退回轮询"),
            ("总渠道数", len(config.CHANNELS), "当前渠道总数"),
            ("模型池数量", len(model_pool.models), "自动模型可选数量"),
        ]
        for param, value, description in rows:
            self.tree.insert("", tk.END, values=(param, value, description))

    def _apply(self):
        try:
            set_max_retry_channels(int(self.retry_var.get()))
            set_max_pool_size(int(self.pool_var.get()))
        except ValueError:
            messagebox.showerror("错误", "配置值必须是整数")
            return
        self._load_config()
        messagebox.showinfo("成功", "运行时配置已应用")