#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
启动相关：启动锁（防重复启动）、端口占用检测与处理、已有窗口查找、开机启动。
"""

import ctypes
import json
import os
import socket
import subprocess
import urllib.error
import urllib.request

from tkinter import messagebox
import tkinter as tk

# 防止重复启动的文件锁
_LOCK_FILE = None


def _acquire_startup_lock():
    """获取启动锁，防止重复启动多个实例"""
    global _LOCK_FILE
    import tempfile
    lock_path = os.path.join(tempfile.gettempdir(), "claude_proxy_gui.lock")
    try:
        # 如果文件已存在，说明已有实例在运行
        if os.path.exists(lock_path):
            # 检查对应的进程是否还在运行
            try:
                with open(lock_path, "r") as f:
                    pid_str = f.read().strip()
                    if pid_str:
                        pid = int(pid_str)
                        # 检查进程是否存在
                        kernel = ctypes.windll.kernel32
                        handle = kernel.OpenProcess(1, False, pid)  # 1 = PROCESS_TERMINATE
                        if handle:
                            kernel.CloseHandle(handle)
                            return False  # 进程仍在运行
            except (ValueError, OSError):
                pass

        # 写入当前进程PID
        with open(lock_path, "w") as f:
            f.write(str(os.getpid()))
        _LOCK_FILE = lock_path
        return True
    except OSError:
        return False


def _release_startup_lock():
    """释放启动锁"""
    global _LOCK_FILE
    if _LOCK_FILE and os.path.exists(_LOCK_FILE):
        try:
            os.remove(_LOCK_FILE)
        except OSError:
            pass
        _LOCK_FILE = None


def is_port_in_use(port):
    """检测端口是否被占用"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(('127.0.0.1', port))
            return False
        except OSError:
            return True


def get_process_using_port(port):
    """获取占用端口的进程信息 (PID, 名称)"""
    try:
        # 使用 netstat 查找占用端口的进程
        result = subprocess.run(
            ['netstat', '-ano', '-p', 'TCP'],
            capture_output=True, text=True, encoding='utf-8', errors='ignore'
        )
        for line in result.stdout.split('\n'):
            if f':{port}' in line and 'LISTENING' in line:
                parts = line.split()
                if len(parts) >= 5:
                    pid = parts[-1]
                    # 获取进程名
                    try:
                        proc_result = subprocess.run(
                            ['tasklist', '/FI', f'PID eq {pid}'],
                            capture_output=True, text=True, encoding='utf-8', errors='ignore'
                        )
                        for proc_line in proc_result.stdout.split('\n'):
                            if pid in proc_line and 'tasklist' not in proc_line.lower():
                                proc_name = proc_line.split()[0]
                                return int(pid), proc_name
                    except (OSError, ValueError, IndexError):
                        pass
                    return int(pid), "未知"
    except Exception:
        pass
    return None, None


def kill_process(pid):
    """强制结束进程"""
    try:
        subprocess.run(['taskkill', '/F', '/PID', str(pid)], capture_output=True)
        return True
    except Exception:
        return False


def is_another_instance_running(port):
    """通过专用健康端点识别本程序，避免把其他 HTTP 服务误判为重复实例。"""
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/__claude_proxy_health", method="GET"
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return response.status == 200 and payload.get("service") == "claude-proxy"
    except (OSError, ValueError, urllib.error.URLError, json.JSONDecodeError):
        return False


def show_port_dialog(port, pid, proc_name):
    """显示端口占用对话框，返回 (action, pid)
    action: 'kill' - 强制释放, 'exit' - 退出, 'continue' - 继续尝试
    """
    root = tk.Tk()
    root.withdraw()

    msg = f"端口 {port} 已被占用！\n\n"
    msg += f"进程: {proc_name}\n"
    msg += f"PID: {pid}\n\n"
    msg += "是否强制释放该端口？"

    result = messagebox.askyesnocancel(
        "端口占用",
        msg,
        icon='warning',
        detail="【是】强制结束占用进程\n【否】继续尝试启动（可能失败）\n【取消】退出程序"
    )
    root.destroy()

    if result is True:
        return 'kill', pid
    elif result is False:
        return 'continue', None
    else:
        return 'exit', None


