# AX Review 공개 서버 자동 시작 + 절전 해제 (이 PC가 서버이므로)
#   설치:  powershell -ExecutionPolicy Bypass -File install-autostart.ps1
#   제거:  powershell -ExecutionPolicy Bypass -File install-autostart.ps1 -Uninstall
#   - 로그온하면 start-public.ps1을 최소화 창으로 띄운다 (작업 스케줄러 'AXReview Public').
#   - 전원이 연결된 상태에서는 절전·최대 절전으로 들어가지 않게 한다 (화면 끄기는 그대로).
param([switch]$Uninstall)

$ErrorActionPreference = "Stop"
$Name = "AXReview React Public"
$Root = $PSScriptRoot

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $Name -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "자동 시작을 지웠습니다. (절전 설정은 그대로입니다 — 되돌리려면 Windows 설정 > 전원에서 바꾸세요)"
    exit 0
}

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Minimized -File `"$Root\start-public.ps1`"" -WorkingDirectory $Root
# 로그온 1분 뒤 (Tailscale이 먼저 연결되도록)
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$trigger.Delay = "PT1M"
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit 0 `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5)
Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Settings $settings `
    -Description "AX Review React 공개 서버 (start-public.ps1)" -Force | Out-Null
Write-Host "[완료] 로그온하면 1분 뒤 공개 서버가 자동으로 뜹니다: 작업 스케줄러 '$Name'"

powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
Write-Host "[완료] 전원 연결 시 절전·최대 절전 해제"
Write-Host "참고: Windows 업데이트 재부팅 뒤에는 로그온해야 서버가 뜹니다 (자동 로그온은 보안상 설정하지 않음)."
