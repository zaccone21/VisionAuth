<p align="center"><img src="assets/logo.png" width="128" alt="VisionAuth"></p>

# VisionAuth

Un "Face ID" para Windows: desbloquear la PC con la cara al sentarse,
sin escribir la contraseña. Prioriza la comodidad sobre la seguridad de
nivel empresarial y funciona con una webcam común (RGB).

El núcleo (cámara, detección, reconocimiento, liveness) está en Python y no
depende del sistema operativo. El desbloqueo de la pantalla de inicio de
sesión lo hace un Credential Provider nativo mínimo (C++) que le pide la
verificación a un servicio de Windows que corre el núcleo.

## Estado

El núcleo funciona: enrollment con poses reales de la cabeza e interfaz tipo
Face ID, y reconocimiento con SFace. El desbloqueo en Windows (servicio y
Credential Provider) está implementado y falta probarlo en la pantalla de
bloqueo real. Ver [docs/03_Roadmap.md](docs/03_Roadmap.md) para el detalle y
[docs/06_Decisiones.md](docs/06_Decisiones.md) para las decisiones tomadas.

## Stack

Python 3.12, OpenCV 5 (DNN, SFace, YuNet), MediaPipe (BlazeFace), Pillow,
PyTest. Credential Provider: C++ compilado con MinGW-w64 (WinLibs).

## Instalación

### Windows

```
git clone https://github.com/zaccone21/VisionAuth.git
cd VisionAuth
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e .[dev]
.venv\Scripts\python scripts\download_models.py
.venv\Scripts\python -m pytest
```

### Linux

```
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python scripts/download_models.py
.venv/bin/python -m pytest
```

`download_models.py` descarga los modelos de reconocimiento (SFace y YuNet,
OpenCV Model Zoo) y verifica sus checksums. Sin ellos los tests de enrollment
y el reconocimiento fallan.

## Uso

Los perfiles se guardan en `data/` en la raíz del proyecto, sin importar
desde dónde se ejecute:

```
.venv/bin/python examples/enrollment_demo.py          # registrar tu cara
.venv/bin/python examples/camera_recognition_demo.py  # ver si te reconoce
```

En Windows reemplazá `.venv/bin/python` por `.venv\Scripts\python`.

El enrollment muestra la cámara dentro de un círculo y un anillo que se
completa a medida que girás la cabeza. Si el usuario ya existe, ofrece
agregar muestras a su perfil: conviene enrolarse en el lugar y con la cámara
en la posición donde se va a desbloquear.

Los datos biométricos (`**/data/users/`) nunca se suben a git.

## Desbloqueo de Windows

Requiere estar enrolado y el compilador WinLibs
(`winget install BrechtSanders.WinLibs.POSIX.UCRT`).

```
sh credential_provider/build.sh --test              # compila la DLL y corre sus tests
.\scripts\install.ps1 -ProfileName <tu perfil>      # PowerShell como administrador
```

El instalador registra el servicio `VisionAuth` (SYSTEM, inicio automático),
el Credential Provider en `C:\Program Files\VisionAuth` y pide la contraseña
de tu cuenta (para una cuenta de Microsoft, la de Microsoft; el PIN no
alcanza). La contraseña queda en un secreto LSA que solo leen SYSTEM y los
administradores. Log del servicio: `C:\ProgramData\VisionAuth\service.log`.

Para quitarlo: `.\scripts\uninstall.ps1` (como administrador).

**Si la pantalla de inicio deja de funcionar:** el PIN sigue disponible en
"Opciones de inicio de sesión". Si aun así no se puede entrar, mantené Shift
y elegí Reiniciar en la pantalla de inicio, después Solucionar problemas >
Opciones avanzadas > Símbolo del sistema, y borrá la DLL (en ese modo la
letra de unidad puede ser otra):

```
del "C:\Program Files\VisionAuth\VisionAuthCredentialProvider.dll"
```

Sin la DLL, Windows ignora el Credential Provider registrado.

## Documentación

| Documento | Contenido |
|---|---|
| [01_PRD](docs/01_PRD.md) | Requisitos del producto |
| [02_SDD](docs/02_SDD.md) | Diseño original (parcialmente desactualizado, ver Decisiones) |
| [03_Roadmap](docs/03_Roadmap.md) | Fases, estado y lo que falta |
| [04_CodingStandards](docs/04_CodingStandards.md) | Estándares de código |
| [05_ARCHITECTURE_LOCK](docs/05_ARCHITECTURE_LOCK.md) | Arquitectura base |
| [06_Decisiones](docs/06_Decisiones.md) | Decisiones tomadas y por qué |
