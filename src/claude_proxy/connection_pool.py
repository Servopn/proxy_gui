#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HTTPS 上游连接池：复用 TCP/TLS 连接，降低握手开销。

MAX_POOL_SIZE 等可调阈值存于 config（模块级全局），本模块通过
`claude_proxy.config.MAX_POOL_SIZE` 读取，set_max_pool_size 同步写回 config。
"""

import http.client
import ssl
import threading

from claude_proxy import config
from claude_proxy.logger import log

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
                conn.sock.settimeout(config.CONNECTION_TIMEOUT)
                return conn
            except (AttributeError, OSError):
                _close_connection(conn)

    context = ssl.create_default_context()
    return http.client.HTTPSConnection(
        config.XUNFEI_HOST, context=context, timeout=config.CONNECTION_TIMEOUT
    )


def _return_connection(conn):
    """将仍可复用的连接归还连接池。"""
    with _conn_lock:
        if conn.sock is not None and len(_conn_pool) < config.MAX_POOL_SIZE:
            try:
                conn.sock.settimeout(config.CONNECTION_TIMEOUT)
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


def shrink_pool():
    """当 MAX_POOL_SIZE 变小后，立即清理超出的空闲连接。"""
    with _conn_lock:
        extra = []
        while len(_conn_pool) > config.MAX_POOL_SIZE:
            extra.append(_conn_pool.pop())
    for conn in extra:
        _close_connection(conn)


def set_max_pool_size(size):
    """设置连接池大小，并立即清理超出的空闲连接。"""
    config.MAX_POOL_SIZE = max(1, int(size))
    shrink_pool()
    log(f"连接池大小已设置为: {config.MAX_POOL_SIZE}")


def get_max_pool_size():
    return config.MAX_POOL_SIZE


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
