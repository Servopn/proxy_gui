#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Claude Code 代理服务 - 系统托盘 + 日志窗口版（薄入口）。

实际实现已拆分到 src/claude_proxy/ 包下，本文件仅作为 PyInstaller 打包入口
与开发运行入口。把 src/ 加入 sys.path 以便直接 python claude_proxy_gui.py 运行。
"""

import os
import sys

# 让未安装为包时也能直接运行本文件（开发模式 / onefile 解压临时目录）
_SRC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
if os.path.isdir(_SRC_DIR) and _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from claude_proxy.app import main  # noqa: E402


if __name__ == "__main__":
    main()
