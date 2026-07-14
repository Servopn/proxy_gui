#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Claude Code 代理服务 - 系统托盘 + 日志窗口版
架构: tkinter主线程 + pystray后台线程
"""

import sys
import os
import json
import threading
import urllib.request
import urllib.error
import http.server
import socketserver
import datetime
import queue
import time
import tkinter as tk
from tkinter import ttk, scrolledtext
import pystray
from PIL import Image
import http.client
import socket
import ssl
import subprocess
import ctypes
from pathlib import Path
from tkinter import messagebox, simpledialog


def get_app_dir():
    """返回脚本或打包后可执行文件所在目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def load_env_file(path):
    """加载简单 KEY=VALUE 文件，不覆盖进程中显式设置的环境变量。"""
    path = Path(path)
    if not path.is_file():
        raise RuntimeError(f"缺少密钥配置文件: {path}")
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not key.strip():
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


ENV_FILE = get_app_dir() / ".env"
load_env_file(ENV_FILE)

# 讯飞 MaaS API 配置
XUNFEI_BASE_URL = "https://maas-coding-api.cn-huabei-1.xf-yun.com/anthropic"
XUNFEI_HOST = "maas-coding-api.cn-huabei-1.xf-yun.com"

# 503 重试配置（可动态调整）
DEFAULT_MAX_RETRY_CHANNELS = 8
MAX_RETRY_CHANNELS = DEFAULT_MAX_RETRY_CHANNELS


def set_max_retry_channels(n):
    """设置 503 重试时的最大渠道轮换数"""
    global MAX_RETRY_CHANNELS
    MAX_RETRY_CHANNELS = max(1, min(int(n), len(CHANNELS)))
    log(f"503 最大重试渠道数已设置为: {MAX_RETRY_CHANNELS}")


def get_max_retry_channels():
    """获取当前 503 最大重试渠道数"""
    return MAX_RETRY_CHANNELS


# 连接池配置（可动态调整）
DEFAULT_MAX_POOL_SIZE = 10
MAX_POOL_SIZE = DEFAULT_MAX_POOL_SIZE
CONNECTION_TIMEOUT = 300.0

_conn_pool = []
_conn_lock = threading.Lock()


def _close_connection(conn):
    try:
        conn.close()
    except Exception:
        pass


def _get_connection():
    """从连接池获取连接，并恢复正常请求超时。"""
    with _conn_lock:
        while _conn_pool:
            conn = _conn_pool.pop()
            try:
                if conn.sock is None or conn.sock.fileno() < 0:
                    raise OSError("连接已关闭")
                conn.sock.settimeout(CONNECTION_TIMEOUT)
                return conn
            except (AttributeError, OSError):
                _close_connection(conn)

    context = ssl.create_default_context()
    return http.client.HTTPSConnection(
        XUNFEI_HOST, context=context, timeout=CONNECTION_TIMEOUT
    )


def _return_connection(conn):
    """将仍可复用的连接归还连接池。"""
    with _conn_lock:
        if conn.sock is not None and len(_conn_pool) < MAX_POOL_SIZE:
            try:
                conn.sock.settimeout(CONNECTION_TIMEOUT)
                _conn_pool.append(conn)
                return
            except OSError:
                pass
    _close_connection(conn)


def _release_connection(conn, response=None):
    """完整读取响应后，仅在上游允许复用时归还连接。"""
    if conn is None:
        return
    try:
        reusable = (
            response is not None
            and not response.will_close
            and conn.sock is not None
            and conn.sock.fileno() >= 0
        )
    except (AttributeError, OSError):
        reusable = False
    if reusable:
        _return_connection(conn)
    else:
        _close_connection(conn)


def close_connection_pool():
    with _conn_lock:
        connections = list(_conn_pool)
        _conn_pool.clear()
    for conn in connections:
        _close_connection(conn)


def set_max_pool_size(size):
    """设置连接池大小，并立即清理超出的空闲连接。"""
    global MAX_POOL_SIZE
    new_size = max(1, int(size))
    with _conn_lock:
        MAX_POOL_SIZE = new_size
        extra = []
        while len(_conn_pool) > MAX_POOL_SIZE:
            extra.append(_conn_pool.pop())
    for conn in extra:
        _close_connection(conn)
    log(f"连接池大小已设置为: {MAX_POOL_SIZE}")


def get_max_pool_size():
    return MAX_POOL_SIZE


def _make_request(method, path, body=None, headers=None):
    """使用连接池发送并完整读取 HTTP 响应。"""
    conn = None
    response = None
    try:
        conn = _get_connection()
        conn.request(method, path, body=body, headers=headers or {})
        response = conn.getresponse()
        status = response.status
        response_headers = response.getheaders()
        response_body = response.read()
        _release_connection(conn, response)
        conn = None
        return status, response_headers, response_body
    except Exception:
        if conn is not None:
            _close_connection(conn)
        raise


def _make_request_stream(method, path, body=None, headers=None):
    """使用连接池发送请求，响应读取完毕后由调用者释放连接。"""
    conn = None
    try:
        conn = _get_connection()
        conn.request(method, path, body=body, headers=headers or {})
        return conn, conn.getresponse()
    except Exception:
        if conn is not None:
            _close_connection(conn)
        raise

CHANNELS = [
    {'id': 50, 'name': '11xfd', 'env': 'CLAUDE_PROXY_CHANNEL_50_KEY', 'key': os.environ.get('CLAUDE_PROXY_CHANNEL_50_KEY', '')},
    {'id': 51, 'name': '12xfg', 'env': 'CLAUDE_PROXY_CHANNEL_51_KEY', 'key': os.environ.get('CLAUDE_PROXY_CHANNEL_51_KEY', '')},
    {'id': 54, 'name': '13xfg', 'env': 'CLAUDE_PROXY_CHANNEL_54_KEY', 'key': os.environ.get('CLAUDE_PROXY_CHANNEL_54_KEY', '')},
    {'id': 55, 'name': '14xfg', 'env': 'CLAUDE_PROXY_CHANNEL_55_KEY', 'key': os.environ.get('CLAUDE_PROXY_CHANNEL_55_KEY', '')},
    {'id': 56, 'name': '15xfk', 'env': 'CLAUDE_PROXY_CHANNEL_56_KEY', 'key': os.environ.get('CLAUDE_PROXY_CHANNEL_56_KEY', '')},
    {'id': 57, 'name': '16xfd', 'env': 'CLAUDE_PROXY_CHANNEL_57_KEY', 'key': os.environ.get('CLAUDE_PROXY_CHANNEL_57_KEY', '')},
    {'id': 58, 'name': '17xfd', 'env': 'CLAUDE_PROXY_CHANNEL_58_KEY', 'key': os.environ.get('CLAUDE_PROXY_CHANNEL_58_KEY', '')},
    {'id': 59, 'name': '18xfg', 'env': 'CLAUDE_PROXY_CHANNEL_59_KEY', 'key': os.environ.get('CLAUDE_PROXY_CHANNEL_59_KEY', '')},
    {'id': 63, 'name': '19xfd', 'env': 'CLAUDE_PROXY_CHANNEL_63_KEY', 'key': os.environ.get('CLAUDE_PROXY_CHANNEL_63_KEY', '')},
    {'id': 64, 'name': '20xfg2', 'env': 'CLAUDE_PROXY_CHANNEL_64_KEY', 'key': os.environ.get('CLAUDE_PROXY_CHANNEL_64_KEY', '')},
    {'id': 65, 'name': '21xfk', 'env': 'CLAUDE_PROXY_CHANNEL_65_KEY', 'key': os.environ.get('CLAUDE_PROXY_CHANNEL_65_KEY', '')},
    {'id': 66, 'name': '22xfk', 'env': 'CLAUDE_PROXY_CHANNEL_66_KEY', 'key': os.environ.get('CLAUDE_PROXY_CHANNEL_66_KEY', '')},
    {'id': 67, 'name': '23xfg2', 'env': 'CLAUDE_PROXY_CHANNEL_67_KEY', 'key': os.environ.get('CLAUDE_PROXY_CHANNEL_67_KEY', '')},
    {'id': 68, 'name': '24xfg2', 'env': 'CLAUDE_PROXY_CHANNEL_68_KEY', 'key': os.environ.get('CLAUDE_PROXY_CHANNEL_68_KEY', '')},
    {'id': 72, 'name': '25xfk', 'env': 'CLAUDE_PROXY_CHANNEL_72_KEY', 'key': os.environ.get('CLAUDE_PROXY_CHANNEL_72_KEY', '')},
    {'id': 73, 'name': '26xfk', 'env': 'CLAUDE_PROXY_CHANNEL_73_KEY', 'key': os.environ.get('CLAUDE_PROXY_CHANNEL_73_KEY', '')},
]

