<#
.SYNOPSIS
    VisionAuth menu: enrolled faces, the stored password and the settings.

.DESCRIPTION
    Run from the project folder:
        .\visionauth.ps1
    It asks for administrator rights if it does not have them: the stored
    password, the service and the settings in the registry need them.

    Faces and settings go through the Python command line
    (python -m visionauth.cli); this script draws the menu and handles the
    service and the registry.
#>
$ErrorActionPreference = "Continue"
$ServiceName = "VisionAuth"
$ProjectRoot = $PSScriptRoot
$ProgramData = "C:\ProgramData\VisionAuth"
$LogFile = Join-Path $ProgramData "service.log"
$SettingsKey = "HKLM:\SOFTWARE\VisionAuth"
$PolicyKey = "HKLM:\SOFTWARE\Policies\Microsoft\Windows\Personalization"
$DefaultSettleMs = 4000

$identity = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit
}

# Face names have accents: read and write the command line in UTF-8
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
Set-Location $ProjectRoot

$Esc = [char]27
$Coral = "$Esc[38;2;217;119;87m"
$Gray = "$Esc[38;2;150;146;140m"
$Reset = "$Esc[0m"

$Banner = @(
    "██╗   ██╗██╗███████╗██╗ ██████╗ ███╗   ██╗ █████╗ ██╗   ██╗████████╗██╗  ██╗"
    "██║   ██║██║██╔════╝██║██╔═══██╗████╗  ██║██╔══██╗██║   ██║╚══██╔══╝██║  ██║"
    "██║   ██║██║███████╗██║██║   ██║██╔██╗ ██║███████║██║   ██║   ██║   ███████║"
    "╚██╗ ██╔╝██║╚════██║██║██║   ██║██║╚██╗██║██╔══██║██║   ██║   ██║   ██╔══██║"
    " ╚████╔╝ ██║███████║██║╚██████╔╝██║ ╚████║██║  ██║╚██████╔╝   ██║   ██║  ██║"
    "  ╚═══╝  ╚═╝╚══════╝╚═╝ ╚═════╝ ╚═╝  ╚═══╝╚═╝  ╚═╝ ╚═════╝    ╚═╝   ╚═╝  ╚═╝"
)

# ---------------------------------------------------------------------------
# Reading the state

function Invoke-Cli {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & python -m visionauth.cli @Arguments
}

function Get-Faces {
    @(Invoke-Cli faces list) | Where-Object { $_ } | ForEach-Object {
        $fields = $_ -split "`t"
        [pscustomobject]@{ Name = $fields[0]; Samples = $fields[1]; Created = $fields[2] }
    }
}

function Get-Settings {
    $settings = @{}
    foreach ($line in @(Invoke-Cli config show)) {
        $fields = $line -split "`t", 2
        if ($fields.Count -eq 2) { $settings[$fields[0]] = $fields[1] }
    }
    $settings
}

function Get-ServiceState {
    $service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if (-not $service) { return "no instalado" }
    if ($service.Status -eq "Running") { return "activo" }
    if ($service.StartType -eq "Manual") { return "en pausa" }
    return "detenido"
}

function Get-SettleSeconds {
    $value = (Get-ItemProperty -Path $SettingsKey -Name DisplaySettleMs -ErrorAction SilentlyContinue).DisplaySettleMs
    if ($null -eq $value) { $value = $DefaultSettleMs }
    [math]::Round($value / 1000)
}

function Test-LockScreenSkipped {
    (Get-ItemProperty -Path $PolicyKey -Name NoLockScreen -ErrorAction SilentlyContinue).NoLockScreen -eq 1
}

# ---------------------------------------------------------------------------
# Drawing

function Show-Header {
    param([string]$State, [string]$Account, [int]$FaceCount)
    Clear-Host
    Write-Host ""
    foreach ($line in $Banner) { Write-Host "  $Coral$line$Reset" }
    Write-Host ""
    $accountText = if ($Account) { $Account } else { "-" }
    Write-Host "  servicio: $State   cuenta: $accountText   caras: $FaceCount"
    Write-Host "  $Gray$('─' * 46)$Reset"
}

function Wait-Return {
    Write-Host ""
    Read-Host "Enter para volver" | Out-Null
}

function Select-Face {
    param([string]$Prompt)
    $faces = @(Get-Faces)
    if ($faces.Count -eq 0) {
        Write-Host "No hay caras registradas."
        return $null
    }
    for ($i = 0; $i -lt $faces.Count; $i++) { Write-Host ("  {0}  {1}" -f ($i + 1), $faces[$i].Name) }
    $choice = Read-Host $Prompt
    $index = 0
    if ([int]::TryParse($choice, [ref]$index) -and $index -ge 1 -and $index -le $faces.Count) {
        return $faces[$index - 1].Name
    }
    Write-Host "Opción inválida."
    $null
}

