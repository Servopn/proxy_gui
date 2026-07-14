#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全局配置：常量、环境加载、可动态调整的运行时开关与渠道/模型映射。

所有模块共享的不可变常量与此处定义；可变全局开关通过 set/get 函数访问，
避免跨模块直接赋值造成的状态不一致。
"""

import os
import sys
from pathlib import Path


def get_app_dir():
    """返回脚本或打包后可执行文件所在目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(sys.argv[0]).resolve().parent


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

# 连接池配置（可动态调整）
DEFAULT_MAX_POOL_SIZE = 10
MAX_POOL_SIZE = DEFAULT_MAX_POOL_SIZE
CONNECTION_TIMEOUT = 300.0

# 强制 ProxyAuto 模式开关（全局）
FORCE_PROXY_AUTO = False


def set_max_retry_channels(n):
    """设置 503 重试时的最大渠道轮换数"""
    global MAX_RETRY_CHANNELS
    MAX_RETRY_CHANNELS = max(1, min(int(n), len(CHANNELS)))
    from claude_proxy.logger import log
    log(f"503 最大重试渠道数已设置为: {MAX_RETRY_CHANNELS}")


def get_max_retry_channels():
    """获取当前 503 最大重试渠道数"""
    return MAX_RETRY_CHANNELS


def set_force_proxy_auto(enabled):
    """设置是否强制使用 ProxyAuto 模式"""
    global FORCE_PROXY_AUTO
    FORCE_PROXY_AUTO = bool(enabled)
    from claude_proxy.logger import log
    log(f"强制 ProxyAuto 模式: {'开启' if FORCE_PROXY_AUTO else '关闭'}")


def get_force_proxy_auto():
    """获取当前是否强制使用 ProxyAuto 模式"""
    return FORCE_PROXY_AUTO


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
