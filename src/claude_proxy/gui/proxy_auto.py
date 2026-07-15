#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ProxyAuto 设置窗口：模型排名状态 + 模型池配置。"""

import os
import tkinter as tk
from tkinter import ttk, messagebox

from claude_proxy.config import (
    DEFAULT_AUTO_MODEL_POOL,
    ENV_FILE,
    MODEL_FRIENDLY_NAMES,
    USER_MODEL_LIST,
    _ENV_POOL_KEY,
)
from claude_proxy.gui.utils import _center_window
from claude_proxy.logger import log
from claude_proxy.stats import model_pool


class ProxyAutoWindow:
    """ProxyAuto 设置窗口 - 模型排名 + 模型池配置"""
    def __init__(self, parent):
        self.window = tk.Toplevel(parent)
        self.window.title("ProxyAuto 设置")
        self.window.geometry("750x600")
        self.window.transient(parent)
        _center_window(self.window)

        # 标签页
        notebook = ttk.Notebook(self.window)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # === 模型排名标签页 ===
        model_frame = ttk.Frame(notebook)
        notebook.add(model_frame, text="模型状态")

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

        # === 模型池配置标签页 ===
        config_frame = ttk.Frame(notebook)
        notebook.add(config_frame, text="模型池配置")

        info_inner = ttk.Frame(config_frame)
        info_inner.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(info_inner, text="当前模型池（拖动排序，优先级从上到下）",
                  font=('Arial', 10, 'bold')).pack(anchor='w')

        pool_inner = ttk.Frame(config_frame)
        pool_inner.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.pool_listbox = tk.Listbox(pool_inner, selectmode=tk.EXTENDED, font=('Consolas', 10),
                                        bg='#1e1e1e', fg='#d4d4d4', selectbackground='#264f78',
                                        height=8)
        pool_scroll = ttk.Scrollbar(pool_inner, orient=tk.VERTICAL, command=self.pool_listbox.yview)
        self.pool_listbox.configure(yscrollcommand=pool_scroll.set)
        self.pool_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        pool_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # 加载当前模型池
        for m in model_pool.models:
            friendly = MODEL_FRIENDLY_NAMES.get(m, m)
            self.pool_listbox.insert(tk.END, friendly)

        # 操作按钮
        btn_frame = ttk.Frame(config_frame)
        btn_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Button(btn_frame, text="↑ 上移", command=self._move_up).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="↓ 下移", command=self._move_down).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="移除选中", command=self._remove_selected).pack(side=tk.LEFT, padx=2)

        add_frame = ttk.LabelFrame(config_frame, text="添加模型")
        add_frame.pack(fill=tk.X, padx=5, pady=5)
        add_inner = ttk.Frame(add_frame)
        add_inner.pack(fill=tk.X, padx=5, pady=5)
        self.add_combo = ttk.Combobox(add_inner, values=USER_MODEL_LIST, width=25, font=('Consolas', 10))
        self.add_combo.pack(side=tk.LEFT, padx=3)
        if USER_MODEL_LIST:
            self.add_combo.set(USER_MODEL_LIST[0])
        ttk.Button(add_inner, text="添加", command=self._add_model).pack(side=tk.LEFT, padx=3)

        bottom_frame = ttk.Frame(config_frame)
        bottom_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Button(bottom_frame, text="恢复默认", command=self._reset_default).pack(side=tk.LEFT, padx=3)
        ttk.Button(bottom_frame, text="应用", command=self._apply).pack(side=tk.RIGHT, padx=3)

        # 颜色标签
        self.model_tree.tag_configure('green', foreground='green')
        self.model_tree.tag_configure('blue', foreground='blue')
        self.model_tree.tag_configure('orange', foreground='orange')
        self.model_tree.tag_configure('red', foreground='red')
        self.model_tree.tag_configure('gray', foreground='gray')

        # 按钮：刷新模型排名
        btn_bar = ttk.Frame(self.window)
        btn_bar.pack(fill=tk.X, padx=10, pady=5)
        ttk.Button(btn_bar, text="刷新", command=self._refresh).pack(side=tk.LEFT, padx=5)

        self._refresh()

    def _refresh(self):
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

    def _move_up(self):
        sel = self.pool_listbox.curselection()
        if not sel or sel[0] == 0:
            return
        idx = sel[0]
        val = self.pool_listbox.get(idx)
        self.pool_listbox.delete(idx)
        self.pool_listbox.insert(idx - 1, val)
        self.pool_listbox.selection_set(idx - 1)

    def _move_down(self):
        sel = self.pool_listbox.curselection()
        if not sel or sel[0] == self.pool_listbox.size() - 1:
            return
        idx = sel[0]
        val = self.pool_listbox.get(idx)
        self.pool_listbox.delete(idx)
        self.pool_listbox.insert(idx + 1, val)
        self.pool_listbox.selection_set(idx + 1)

    def _remove_selected(self):
        sel = self.pool_listbox.curselection()
        if not sel:
            return
        for idx in reversed(sel):
            self.pool_listbox.delete(idx)

    def _add_model(self):
        friendly = self.add_combo.get().strip()
        if not friendly:
            return
        existing = [self.pool_listbox.get(i) for i in range(self.pool_listbox.size())]
        if friendly in existing:
            messagebox.showinfo("提示", f"模型 {friendly} 已在池中")
            return
        self.pool_listbox.insert(tk.END, friendly)

    def _reset_default(self):
        self.pool_listbox.delete(0, tk.END)
        for m in DEFAULT_AUTO_MODEL_POOL:
            friendly = MODEL_FRIENDLY_NAMES.get(m, m)
            self.pool_listbox.insert(tk.END, friendly)
        _remove_env_pool_key()

    def _apply(self):
        friendly_to_id = {v: k for k, v in MODEL_FRIENDLY_NAMES.items()}
        models = []
        for i in range(self.pool_listbox.size()):
            friendly = self.pool_listbox.get(i)
            xfid = friendly_to_id.get(friendly, friendly)
            models.append(xfid)
        if not models:
            messagebox.showwarning("警告", "模型池不能为空")
            return
        model_pool.set_models(models)
        from claude_proxy import config
        config.AUTO_MODEL_POOL = list(models)
        _write_env_pool_key(models)
        log(f"ProxyAuto 模型池已更新: {', '.join(models)}")
        messagebox.showinfo("成功", f"模型池已更新，共 {len(models)} 个模型")


