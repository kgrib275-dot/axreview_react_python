# AX Review (React + FastAPI) 외부 공개 실행 — 이 프로젝트 전용. Streamlit 판(AxReview)과 완전히 별개로 돈다.
#   - 프론트 빌드(frontend/dist)가 없거나 소스보다 오래됐으면 npm run build 를 먼저 돈다.
#   - FastAPI 서버를 127.0.0.1:<로컬 포트> 에 띄우고 Tailscale Funnel 로 공개한다.
#   - Funnel 포트는 10000 (AXREVIEW_FUNNEL_PORT 로 바꿀 수 있음, 443 = Trade_IQ · 8443 = 다른 프로젝트).
#     10000 을 다른 서버(예: Streamlit 판 AX Review, 127.0.0.1:4012)가 쓰고 있으면 그 공개를 끄고 이 프로젝트로 넘겨받는다.
#     넘겨받기 전 그 서버가 아직 켜져 있으면 알려 준다 — 예전 start-public 창은 닫힐 때 10000 공개를 꺼 버리므로 먼저 닫는 게 안전하다.
#   - 종료: 이 창에서 Ctrl+C → 10000 이 아직 이 서버를 가리킬 때만 해제 (funnel reset 은 쓰지 않는다).
#   - 서버가 오류로 죽으면 5초 뒤 다시 띄운다.
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Py = Join-Path $Root "backend\venv\Scripts\python.exe"
$Port = if ($env:AXREVIEW_LOCAL_PORT) { [int]$env:AXREVIEW_LOCAL_PORT } else { 5012 }

function Fail($msg) { Write-Host "`n[오류] $msg" -ForegroundColor Red; exit 1 }
Write-Host "`n  ======================================"
Write-Host "    AX Review (React·FastAPI) 외부 공개"
Write-Host "  ======================================`n"

if (-not (Test-Path $Py)) { Fail "backend\venv 가 없습니다. README 의 설치 순서를 먼저 하세요." }
$ts = (Get-Command tailscale -ErrorAction SilentlyContinue).Source
if (-not $ts -and (Test-Path "$env:ProgramFiles\Tailscale\tailscale.exe")) { $ts = "$env:ProgramFiles\Tailscale\tailscale.exe" }
if (-not $ts) { Fail "Tailscale 이 설치되어 있지 않습니다. https://tailscale.com/download/windows" }
$status = & $ts status --json | ConvertFrom-Json
if ($status.BackendState -ne "Running") { Fail "Tailscale 에 로그인되어 있지 않습니다." }
$dns = $status.Self.DNSName.TrimEnd(".")

# ---- Funnel 포트: 10000 (지금 누가 쓰는지 확인) ----
$FunnelPort = if ($env:AXREVIEW_FUNNEL_PORT) { [int]$env:AXREVIEW_FUNNEL_PORT } else { 10000 }
function Get-FunnelTarget {
    try {
        $fs = & $ts funnel status --json 2>$null | ConvertFrom-Json
        $web = $fs.Web."${dns}:$FunnelPort"
        if ($web) { return $web.Handlers."/".Proxy }
    } catch {}
    return $null
}
$publicUrl = "https://${dns}:$FunnelPort"
Write-Host "[확인] 공개 주소: $publicUrl  (Funnel 포트 $FunnelPort)"

# ---- 이 프로젝트의 start-public 이 이미 떠 있으면 정리 (두 개가 돌면 배치가 두 번 돈다) ----
function Get-ChildTree($id) {
    Get-CimInstance Win32_Process -Filter "ParentProcessId = $id" | ForEach-Object { Get-ChildTree $_.ProcessId; $_.ProcessId }
}
$me = Join-Path $Root "start-public.ps1"
$others = Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe'" |
    Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -and $_.CommandLine.Contains($me) }