missing_channel_keys = [ch['env'] for ch in CHANNELS if not ch['key']]
if missing_channel_keys:
    raise RuntimeError('缺少渠道密钥环境变量: ' + ', '.join(missing_channel_keys))

MODEL_MAP = {
    # Claude Code 默认模型 -> 讯飞模型
    "claude-sonnet-4-20250514": "xopdeepseekv4pro",
    "claude-sonnet-4": "xopdeepseekv4pro",
    "claude-opus-4": "xopdeepseekv4pro",
    "claude-haiku-4": "xopdeepseekv4pro",
    "astron-code-latest": "xopdeepseekv4pro",
    # 用户选择模型 -> 讯飞模型
    "Spark X2 Agent": "xsparkx2agent",
    "Spark X2": "xsparkx2",
    "Spark-X2-Flash": "xsparkx2flash",
    "Auto": "auto",
    "GLM-5.2": "xopglm52",
    "GLM-5.1": "xopglm51",
    "GLM-5": "xopglm5",
    "DeepSeek-V4-Pro": "xopdeepseekv4pro",
    "DeepSeek-V4-Flash": "xopdeepseekv4flash",
    "DeepSeek-V3.2": "xopdeepseekv32",
    "Kimi-K2.6": "xopkimik26",
    "KiMi-K2.5": "xopkimik25",
    "MiniMax-M2.5": "xminimaxm25",
    "Qwen3.5-397B-A17B": "xopqwen35397b",
    "Qwen3.6-35B-A3B": "xopqwen36v35b",
    "Qwen3.5-35B-A3B": "xopqwen35v35b",
    "Qwen3-Coder-Next-FP8": "xop3qwencodernext",
    "GLM-4.7-Flash": "xopglmv47flash",
}

# 讯飞模型ID -> 用户友好名称（反向映射，取第一个出现的友好名）
MODEL_FRIENDLY_NAMES = {
    "xsparkx2agent": "Spark X2 Agent",
    "xsparkx2": "Spark X2",
    "xsparkx2flash": "Spark-X2-Flash",
    "auto": "Auto",
    "xopglm52": "GLM-5.2",
    "xopglm51": "GLM-5.1",
    "xopglm5": "GLM-5",
    "xopdeepseekv4pro": "DeepSeek-V4-Pro",
    "xopdeepseekv4flash": "DeepSeek-V4-Flash",
    "xopdeepseekv32": "DeepSeek-V3.2",
    "xopkimik26": "Kimi-K2.6",
    "xopkimik25": "KiMi-K2.5",
    "xminimaxm25": "MiniMax-M2.5",
    "xopqwen35397b": "Qwen3.5-397B-A17B",
    "xopqwen36v35b": "Qwen3.6-35B-A3B",
    "xopqwen35v35b": "Qwen3.5-35B-A3B",
    "xop3qwencodernext": "Qwen3-Coder-Next-FP8",
    "xopglmv47flash": "GLM-4.7-Flash",
}

# 用户可选的模型列表（友好名称）
USER_MODEL_LIST = [
    "DeepSeek-V4-Pro",
    "DeepSeek-V4-Flash",
    "DeepSeek-V3.2",
    "Spark X2 Agent",
    "Spark X2",
    "Spark-X2-Flash",
    "GLM-5.2",
    "GLM-5.1",
    "GLM-5",
    "Kimi-K2.6",
    "KiMi-K2.5",
    "MiniMax-M2.5",
    "Qwen3.5-397B-A17B",
    "Qwen3.6-35B-A3B",
    "Qwen3.5-35B-A3B",
    "Qwen3-Coder-Next-FP8",
    "GLM-4.7-Flash",
]


