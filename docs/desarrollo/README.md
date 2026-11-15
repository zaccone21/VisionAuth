# Desarrollo

## Cómo está hecho

```
Pantalla de inicio (LogonUI)                Servicio VisionAuth (SYSTEM)
┌────────────────────────────────┐          ┌──────────────────────────────────┐
│ VisionAuthCredentialProvider   │  STATUS  │ scripts/visionauth_service.py    │
│ (DLL C++)                      │ ───────► │  integration/windows/            │
│  - pregunta cada 200 ms        │ ◄─────── │    unlock_daemon.py  (pipe)      │
│  - dibuja la isla (Direct2D)   │  STATE / │  visionauth/service/             │
│  - entra con la contraseña     │  MATCH   │    unlock_service.py (cámara)    │
│    guardada (secreto LSA)      │          │  visionauth/auth/auth_service.py │
└────────────────────────────────┘          └──────────────────────────────────┘
          \\.\pipe\VisionAuth (solo SYSTEM)
```

- **Núcleo en Python** (`visionauth/`): cámara, detección (BlazeFace/YuNet),
  embeddings (SFace), liveness, enrollment y autenticación. No depende de
  Windows.
- **Servicio** (`scripts/visionauth_service.py`, `integration/windows/`):
  mientras la sesión está bloqueada mantiene la cámara abierta, compara contra
  todas las caras registradas y publica la fase por un named pipe.
- **Credential Provider** (`credential_provider/`): DLL que LogonUI carga en
  la pantalla de inicio. Pregunta al servicio, muestra la isla y, ante un
  `MATCH`, entra con `KERB_INTERACTIVE_UNLOCK_LOGON`.
- **Administración**: `visionauth/cli.py` (caras y ajustes) y `visionauth.ps1`
  (el menú).

## Tests

```powershell
python -m pytest -q
```

Para la DLL, compilar con los tests (Git Bash o el `sh.exe` de Git):

```sh
sh credential_provider/build.sh --test
```

El harness (`credential_provider/test_harness.cpp`) carga variantes de prueba
de la DLL que usan su propio pipe (`\\.\pipe\VisionAuthHarness`), así nunca
hablan con un servicio instalado.

## Vista previa de la isla

```sh
./credential_provider/build/island_preview.exe hoja.png 1.5 logo.png
```

Renderiza una secuencia de la animación (cámara, buscando, en espera,
verificando, no reconocida, saludo) en una hoja PNG, y opcionalmente el logo.

## Sondas

`scripts/dev/` tiene las sondas usadas para decidir la arquitectura (si la
cámara funciona con la sesión bloqueada y al arrancar como SYSTEM). Ver D11 y
D12 en las decisiones.

## Documentos de diseño

| Documento | Contenido |
|---|---|
| [01_PRD](01_PRD.md) | Requisitos del producto |
| [02_SDD](02_SDD.md) | Diseño original (parcialmente desactualizado, ver Decisiones) |
| [03_Roadmap](03_Roadmap.md) | Fases, estado y lo que falta |
| [04_CodingStandards](04_CodingStandards.md) | Estándares de código |
| [05_ARCHITECTURE_LOCK](05_ARCHITECTURE_LOCK.md) | Arquitectura base |
| [06_Decisiones](06_Decisiones.md) | Decisiones tomadas y por qué |

Los diseños y planes de cada funcionalidad nueva están en
[`docs/superpowers/`](../superpowers/).