function Restart-VisionAuth {
    if ((Get-ServiceState) -eq "activo") {
        Restart-Service -Name $ServiceName -Force
        Write-Host "Servicio reiniciado con el ajuste nuevo."
    }
}

# ---------------------------------------------------------------------------
# Actions

function Show-Faces {
    $faces = @(Get-Faces)
    if ($faces.Count -eq 0) { Write-Host "No hay caras registradas."; return }
    $faces | ForEach-Object {
        $date = if ($_.Created) { $_.Created.Substring(0, [math]::Min(10, $_.Created.Length)) } else { "" }
        [pscustomobject]@{ Nombre = $_.Name; Muestras = $_.Samples; Registrada = $date }
    } | Format-Table -AutoSize | Out-Host
}

function Add-Face {
    Write-Host "El nombre es el que aparece en el saludo (""Hola, <nombre>"")."
    $name = Read-Host "Nombre"
    if (-not $name) { return }
    Write-Host "Se abre la cámara: mirá la pantalla y girá la cabeza despacio. Q para cancelar."
    Invoke-Cli faces add $name
}

function Add-Samples {
    $name = Select-Face "Número de la cara"
    if (-not $name) { return }
    Write-Host "Se abre la cámara. Conviene hacerlo desde donde desbloqueás la PC. Q para cancelar."
    Invoke-Cli faces add-samples $name
}

function Rename-Face {
    $name = Select-Face "Número de la cara a renombrar"
    if (-not $name) { return }
    $new = Read-Host "Nombre nuevo"
    if (-not $new) { return }
    Invoke-Cli faces rename $name $new
}

function Remove-Face {
    $faces = @(Get-Faces)
    $name = Select-Face "Número de la cara a eliminar"
    if (-not $name) { return }
    if ($faces.Count -eq 1) {
        Write-Host "${Coral}Es la única cara registrada: VisionAuth deja de desbloquear hasta que registres otra.$Reset"
    }
    $confirm = Read-Host "Escribí '$name' para confirmar"
    if ($confirm -cne $name) { Write-Host "No coincide: no se borró nada."; return }
    Invoke-Cli faces remove $name
}

function Set-Password {
    Write-Host "La contraseña de tu cuenta de Windows (para una cuenta de Microsoft, la de Microsoft; el PIN no sirve)."
    & python (Join-Path $ProjectRoot "scripts\set_password.py")
}

function Set-Camera {
    Write-Host "Buscando cámaras..."
    $cameras = @(Invoke-Cli cameras)
    if ($cameras.Count -eq 0) { Write-Host "No se encontró ninguna cámara."; return }
    Write-Host ("Cámaras que abren: " + ($cameras -join ", "))
    $choice = Read-Host "Número de cámara"
    if ($cameras -notcontains $choice) { Write-Host "Opción inválida."; return }
    Invoke-Cli config set camera $choice
    if ($LASTEXITCODE -eq 0) { Restart-VisionAuth }
}

function Set-Sensitivity {
    Write-Host "  1  estricta    reconoce solo con mucha seguridad (más rechazos)"
    Write-Host "  2  normal      recomendada"
    Write-Host "  3  permisiva   reconoce más fácil, con poca luz o de costado"
    $levels = @{ "1" = "estricta"; "2" = "normal"; "3" = "permisiva" }
    $choice = Read-Host "Opción"
    if (-not $levels.ContainsKey($choice)) { Write-Host "Opción inválida."; return }
    Invoke-Cli config set sensitivity $levels[$choice]
    if ($LASTEXITCODE -eq 0) { Restart-VisionAuth }
}

function Set-SettleDelay {
    Write-Host "Después de despertar la PC, VisionAuth espera este tiempo antes de entrar,"
    Write-Host "para que llegues a ver la pantalla de inicio. Con un monitor que tarda en prender, subilo."
    $choice = Read-Host "Segundos (0 a 30)"
    $seconds = 0
    if (-not [int]::TryParse($choice, [ref]$seconds) -or $seconds -lt 0 -or $seconds -gt 30) {
        Write-Host "Tiene que ser un número de 0 a 30."
        return
    }
    New-Item -Path $SettingsKey -Force | Out-Null
    Set-ItemProperty -Path $SettingsKey -Name DisplaySettleMs -Value ($seconds * 1000) -Type DWord
    Write-Host "Listo. Vale desde el próximo bloqueo."
}