class ChannelPool:
    # 动态切换阈值
    WARMUP_REQUESTS = 30          # 全局前30个请求后启用评分
    MIN_CHANNEL_REQUESTS = 5      # 单个渠道至少5个请求后才参与评分
    SCORE_THRESHOLD = 0.6         # 评分低于0.6回到轮询
    COOLDOWN_CHANNELS = 10        # 冷却超过10个渠道也回到轮询

    def __init__(self):
        self.channels = CHANNELS
        self.lock = threading.Lock()
        self.index = 0
        self.mode = "round_robin"  # round_robin | scoring
        self.total_requests = 0
        self.total_attempts = 0
        self.client_errors = 0
        self.stats = {}
        self._reset_stats()

    def _reset_stats(self):
        for c in self.channels:
            cid = c["id"]
            if cid not in self.stats:
                self.stats[cid] = {
                    "requests": 0, "errors": 0, "success": 0,
                    "input_tokens": 0, "output_tokens": 0,
                    "consecutive_errors": 0, "score": 1.0,
                    "cooldown_until": 0,  # 冷却到什么时候
                }

    def _update_score(self, ch_id):
        """根据成功率计算评分"""
        s = self.stats[ch_id]
        total = s["requests"]
        if total < self.MIN_CHANNEL_REQUESTS:
            s["score"] = 1.0  # 数据不足，默认满分
        else:
            success_rate = s["success"] / max(total, 1)
            s["score"] = success_rate
        return s["score"]

    def _should_use_scoring(self):
        """判断是否应该使用评分模式"""
        if self.total_attempts < self.WARMUP_REQUESTS:
            return False

        # 统计冷却中的渠道数量
        now = time.time()
        cooldown_count = sum(1 for s in self.stats.values()
                           if s["cooldown_until"] > now)
        if cooldown_count > self.COOLDOWN_CHANNELS:
            return False  # 太多渠道冷却，退回轮询

        # 计算平均分
        scores = [s["score"] for s in self.stats.values()]
        avg_score = sum(scores) / len(scores) if scores else 1.0
        if avg_score < self.SCORE_THRESHOLD:
            return False  # 平均分太低，退回轮询

        return True

    def get_channel(self):
        with self.lock:
            now = time.time()

            if self._should_use_scoring():
                self.mode = "scoring"
                # 按评分排序，过滤掉冷却中的渠道
                scored = []
                for ch in self.channels:
                    cid = ch["id"]
                    if self.stats[cid]["cooldown_until"] > now:
                        continue  # 跳过冷却中的渠道
                    scored.append((self.stats[cid]["score"], ch))

                if not scored:
                    # 全部冷却，用轮询
                    scored = [(1.0, ch) for ch in self.channels]

                scored.sort(key=lambda x: x[0], reverse=True)
                # 评分最高的一批渠道中随机选一个
                top_score = scored[0][0]
                top_channels = [ch for score, ch in scored if score == top_score]
                ch = top_channels[self.index % len(top_channels)]
                self.index += 1
            else:
                self.mode = "round_robin"
                now = time.time()
                # 轮询时也跳过冷却中的渠道
                for _ in range(len(self.channels)):
                    ch = self.channels[self.index]
                    self.index = (self.index + 1) % len(self.channels)
                    if self.stats[ch["id"]]["cooldown_until"] <= now:
                        break

            return ch["key"], ch["name"], ch["id"]

    def skip_to_next(self):
        """跳过一个渠道（503重试用）"""
        with self.lock:
            self.index = (self.index + 1) % len(self.channels)

    def record_client_request(self):
        with self.lock:
            self.total_requests += 1

    def record_client_error(self):
        with self.lock:
            self.client_errors += 1

    def record_success(self, ch_id, input_tokens, output_tokens):
        with self.lock:
            self.total_attempts += 1
            s = self.stats[ch_id]
            s["requests"] += 1
            s["success"] += 1
            s["input_tokens"] += input_tokens
            s["output_tokens"] += output_tokens
            s["consecutive_errors"] = 0
            s["cooldown_until"] = 0  # 清除冷却
            self._update_score(ch_id)

    def record_error(self, ch_id):
        with self.lock:
            self.total_attempts += 1
            s = self.stats[ch_id]
            s["requests"] += 1
            s["errors"] += 1
            s["consecutive_errors"] += 1
            # 连续2次以上错误，冷却30秒
            if s["consecutive_errors"] >= 2:
                s["cooldown_until"] = time.time() + 30
            self._update_score(ch_id)

    def get_stats(self):
        with self.lock:
            channels_data = []
            for ch in self.channels:
                cid = ch["id"]
                s = self.stats[cid]
                total = s["requests"]
                success_rate = f"{s['success']/max(total,1)*100:.1f}%" if total > 0 else "-"
                channels_data.append({
                    "id": cid,
                    "name": ch["name"],
                    "requests": total,
                    "success": s["success"],
                    "errors": s["errors"],
                    "success_rate": success_rate,
                    "score": f"{s['score']:.2f}",
                    "input_tokens": s["input_tokens"],
                    "output_tokens": s["output_tokens"],
                    "mode": self.mode,
                })
            return {
                "total_requests": self.total_requests,
                "total_attempts": self.total_attempts,
                "mode": self.mode,
                "total_errors": self.client_errors,
                "total_channel_errors": sum(s["errors"] for s in self.stats.values()),
                "total_input_tokens": sum(s["input_tokens"] for s in self.stats.values()),
                "total_output_tokens": sum(s["output_tokens"] for s in self.stats.values()),
                "channels": channels_data,
            }


pool = ChannelPool()

# ========== 模型自动选择池 ==========
# ProxyAutoModel: 虚拟模型名，请求此模型时由系统自动选择实际模型
# 按模型维度评分，而非渠道维度

# 默认参与自动选择的模型池（用户可在GUI中配置）
DEFAULT_AUTO_MODEL_POOL = [
    "xopdeepseekv4pro",
    "xopdeepseekv4flash",
    "xopdeepseekv32",
    "xopkimik26",
    "xopkimik25",
    "xopglm52",
    "xopqwen35397b",
    "xop3qwencodernext",
]

AUTO_MODEL_POOL = list(DEFAULT_AUTO_MODEL_POOL)


class ModelPool:
    """模型评分池 - 按模型维度追踪成功/失败率，用于 ProxyAutoModel 自动选择"""

    WARMUP_REQUESTS = 10
    MIN_MODEL_REQUESTS = 3
    COOLDOWN_SECONDS = 60  # 模型冷却时间（比渠道长，因为模型故障更可能是持续性的）

    def __init__(self, models=None):
        self.models = models or list(AUTO_MODEL_POOL)
        self.lock = threading.Lock()
        self.index = 0
        self.total_requests = 0
        self.stats = {}
        self._reset_stats()

    def _reset_stats(self):
        for m in self.models:
            if m not in self.stats:
                self.stats[m] = {
                    "requests": 0, "errors": 0, "success": 0,
                    "consecutive_errors": 0, "score": 1.0,
                    "cooldown_until": 0,
                }

    def _update_score(self, model):
        s = self.stats[model]
        total = s["requests"]
        if total < self.MIN_MODEL_REQUESTS:
            s["score"] = 1.0
        else:
            s["score"] = s["success"] / max(total, 1)
        return s["score"]

    def get_model(self):
        """获取当前最优模型，跳过冷却中的"""
        with self.lock:
            now = time.time()
            # 先尝试按评分选
            if self.total_requests >= self.WARMUP_REQUESTS:
                scored = []
                for m in self.models:
                    s = self.stats.get(m)
                    if not s:
                        continue
                    if s["cooldown_until"] > now:
                        continue
                    scored.append((s["score"], m))
                if scored:
                    scored.sort(key=lambda x: x[0], reverse=True)
                    # 从评分最高的一批中轮询
                    top_score = scored[0][0]
                    top_models = [m for score, m in scored if score == top_score]
                    m = top_models[self.index % len(top_models)]
                    self.index += 1
                    return m

            # 评分不足或全部冷却，轮询
            for _ in range(len(self.models)):
                m = self.models[self.index % len(self.models)]
                self.index += 1
                s = self.stats.get(m)
                if not s or s["cooldown_until"] <= now:
                    return m
            # 全部冷却，返回第一个
            return self.models[0]

    def skip_to_next(self):
        with self.lock:
            self.index = (self.index + 1) % len(self.models)

    def record_success(self, model):
        with self.lock:
            self.total_requests += 1
            if model in self.stats:
                s = self.stats[model]
                s["requests"] += 1
                s["success"] += 1
                s["consecutive_errors"] = 0
                s["cooldown_until"] = 0
                self._update_score(model)

    def record_error(self, model):
        with self.lock:
            self.total_requests += 1
            if model in self.stats:
                s = self.stats[model]
                s["requests"] += 1
                s["errors"] += 1
                s["consecutive_errors"] += 1
                if s["consecutive_errors"] >= 2:
                    s["cooldown_until"] = time.time() + self.COOLDOWN_SECONDS
                self._update_score(model)

    def get_stats(self):
        with self.lock:
            result = []
            for m in self.models:
                s = self.stats.get(m, {})
                total = s.get("requests", 0)
                success_rate = f"{s.get('success',0)/max(total,1)*100:.1f}%" if total > 0 else "-"
                result.append({
                    "model": m,
                    "requests": total,
                    "success": s.get("success", 0),
                    "errors": s.get("errors", 0),
                    "success_rate": success_rate,
                    "score": f"{s.get('score', 1.0):.2f}",
                    "cooldown": "冷却中" if s.get("cooldown_until", 0) > time.time() else "正常",
                })
            return result

    def set_models(self, model_list):
        """更新模型池"""
        with self.lock:
            self.models = list(model_list)
            self._reset_stats()
            self.index = 0


