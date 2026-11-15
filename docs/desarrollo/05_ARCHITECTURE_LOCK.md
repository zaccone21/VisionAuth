Arquitectura (INMUTABLE)

Camera → Recognition → Liveness → EventBus → Consumers

Módulos
camera/
recognition/
enrollment/
liveness/
events/
persistence/
services/
config/
utils/
Eventos del sistema
FACE_DETECTED
FACE_RECOGNIZED
AUTH_SUCCESS
AUTH_FAILED
UNLOCK_REQUESTED
Reglas de diseño
El core NO depende del sistema operativo
Todo módulo es independiente
Comunicación solo vía EventBus
Type hints obligatorios
Logging obligatorio
Tests desde Fase 1
Persistencia
JSON config
users/<user>/
embedding.npy
metadata.json
Stack

Python 3.12+, OpenCV, InsightFace, ONNX Runtime, MediaPipe, PyTest

Regla crítica

Este documento es inmutable. Toda implementación debe seguirlo sin reinterpretación.