def _write_env_pool_key(models):
    """将模型池配置持久化到 .env 文件"""
    if not ENV_FILE.exists():
        log("持久化: .env 文件不存在，跳过写入")
        return
    value = ",".join(models)
    try:
        existing_lines = ENV_FILE.read_text(encoding="utf-8-sig").splitlines()
        kept = [line for line in existing_lines
                if not line.lstrip().startswith(_ENV_POOL_KEY + "=")]
        kept.append(f"{_ENV_POOL_KEY}={value}")
        ENV_FILE.write_text("\n".join(kept) + "\n", encoding="utf-8")
        os.environ[_ENV_POOL_KEY] = value
        log(f"持久化: 模型池配置已写入 .env")
    except OSError as e:
        log(f"持久化: 写入 .env 失败 - {e}")
        messagebox.showwarning("写入失败", f"无法写入 .env 文件，请检查文件权限。\n{e}")


def _remove_env_pool_key():
    """从 .env 中删除模型池配置（恢复默认时调用）"""
    if not ENV_FILE.exists():
        return
    try:
        existing_lines = ENV_FILE.read_text(encoding="utf-8-sig").splitlines()
        kept = [line for line in existing_lines
                if not line.lstrip().startswith(_ENV_POOL_KEY + "=")]
        ENV_FILE.write_text("\n".join(kept) + "\n", encoding="utf-8")
        os.environ.pop(_ENV_POOL_KEY, None)
    except OSError:
        pass