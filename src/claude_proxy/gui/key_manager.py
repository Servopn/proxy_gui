#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""密钥管理窗口：查看当前密钥、解密新密钥、一键测试。"""

import json
import os
import queue
import urllib.error
import urllib.request

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

from claude_proxy import config
from claude_proxy.config import ENV_FILE, XUNFEI_BASE_URL
from claude_proxy.gui.utils import _center_window
from claude_proxy.logger import log


class KeyManagerWindow:
    def __init__(self, parent):
        self.window = tk.Toplevel(parent)
        self.window.title("密钥管理")
        self.window.geometry("900x700")
        self.window.transient(parent)
        _center_window(self.window)
        self.window.grab_set()

        # 创建Notebook标签页
        self.notebook = ttk.Notebook(self.window)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 标签页1: 当前已应用密钥
        self.tab_current = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_current, text="当前已应用密钥")
        self._build_current_tab()

        # 标签页2: 解密新密钥
        self.tab_decrypt = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_decrypt, text="解密新密钥")
        self._build_decrypt_tab()

        # 标签页3: 一键测试
        self.tab_test = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_test, text="一键测试所有密钥")
        self._build_test_tab()

        self.decrypted_keys = {}  # id -> key

    def _build_current_tab(self):
        """构建当前已应用密钥标签页"""
        ttk.Label(self.tab_current, text="当前系统已应用的密钥:").pack(anchor=tk.W, padx=10, pady=5)

        # 创建表格
        columns = ('id', 'name', 'key_preview', 'status')
        self.current_tree = ttk.Treeview(self.tab_current, columns=columns, show='headings')
        self.current_tree.heading('id', text='ID')
        self.current_tree.heading('name', text='名称')
        self.current_tree.heading('key_preview', text='密钥预览')
        self.current_tree.heading('status', text='状态')
        self.current_tree.column('id', width=50)
        self.current_tree.column('name', width=80)
        self.current_tree.column('key_preview', width=300)
        self.current_tree.column('status', width=80)

        scrollbar = ttk.Scrollbar(self.tab_current, orient=tk.VERTICAL, command=self.current_tree.yview)
        self.current_tree.configure(yscrollcommand=scrollbar.set)

        self.current_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=5)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 刷新按钮
        ttk.Button(self.tab_current, text="刷新", command=self._refresh_current_keys).pack(pady=5)

        self._refresh_current_keys()

    def _refresh_current_keys(self):
        """刷新当前已应用密钥列表"""
        for item in self.current_tree.get_children():
            self.current_tree.delete(item)

        for ch in config.CHANNELS:
            ch_id = str(ch['id'])
            name = ch['name']
            key = ch['key']
            key_preview = key[:20] + "..." if len(key) > 20 else key
            self.current_tree.insert('', tk.END, values=(ch_id, name, key_preview, '已应用'))

    def _test_current_keys(self):
        """在后台并发测试密钥，所有 Tk 操作只在主线程执行。"""
        import concurrent.futures

        def test_single_channel(ch):
            ch_id = str(ch["id"])
            name = ch["name"]
            try:
                headers = {
                    "Content-Type": "application/json",
                    "x-api-key": ch["key"],
                    "anthropic-version": "2023-06-01",
                    "User-Agent": "claude-proxy/2.0",
                }
                body = json.dumps({
                    "model": "xopkimik26",
                    "messages": [{"role": "user", "content": "Hello"}],
                    "max_tokens": 5,
                }).encode("utf-8")
                request = urllib.request.Request(
                    XUNFEI_BASE_URL + "/v1/messages",
                    data=body,
                    headers=headers,
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=10):
                    return f"✅ {name} ({ch_id}): 可用"
            except urllib.error.HTTPError as exc:
                if exc.code in (429, 503):
                    return f"✅ {name} ({ch_id}): 已认证，服务繁忙 ({exc.code})"
                return f"❌ {name} ({ch_id}): HTTP {exc.code}"
            except Exception as exc:
                return f"❌ {name} ({ch_id}): {type(exc).__name__}: {str(exc)[:50]}"

        progress_window = tk.Toplevel(self.window)
        progress_window.title("测试进度")
        progress_window.geometry("400x110")
        _center_window(progress_window)
        progress_window.transient(self.window)
        progress_window.protocol("WM_DELETE_WINDOW", lambda: None)
        progress_label = ttk.Label(progress_window, text="正在测试密钥...")
        progress_label.pack(pady=10)
        progress_bar = ttk.Progressbar(
            progress_window, mode="determinate", maximum=len(config.CHANNELS)
        )
        progress_bar.pack(fill=tk.X, padx=20, pady=10)

        result_queue = queue.Queue()
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=5)
        for channel in list(config.CHANNELS):
            future = executor.submit(test_single_channel, channel.copy())
            future.add_done_callback(
                lambda completed: result_queue.put(completed.result())
            )
        executor.shutdown(wait=False)
        results = []

        def poll_results():
            try:
                while True:
                    results.append(result_queue.get_nowait())
            except queue.Empty:
                pass
            progress_bar["value"] = len(results)
            progress_label.config(text=f"已完成 {len(results)}/{len(config.CHANNELS)}")
            if len(results) < len(config.CHANNELS):
                progress_window.after(100, poll_results)
                return
            progress_window.destroy()
            result_window = tk.Toplevel(self.window)
            result_window.title("测试结果")
            result_window.geometry("600x400")
            _center_window(result_window)
            text = scrolledtext.ScrolledText(result_window, font=("Consolas", 9))
            text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
            text.insert(tk.END, "\n".join(sorted(results)))

        progress_window.after(100, poll_results)

    def _build_decrypt_tab(self):
        """构建解密新密钥标签页"""
        # 密码输入
        pwd_frame = ttk.Frame(self.tab_decrypt)
        pwd_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(pwd_frame, text="解密密码:").pack(side=tk.LEFT)
        self.pwd_var = tk.StringVar()
        ttk.Entry(pwd_frame, textvariable=self.pwd_var, show="*", width=50).pack(side=tk.LEFT, padx=5)
        ttk.Button(pwd_frame, text="解密", command=self.decrypt_keys).pack(side=tk.LEFT, padx=5)

        # 待解密列表输入
        ttk.Label(self.tab_decrypt, text="待解密列表 (格式: id,name,encrypted_key 每行一个):").pack(anchor=tk.W, padx=10, pady=2)
        self.input_text = scrolledtext.ScrolledText(self.tab_decrypt, height=10, font=('Consolas', 9))
        self.input_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # 结果输出
        ttk.Label(self.tab_decrypt, text="结果:").pack(anchor=tk.W, padx=10, pady=2)
        self.output_text = scrolledtext.ScrolledText(self.tab_decrypt, height=10, font=('Consolas', 9))
        self.output_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        action_frame = ttk.Frame(self.tab_decrypt)
        action_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Button(action_frame, text="应用到渠道并保存 .env", command=self.apply_to_channels).pack(side=tk.LEFT, padx=3)
        ttk.Button(action_frame, text="清空", command=self.clear_all).pack(side=tk.LEFT, padx=3)

    def _build_test_tab(self):
        """构建一键测试标签页"""
        ttk.Label(self.tab_test, text="一键测试所有当前已应用的密钥").pack(pady=10)
        ttk.Button(self.tab_test, text="开始测试", command=self._test_current_keys).pack(pady=10)

        ttk.Label(self.tab_test, text="说明: 测试会向每个密钥发送一个轻量请求，验证密钥是否可用。").pack(pady=5)
        ttk.Label(self.tab_test, text="503/429 表示密钥有效但模型繁忙，其他错误表示密钥可能已失效。").pack(pady=5)

    def decrypt_api_key(self, encrypted_b64, password):
        import hashlib
        import base64
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        key = hashlib.sha256(password.encode('utf-8')).digest()[:16]
        data = base64.b64decode(encrypted_b64)
        iv = data[:12]
        ciphertext = data[12:]
        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(iv, ciphertext, None)
        return plaintext.decode('utf-8')

    def decrypt_keys(self):
        password = self.pwd_var.get().strip()
        if not password:
            messagebox.showwarning("警告", "请输入解密密码")
            return

        lines = self.input_text.get(1.0, tk.END).strip().split('\n')
        self.decrypted_keys = {}
        results = []

        for line in lines:
            line = line.strip()
            if not line:
                continue
            parts = line.split(',')
            if len(parts) >= 3:
                id, name, encrypted = parts[0], parts[1], parts[2]
                try:
                    key = self.decrypt_api_key(encrypted, password)
                    self.decrypted_keys[id] = key
                    results.append(f"✅ {id} ({name}): {key}")
                except Exception as e:
                    results.append(f"❌ {id} ({name}): 解密失败 - {e}")
            else:
                results.append(f"⚠️  格式错误: {line}")

        self.output_text.delete(1.0, tk.END)
        self.output_text.insert(tk.END, '\n'.join(results))

    def test_all_keys(self):
        """测试所有密钥（兼容旧版本）"""
        self._test_current_keys()

    def apply_to_channels(self):
        if not self.decrypted_keys:
            messagebox.showwarning("警告", "请先解密密钥")
            return

        # 更新全局 CHANNELS
        updated = 0
        for ch in config.CHANNELS:
            ch_id = str(ch['id'])
            if ch_id in self.decrypted_keys:
                ch['key'] = self.decrypted_keys[ch_id]
                updated += 1

        env_values = {ch["env"]: ch["key"] for ch in config.CHANNELS}
        existing_lines = ENV_FILE.read_text(encoding="utf-8-sig").splitlines()
        preserved = [
            line for line in existing_lines
            if not any(line.lstrip().startswith(name + "=") for name in env_values)
        ]
        preserved.extend(f"{name}={value}" for name, value in env_values.items())
        temp_path = ENV_FILE.with_name(".env.tmp")
        temp_path.write_text("\n".join(preserved) + "\n", encoding="utf-8")
        os.replace(temp_path, ENV_FILE)
        for ch in config.CHANNELS:
            os.environ[ch["env"]] = ch["key"]

        messagebox.showinfo("成功", f"已更新 {updated} 个渠道的密钥并保存到 .env")
        log(f"密钥管理: 已更新 {updated} 个渠道的密钥")
        self._refresh_current_keys()

    def clear_all(self):
        self.input_text.delete(1.0, tk.END)
        self.output_text.delete(1.0, tk.END)
        self.decrypted_keys = {}