model_pool = ModelPool()

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


class RequestBodyTooLarge(Exception):
    pass


class ClientDisconnected(Exception):
    pass


MAX_REQUEST_BODY = 32 * 1024 * 1024
MAX_USAGE_CAPTURE = 4 * 1024 * 1024
HOP_BY_HOP_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade",
}


def _extract_usage(payload):
    """从普通 JSON 或 Anthropic SSE 响应中提取 token 用量。"""
    input_tokens = 0
    output_tokens = 0

    def visit(value):
        nonlocal input_tokens, output_tokens
        if isinstance(value, dict):
            usage = value.get("usage")
            if isinstance(usage, dict):
                try:
                    input_tokens = max(input_tokens, int(usage.get("input_tokens", 0) or 0))
                    output_tokens = max(output_tokens, int(usage.get("output_tokens", 0) or 0))
                except (TypeError, ValueError):
                    pass
            for child in value.values():
                if isinstance(child, (dict, list)):
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    try:
        visit(json.loads(payload.decode("utf-8")))
        return input_tokens, output_tokens
    except (UnicodeDecodeError, json.JSONDecodeError):
        pass

    for raw_line in payload.splitlines():
        line = raw_line.strip()
        if not line.startswith(b"data:"):
            continue
        data = line[5:].strip()
        if not data or data == b"[DONE]":
            continue
        try:
            visit(json.loads(data.decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    return input_tokens, output_tokens


class ProxyHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        pass

    def _send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/__claude_proxy_health":
            self._send_json(200, {"service": "claude-proxy", "status": "ok"})
        elif self.path in ("/anthropic", "/anthropic/", "/", "/oneapi", "/oneapi/"):
            self._handle_test()
        elif self.path.split("?", 1)[0].endswith(("/v1/models", "/models")):
            self._handle_models()
        elif self.path.split("?", 1)[0].endswith(("/v1/usage", "/usage", "/api/usage")):
            self._handle_usage()
        else:
            self._proxy_request("GET")

    def do_POST(self):
        if self.path.split("?", 1)[0].endswith("/api/usage"):
            self._handle_usage()
        else:
            self._proxy_request("POST")

    def do_OPTIONS(self):
        self._proxy_request("OPTIONS")

    def _handle_test(self):
        test_key = CHANNELS[0]["key"] if CHANNELS else ""
        conn = None
        response = None
        try:
            conn = _get_connection()
            conn.request("GET", "/anthropic/v1/models", headers={
                "Host": XUNFEI_HOST,
                "User-Agent": "claude-proxy/2.0",
                "x-api-key": test_key,
            })
            response = conn.getresponse()
            response_body = response.read()
            status = response.status
            _release_connection(conn, response)
            conn = None
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response_body)))
            self.end_headers()
            self.wfile.write(response_body)
            log(f"TEST client={self.client_address[0]} status={status} pool=ok")
        except Exception as exc:
            if conn is not None:
                _close_connection(conn)
            self._send_json(503, {"status": "unavailable", "pool": "failed"})
            log(f"TEST client={self.client_address[0]} pool=failed: {str(exc)[:80]}")

    def _handle_models(self):
        user_models = ["ProxyAutoModel"] + USER_MODEL_LIST + ["Auto"]
        self._send_json(200, {
            "object": "list",
            "data": [
                {"id": model, "object": "model", "type": "claude", "display_name": model}
                for model in user_models
            ],
        })

    def _handle_usage(self):
        stats = pool.get_stats()
        total_requests = stats["total_requests"]
        total_errors = stats["total_errors"]
        self._send_json(200, {
            "balance": float(total_requests),
            "unit": "requests",
            "total": float(total_requests),
            "used": float(total_errors),
            "planName": f"Pool {len(CHANNELS)}ch | {total_requests}req",
            "extra": (
                f"req:{total_requests} attempts:{stats['total_attempts']} "
                f"err:{total_errors} in:{stats['total_input_tokens']} "
                f"out:{stats['total_output_tokens']}"
            ),
        })

    def _read_request_body(self):
        transfer_encoding = self.headers.get("Transfer-Encoding", "").lower()
        if "chunked" in transfer_encoding:
            body = bytearray()
            while True:
                size_line = self.rfile.readline(128)
                if not size_line:
                    raise ValueError("chunked 请求意外结束")
                try:
                    chunk_size = int(size_line.split(b";", 1)[0].strip(), 16)
                except ValueError as exc:
                    raise ValueError("无效的 chunked 请求") from exc
                if chunk_size == 0:
                    while True:
                        trailer = self.rfile.readline(8192)
                        if trailer in (b"\r\n", b"\n", b""):
                            break
                    break
                if len(body) + chunk_size > MAX_REQUEST_BODY:
                    raise RequestBodyTooLarge
                chunk = self.rfile.read(chunk_size)
                if len(chunk) != chunk_size:
                    raise ValueError("chunked 请求内容不完整")
                body.extend(chunk)
                if self.rfile.read(2) != b"\r\n":
                    raise ValueError("chunked 请求分隔符无效")
            return bytes(body)

        raw_length = self.headers.get("Content-Length", "0")
        try:
            content_length = int(raw_length)
        except ValueError as exc:
            raise ValueError("无效的 Content-Length") from exc
        if content_length < 0:
            raise ValueError("无效的 Content-Length")
        if content_length > MAX_REQUEST_BODY:
            raise RequestBodyTooLarge
        return self.rfile.read(content_length) if content_length else b""

    def _upstream_path(self):
        from urllib.parse import urlsplit
        parsed = urlsplit(self.path)
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        return path

    def _upstream_headers(self, api_key, body):
        blocked = HOP_BY_HOP_HEADERS | {
            "host", "content-length", "x-api-key", "authorization", "accept-encoding"
        }
        headers = {
            key: value for key, value in self.headers.items()
            if key.lower() not in blocked
        }
        headers["x-api-key"] = api_key
        headers.setdefault("anthropic-version", "2023-06-01")
        headers["Accept-Encoding"] = "identity"
        headers["Host"] = XUNFEI_HOST
        headers["User-Agent"] = self.headers.get("User-Agent", "claude-proxy/2.0")
        if body and "Content-Type" not in headers:
            headers["Content-Type"] = "application/json"
        return headers

    def _relay_buffered(self, status, headers, body):
        self.send_response(status)
        for key, value in headers:
            if key.lower() not in HOP_BY_HOP_HEADERS | {"content-length", "content-encoding"}:
                self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _relay_stream(self, status, headers, response):
        self.send_response(status)
        for key, value in headers:
            if key.lower() not in HOP_BY_HOP_HEADERS | {"content-length", "content-encoding"}:
                self.send_header(key, value)
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        total_size = 0
        usage_capture = bytearray()
        while True:
            chunk = response.read(8192)
            if not chunk:
                break
            try:
                self.wfile.write(f"{len(chunk):X}\r\n".encode("ascii"))
                self.wfile.write(chunk)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError) as exc:
                raise ClientDisconnected from exc
            total_size += len(chunk)
            if len(usage_capture) < MAX_USAGE_CAPTURE:
                remaining = MAX_USAGE_CAPTURE - len(usage_capture)
                usage_capture.extend(chunk[:remaining])
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()
        return total_size, _extract_usage(bytes(usage_capture))

    def _record_client_error(self):
        if not getattr(self, "_client_error_recorded", False):
            pool.record_client_error()
            self._client_error_recorded = True

    def _proxy_request(self, method):
        self._client_error_recorded = False
        pool.record_client_request()
        try:
            try:
                original_body = self._read_request_body()
            except RequestBodyTooLarge:
                self._record_client_error()
                self._send_json(413, {"error": "request body exceeds 32 MiB limit"})
                return
            except ValueError as exc:
                self._record_client_error()
                self._send_json(400, {"error": str(exc)})
                return

            data = None
            if original_body:
                try:
                    decoded = json.loads(original_body.decode("utf-8"))
                    if isinstance(decoded, dict):
                        data = decoded
                except (UnicodeDecodeError, json.JSONDecodeError):
                    pass

            original_model = None
            is_auto_model = False
            if data is not None and "model" in data:
                original_model = data["model"]
                if isinstance(original_model, str) and original_model.lower() in (
                    "proxyautomodel", "proxy-auto-model", "auto_model"
                ):
                    is_auto_model = True
                    data["model"] = model_pool.get_model()
                    log(f"AUTO model={original_model}->{data['model']}")
                else:
                    data["model"] = MODEL_MAP.get(original_model, original_model)

            request_body = (
                json.dumps(data, ensure_ascii=False).encode("utf-8")
                if data is not None else original_body
            )
            path = self._upstream_path()
            max_retries = min(MAX_RETRY_CHANNELS, len(CHANNELS))
            client_ip = self.client_address[0] if self.client_address else "unknown"
            user_agent = self.headers.get("User-Agent", "unknown")
            log(f"REQ method={method} path={path} client={client_ip} ua={user_agent[:30]}")
            if data is not None and "model" in data:
                log(f"REQ model={original_model}->{data['model']}")

            for attempt in range(max_retries):
                api_key, channel_name, channel_id = pool.get_channel()
                conn = None
                response = None
                headers_sent = False
                try:
                    headers = self._upstream_headers(api_key, request_body)
                    conn, response = _make_request_stream(
                        method, path, body=request_body or None, headers=headers
                    )
                    status = response.status
                    response_headers = response.getheaders()

                    if status >= 400:
                        error_body = response.read()
                        _release_connection(conn, response)
                        conn = None
                        error_message = error_body.decode("utf-8", errors="replace")[:200]

                        if status == 400:
                            self._record_client_error()
                            self._relay_buffered(status, response_headers, error_body)
                            log(f"400 ch={channel_name} path={path} msg={error_message[:100]}")
                            return

                        pool.record_error(channel_id)
                        if is_auto_model and status in (500, 503):
                            previous_model = data["model"]
                            model_pool.record_error(previous_model)
                            new_model = model_pool.get_model()
                            if new_model != previous_model:
                                data["model"] = new_model
                                request_body = json.dumps(data, ensure_ascii=False).encode("utf-8")
                                log(f"AUTO switch {previous_model}->{new_model} (after {status})")

                        if status in (403, 429, 500, 503) and attempt < max_retries - 1:
                            log(f"{status} ch={channel_name} retry={attempt + 1} path={path}")
                            continue

                        self._record_client_error()
                        self._relay_buffered(status, response_headers, error_body)
                        log(f"ERR ch={channel_name} HTTP={status} path={path} msg={error_message[:100]}")
                        return

                    headers_sent = True
                    total_size, (input_tokens, output_tokens) = self._relay_stream(
                        status, response_headers, response
                    )
                    _release_connection(conn, response)
                    conn = None
                    pool.record_success(channel_id, input_tokens, output_tokens)
                    if is_auto_model:
                        model_pool.record_success(data["model"])
                    model_info = f"model={original_model}->{data['model']}" if original_model else ""
                    log(
                        f"OK ch={channel_name} {model_info} size={total_size} "
                        f"tokens={input_tokens}/{output_tokens} path={path}"
                    )
                    return

                except ClientDisconnected:
                    if conn is not None:
                        _close_connection(conn)
                    self._record_client_error()
                    log(f"CLIENT disconnected ch={channel_name} path={path}")
                    return
                except Exception as exc:
                    if conn is not None:
                        _close_connection(conn)
                    pool.record_error(channel_id)
                    if headers_sent:
                        self._record_client_error()
                        log(f"ERR ch={channel_name} response interrupted: {str(exc)[:100]}")
                        return
                    if attempt < max_retries - 1:
                        log(f"ERR ch={channel_name} retry={attempt + 1}: {str(exc)[:100]}")
                        continue
                    self._record_client_error()
                    self._send_json(502, {
                        "type": "error",
                        "error": {"type": "api_error", "message": "All channels failed"},
                    })
                    log(f"ERR ch={channel_name} all retries exhausted: {str(exc)[:100]}")
                    return

            self._record_client_error()
            self._send_json(503, {"error": "all channels exhausted"})
        except Exception as exc:
            self._record_client_error()
            try:
                self._send_json(500, {"error": "internal proxy error"})
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            log(f"ERR internal: {str(exc)[:100]}")


class ThreadingProxyServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


_proxy_server = None
_proxy_server_lock = threading.Lock()


def create_proxy_server(port=18081):
    global _proxy_server
    server = ThreadingProxyServer(("127.0.0.1", port), ProxyHandler)
    with _proxy_server_lock:
        _proxy_server = server
    return server


def run_proxy(server):
    log(f"Proxy started on 127.0.0.1:{server.server_address[1]}")
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()


def stop_proxy():
    global _proxy_server
    with _proxy_server_lock:
        server = _proxy_server
        _proxy_server = None
    if server is not None:
        server.shutdown()
        server.server_close()
    close_connection_pool()


# ========== 日志窗口 ==========
# ========== 日志窗口 ==========

class LogWindow:
    def __init__(self, root, port):
        self.root = root
        self.root.title("Claude Proxy")
        self.root.geometry("1050x700")
        self.root.minsize(800, 500)
        self.root.protocol("WM_DELETE_WINDOW", self.hide)

        # 全局样式
        style = ttk.Style()
        style.configure(".", font=("Microsoft YaHei UI", 9))
        style.configure("Header.TLabel", font=("Microsoft YaHei UI", 16, "bold"))
        style.configure("Stats.TLabel", font=("Microsoft YaHei UI", 10))
        style.configure("Card.TFrame", relief="flat", borderwidth=0)
        style.configure("Btn.TButton", font=("Microsoft YaHei UI", 9), padding=6)

        # 顶部标题栏
        header = ttk.Frame(root)
        header.pack(fill=tk.X, padx=12, pady=(10, 0))
        ttk.Label(header, text="Claude Proxy", style="Header.TLabel").pack(side=tk.LEFT)
        ttk.Label(header, text=f"Port {port}", style="Stats.TLabel").pack(side=tk.LEFT, padx=10)

        # 统计卡片行
        stats_card = ttk.Frame(root, relief="groove", borderwidth=1)
        stats_card.pack(fill=tk.X, padx=12, pady=8)

        card_inner = ttk.Frame(stats_card)
        card_inner.pack(fill=tk.X, padx=10, pady=10)

        self.lbl_requests = ttk.Label(card_inner, text="0", font=("Microsoft YaHei UI", 18, "bold"))
        self.lbl_requests.pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(card_inner, text="请求  ", font=("Microsoft YaHei UI", 8)).pack(side=tk.LEFT, padx=(0, 16))

        self.lbl_errors = ttk.Label(card_inner, text="0", font=("Microsoft YaHei UI", 18, "bold"), foreground="#e74c3c")
        self.lbl_errors.pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(card_inner, text="错误  ", font=("Microsoft YaHei UI", 8)).pack(side=tk.LEFT, padx=(0, 16))

        self.lbl_input = ttk.Label(card_inner, text="0", font=("Microsoft YaHei UI", 18, "bold"))
        self.lbl_input.pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(card_inner, text="Input Token  ", font=("Microsoft YaHei UI", 8)).pack(side=tk.LEFT, padx=(0, 16))

        self.lbl_output = ttk.Label(card_inner, text="0", font=("Microsoft YaHei UI", 18, "bold"))
        self.lbl_output.pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(card_inner, text="Output Token  ", font=("Microsoft YaHei UI", 8)).pack(side=tk.LEFT, padx=(0, 16))

        self.lbl_channels = ttk.Label(card_inner, text=str(len(CHANNELS)), font=("Microsoft YaHei UI", 18, "bold"))
        self.lbl_channels.pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(card_inner, text="渠道  ", font=("Microsoft YaHei UI", 8)).pack(side=tk.LEFT, padx=(0, 16))

        self.lbl_mode = ttk.Label(card_inner, text="-", font=("Microsoft YaHei UI", 18, "bold"))
        self.lbl_mode.pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(card_inner, text="模式", font=("Microsoft YaHei UI", 8)).pack(side=tk.LEFT)

        # 控制栏
        ctrl_bar = ttk.Frame(root)
        ctrl_bar.pack(fill=tk.X, padx=12, pady=4)

        self.log_title = ttk.Label(ctrl_bar, text="实时日志", font=("Microsoft YaHei UI", 11, "bold"))
        self.log_title.pack(side=tk.LEFT)

        retry_frame = ttk.Frame(ctrl_bar)
        retry_frame.pack(side=tk.RIGHT, padx=10)
        ttk.Label(retry_frame, text="503重试:", font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT, padx=(0, 4))
        self.retry_var = tk.StringVar(value=str(DEFAULT_MAX_RETRY_CHANNELS))
        self.retry_spin = ttk.Spinbox(retry_frame, from_=1, to=len(CHANNELS), width=4,
                                      textvariable=self.retry_var, command=self._on_retry_change)
        self.retry_spin.pack(side=tk.LEFT, padx=2)
        ttk.Label(retry_frame, text=f"/{len(CHANNELS)}", font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT)

        # 日志区域
        log_frame = ttk.Frame(root, relief="sunken", borderwidth=1)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=4)
        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD,
                                                   font=('Cascadia Code', 9),
                                                   bg="#1e1e1e", fg="#d4d4d4",
                                                   insertbackground="white",
                                                   selectbackground="#264f78")
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        self.log_text.tag_config("error", foreground="#f44747")
        self.log_text.tag_config("success", foreground="#4ec9b0")
        self.log_text.tag_config("retry", foreground="#ce9178")
        self.log_text.tag_config("info", foreground="#569cd6")

        # 底部按钮
        self.btn_frame = ttk.Frame(root)
        self.btn_frame.pack(fill=tk.X, padx=12, pady=6)

        ttk.Button(self.btn_frame, text="清空日志", command=self.clear_log, style="Btn.TButton").pack(side=tk.LEFT, padx=3)
        ttk.Button(self.btn_frame, text="隐藏到托盘", command=self.hide, style="Btn.TButton").pack(side=tk.LEFT, padx=3)
        ttk.Button(self.btn_frame, text="密钥管理", command=self.open_key_manager, style="Btn.TButton").pack(side=tk.LEFT, padx=3)
        ttk.Button(self.btn_frame, text="排名面板", command=self.open_ranking, style="Btn.TButton").pack(side=tk.LEFT, padx=3)
        ttk.Button(self.btn_frame, text="系统配置", command=self.open_config, style="Btn.TButton").pack(side=tk.LEFT, padx=3)
        ttk.Button(self.btn_frame, text="退出",  command=self.quit_app, style="Btn.TButton").pack(side=tk.RIGHT, padx=3)

        self.visible = False
        self.running = True
        self.log_line_count = 0
        self.update_log()

    def show(self):
        self.visible = True
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def hide(self):
        self.visible = False
        self.root.withdraw()

    def quit_app(self):
        self.running = False
        global tray_icon
        if tray_icon is not None:
            try:
                tray_icon.stop()
            except Exception:
                pass
            tray_icon = None
        stop_proxy()
        self.root.quit()
        self.root.destroy()

    def clear_log(self):
        self.log_text.delete(1.0, tk.END)

    def _on_retry_change(self):
        """503 重试渠道数改变时的回调"""
        try:
            new_size = int(self.retry_var.get())
            set_max_retry_channels(new_size)
        except ValueError:
            pass

    def open_key_manager(self):
        """打开密钥管理窗口"""
        KeyManagerWindow(self.root)

    def open_ranking(self):
        """打开排名面板"""
        RankingWindow(self.root)

    def open_config(self):
        """打开系统配置窗口"""
        ConfigWindow(self.root)

    def update_log(self):
        """从队列读取日志并显示"""
        if not self.running:
            return

        try:
            while True:
                line = log_queue.get_nowait()
                if line:
                    self.log_text.insert(tk.END, line + "\n")
                    # VS Code 风格着色
                    if "REQ" in line:
                        self.log_text.tag_add("info", f"{self.log_text.index(tk.END)}-1l", f"{self.log_text.index(tk.END)}-1l+1l")
                    elif "OK" in line:
                        self.log_text.tag_add("success", f"{self.log_text.index(tk.END)}-1l", f"{self.log_text.index(tk.END)}-1l+1l")
                    elif "ERR" in line or "403" in line or "500" in line:
                        self.log_text.tag_add("error", f"{self.log_text.index(tk.END)}-1l", f"{self.log_text.index(tk.END)}-1l+1l")
                    elif "503" in line or "retry" in line or "429" in line:
                        self.log_text.tag_add("retry", f"{self.log_text.index(tk.END)}-1l", f"{self.log_text.index(tk.END)}-1l+1l")
                    elif "TEST" in line:
                        self.log_text.tag_add("info", f"{self.log_text.index(tk.END)}-1l", f"{self.log_text.index(tk.END)}-1l+1l")

                    self.log_text.see(tk.END)

                    # 限制行数，避免每条日志都复制整个文本框内容。
                    self.log_line_count += 1
                    if self.log_line_count > 1000:
                        self.log_text.delete(1.0, "2.0")
                        self.log_line_count -= 1
        except queue.Empty:
            pass

        # 更新统计
        try:
            stats = pool.get_stats()
            self.lbl_requests.config(text=str(stats['total_requests']))
            self.lbl_errors.config(text=str(stats['total_errors']))
            self.lbl_input.config(text=str(stats['total_input_tokens']))
            self.lbl_output.config(text=str(stats['total_output_tokens']))
            self.lbl_channels.config(text=str(len(CHANNELS)))
            mode_text = "评分" if stats['mode'] == 'scoring' else "轮询"
            self.lbl_mode.config(text=mode_text,
                               foreground="#27ae60" if stats['mode'] == 'scoring' else "#2980b9")
        except (KeyError, tk.TclError):
            pass

        self.root.after(100, self.update_log)


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
        ttk.Button(self.tab_current, text="一键测试当前密钥", command=self._test_current_keys).pack(pady=5)

        self._refresh_current_keys()

    def _refresh_current_keys(self):
        """刷新当前已应用密钥列表"""
        for item in self.current_tree.get_children():
            self.current_tree.delete(item)

        for ch in CHANNELS:
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
                    "model": "xopdeepseekv4pro",
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
        progress_window.transient(self.window)
        progress_window.protocol("WM_DELETE_WINDOW", lambda: None)
        progress_label = ttk.Label(progress_window, text="正在测试密钥...")
        progress_label.pack(pady=10)
        progress_bar = ttk.Progressbar(
            progress_window, mode="determinate", maximum=len(CHANNELS)
        )
        progress_bar.pack(fill=tk.X, padx=20, pady=10)

        result_queue = queue.Queue()
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=5)
        for channel in list(CHANNELS):
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
            progress_label.config(text=f"已完成 {len(results)}/{len(CHANNELS)}")
            if len(results) < len(CHANNELS):
                progress_window.after(100, poll_results)
                return
            progress_window.destroy()
            result_window = tk.Toplevel(self.window)
            result_window.title("测试结果")
            result_window.geometry("600x400")
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
        global CHANNELS
        updated = 0
        for ch in CHANNELS:
            ch_id = str(ch['id'])
            if ch_id in self.decrypted_keys:
                ch['key'] = self.decrypted_keys[ch_id]
                updated += 1

        env_values = {ch["env"]: ch["key"] for ch in CHANNELS}
        existing_lines = ENV_FILE.read_text(encoding="utf-8-sig").splitlines()
        preserved = [
            line for line in existing_lines
            if not any(line.lstrip().startswith(name + "=") for name in env_values)
        ]
        preserved.extend(f"{name}={value}" for name, value in env_values.items())
        temp_path = ENV_FILE.with_name(".env.tmp")
        temp_path.write_text("\n".join(preserved) + "\n", encoding="utf-8")
        os.replace(temp_path, ENV_FILE)
        for ch in CHANNELS:
            os.environ[ch["env"]] = ch["key"]

        messagebox.showinfo("成功", f"已更新 {updated} 个渠道的密钥并保存到 .env")
        log(f"密钥管理: 已更新 {updated} 个渠道的密钥")
        self._refresh_current_keys()

    def clear_all(self):
        self.input_text.delete(1.0, tk.END)
        self.output_text.delete(1.0, tk.END)
        self.decrypted_keys = {}


