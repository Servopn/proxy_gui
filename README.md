# Claude Proxy GUI

Windows 本地 Claude/Anthropic 兼容代理，提供系统托盘、日志窗口、渠道轮换、模型自动选择与运行统计。

服务默认只监听 `127.0.0.1:18081`，并将请求转发到讯飞 MaaS Anthropic 兼容接口。

## 配置

复制示例配置并填写现有渠道密钥：

```powershell
Copy-Item .env.example .env
```

`.env` 包含真实密钥，已被 `.gitignore` 忽略，不要提交到版本库。程序启动时要求 `.env` 与脚本或打包后的 EXE 位于同一目录。

## 使用 uv 运行

```powershell
uv sync
uv run python claude_proxy_gui.py
```

指定端口：

```powershell
uv run python claude_proxy_gui.py --port 18082
```

## 构建 EXE

仓库中的 `claude.ico` 会同时作为 EXE 文件图标。运行：

```powershell
.\build.ps1
```

产物位于 `dist\ClaudeProxyGUI.exe`。运行时仍需将 `.env` 放在 EXE 同目录，密钥不会嵌入二进制。

## 主要行为

- 仅监听本机回环地址。
- 保留查询参数、JSON 与非 JSON 请求体，并支持 chunked 请求。
- 复用可用的上游 HTTPS 连接。
- 区分客户端请求数和上游重试次数。
- 网络密钥测试在后台运行，不阻塞 Tkinter 主线程。
- 退出时正常关闭托盘、HTTP 服务和连接池。
