#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模型池配置窗口：配置 ProxyAutoModel 参与的模型。"""

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


class ModelPoolConfigWindow:
    """模型池配置窗口 - 配置 ProxyAutoModel 参与的模型"""
    def __init__(self, parent):
        self.window = tk.Toplevel(parent)
        self.window.title("ProxyAutoModel 模型池配置")
        self.window.geometry("600x550")
        self.window.transient(parent)
        _center_window(self.window)

        # 说明
        info_frame = ttk.Frame(self.window)
        info_frame.pack(fill=tk.X, padx=15, pady=8)
        ttk.Label(info_frame, text="ProxyAutoModel 自动选择模型池", font=('Arial', 13, 'bold')).pack(anchor='w')
        ttk.Label(info_frame, text="当请求模型为 ProxyAutoModel 时，系统根据评分自动选择池中模型\n"
                                    "上下文限制: 256K tokens（兼容最短上下文模型）",
                  font=('Arial', 9), foreground='gray').pack(anchor='w', pady=2)

        # 当前模型池
        pool_frame = ttk.LabelFrame(self.window, text="当前模型池（拖动排序，优先级从上到下）")
        pool_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=5)

        pool_inner = ttk.Frame(pool_frame)
        pool_inner.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.pool_listbox = tk.Listbox(pool_inner, selectmode=tk.EXTENDED, font=('Consolas', 10),
                                        bg='#1e1e1e', fg='#d4d4d4', selectbackground='#264f78',
                                        height=12)
        pool_scroll = ttk.Scrollbar(pool_inner, orient=tk.VERTICAL, command=self.pool_listbox.yview)
        self.pool_listbox.configure(yscrollcommand=pool_scroll.set)
        self.pool_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        pool_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # 加载当前模型池（显示友好名称）
        for m in model_pool.models:
            friendly = MODEL_FRIENDLY_NAMES.get(m, m)
            self.pool_listbox.insert(tk.END, friendly)

        # 操作按钮
        btn_frame = ttk.Frame(self.window)
        btn_frame.pack(fill=tk.X, padx=15, pady=5)

        ttk.Button(btn_frame, text="↑ 上移", command=self._move_up).pack(side=tk.LEFT, padx=3)
        ttk.Button(btn_frame, text="↓ 下移", command=self._move_down).pack(side=tk.LEFT, padx=3)
        ttk.Button(btn_frame, text="移除选中", command=self._remove_selected).pack(side=tk.LEFT, padx=3)

        # 添加模型
        add_frame = ttk.LabelFrame(self.window, text="添加模型")
        add_frame.pack(fill=tk.X, padx=15, pady=5)

        add_inner = ttk.Frame(add_frame)
        add_inner.pack(fill=tk.X, padx=5, pady=5)

        # 可选模型列表（友好名称，与请求模型列表一致）
        self.add_combo = ttk.Combobox(add_inner, values=USER_MODEL_LIST, width=25, font=('Consolas', 10))
        self.add_combo.pack(side=tk.LEFT, padx=3)
        if USER_MODEL_LIST:
            self.add_combo.set(USER_MODEL_LIST[0])

        ttk.Button(add_inner, text="添加", command=self._add_model).pack(side=tk.LEFT, padx=3)

        # 底部按钮
        bottom_frame = ttk.Frame(self.window)
        bottom_frame.pack(fill=tk.X, padx=15, pady=10)

        ttk.Button(bottom_frame, text="恢复默认", command=self._reset_default).pack(side=tk.LEFT, padx=3)
        ttk.Button(bottom_frame, text="应用", command=self._apply).pack(side=tk.RIGHT, padx=3)
        ttk.Button(bottom_frame, text="取消", command=self.window.destroy).pack(side=tk.RIGHT, padx=3)

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
        # 检查重复
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
        # 从 .env 中删除持久化配置，下次启动用默认池
        _remove_env_pool_key()

    def _apply(self):
        # 将友好名称转换回讯飞ID
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
        # 同步全局变量
        from claude_proxy import config
        config.AUTO_MODEL_POOL = list(models)
        # 持久化到 .env
        _write_env_pool_key(models)
        log(f"ProxyAutoModel 模型池已更新: {', '.join(models)}")
        messagebox.showinfo("成功", f"模型池已更新，共 {len(models)} 个模型")
        self.window.destroy()


def _write_env_pool_key(models):
    """将模型池配置持久化到 .env 文件"""
    if not ENV_FILE.exists():
        log("持久化: .env 文件不存在，跳过写入")
        return
    value = ",".join(models)
    try:
        existing_lines = ENV_FILE.read_text(encoding="utf-8-sig").splitlines()
        # 移除旧的 _ENV_POOL_KEY 行
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
