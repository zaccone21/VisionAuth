# Software Design Document

## Arquitectura

VisionAuth se divide en capas:

-   Camera
-   Recognition
-   Enrollment
-   Liveness
-   Event Bus
-   Persistence
-   Services
-   Integration

El núcleo nunca depende del sistema operativo.

## Flujo

Camera -\> Recognition -\> Liveness -\> EventBus -\> Consumer

## Eventos

-   FACE_DETECTED
-   FACE_RECOGNIZED
-   AUTH_SUCCESS
-   AUTH_FAILED
-   UNLOCK_REQUESTED

## Persistencia

Configuración: - JSON

Usuarios: data/users/`<usuario>`{=html}/ - embedding.npy - metadata.json

## Estructura inicial

visionauth/ - camera/ - recognition/ - enrollment/ - events/ -
persistence/ - services/ - config/ - utils/

tests/ docs/ models/ data/

## Calidad

-   Type hints
-   PyTest
-   Ruff
-   Black
-   Docstrings estilo Google
-   Logging con rotación
