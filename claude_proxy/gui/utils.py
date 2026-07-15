#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GUI 通用工具。"""


def _center_window(window):
    """将窗口居中到屏幕中央"""
    window.update_idletasks()
    w = window.winfo_width()
    h = window.winfo_height()
    sw = window.winfo_screenwidth()
    sh = window.winfo_screenheight()
    x = (sw - w) // 2
    y = (sh - h) // 2
    window.geometry(f"+{x}+{y}")
