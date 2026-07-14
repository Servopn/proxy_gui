#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日志：线程安全的日志队列 + 文件写入。GUI 主线程通过队列消费日志显示。
"""

import datetime
import queue
import threading

log_queue = queue.Queue(maxsize=1000)

# 日志文件路径（程序启动时设置）
_log_file = None
_log_lock = threading.Lock()


def set_log_file(filepath):
    """设置日志文件路径"""
    global _log_file
    _log_file = filepath


def log(msg):
    """添加日志到队列，同时写入文件"""
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    line = f"[{timestamp}] {msg}"
    try:
        log_queue.put_nowait(line)
    except queue.Full:
        pass
    # 写入日志文件
    global _log_file
    if _log_file:
        try:
            with _log_lock:
                with open(_log_file, 'a', encoding='utf-8') as f:
                    f.write(line + '\n')
        except OSError:
            pass
