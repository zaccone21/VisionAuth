<#
.SYNOPSIS
    Installs VisionAuth: the unlock service and the credential provider.

.DESCRIPTION
    Run from PowerShell as administrator, signed in as the user to unlock:
        .\scripts\install.ps1 [-SkipLockScreen] [-Camera <index>]

    0. Checks the Python dependencies.
    1. Writes C:\ProgramData\VisionAuth\config.json. The account to unlock is
       the one running this script; a reinstall keeps the camera and sensitivity.
       If no face is enrolled yet, opens the enrollment window for the first one.
    2. Registers and starts the "VisionAuth" service (SYSTEM, automatic start).
    3. Copies the credential provider to C:\Program Files\VisionAuth and registers it.
    4. Asks for the account password if none is stored yet (scripts\set_password.py).

    Build the DLL first with: sh credential_provider/build.sh
    Undo everything with scripts\uninstall.ps1.
#>
param(
    [int]$Camera = 0,
    # Skip the clock screen, so locking shows the sign-in screen and its island
    [switch]$SkipLockScreen
)

$ErrorActionPreference = "Stop"
$ServiceName = "VisionAuth"
$Clsid = "{AF1032B6-3657-4B4C-B230-7237F0183A6C}"
$ProgramData = "C:\ProgramData\VisionAuth"
$InstallDir = Join-Path $env:ProgramFiles "VisionAuth"
$DllName = "VisionAuthCredentialProvider.dll"

$identity = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Ejecutá este script desde PowerShell como administrador."
}

$projectRoot = Split-Path -Parent $PSScriptRoot
$builtDll = Join-Path $projectRoot "credential_provider\build\$DllName"
if (-not (Test-Path $builtDll)) { throw "Falta $builtDll. Compilalo con: sh credential_provider/build.sh" }
$dataDir = Join-Path $projectRoot "data"
$configFile = Join-Path $ProgramData "config.json"

# The command line prints face names with accents
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
Set-Location $projectRoot

# PowerShell 5.1 turns a redirected stderr line into an error that "Stop" would throw
$dependencies = $false
try { & python -c "import cv2, mediapipe" 2>$null; $dependencies = ($LASTEXITCODE -eq 0) } catch { }
if (-not $dependencies) {
    throw 'Faltan las dependencias de Python. Instalalas con: python -m pip install --user -e ".[dev]"'
}

$python = (& python -c "import sys; print(sys.executable)").Trim()
$userSite = (& python -c "import site; print(site.getusersitepackages())").Trim()
$serviceScript = Join-Path $projectRoot "scripts\visionauth_service.py"
$passwordScript = Join-Path $projectRoot "scripts\set_password.py"

# The boot probe used during development would compete for the camera
Unregister-ScheduledTask -TaskName "VisionAuthBootCameraProbe" -Confirm:$false -ErrorAction SilentlyContinue

# 1. Configuration. A reinstall keeps the camera and the sensitivity.
New-Item -ItemType Directory -Force -Path $ProgramData | Out-Null
$previous = $null
if (Test-Path $configFile) { $previous = Get-Content -Path $configFile -Raw -Encoding UTF8 | ConvertFrom-Json }
$cameraIndex = $Camera
if (-not $PSBoundParameters.ContainsKey("Camera") -and $previous -and $null -ne $previous.camera) {
    $cameraIndex = [int]$previous.camera
}
$sensitivity = if ($previous -and $previous.sensitivity) { $previous.sensitivity } else { "normal" }
$config = [ordered]@{
    account     = $env:USERNAME
    site        = @($userSite)
    data_dir    = $dataDir
    camera      = $cameraIndex
    sensitivity = $sensitivity
}
$config | ConvertTo-Json -Depth 3 | Set-Content -Path $configFile -Encoding UTF8
Write-Host "Configuración escrita: $configFile (cuenta $env:USERNAME, cámara $cameraIndex, sensibilidad $sensitivity)"

# The first face, with the camera just configured. Its name is the one in the
# greeting ("Hola, <nombre>").
$faces = @(& python -m visionauth.cli --data-dir $dataDir faces list)
if ($faces.Count -eq 0) {
    Write-Host "Todavía no hay ninguna cara registrada. Vamos a registrar la tuya."
    $name = Read-Host "Nombre para el saludo (por ejemplo, tu nombre de pila)"
    & python -m visionauth.cli --data-dir $dataDir faces add $name
    if ($LASTEXITCODE -ne 0) { throw "No se registró ninguna cara. Volvé a correr el instalador para intentarlo." }
}

# 2. Service
$existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existing) {
    if ($existing.Status -ne "Stopped") { Stop-Service -Name $ServiceName -Force }
    & sc.exe delete $ServiceName | Out-Null
    Start-Sleep -Seconds 1
}
New-Service -Name $ServiceName `
    -BinaryPathName "`"$python`" `"$serviceScript`"" `
    -DisplayName "VisionAuth" `
    -Description "Desbloquea la sesión cuando reconoce la cara del dueño frente a la cámara." `
    -StartupType Automatic | Out-Null
& sc.exe failure $ServiceName reset= 86400 actions= restart/5000/restart/5000/restart/30000 | Out-Null
Start-Service -Name $ServiceName
Write-Host "Servicio '$ServiceName' instalado y en ejecución."

# 3. Credential provider. LogonUI only runs while the lock or sign-in screen
# is shown, so the DLL is not in use now.
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
$installedDll = Join-Path $InstallDir $DllName
Copy-Item -Path $builtDll -Destination $installedDll -Force
$clsidKey = "HKLM:\SOFTWARE\Classes\CLSID\$Clsid"
New-Item -Path "$clsidKey\InprocServer32" -Force | Out-Null
Set-ItemProperty -Path $clsidKey -Name "(default)" -Value "VisionAuthCredentialProvider"
Set-ItemProperty -Path "$clsidKey\InprocServer32" -Name "(default)" -Value $installedDll
Set-ItemProperty -Path "$clsidKey\InprocServer32" -Name "ThreadingModel" -Value "Apartment"
$providerKey = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Authentication\Credential Providers\$Clsid"
New-Item -Path $providerKey -Force | Out-Null
Set-ItemProperty -Path $providerKey -Name "(default)" -Value "VisionAuthCredentialProvider"
Write-Host "Credential provider registrado: $installedDll"

if ($SkipLockScreen) {
    $personalization = "HKLM:\SOFTWARE\Policies\Microsoft\Windows\Personalization"
    New-Item -Path $personalization -Force | Out-Null
    Set-ItemProperty -Path $personalization -Name "NoLockScreen" -Value 1 -Type DWord
    Write-Host "Pantalla del reloj desactivada: al bloquear se ve la pantalla de inicio de sesión."
}

# 4. Password
$check = & python $passwordScript --check
if ($LASTEXITCODE -ne 0) { throw "No se pudo consultar la contraseña guardada." }
Write-Host $check
if ($check -notmatch "^Hay") {
    & python $passwordScript
    if ($LASTEXITCODE -ne 0) { Write-Warning "No se guardó la contraseña. Corré: python scripts\set_password.py" }
}

Write-Host ""
Write-Host "Listo. Bloqueá la sesión (Win+L) y mirá a la cámara para probarlo."
Write-Host "Para administrar caras y ajustes: .\visionauth.ps1"
Write-Host "Log del servicio: $ProgramData\service.log"
