#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统计池：ChannelPool（渠道维度评分轮换）与 ModelPool（ProxyAutoModel 维度评分）。

两个池都内置“冷却 + 评分”双模式，并对外提供单例实例 pool / model_pool。
"""

import threading
import time

from claude_proxy import config


class ChannelPool:
    # 动态切换阈值
    WARMUP_REQUESTS = 30          # 全局前30个请求后启用评分
    MIN_CHANNEL_REQUESTS = 5      # 单个渠道至少5个请求后才参与评分
    SCORE_THRESHOLD = 0.6         # 评分低于0.6回到轮询
    COOLDOWN_CHANNELS = 10        # 冷却超过10个渠道也回到轮询

    def __init__(self):
        self.channels = config.CHANNELS
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
                    if not scored:
                        # 无可用渠道，返回默认（理论上不应发生）
                        return ("", "no-channel", 0)

                scored.sort(key=lambda x: x[0], reverse=True)
                # 评分最高的一批渠道中随机选一个
                top_score = scored[0][0]
                top_channels = [ch for score, ch in scored if score == top_score]
                ch = top_channels[self.index % len(top_channels)]
                self.index = (self.index + 1) % len(self.channels)
            else:
                self.mode = "round_robin"
                now = time.time()
                # 轮询时也跳过冷却中的渠道
                ch = None
                for _ in range(len(self.channels)):
                    ch = self.channels[self.index]
                    self.index = (self.index + 1) % len(self.channels)
                    if self.stats[ch["id"]]["cooldown_until"] <= now:
                        break
                if ch is None:
                    # 无可用渠道
                    return ("", "no-channel", 0)

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


class ModelPool:
    """模型评分池 - 按模型维度追踪成功/失败率，用于 ProxyAutoModel 自动选择"""

    WARMUP_REQUESTS = 10
    MIN_MODEL_REQUESTS = 3
    COOLDOWN_SECONDS = 60  # 模型冷却时间（比渠道长，因为模型故障更可能是持续性的）

    def __init__(self, models=None):
        self.models = models or list(config.AUTO_MODEL_POOL)
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
            ch = None
            for _ in range(len(self.models)):
                m = self.models[self.index % len(self.models)]
                self.index += 1
                s = self.stats.get(m)
                if not s or s["cooldown_until"] <= now:
                    return m
            # 全部冷却或模型池为空，返回第一个（如果存在）
            return self.models[0] if self.models else "xopdeepseekv4pro"

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


pool = ChannelPool()
model_pool = ModelPool()
