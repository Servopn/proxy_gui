#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""渠道状态窗口：查看各渠道的请求量、成功率、评分和状态。"""

import tkinter as tk
from tkinter import ttk

from claude_proxy.gui.utils import _center_window
from claude_proxy.stats import pool


class ChannelStatusWindow:
    """渠道状态窗口 - 查看各渠道运行状态"""
    def __init__(self, parent):
        self.window = tk.Toplevel(parent)
        self.window.title("渠道状态")
        self.window.geometry("850x520")
        self.window.transient(parent)
        _center_window(self.window)

        columns = ('rank', 'name', 'requests', 'success', 'errors', 'success_rate', 'score', 'status')
        self.ch_tree = ttk.Treeview(self.window, columns=columns, show='headings')
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

        ch_scroll = ttk.Scrollbar(self.window, orient=tk.VERTICAL, command=self.ch_tree.yview)
        self.ch_tree.configure(yscrollcommand=ch_scroll.set)
        self.ch_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=5)
        ch_scroll.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 10), pady=5)

        btn_frame = ttk.Frame(self.window)
        btn_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Button(btn_frame, text="刷新", command=self._refresh).pack(side=tk.LEFT, padx=5)

        for tree in (self.ch_tree,):
            tree.tag_configure('green', foreground='green')
            tree.tag_configure('blue', foreground='blue')
            tree.tag_configure('orange', foreground='orange')
            tree.tag_configure('red', foreground='red')
            tree.tag_configure('gray', foreground='gray')

        self._refresh()

    def _refresh(self):
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