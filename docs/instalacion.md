# Instalación

Esta guía instala VisionAuth desde cero. Lleva unos 20 minutos, la mayor
parte esperando descargas.

## 1. Requisitos previos

- **Windows 11 o Windows 10** con una cuenta de administrador.
- **Una webcam** conectada. Conviene que esté donde vas a estar sentado al
  desbloquear (arriba o al costado del monitor).
- **Una contraseña en tu cuenta de Windows.** VisionAuth entra con la
  contraseña, no con el PIN. Si tu cuenta es de Microsoft (entrás con un
  email), es la contraseña de tu cuenta de Microsoft.

### Python

Python 3.12 o más nuevo. Si no lo tenés, instalalo desde
[python.org](https://www.python.org/downloads/windows/) y marcá **"Add
python.exe to PATH"**, o con:

```powershell
winget install Python.Python.3.12
```

Comprobalo en una PowerShell nueva:

```powershell
python --version
```

### Git

```powershell
winget install Git.Git
```

Git for Windows trae `sh.exe`, que se usa para compilar.

### Compilador (WinLibs)

El componente de la pantalla de inicio es una DLL en C++ que se compila en tu
PC:

```powershell
winget install BrechtSanders.WinLibs.POSIX.UCRT
```

Cerrá y volvé a abrir PowerShell después de instalar todo, para que tome el
PATH nuevo.

## 2. Descargar VisionAuth

```powershell
cd $HOME
git clone https://github.com/zaccone21/VisionAuth.git
cd VisionAuth
```

La carpeta tiene que quedar donde está: el servicio usa el código y las caras
registradas desde ahí.

## 3. Dependencias y modelos

```powershell
python -m pip install --user -e ".[dev]"
python scripts\download_models.py
```

El segundo comando descarga los modelos de reconocimiento facial (YuNet y
SFace, del OpenCV Model Zoo) a `models\` y verifica sus checksums.

Opcional, para comprobar que todo quedó bien:

```powershell
python -m pytest -q
```

## 4. Compilar la DLL

```powershell
& "C:\Program Files\Git\bin\sh.exe" credential_provider/build.sh --test
```

Tiene que terminar con `ALL PASSED` dos veces. La DLL queda en
`credential_provider\build\`.

**Smart App Control.** Si Windows tiene Smart App Control activado, puede
bloquear la DLL recién compilada porque no está firmada. Comprobalo:

```powershell
python -c "import ctypes; ctypes.WinDLL(r'credential_provider\build\VisionAuthCredentialProvider.dll'); print('ok')"
```

Si dice `ok`, seguí. Si dice que una directiva de Control de aplicaciones
bloqueó el archivo, VisionAuth no va a aparecer en la pantalla de inicio. No
desactives Smart App Control para esto: una vez apagado no se puede volver a
prender sin reinstalar Windows.

## 5. Instalar

Abrí **PowerShell como administrador** (clic derecho en Inicio > Terminal
(Administrador)), andá a la carpeta y corré el instalador:

```powershell
cd $HOME\VisionAuth
.\scripts\install.ps1 -SkipLockScreen
```

Si PowerShell no deja correr scripts, habilitalos para tu usuario y volvé a
intentar:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

El instalador:

1. **Registra tu cara**, si todavía no hay ninguna. Te pide un nombre (el del
   saludo, "Hola, <nombre>") y abre la cámara: mirá la pantalla y girá la
   cabeza despacio hasta completar el círculo.
2. Escribe la configuración en `C:\ProgramData\VisionAuth\config.json`.
3. Instala y arranca el servicio `VisionAuth`.
4. Copia la DLL a `C:\Program Files\VisionAuth` y la registra en la pantalla
   de inicio.
5. **Te pide la contraseña de tu cuenta** y la verifica con Windows. Queda
   guardada en un secreto del sistema (ver [Seguridad](seguridad.md)).

`-SkipLockScreen` saca la pantalla del reloj: al bloquear se va directo a la
pantalla de inicio de sesión, donde se ve la isla. Sin esa opción, hay que
tocar una tecla para ver la isla. Con `-Camera <número>` se elige otra cámara
(por defecto, la 0).

## 6. Probarlo

Bloqueá con **Win+L** y mirá a la cámara. Arriba de la pantalla aparece la
isla: "Mirá a la cámara", "Verificando…" y, al reconocerte, "Hola, <nombre>"
y entra.

Si no te reconoce, desde el menú podés sumar muestras a tu cara o probar el
reconocimiento: ver [Uso](uso.md).

## Actualizar

```powershell
cd $HOME\VisionAuth
git pull
python -m pip install --user -e ".[dev]"
& "C:\Program Files\Git\bin\sh.exe" credential_provider/build.sh --test
.\scripts\install.ps1 -SkipLockScreen   # como administrador
```

Reinstalar conserva las caras, la cámara y la sensibilidad.

## Desinstalar

Ver [Recuperación](recuperacion.md#desinstalar).
