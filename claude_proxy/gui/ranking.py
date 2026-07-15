#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""排名面板：渠道排名 + 模型排名。"""

import tkinter as tk
from tkinter import ttk

from claude_proxy import config
from claude_proxy.config import MODEL_FRIENDLY_NAMES
from claude_proxy.gui.utils import _center_window
from claude_proxy.stats import model_pool, pool


class RankingWindow:
    """排名面板 - 渠道排名 + 模型排名"""
    def __init__(self, parent):
        self.window = tk.Toplevel(parent)
        self.window.title("排名面板")
        self.window.geometry("850x520")
        self.window.transient(parent)
        _center_window(self.window)

        # 标签页
        notebook = ttk.Notebook(self.window)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # === 渠道排名标签页 ===
        ch_frame = ttk.Frame(notebook)
        notebook.add(ch_frame, text="渠道排名")

        columns = ('rank', 'name', 'requests', 'success', 'errors', 'success_rate', 'score', 'status')
        self.ch_tree = ttk.Treeview(ch_frame, columns=columns, show='headings')
        self.ch_tree.heading('rank', text='排名')
        self.ch_tree.heading('name', text='渠道名称')
        self.ch_tree.heading('requests', text='总请求')
        self.ch_tree.heading('success', text='成功')
        self.ch_tree.heading('errors', text='失败')
        self.ch_tree.heading('success_rate', text='成功率')
        self.ch_tree.heading('score', text='评分')
        self.ch_tree.heading('status', text='状态')

        self.ch_tree.column('rank', width=50, anchor='center')
        self.ch_tree.column('name', width=80, anchor='center')
        self.ch_tree.column('requests', width=80, anchor='center')
        self.ch_tree.column('success', width=80, anchor='center')
        self.ch_tree.column('errors', width=80, anchor='center')
        self.ch_tree.column('success_rate', width=80, anchor='center')
        self.ch_tree.column('score', width=80, anchor='center')
        self.ch_tree.column('status', width=100, anchor='center')

        ch_scroll = ttk.Scrollbar(ch_frame, orient=tk.VERTICAL, command=self.ch_tree.yview)
        self.ch_tree.configure(yscrollcommand=ch_scroll.set)
        self.ch_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ch_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # === 模型排名标签页 ===
        model_frame = ttk.Frame(notebook)
        notebook.add(model_frame, text="模型排名 (ProxyAutoModel)")

        m_columns = ('rank', 'model', 'requests', 'success', 'errors', 'success_rate', 'score', 'status')
        self.model_tree = ttk.Treeview(model_frame, columns=m_columns, show='headings')
        self.model_tree.heading('rank', text='排名')
        self.model_tree.heading('model', text='模型ID')
        self.model_tree.heading('requests', text='总请求')
        self.model_tree.heading('success', text='成功')
        self.model_tree.heading('errors', text='失败')
        self.model_tree.heading('success_rate', text='成功率')
        self.model_tree.heading('score', text='评分')
        self.model_tree.heading('status', text='状态')

        self.model_tree.column('rank', width=50, anchor='center')
        self.model_tree.column('model', width=180, anchor='center')
        self.model_tree.column('requests', width=80, anchor='center')
        self.model_tree.column('success', width=80, anchor='center')
        self.model_tree.column('errors', width=80, anchor='center')
        self.model_tree.column('success_rate', width=80, anchor='center')
        self.model_tree.column('score', width=80, anchor='center')
        self.model_tree.column('status', width=100, anchor='center')

        m_scroll = ttk.Scrollbar(model_frame, orient=tk.VERTICAL, command=self.model_tree.yview)
        self.model_tree.configure(yscrollcommand=m_scroll.set)
        self.model_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        m_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # 刷新按钮
        btn_frame = ttk.Frame(self.window)
        btn_frame.pack(pady=5)
        ttk.Button(btn_frame, text="刷新", command=self._refresh).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="配置模型池", command=self._open_model_config).pack(side=tk.LEFT, padx=5)

        # 颜色标签
        for tree in (self.ch_tree, self.model_tree):
            tree.tag_configure('green', foreground='green')
            tree.tag_configure('blue', foreground='blue')
            tree.tag_configure('orange', foreground='orange')
            tree.tag_configure('red', foreground='red')
            tree.tag_configure('gray', foreground='gray')

        self._refresh()

    def _open_model_config(self):
        from claude_proxy.gui.model_pool import ModelPoolConfigWindow
        ModelPoolConfigWindow(self.window)

    def _refresh(self):
        # 刷新渠道排名
        for item in self.ch_tree.get_children():
            self.ch_tree.delete(item)
        try:
            stats = pool.get_stats()
            channels = stats.get('channels', [])
            sorted_channels = sorted(channels, key=lambda x: (
                float(x.get('success_rate', '0%').replace('%', '')) if x.get('success_rate', '-') != '-' else 0
            ), reverse=True)
            for i, ch in enumerate(sorted_channels):
                success_rate = ch.get('success_rate', '-')
                requests = ch.get('requests', 0)
                tag = self._get_status_tag(requests, success_rate)
                status = self._get_status_text(requests, success_rate)
                self.ch_tree.insert('', tk.END, values=(
                    i + 1, ch.get('name', ''), requests,
                    ch.get('success', 0), ch.get('errors', 0),
                    success_rate, ch.get('score', '-'), status
                ), tags=(tag,))
        except Exception as e:
            self.ch_tree.insert('', tk.END, values=('错误', str(e), '', '', '', '', '', ''))

        # 刷新模型排名
        for item in self.model_tree.get_children():
            self.model_tree.delete(item)
        try:
            model_stats = model_pool.get_stats()
            sorted_models = sorted(model_stats, key=lambda x: (
                float(x.get('success_rate', '0%').replace('%', '')) if x.get('success_rate', '-') != '-' else 0
            ), reverse=True)
            for i, m in enumerate(sorted_models):
                xfid = m.get('model', '')
                friendly = MODEL_FRIENDLY_NAMES.get(xfid, xfid)
                success_rate = m.get('success_rate', '-')
                requests = m.get('requests', 0)
                tag = self._get_status_tag(requests, success_rate)
                status = m.get('cooldown', '正常')
                if requests == 0:
                    status = "未使用"
                self.model_tree.insert('', tk.END, values=(
                    i + 1, friendly, requests,
                    m.get('success', 0), m.get('errors', 0),
                    success_rate, m.get('score', '-'), status
                ), tags=(tag,))
        except Exception as e:
            self.model_tree.insert('', tk.END, values=('错误', str(e), '', '', '', '', '', ''))

    def _get_status_tag(self, requests, success_rate):
        if requests == 0:
            return 'gray'
        if success_rate == '100.0%':
            return 'green'
        try:
            rate = float(success_rate.replace('%', ''))
        except (AttributeError, ValueError):
            return 'gray'
        if rate > 80:
            return 'blue'
        elif rate > 50:
            return 'orange'
        return 'red'

    def _get_status_text(self, requests, success_rate):
        if requests == 0:
            return "未使用"
        if success_rate == '100.0%':
            return "优秀"
        try:
            rate = float(success_rate.replace('%', ''))
        except (AttributeError, ValueError):
            return "未知"
        if rate > 80:
            return "良好"
        elif rate > 50:
            return "一般"
        return "较差"