class RankingWindow:
    """排名面板 - 渠道排名 + 模型排名"""
    def __init__(self, parent):
        self.window = tk.Toplevel(parent)
        self.window.title("排名面板")
        self.window.geometry("850x520")
        self.window.transient(parent)
        _center_window(self.window)

        # 标签页
        notebook = ttk.Notebook(self.window)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # === 渠道排名标签页 ===
        ch_frame = ttk.Frame(notebook)
        notebook.add(ch_frame, text="渠道排名")

        columns = ('rank', 'name', 'requests', 'success', 'errors', 'success_rate', 'score', 'status')
        self.ch_tree = ttk.Treeview(ch_frame, columns=columns, show='headings')
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

        ch_scroll = ttk.Scrollbar(ch_frame, orient=tk.VERTICAL, command=self.ch_tree.yview)
        self.ch_tree.configure(yscrollcommand=ch_scroll.set)
        self.ch_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ch_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # === 模型排名标签页 ===
        model_frame = ttk.Frame(notebook)
        notebook.add(model_frame, text="模型排名 (ProxyAutoModel)")

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

        # 刷新按钮
        btn_frame = ttk.Frame(self.window)
        btn_frame.pack(pady=5)
        ttk.Button(btn_frame, text="刷新", command=self._refresh).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="配置模型池", command=self._open_model_config).pack(side=tk.LEFT, padx=5)

        # 颜色标签
        for tree in (self.ch_tree, self.model_tree):
            tree.tag_configure('green', foreground='green')
            tree.tag_configure('blue', foreground='blue')
            tree.tag_configure('orange', foreground='orange')
            tree.tag_configure('red', foreground='red')
            tree.tag_configure('gray', foreground='gray')

        self._refresh()

    def _open_model_config(self):
        ModelPoolConfigWindow(self.window)

    def _refresh(self):
        # 刷新渠道排名
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

        # 刷新模型排名
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