foreach ($o in $others) {
    Write-Host "[정리] 이미 실행 중인 이 프로젝트의 공개 창(PID $($o.ProcessId))과 그 서버를 끄고 새로 시작합니다." -ForegroundColor Yellow
    $ids = @(Get-ChildTree $o.ProcessId) + $o.ProcessId
    Stop-Process -Id $ids -Force -ErrorAction SilentlyContinue
}
if ($others) { Start-Sleep -Seconds 2 }

# ---- 로컬 포트 ----
while ((Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) -and $Port -lt 5099) { $Port++ }
Write-Host "[확인] 로컬 포트: $Port"

# ---- 10000 을 다른 서버가 쓰고 있으면 넘겨받기 ----
$prev = Get-FunnelTarget
if ($prev -and $prev -ne "http://127.0.0.1:$Port") {
    Write-Host "[전환] Funnel $FunnelPort 을(를) 지금 $prev 가 쓰고 있습니다 → 그 공개를 끄고 이 프로젝트로 바꿉니다." -ForegroundColor Yellow
    if ($prev -match ':(\d+)$' -and (Get-NetTCPConnection -LocalPort ([int]$Matches[1]) -State Listen -ErrorAction SilentlyContinue)) {
        # Streamlit 판 start-public(2026-10-28 16:14 이후 판)은 닫힐 때 포트가 아직 자기 것일 때만 공개를 끈다 — 그대로 둬도 안전
        Write-Host "  [안내] 기존 서버(로컬 $($Matches[1]))는 켜진 채로 남고 외부 공개만 이쪽으로 옮깁니다." -ForegroundColor Yellow
        Write-Host "         필요 없으면 그 창을 Ctrl+C 로 닫으세요 — 닫아도 이 사이트 공개는 유지됩니다."
    }
    & $ts funnel --https=$FunnelPort off 2>$null | Out-Null
}

# ---- 프론트 빌드 ----
$dist = Join-Path $Root "frontend\dist\index.html"
$srcNewest = (Get-ChildItem (Join-Path $Root "frontend\src") -Recurse -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1).LastWriteTime
if (-not (Test-Path $dist) -or (Get-Item $dist).LastWriteTime -lt $srcNewest) {
    Write-Host "[빌드] 프론트엔드 빌드 중 (npm run build)…"
    Push-Location (Join-Path $Root "frontend")
    try { & npm.cmd run build; if ($LASTEXITCODE -ne 0) { Fail "프론트 빌드 실패" } } finally { Pop-Location }
}

$env:SITE_URL = $publicUrl
$env:AXREVIEW_PORT = "$Port"
$env:AXREVIEW_HOST = "127.0.0.1"
$env:AXREVIEW_SCHEDULER = "1"   # 배치 스케줄러는 공개 서버에서만
try {
    & $ts funnel --bg --https=$FunnelPort "http://127.0.0.1:$Port" | Out-Null
    Write-Host "[공개] $publicUrl  →  127.0.0.1:$Port`n"
    Push-Location (Join-Path $Root "backend")
    while ($true) {
        & $Py serve.py
        if ($LASTEXITCODE -eq 0) { break }
        Write-Host "`n[재시작] 서버가 종료 코드 $LASTEXITCODE 로 멈췄습니다. 5초 뒤 다시 시작합니다." -ForegroundColor Yellow
        Start-Sleep -Seconds 5
    }
} finally {
    Pop-Location
    # 그사이 다른 서버가 이 포트를 넘겨받았으면 건드리지 않는다 (남의 공개를 끄지 않게)
    if ((Get-FunnelTarget) -eq "http://127.0.0.1:$Port") {
        & $ts funnel --https=$FunnelPort off 2>$null | Out-Null
        Write-Host "`n[종료] Funnel 포트 $FunnelPort 공개를 해제했습니다."
    } else {
        Write-Host "`n[종료] Funnel 포트 $FunnelPort 는 다른 서버가 쓰고 있어 그대로 둡니다."
    }
}
