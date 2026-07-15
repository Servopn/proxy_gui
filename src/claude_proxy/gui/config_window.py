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
        self.window.geometry("650x550")
        self.window.transient(parent)
        _center_window(self.window)

        ttk.Label(self.window, text="系统配置参数", font=("Arial", 14, "bold")).pack(pady=10)

        # === 可调整参数区域 ===
        editable = ttk.LabelFrame(self.window, text="可调整参数（修改后点击应用生效）")
        editable.pack(fill=tk.X, padx=12, pady=6)

        # 参数：变量名 / 标签 / 范围 / 配置键名
        self._editable_params = [
            ("max_retry", "最大重试渠道数", 1, len(config.CHANNELS), 1, "MAX_RETRY_CHANNELS"),
            ("pool_size", "连接池大小", 1, 100, 1, "MAX_POOL_SIZE"),
            ("warmup", "渠道评分预热请求数", 1, 500, 10, "WARMUP_REQUESTS"),
            ("min_ch", "渠道最少样本数", 1, 100, 1, "MIN_CHANNEL_REQUESTS"),
            ("score_th", "评分模式最低平均分", 1, 100, 5, "SCORE_THRESHOLD"),
            ("cooldown_ch", "渠道冷却上限", 1, 50, 1, "COOLDOWN_CHANNELS"),
            ("model_warmup", "模型评分预热请求数", 1, 200, 10, "MODEL_WARMUP_REQUESTS"),
            ("min_model", "模型最少样本数", 1, 50, 1, "MIN_MODEL_REQUESTS"),
            ("cooldown_sec", "模型冷却时间(秒)", 5, 600, 10, "COOLDOWN_SECONDS"),
        ]

        self._vars = {}
        for i, (key, label, lo, hi, step, _) in enumerate(self._editable_params):
            cur = getattr(config, key, None)
            if cur is None:
                # 映射名称到 config 属性
                for attr_name in dir(config):
                    if attr_name.upper() == self._editable_params[i][5]:
                        cur = getattr(config, attr_name)
                        break
            # 直接取配置值
            cur = getattr(config, self._editable_params[i][5])
            if isinstance(cur, float):
                # 浮点数转成 0-100 百分比整数显示
                display_val = int(cur * 100) if cur < 1 else int(cur)
                self._vars[key] = tk.StringVar(value=str(display_val))
                ttk.Label(editable, text=label).grid(row=i, column=0, sticky="w", padx=8, pady=3)
                sp = ttk.Spinbox(editable, from_=lo, to=hi, textvariable=self._vars[key], width=8)
                sp.grid(row=i, column=1, padx=8)
            else:
                self._vars[key] = tk.StringVar(value=str(cur))
                ttk.Label(editable, text=label).grid(row=i, column=0, sticky="w", padx=8, pady=3)
                sp = ttk.Spinbox(editable, from_=lo, to=hi, textvariable=self._vars[key], width=8)
                sp.grid(row=i, column=1, padx=8)

        # 应用按钮跨行
        total_rows = len(self._editable_params)
        ttk.Button(editable, text="应用", command=self._apply).grid(
            row=0, column=2, rowspan=total_rows, padx=12, sticky="n")

        # === 只读参数区域 ===
        readonly = ttk.LabelFrame(self.window, text="只读参数")
        readonly.pack(fill=tk.BOTH, expand=True, padx=12, pady=6)

        columns = ("param", "value", "description")
        self.tree = ttk.Treeview(readonly, columns=columns, show="headings", height=6)
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
            ("总渠道数", len(config.CHANNELS), "当前渠道总数"),
            ("模型池数量", len(model_pool.models), "自动模型可选数量"),
        ]
        for param, value, description in rows:
            self.tree.insert("", tk.END, values=(param, value, description))

    def _apply(self):
        try:
            set_max_retry_channels(int(self._vars["max_retry"].get()))
            set_max_pool_size(int(self._vars["pool_size"].get()))
            # 更新 config 中的可调参数
            config.WARMUP_REQUESTS = int(self._vars["warmup"].get())
            config.MIN_CHANNEL_REQUESTS = int(self._vars["min_ch"].get())
            # SCORE_THRESHOLD 是浮点数，显示为 0-100 整数，转换回浮点
            config.SCORE_THRESHOLD = float(self._vars["score_th"].get()) / 100.0
            config.COOLDOWN_CHANNELS = int(self._vars["cooldown_ch"].get())
            config.MODEL_WARMUP_REQUESTS = int(self._vars["model_warmup"].get())
            config.MIN_MODEL_REQUESTS = int(self._vars["min_model"].get())
            config.COOLDOWN_SECONDS = int(self._vars["cooldown_sec"].get())
        except ValueError:
            messagebox.showerror("错误", "配置值必须是整数")
            return
        self._load_config()
        messagebox.showinfo("成功", "运行时配置已应用（重启后失效）")