class ConfigWindow:
    """运行时系统配置窗口。"""
    def __init__(self, parent):
        self.window = tk.Toplevel(parent)
        self.window.title("系统配置")
        self.window.geometry("520x430")
        self.window.transient(parent)
        _center_window(self.window)

        ttk.Label(self.window, text="系统配置参数", font=("Arial", 14, "bold")).pack(pady=10)
        editable = ttk.LabelFrame(self.window, text="可调整参数")
        editable.pack(fill=tk.X, padx=12, pady=6)

        self.retry_var = tk.StringVar(value=str(MAX_RETRY_CHANNELS))
        self.pool_var = tk.StringVar(value=str(MAX_POOL_SIZE))
        ttk.Label(editable, text="最大重试渠道数").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        ttk.Spinbox(editable, from_=1, to=len(CHANNELS), textvariable=self.retry_var, width=8).grid(row=0, column=1, padx=8)
        ttk.Label(editable, text="连接池大小").grid(row=1, column=0, sticky="w", padx=8, pady=6)
        ttk.Spinbox(editable, from_=1, to=100, textvariable=self.pool_var, width=8).grid(row=1, column=1, padx=8)
        ttk.Button(editable, text="应用", command=self._apply).grid(row=0, column=2, rowspan=2, padx=12)

        columns = ("param", "value", "description")
        self.tree = ttk.Treeview(self.window, columns=columns, show="headings")
        self.tree.heading("param", text="参数名")
        self.tree.heading("value", text="当前值")
        self.tree.heading("description", text="说明")
        self.tree.column("param", width=190)
        self.tree.column("value", width=80, anchor="center")
        self.tree.column("description", width=230)
        self.tree.pack(fill=tk.BOTH, expand=True, padx=12, pady=6)
        self._load_config()

    def _load_config(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        configs = [
            ("WARMUP_REQUESTS", ChannelPool.WARMUP_REQUESTS, "尝试达到此数量后启用评分"),
            ("MIN_CHANNEL_REQUESTS", ChannelPool.MIN_CHANNEL_REQUESTS, "单渠道最少样本数"),
            ("SCORE_THRESHOLD", ChannelPool.SCORE_THRESHOLD, "评分模式最低平均分"),
            ("COOLDOWN_CHANNELS", ChannelPool.COOLDOWN_CHANNELS, "过多冷却时退回轮询"),
            ("MAX_RETRY_CHANNELS", MAX_RETRY_CHANNELS, "单请求最大渠道尝试数"),
            ("MAX_POOL_SIZE", MAX_POOL_SIZE, "当前连接池上限"),
            ("总渠道数", len(CHANNELS), "当前渠道总数"),
            ("模型池数量", len(model_pool.models), "自动模型可选数量"),
        ]
        for param, value, description in configs:
            self.tree.insert("", tk.END, values=(param, value, description))

    def _apply(self):
        try:
            set_max_retry_channels(int(self.retry_var.get()))
            set_max_pool_size(int(self.pool_var.get()))
        except ValueError:
            messagebox.showerror("错误", "配置值必须是整数")
            return
        self._load_config()
        messagebox.showinfo("成功", "运行时配置已应用")


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
        global AUTO_MODEL_POOL
        AUTO_MODEL_POOL = list(models)
        log(f"ProxyAutoModel 模型池已更新: {', '.join(models)}")
        messagebox.showinfo("成功", f"模型池已更新，共 {len(models)} 个模型")
        self.window.destroy()


# ========== 系统托盘 ==========

import io
import base64

# 内嵌的 claude.ico 图标（base64编码，无需外部文件）
_ICO_BASE64 = "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"


def create_icon_image():
    """从内嵌的 base64 ico 数据生成托盘图标"""
    try:
        import base64
        from PIL import Image
        ico_data = base64.b64decode(_ICO_BASE64)
        return Image.open(io.BytesIO(ico_data))
    except (OSError, ValueError):
        # 回退：手动绘制图标
        from PIL import Image, ImageDraw, ImageFilter
        size = 64
        img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        # 圆角矩形背景
        draw.rounded_rectangle([2, 2, size-2, size-2], radius=16, fill=(204, 153, 102, 255))
        # C 字母
        draw.arc([10, 10, size-10, size-10], start=45, end=315, fill=(255, 255, 255, 255), width=8)
        return img


# 全局变量
log_window = None
tray_icon = None

# 端口检测和重复启动相关
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
        import ctypes
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
    import os
    return os.path.join(os.environ.get('APPDATA', ''),
                        'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup')


def get_startup_shortcut_path():
    """获取启动项快捷方式路径"""
    import os
    return os.path.join(get_startup_dir(), 'ClaudeProxyGUI.lnk')


def is_startup_enabled():
    """检查是否已设置为开机启动"""
    return os.path.exists(get_startup_shortcut_path())


def enable_startup():
    """设置开机启动（创建快捷方式到启动文件夹）"""
    import os
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


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18081)
    args = parser.parse_args()

    port_check = check_port_and_handle(args.port)
    if port_check == "duplicate":
        time.sleep(0.5)
        success = find_existing_window()
        dialog_root = tk.Tk()
        dialog_root.withdraw()
        message = (
            f"代理已在端口 {args.port} 运行，已显示日志窗口。"
            if success else f"代理已在端口 {args.port} 运行。"
        )
        messagebox.showinfo("Claude Proxy", message)
        dialog_root.destroy()
        return
    if port_check == "exit":
        return

    try:
        server = create_proxy_server(args.port)
    except OSError as exc:
        dialog_root = tk.Tk()
        dialog_root.withdraw()
        messagebox.showerror("启动失败", f"无法监听 127.0.0.1:{args.port}：{exc}")
        dialog_root.destroy()
        return

    log_root = Path(os.environ.get("LOCALAPPDATA", get_app_dir())) / "ClaudeProxy" / "logs"
    try:
        log_root.mkdir(parents=True, exist_ok=True)
    except OSError:
        log_root = get_app_dir()
    log_filename = datetime.datetime.now().strftime("claude_proxy_%Y%m%d_%H%M%S.log")
    set_log_file(str(log_root / log_filename))
    log(f"日志文件: {log_root / log_filename}")

    proxy_thread = threading.Thread(target=run_proxy, args=(server,), daemon=True)
    proxy_thread.start()

    try:
        from ttkthemes import ThemedTk
        root = ThemedTk(theme="arc")
    except (ImportError, tk.TclError):
        root = tk.Tk()

    try:
        import tempfile
        ico_data = base64.b64decode(_ICO_BASE64)
        ico_img = Image.open(io.BytesIO(ico_data))
        temp_ico = os.path.join(tempfile.gettempdir(), "claude_proxy_icon.ico")
        ico_img.save(temp_ico, format="ICO", sizes=[
            (16, 16), (24, 24), (32, 32), (48, 48),
            (64, 64), (128, 128), (256, 256),
        ])
        root.iconbitmap(temp_ico)
        root.iconbitmap(default=temp_ico)
    except (OSError, ValueError, tk.TclError):
        pass

    root.withdraw()
    global log_window, tray_icon
    log_window = LogWindow(root, args.port)

    def on_show(icon, item):
        root.after(0, log_window.show)

    def on_hide(icon, item):
        root.after(0, log_window.hide)

    def on_quit(icon, item):
        root.after(0, log_window.quit_app)

    def on_toggle_startup(icon, item):
        if is_startup_enabled():
            disable_startup()
        else:
            enable_startup()
        icon.menu = build_menu()
        icon.update_menu()

    def build_menu():
        startup_text = "开机启动 ✓" if is_startup_enabled() else "开机启动"
        return pystray.Menu(
            pystray.MenuItem(f"端口: {args.port}", lambda icon, item: None, enabled=False),
            pystray.MenuItem("显示日志窗口", on_show, default=True),
            pystray.MenuItem("隐藏日志窗口", on_hide),
            pystray.MenuItem(startup_text, on_toggle_startup),
            pystray.MenuItem("退出", on_quit),
        )

    tray_icon = pystray.Icon(
        "claude-proxy", create_icon_image(), f"Claude Proxy ({args.port})", build_menu()
    )
    tray_thread = threading.Thread(target=tray_icon.run, daemon=True)
    tray_thread.start()

    try:
        root.mainloop()
    finally:
        if tray_icon is not None:
            try:
                tray_icon.stop()
            except Exception:
                pass
            tray_icon = None
        stop_proxy()


if __name__ == "__main__":
    main()
if __name__ == '__main__':
    main()
