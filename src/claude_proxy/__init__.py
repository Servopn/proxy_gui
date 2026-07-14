#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Claude Code 代理服务 - 系统托盘 + 日志窗口版
架构: tkinter主线程 + pystray后台线程

模块化拆分后的包入口。实际启动逻辑在 app.main()。
"""

from claude_proxy.config import get_app_dir  # noqa: F401

__all__ = ["get_app_dir"]