function Switch-LockScreen {
    if (Test-LockScreenSkipped) {
        Remove-ItemProperty -Path $PolicyKey -Name NoLockScreen -ErrorAction SilentlyContinue
        Write-Host "La pantalla del reloj vuelve a aparecer al bloquear (hay que tocar una tecla para ver la isla)."
    } else {
        New-Item -Path $PolicyKey -Force | Out-Null
        Set-ItemProperty -Path $PolicyKey -Name NoLockScreen -Value 1 -Type DWord
        Write-Host "Al bloquear se va directo a la pantalla de inicio de sesión, con la isla."
        Write-Host "Mientras esté así, Windows muestra ""administrado por su organización"" en los ajustes"
        Write-Host "de la pantalla de bloqueo: es por este ajuste, no hay ninguna organización."
    }
}

function Switch-Pause {
    if ((Get-ServiceState) -eq "activo") {
        Set-Service -Name $ServiceName -StartupType Manual
        Stop-Service -Name $ServiceName -Force
        Write-Host "VisionAuth en pausa: se entra con el PIN hasta que lo reanudes."
    } else {
        Set-Service -Name $ServiceName -StartupType Automatic
        Start-Service -Name $ServiceName
        Write-Host "VisionAuth activo."
    }
}

function Test-Recognition {
    Write-Host "Se abre la cámara con el nombre y la similitud de cada cara. Q para salir."
    Invoke-Cli test
}

function Show-Log {
    if (Test-Path $LogFile) { Get-Content -Path $LogFile -Tail 40 -Encoding UTF8 | Out-Host }
    else { Write-Host "Todavía no hay log." }
}

function Install-VisionAuth {
    $answer = Read-Host "¿Ir directo a la pantalla de inicio al bloquear, sin la del reloj? (s/n)"
    $script = Join-Path $ProjectRoot "scripts\install.ps1"
    if ($answer -match "^(s|si|sí)$") { & $script -SkipLockScreen } else { & $script }
}

# ---------------------------------------------------------------------------
# Menu

while ($true) {
    $state = Get-ServiceState
    $settings = Get-Settings
    $faceCount = @(Get-Faces).Count
    Show-Header -State $state -Account $settings["account"] -FaceCount $faceCount

    if ($state -eq "no instalado") {
        Write-Host "  VisionAuth todavía no está instalado."
        Write-Host ""
        Write-Host "   1  Instalar"
        Write-Host "   0  Salir"
        $choice = Read-Host "`nOpción"
        if ($choice -eq "1") {
            try { Install-VisionAuth } catch { Write-Host "$Coral$($_.Exception.Message)$Reset" }
            Wait-Return
        } elseif ($choice -eq "0") {
            break
        }
        continue
    }

    $settle = Get-SettleSeconds
    $clock = if (Test-LockScreenSkipped) { "omitida" } else { "visible" }
    $pause = if ($state -eq "activo") { "Pausar" } else { "Reanudar" }
    Write-Host " Caras"
    Write-Host "   1  Ver caras registradas"
    Write-Host "   2  Agregar cara"
    Write-Host "   3  Sumar muestras a una cara"
    Write-Host "   4  Renombrar cara"
    Write-Host "   5  Eliminar cara"
    Write-Host " Cuenta"
    Write-Host "   6  Cambiar contraseña guardada"
    Write-Host " Ajustes"
    Write-Host ("   7  Cámara                 {0}" -f $settings["camera"])
    Write-Host ("   8  Sensibilidad           {0}" -f $settings["sensitivity"])
    Write-Host ("   9  Espera al despertar    {0} s" -f $settle)
    Write-Host ("  10  Pantalla del reloj     {0}" -f $clock)
    Write-Host " Servicio"
    Write-Host "  11  $pause"
    Write-Host "  12  Probar reconocimiento"
    Write-Host "  13  Ver log"
    Write-Host "   0  Salir"

    $choice = Read-Host "`nOpción"
    if ($choice -eq "0") { break }
    $actions = @{
        "1" = { Show-Faces }; "2" = { Add-Face }; "3" = { Add-Samples }; "4" = { Rename-Face }
        "5" = { Remove-Face }; "6" = { Set-Password }; "7" = { Set-Camera }; "8" = { Set-Sensitivity }
        "9" = { Set-SettleDelay }; "10" = { Switch-LockScreen }; "11" = { Switch-Pause }
        "12" = { Test-Recognition }; "13" = { Show-Log }
    }
    if (-not $actions.ContainsKey($choice)) { continue }
    Write-Host ""
    try { & $actions[$choice] } catch { Write-Host "$Coral$($_.Exception.Message)$Reset" }
    Wait-Return
}
