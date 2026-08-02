# Synalysis Crew 一键启动脚本
# 检查 .env 是否存在（不存在给出中文提示），然后启动 Streamlit。

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$envFile = Join-Path $Root ".env"
if (-not (Test-Path -LiteralPath $envFile)) {
    Write-Host ""
    Write-Host "提示：未找到 .env 文件。" -ForegroundColor Yellow
    Write-Host "  - 如有 .env.example，请先执行：Copy-Item .env.example .env，并填入 DEEPSEEK_API_KEY 等变量；" -ForegroundColor Yellow
    Write-Host "  - 没有 API Key 也能正常使用：AI 分析将自动降级为规则引擎，指标与图表功能不受影响。" -ForegroundColor Yellow
    Write-Host ""
}

try {
    streamlit run app.py
}
catch {
    Write-Host "未找到 streamlit 命令，改用 python -m streamlit 启动……" -ForegroundColor Cyan
    python -m streamlit run app.py
}

