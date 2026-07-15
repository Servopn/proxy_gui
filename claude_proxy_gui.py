#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Claude Code 代理服务 - 系统托盘 + 日志窗口版（薄入口）。

实际实现已拆分到 claude_proxy/ 包下，本文件仅作为 PyInstaller 打包入口
与开发运行入口。
"""

from claude_proxy.app import main


if __name__ == "__main__":
    main()