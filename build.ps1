$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv was not found in PATH"
}

uv sync --dev
uv run pyinstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name ClaudeProxyGUI `
    --icon claude.ico `
    --paths src `
    --collect-all ttkthemes `
    --hidden-import pystray._win32 `
    --hidden-import win32timezone `
    --hidden-import pythoncom `
    --hidden-import pywintypes `
    --hidden-import claude_proxy.gui.main_window `
    --hidden-import claude_proxy.gui.channel_status `
    --hidden-import claude_proxy.gui.proxy_auto `
    --hidden-import claude_proxy.gui.config_window `
    --hidden-import claude_proxy.gui.key_manager `
    --hidden-import claude_proxy.gui.model_pool `
    --hidden-import claude_proxy.gui.utils `
    --hidden-import claude_proxy.tray `
    --hidden-import claude_proxy.startup `
    --hidden-import claude_proxy.proxy `
    --hidden-import claude_proxy.stats `
    --hidden-import claude_proxy.connection_pool `
    --hidden-import claude_proxy.logger `
    claude_proxy_gui.py

Write-Host "Built: $ProjectRoot\dist\ClaudeProxyGUI.exe"
