<#
.SYNOPSIS
    Installs, runs or removes the SYSTEM scheduled task for boot_camera_probe.py.

.DESCRIPTION
    Run from an administrator PowerShell:
      -Install  registers the task to run as SYSTEM at every startup
      -RunNow   runs it right away as SYSTEM (quick check, with you signed in)
      -Remove   deletes the task
    The log goes to C:\ProgramData\VisionAuth\boot_camera_probe.log.
#>
param(
    [switch]$Install,
    [switch]$RunNow,
    [switch]$Remove,
    [int]$Seconds = 300
)

$ErrorActionPreference = "Stop"
$TaskName = "VisionAuthBootCameraProbe"

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this from PowerShell as administrator."
}

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Task removed."
    return
}

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = (& python -c "import sys; print(sys.executable)").Trim()
$userSite = (& python -c "import site; print(site.getusersitepackages())").Trim()
$script = Join-Path $PSScriptRoot "boot_camera_probe.py"

if ($Install -or $RunNow) {
    $action = New-ScheduledTaskAction -Execute $python `
        -Argument "`"$script`" --site `"$userSite`" --seconds $Seconds" `
        -WorkingDirectory $projectRoot
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $taskPrincipal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
        -Principal $taskPrincipal -Settings $settings -Force | Out-Null
    Write-Host "Task registered: runs $python as SYSTEM at startup."
}

if ($RunNow) {
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "Task started. Read C:\ProgramData\VisionAuth\boot_camera_probe.log in about a minute."
}
