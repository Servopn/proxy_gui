#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HTTP 代理核心：转发 Claude / OpenAI 兼容请求到讯飞 MaaS，支持流式、chunked、
渠道轮换重试、ProxyAuto 模型自动选择与 token 用量提取。

同时兼容 OpenAI 格式（/v1/chat/completions），自动做请求/响应双向转换。
"""

import http.server
import json
import re
import socketserver
import threading

from claude_proxy import config
from claude_proxy.connection_pool import (
    _close_connection,
    _get_connection,
    _make_request_stream,
    _release_connection,
    close_connection_pool,
)
from claude_proxy.logger import log
from claude_proxy.stats import model_pool, pool


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


# ── OpenAI ↔ Anthropic 格式转换 ──────────────────────────────────────

def _openai_to_anthropic(body):
    """
    将 OpenAI /v1/chat/completions 请求体转为 Anthropic /v1/messages 格式。
    返回 (anthropic_dict, original_model, is_stream)。
    """
    openai_model = body.get("model", "")
    stream = body.get("stream", False)
    max_tokens = body.get("max_tokens", body.get("max_completion_tokens", 4096))
    temperature = body.get("temperature", body.get("top_p", None))

    # 提取 system prompt
    system = None
    messages = body.get("messages", [])
    if messages and messages[0].get("role") == "system":
        system = messages[0]["content"]
        messages = messages[1:]

    # 转换 messages
    antr_messages = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "assistant":
            antr_messages.append({"role": "assistant", "content": content})
        else:
            # user / tool / function 都映射为 user
            antr_messages.append({"role": "user", "content": content})

    result = {
        "model": openai_model,
        "messages": antr_messages,
        "max_tokens": max_tokens,
        "stream": stream,
    }
    if system:
        result["system"] = system
    if temperature is not None:
        result["temperature"] = temperature

    return result, openai_model, stream


def _anthropic_to_openai_nonstream(anthropic_body, model):
    """
    将 Anthropic 非流式响应转为 OpenAI /v1/chat/completions 格式。
    """
    content_text = ""
    for block in anthropic_body.get("content", []):
        if block.get("type") == "text":
            content_text += block.get("text", "")

    usage = anthropic_body.get("usage", {})
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)

    return {
        "id": anthropic_body.get("id", "chatcmpl-default"),
        "object": "chat.completion",
        "created": int(__import__("time").time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content_text,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    }


class AnthropicToOpenAIStream:
    """
    将 Anthropic SSE 流实时转换为 OpenAI SSE 格式。

    用法:
        converter = AnthropicToOpenAIStream(model_name)
        for chunk in converter.feed(anthropic_sse_chunk):
            yield openai_sse_chunk
    """

    def __init__(self, model):
        self.model = model
        self._buffer = ""
        self._content_index = 0
        self._role_sent = False

    def feed(self, raw_chunk):
        """接收原始字节块，产出 OpenAI 格式的 SSE 行（str 列表）。"""
        results = []
        decoded = raw_chunk.decode("utf-8", errors="replace")
        self._buffer += decoded

        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            line = line.strip()
            if not line or line.startswith(":"):
                continue

            # event: xxx
            if line.startswith("event: "):
                self._current_event = line[7:].strip()
                continue

            # data: ...
            if line.startswith("data: "):
                data_str = line[6:].strip()
            else:
                continue

            if data_str == "[DONE]":
                continue

            try:
                data = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            event = getattr(self, "_current_event", "")

            if event == "message_start":
                # 首次响应，发 role 标识
                results.append(self._make_delta({"role": "assistant", "content": ""}, finish_reason=None))
                self._role_sent = True

            elif event == "content_block_start":
                block = data.get("content_block", {})
                if block.get("type") == "text":
                    text = block.get("text", "")
                    if text:
                        results.append(self._make_delta({"content": text}, finish_reason=None))

            elif event == "content_block_delta":
                delta = data.get("delta", {})
                if delta.get("type") == "text_delta":
                    text = delta.get("text", "")
                    if text:
                        results.append(self._make_delta({"content": text}, finish_reason=None))

            elif event == "message_delta":
                delta = data.get("delta", {})
                stop_reason = delta.get("stop_reason")
                finish = _map_stop_reason(stop_reason) if stop_reason else None
                usage = data.get("usage", {})
                results.append(self._make_delta({}, finish_reason=finish, usage=usage))

            elif event == "message_stop":
                results.append(self._make_delta({}, finish_reason="stop"))
                results.append("data: [DONE]\n")

            elif event == "error":
                err = data.get("error", {})
                error_msg = err.get("message", str(data))
                results.append(f"data: {json.dumps({'error': {'message': error_msg}})}\n")

            self._current_event = ""

        return results

    def _make_delta(self, delta_body, finish_reason=None, usage=None):
        choice = {
            "index": 0,
            "delta": delta_body,
        }
        if finish_reason is not None:
            choice["finish_reason"] = finish_reason
        result = {
            "id": f"chatcmpl-{self._content_index}",
            "object": "chat.completion.chunk",
            "created": int(__import__("time").time()),
            "model": self.model,
            "choices": [choice],
        }
        if usage:
            result["usage"] = {
                "prompt_tokens": usage.get("input_tokens", 0),
                "completion_tokens": usage.get("output_tokens", 0),
                "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
            }
        return f"data: {json.dumps(result, ensure_ascii=False)}\n"


def _map_stop_reason(anthropic_reason):
    mapping = {
        "end_turn": "stop",
        "max_tokens": "length",
        "stop_sequence": "stop",
        "tool_use": "tool_calls",
    }
    return mapping.get(anthropic_reason, "stop")


# ── 结束 OpenAI 转换函数 ─────────────────────────────────────────────


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
        path_no_qs = self.path.split("?", 1)[0]
        if self.path == "/__claude_proxy_health":
            self._send_json(200, {"service": "claude-proxy", "status": "ok"})
        elif self.path in ("/anthropic", "/anthropic/", "/", "/oneapi", "/oneapi/"):
            self._handle_test()
        elif path_no_qs.endswith(("/v1/models", "/models")):
            self._handle_models()
        elif path_no_qs.endswith(("/v1/usage", "/usage", "/api/usage")):
            self._handle_usage()
        elif path_no_qs.endswith("/v1/chat/completions"):
            self._send_json(405, {"error": "Use POST for chat completions"})
        else:
            self._proxy_request("GET")

    def do_POST(self):
        path_no_qs = self.path.split("?", 1)[0]
        if path_no_qs.endswith("/api/usage"):
            self._handle_usage()
        elif path_no_qs.endswith("/v1/chat/completions"):
            self._handle_openai_chat()
        else:
            self._proxy_request("POST")

    def do_OPTIONS(self):
        self._proxy_request("OPTIONS")

    def _handle_test(self):
        test_key = config.CHANNELS[0]["key"] if config.CHANNELS else ""
        conn = None
        response = None
        try:
            conn = _get_connection()
            conn.request("GET", "/anthropic/v1/models", headers={
                "Host": config.XUNFEI_HOST,
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
        user_models = ["ProxyAutoModel"] + config.USER_MODEL_LIST + ["Auto"]
        self._send_json(200, {
            "object": "list",
            "data": [
                {"id": model, "object": "model", "type": "claude", "display_name": model}
                for model in user_models
            ],
        })

    def _handle_openai_chat(self):
        """
        处理 OpenAI /v1/chat/completions 请求。
        将请求体转为 Anthropic 格式发送到上游，再将响应转回 OpenAI 格式。
        """
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

            if not original_body:
                self._record_client_error()
                self._send_json(400, {"error": "empty request body"})
                return

            try:
                openai_req = json.loads(original_body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                self._record_client_error()
                self._send_json(400, {"error": f"invalid JSON: {exc}"})
                return

            # 转换请求体为 Anthropic 格式
            antr_body, original_model, is_stream = _openai_to_anthropic(openai_req)
            original_model = original_model or "openai-model"

            # 处理模型映射和 ProxyAuto
            is_auto_model = False
            if config.FORCE_PROXY_AUTO:
                is_auto_model = True
                antr_body["model"] = model_pool.get_model()
                log(f"FORCE_AUTO model={original_model}->{antr_body['model']}")
            elif isinstance(original_model, str) and original_model.lower() in (
                "proxyautomodel", "proxy-auto-model", "auto_model"
            ):
                is_auto_model = True
                antr_body["model"] = model_pool.get_model()
                log(f"AUTO model={original_model}->{antr_body['model']}")
            else:
                antr_body["model"] = config.MODEL_MAP.get(original_model, original_model)

            final_model = antr_body["model"]
            request_body = json.dumps(antr_body, ensure_ascii=False).encode("utf-8")
            path = self._upstream_path()
            max_retries = min(config.MAX_RETRY_CHANNELS, len(config.CHANNELS))
            client_ip = self.client_address[0] if self.client_address else "unknown"
            user_agent = self.headers.get("User-Agent", "unknown")
            log(f"REQ method=POST path={path} client={client_ip} ua={user_agent[:30]}")
            log(f"REQ model={original_model}->{final_model} (openai format)")

            for attempt in range(max_retries):
                api_key, channel_name, channel_id = pool.get_channel()
                conn = None
                response = None
                headers_sent = False
                try:
                    headers = self._upstream_headers(api_key, request_body)
                    conn, response = _make_request_stream(
                        "POST", path, body=request_body or None, headers=headers
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
                            self._send_json(400, {"error": {"message": error_message[:100]}})
                            log(f"400 ch={channel_name} path={path} msg={error_message[:100]}")
                            return

                        pool.record_error(channel_id)
                        if is_auto_model and status in (500, 503):
                            previous_model = final_model
                            model_pool.record_error(previous_model)
                            new_model = model_pool.get_model()
                            if new_model != previous_model:
                                antr_body["model"] = new_model
                                final_model = new_model
                                request_body = json.dumps(antr_body, ensure_ascii=False).encode("utf-8")
                                log(f"AUTO switch {previous_model}->{new_model} (after {status})")

                        if status in (403, 429, 500, 503) and attempt < max_retries - 1:
                            log(f"{status} ch={channel_name} retry={attempt + 1} path={path}")
                            continue

                        self._record_client_error()
                        self._send_json(status, {
                            "error": {"message": error_message[:100], "type": "api_error"}
                        })
                        log(f"ERR ch={channel_name} HTTP={status} path={path} msg={error_message[:100]}")
                        return

                    # 成功响应
                    if is_stream:
                        # 流式响应
                        headers_sent = True
                        total_size, (input_tokens, output_tokens) = self._relay_openai_stream(
                            status, response_headers, response, final_model
                        )
                        _release_connection(conn, response)
                        conn = None
                    else:
                        # 非流式响应
                        response_body = response.read()
                        _release_connection(conn, response)
                        conn = None
                        try:
                            antr_resp = json.loads(response_body.decode("utf-8"))
                            openai_resp = _anthropic_to_openai_nonstream(antr_resp, final_model)
                            input_tokens = antr_resp.get("usage", {}).get("input_tokens", 0)
                            output_tokens = antr_resp.get("usage", {}).get("output_tokens", 0)
                        except (json.JSONDecodeError, UnicodeDecodeError):
                            # 无法解析则直接透传
                            self._relay_buffered(status, response_headers, response_body)
                            log(f"OK ch={channel_name} non-json response path={path}")
                            return

                        self._send_json(status, openai_resp)
                        total_size = len(response_body)

                    pool.record_success(channel_id, input_tokens, output_tokens)
                    if is_auto_model:
                        model_pool.record_success(final_model)
                    log(
                        f"OK ch={channel_name} model={original_model}->{final_model} "
                        f"size={total_size} tokens={input_tokens}/{output_tokens} path={path}"
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
                        "error": {"message": "All channels failed", "type": "api_error"},
                    })
                    log(f"ERR ch={channel_name} all retries exhausted: {str(exc)[:100]}")
                    return

            self._record_client_error()
            self._send_json(503, {"error": {"message": "all channels exhausted"}})
        except Exception as exc:
            self._record_client_error()
            try:
                self._send_json(500, {"error": {"message": "internal proxy error"}})
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            log(f"ERR internal: {str(exc)[:100]}")
            import traceback
            for line in traceback.format_exc().splitlines():
                log(f"TRACE: {line[:200]}")

    def _relay_openai_stream(self, status, headers, response, model):
        """将 Anthropic 流式响应实时转为 OpenAI SSE 格式并发送给客户端。"""
        self.send_response(status)
        for key, value in headers:
            if key.lower() not in HOP_BY_HOP_HEADERS | {"content-length", "content-encoding"}:
                self.send_header(key, value)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        converter = AnthropicToOpenAIStream(model)
        total_size = 0
        usage_capture = bytearray()

        while True:
            chunk = response.read(8192)
            if not chunk:
                break
            total_size += len(chunk)
            if len(usage_capture) < MAX_USAGE_CAPTURE:
                remaining = MAX_USAGE_CAPTURE - len(usage_capture)
                usage_capture.extend(chunk[:remaining])

            try:
                sse_lines = converter.feed(chunk)
                for sse_line in sse_lines:
                    encoded = sse_line.encode("utf-8")
                    self.wfile.write(f"{len(encoded):X}\r\n".encode("ascii"))
                    self.wfile.write(encoded)
                    self.wfile.write(b"\r\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError) as exc:
                raise ClientDisconnected from exc

        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()
        input_tokens, output_tokens = _extract_usage(bytes(usage_capture))
        return total_size, (input_tokens, output_tokens)

    def _handle_usage(self):
        stats = pool.get_stats()
        total_requests = stats["total_requests"]
        total_errors = stats["total_errors"]
        self._send_json(200, {
            "balance": float(total_requests),
            "unit": "requests",
            "total": float(total_requests),
            "used": float(total_errors),
            "planName": f"Pool {len(config.CHANNELS)}ch | {total_requests}req",
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
        # OpenAI 兼容路径映射到 Anthropic 路径
        if path.endswith("/v1/chat/completions"):
            path = "/anthropic/v1/messages"
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
        headers["Host"] = config.XUNFEI_HOST
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
                # 检查是否强制启用 ProxyAuto 模式
                if config.FORCE_PROXY_AUTO:
                    is_auto_model = True
                    data["model"] = model_pool.get_model()
                    log(f"FORCE_AUTO model={original_model}->{data['model']}")
                elif isinstance(original_model, str) and original_model.lower() in (
                    "proxyautomodel", "proxy-auto-model", "auto_model"
                ):
                    is_auto_model = True
                    data["model"] = model_pool.get_model()
                    log(f"AUTO model={original_model}->{data['model']}")
                else:
                    data["model"] = config.MODEL_MAP.get(original_model, original_model)

            request_body = (
                json.dumps(data, ensure_ascii=False).encode("utf-8")
                if data is not None else original_body
            )
            path = self._upstream_path()
            max_retries = min(config.MAX_RETRY_CHANNELS, len(config.CHANNELS))
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
            import traceback
            for line in traceback.format_exc().splitlines():
                log(f"TRACE: {line[:200]}")


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
