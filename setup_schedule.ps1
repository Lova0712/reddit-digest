# Windows 작업 스케줄러에 "매일 자동 실행"을 등록하는 스크립트
#
# 사용법 (PowerShell 에서 프로젝트 폴더로 이동 후):
#   powershell -ExecutionPolicy Bypass -File setup_schedule.ps1            # 매일 20:30
#   powershell -ExecutionPolicy Bypass -File setup_schedule.ps1 -Time 07:30 # 시간 바꾸기
#   powershell -ExecutionPolicy Bypass -File setup_schedule.ps1 -Remove     # 등록 해제
#
# 설정 내용
# - 로그인한 상태에서만 실행 (claude 구독 로그인이 필요하기 때문)
# - 그 시간에 컴퓨터가 꺼져 있었으면, 다음에 켰을 때 바로 실행
# - 인터넷 연결이 있을 때만 실행, 노트북 배터리 상태에서도 실행
# - 창 없이(pythonw) 실행, 기록은 output\digest.log 에 남음

param(
    [string]$Time = "20:30",
    [switch]$Remove
)

$TaskName = "RedditDigest"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "작업 '$TaskName' 을(를) 해제했습니다."
    exit 0
}

# 이 스크립트가 있는 폴더 = 프로젝트 폴더
$ProjectDir = $PSScriptRoot
$Python = Join-Path $ProjectDir ".venv\Scripts\pythonw.exe"
$Main = Join-Path $ProjectDir "main.py"

if (-not (Test-Path $Python)) {
    Write-Host "가상환경을 찾을 수 없습니다: $Python"
    Write-Host "먼저 README 의 설치 방법대로 .venv 를 만들어 주세요."
    exit 1
}

$Action = New-ScheduledTaskAction -Execute $Python -Argument "`"$Main`"" -WorkingDirectory $ProjectDir
$Trigger = New-ScheduledTaskTrigger -Daily -At $Time
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)
$Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings `
    -Principal $Principal -Description "Reddit 게임개발 다이제스트 매일 자동 실행" -Force | Out-Null

Write-Host "등록 완료: 매일 $Time 에 실행됩니다. (작업 이름: $TaskName)"
Write-Host "지금 바로 실행해 보기: Start-ScheduledTask -TaskName $TaskName"
