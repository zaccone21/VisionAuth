<#
.SYNOPSIS
    Removes VisionAuth: the service, the credential provider and the stored password.

.DESCRIPTION
    Run from PowerShell as administrator:
        .\scripts\uninstall.ps1
    Keeps the enrolled profiles in data\users and the logs in C:\ProgramData\VisionAuth.
#>
$ErrorActionPreference = "Stop"
$ServiceName = "VisionAuth"
$Clsid = "{AF1032B6-3657-4B4C-B230-7237F0183A6C}"
$InstallDir = Join-Path $env:ProgramFiles "VisionAuth"

$identity = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Ejecutá este script desde PowerShell como administrador."
}
$projectRoot = Split-Path -Parent $PSScriptRoot

# Credential provider first, so the sign-in screen stops loading it
Remove-Item -Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Authentication\Credential Providers\$Clsid" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -Path "HKLM:\SOFTWARE\Classes\CLSID\$Clsid" -Recurse -Force -ErrorAction SilentlyContinue
if (Test-Path $InstallDir) {
    try {
        Remove-Item -Path $InstallDir -Recurse -Force
    } catch {
        Write-Warning "LogonUI todavía usa la DLL; ya no está registrada. Borrá $InstallDir después de reiniciar."
    }
}
Write-Host "Credential provider quitado."

# Bring the clock screen back if install.ps1 -SkipLockScreen removed it
Remove-ItemProperty -Path "HKLM:\SOFTWARE\Policies\Microsoft\Windows\Personalization" -Name "NoLockScreen" -ErrorAction SilentlyContinue

$service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($service) {
    if ($service.Status -ne "Stopped") { Stop-Service -Name $ServiceName -Force }
    & sc.exe delete $ServiceName | Out-Null
}
Write-Host "Servicio quitado."

& python (Join-Path $projectRoot "scripts\set_password.py") --remove
Unregister-ScheduledTask -TaskName "VisionAuthBootCameraProbe" -Confirm:$false -ErrorAction SilentlyContinue
Write-Host "Listo. Los perfiles en data\users y los logs en C:\ProgramData\VisionAuth no se borraron."
