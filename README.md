# VisionAuth

Un "Face ID" para Windows: desbloquear la PC con la cara al sentarse,
sin escribir la contraseña. Prioriza la comodidad sobre la seguridad de
nivel empresarial y funciona con una webcam común (RGB).

El núcleo (cámara, detección, reconocimiento, liveness) está en Python y no
depende del sistema operativo. El desbloqueo de la pantalla de inicio de
sesión lo hará un Credential Provider nativo mínimo que le pide la
verificación al núcleo.

## Estado

El núcleo funciona: enrollment con poses reales de la cabeza e interfaz tipo
Face ID, y reconocimiento con SFace. La integración con Windows todavía no
está empezada. Ver [docs/03_Roadmap.md](docs/03_Roadmap.md) para el detalle y
[docs/06_Decisiones.md](docs/06_Decisiones.md) para las decisiones tomadas.

## Stack

Python 3.12, OpenCV 5 (DNN, SFace, YuNet), MediaPipe (BlazeFace), Pillow,
PyTest. Credential Provider (pendiente): C++.

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

Desde la raíz del proyecto (los datos se guardan en `data/` relativo al
directorio desde donde se ejecuta):

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

## Documentación

| Documento | Contenido |
|---|---|
| [01_PRD](docs/01_PRD.md) | Requisitos del producto |
| [02_SDD](docs/02_SDD.md) | Diseño original (parcialmente desactualizado, ver Decisiones) |
| [03_Roadmap](docs/03_Roadmap.md) | Fases, estado y lo que falta |
| [04_CodingStandards](docs/04_CodingStandards.md) | Estándares de código |
| [05_ARCHITECTURE_LOCK](docs/05_ARCHITECTURE_LOCK.md) | Arquitectura base |
| [06_Decisiones](docs/06_Decisiones.md) | Decisiones tomadas y por qué |
