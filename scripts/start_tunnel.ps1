# 一键启动：后端 + Cloudflare Tunnel 快速隧道（无需服务器）
# 用法：powershell -ExecutionPolicy Bypass -File scripts\start_tunnel.ps1

$ErrorActionPreference = "Stop"
Set-Location "H:\synalysis_crew"

# 1. 确保后端（uvicorn:8501）在运行
if (-not (Get-NetTCPConnection -LocalPort 8501 -State Listen -ErrorAction SilentlyContinue)) {
    Write-Host "启动后端服务..."
    Start-Process python -ArgumentList "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "8501" `
        -WorkingDirectory "H:\synalysis_crew" -WindowStyle Hidden
    Start-Sleep -Seconds 7
}

# 2. 确保 cloudflared 存在
$cf = "H:\synalysis_crew\.tmp\cloudflared.exe"
if (-not (Test-Path $cf)) {
    Write-Host "未找到 cloudflared，请先下载到 $cf（github.com/cloudflare/cloudflared releases）" -ForegroundColor Red
    exit 1
}

# 3. 启动快速隧道并等待公网地址
$log = "H:\synalysis_crew\.tmp\tunnel.log"
$err = "H:\synalysis_crew\.tmp\tunnel.err"
Remove-Item $log, $err -Force -ErrorAction SilentlyContinue
Start-Process $cf -ArgumentList "tunnel", "--url", "http://127.0.0.1:8501", "--no-autoupdate" `
    -WindowStyle Hidden -RedirectStandardOutput $log -RedirectStandardError $err

for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 2
    $txt = ""
    if (Test-Path $log) { $txt += Get-Content -Raw $log }
    if (-not $txt -and (Test-Path $err)) { $txt += Get-Content -Raw $err }
    $m = [regex]::Match($txt, "https://[a-z0-9-]+\.trycloudflare\.com")
    if ($m.Success) {
        Write-Host ""
        Write-Host "公网地址: $($m.Value)" -ForegroundColor Green
        Write-Host "提示: 快速隧道地址每次重启会变化；电脑关机后服务停止。" -ForegroundColor Yellow
        exit 0
    }
}
Write-Host "隧道启动超时，请查看 $err" -ForegroundColor Red
exit 1