def check_port_and_handle(port):
    """检测端口并处理占用情况
    返回: True - 可以继续启动, False - 应该退出
    """
    # 使用专用健康端点确认重复启动。
    if is_another_instance_running(port):
        return 'duplicate'

    # 检测端口是否被占用
    if not is_port_in_use(port):
        return 'ok'

    # 端口被占用，获取占用进程信息
    pid, proc_name = get_process_using_port(port)
    if pid is None:
        # 获取不到进程信息，直接返回继续
        return 'ok'

    action, target_pid = show_port_dialog(port, pid, proc_name)

    if action == 'kill':
        if kill_process(target_pid):
            # 等待端口释放
            import time
            for _ in range(10):
                if not is_port_in_use(port):
                    return 'ok'
                time.sleep(0.5)
            # 端口仍未释放
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("错误", "无法释放端口，请手动关闭占用程序后重试。")
            root.destroy()
            return 'exit'
        else:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("错误", "无法结束占用进程，请以管理员身份运行。")
            root.destroy()
            return 'exit'
    elif action == 'continue':
        return 'ok'
    else:
        return 'exit'


def find_existing_window():
    """查找已存在的代理窗口并显示它"""
    try:
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        # 获取当前进程ID
        current_pid = kernel32.GetCurrentProcessId()
        found_hwnd = None

        # 枚举所有窗口
        def enum_windows_proc(hwnd, lParam):
            nonlocal found_hwnd
            if not user32.IsWindowVisible(hwnd):
                return True

            # 获取窗口标题
            length = user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True

            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            title = buffer.value

            # 检查是否是 Claude Proxy 窗口
            if 'Claude Proxy' in title or '日志' in title:
                # 获取窗口所属进程
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

                # 只激活其他进程的窗口（不是当前进程）
                if pid.value != current_pid:
                    found_hwnd = hwnd
                    return False
            return True

        # 创建回调类型
        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        callback = EnumWindowsProc(enum_windows_proc)
        user32.EnumWindows(callback, 0)

        # 如果找到了窗口，激活它
        if found_hwnd:
            # 使用多种方法激活窗口
            user32.ShowWindow(found_hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(found_hwnd)
            user32.BringWindowToTop(found_hwnd)
            # 发送系统命令恢复窗口
            WM_SYSCOMMAND = 0x0112
            SC_RESTORE = 0xF120
            user32.SendMessageW(found_hwnd, WM_SYSCOMMAND, SC_RESTORE, 0)
            return True

    except Exception as e:
        print(f"查找窗口失败: {e}")
        pass

    return False


# ========== 开机启动 ==========

def get_startup_dir():
    """获取 Windows 启动文件夹路径"""
    return os.path.join(os.environ.get('APPDATA', ''),
                        'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup')


def get_startup_shortcut_path():
    """获取启动项快捷方式路径"""
    return os.path.join(get_startup_dir(), 'ClaudeProxyGUI.lnk')


def is_startup_enabled():
    """检查是否已设置为开机启动"""
    return os.path.exists(get_startup_shortcut_path())


def enable_startup():
    """设置开机启动（创建快捷方式到启动文件夹）"""
    import sys

    # 当前exe的路径
    exe_path = sys.executable if getattr(sys, 'frozen', False) else os.path.abspath(sys.argv[0])
    if not exe_path.endswith('.exe'):
        # 开发模式，使用python解释器
        return False

    shortcut_path = get_startup_shortcut_path()
    try:
        import pythoncom
        from win32com.client import Dispatch

        pythoncom.CoInitialize()
        shell = Dispatch('WScript.Shell')
        shortcut = shell.CreateShortCut(shortcut_path)
        shortcut.Targetpath = exe_path
        shortcut.WorkingDirectory = os.path.dirname(exe_path)
        shortcut.save()
        pythoncom.CoUninitialize()
        return True
    except Exception:
        return False


def disable_startup():
    """取消开机启动（删除启动文件夹中的快捷方式）"""
    shortcut_path = get_startup_shortcut_path()
    try:
        if os.path.exists(shortcut_path):
            os.remove(shortcut_path)
        return True
    except Exception:
        return False
