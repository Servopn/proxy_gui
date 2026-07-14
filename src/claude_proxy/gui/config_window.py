#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""系统配置窗口：查看运行时参数并调整重试/连接池大小。"""

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
from claude_proxy.stats import ChannelPool, model_pool


class ConfigWindow:
    """运行时系统配置窗口。"""
    def __init__(self, parent):
        self.window = tk.Toplevel(parent)
        self.window.title("系统配置")
        self.window.geometry("520x430")
        self.window.transient(parent)
        _center_window(self.window)

        ttk.Label(self.window, text="系统配置参数", font=("Arial", 14, "bold")).pack(pady=10)
        editable = ttk.LabelFrame(self.window, text="可调整参数")
        editable.pack(fill=tk.X, padx=12, pady=6)

        self.retry_var = tk.StringVar(value=str(MAX_RETRY_CHANNELS))
        self.pool_var = tk.StringVar(value=str(MAX_POOL_SIZE))
        ttk.Label(editable, text="最大重试渠道数").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        ttk.Spinbox(editable, from_=1, to=len(config.CHANNELS), textvariable=self.retry_var, width=8).grid(row=0, column=1, padx=8)
        ttk.Label(editable, text="连接池大小").grid(row=1, column=0, sticky="w", padx=8, pady=6)
        ttk.Spinbox(editable, from_=1, to=100, textvariable=self.pool_var, width=8).grid(row=1, column=1, padx=8)
        ttk.Button(editable, text="应用", command=self._apply).grid(row=0, column=2, rowspan=2, padx=12)

        columns = ("param", "value", "description")
        self.tree = ttk.Treeview(self.window, columns=columns, show="headings")
        self.tree.heading("param", text="参数名")
        self.tree.heading("value", text="当前值")
        self.tree.heading("description", text="说明")
        self.tree.column("param", width=190)
        self.tree.column("value", width=80, anchor="center")
        self.tree.column("description", width=230)
        self.tree.pack(fill=tk.BOTH, expand=True, padx=12, pady=6)
        self._load_config()

    def _load_config(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        configs = [
            ("WARMUP_REQUESTS", ChannelPool.WARMUP_REQUESTS, "尝试达到此数量后启用评分"),
            ("MIN_CHANNEL_REQUESTS", ChannelPool.MIN_CHANNEL_REQUESTS, "单渠道最少样本数"),
            ("SCORE_THRESHOLD", ChannelPool.SCORE_THRESHOLD, "评分模式最低平均分"),
            ("COOLDOWN_CHANNELS", ChannelPool.COOLDOWN_CHANNELS, "过多冷却时退回轮询"),
            ("MAX_RETRY_CHANNELS", config.MAX_RETRY_CHANNELS, "单请求最大渠道尝试数"),
            ("MAX_POOL_SIZE", config.MAX_POOL_SIZE, "当前连接池上限"),
            ("总渠道数", len(config.CHANNELS), "当前渠道总数"),
            ("模型池数量", len(model_pool.models), "自动模型可选数量"),
        ]
        for param, value, description in configs:
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
