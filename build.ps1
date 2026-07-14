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
    claude_proxy_gui.py

Write-Host "Built: $ProjectRoot\dist\ClaudeProxyGUI.exe"
