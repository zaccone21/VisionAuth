# Roadmap

Última actualización: 2026-11-14.

## Objetivo

Desbloquear la sesión de Windows del desktop con la cara al sentarse, con una
webcam RGB ubicada al costado de la pantalla. Ver [01_PRD](01_PRD.md) y
[06_Decisiones](06_Decisiones.md).

## Estado por fase

| Fase | Tema | Estado |
|---|---|---|
| 1 | Estructura, configuración, logging | Parcial |
| 2 | Cámara | Hecha |
| 3 | Enrollment | Hecha |
| 4 | Reconocimiento | Hecha, falta calibrar el umbral |
| 5 | Liveness | Pasivo, sin gestos (ver D10) |
| 6 | Event Bus | Hecha |
| 7 | Servicio residente | Hecha |
| 8 | Integración con Windows | Funciona (v0.1.0) |
| 9 | GUI | Parcial: interfaz de enrollment tipo Face ID |

## Fase 1: estructura, configuración, logging

- [x] Estructura de paquetes y tests.
- [x] `EnrollmentConfig` (dataclass).
- [ ] Configuración persistente en JSON, según el SDD.
- [ ] Logging con rotación, según el SDD.
- [ ] Deuda: 57 errores de `ruff` y formateo de `black` previos.

## Fase 2: cámara

- [x] `Camera` sobre OpenCV, con DirectShow en Windows.

## Fase 3: enrollment

- [x] Captura con filtros de calidad (nitidez, tamaño, centrado, estabilidad).
- [x] Poses reales de la cabeza (yaw/pitch desde los puntos de la cara).
- [x] Agregar muestras a un usuario existente (`append`).
- [x] Interfaz tipo Face ID (`visionauth/ui`).
- [x] Detectar caras con cámaras 16:9 (la proporción de la cara se mide en
      píxeles; antes se descartaban todas).
- [ ] Verificar en Windows que el anillo se ilumine del lado correcto.
- [ ] Calibrar los umbrales de pose (`pose_yaw_threshold`,
      `pose_pitch_threshold`, `NEUTRAL_PITCH_RATIO`) con los ángulos que guarda
      cada muestra en `profile.json`.
- [x] Enrolarse en el setup final, con la cámara de costado (2026-11-14:
      8 muestras; la autenticación da similitud 0.78 con umbral 0.45).

## Fase 4: reconocimiento

- [x] Detección con MediaPipe BlazeFace.
- [x] Embeddings SFace de 128 dimensiones con alineación YuNet.
- [x] Comparación contra la muestra enrolada más parecida.
- [ ] Calibrar el umbral (hoy 0.45, provisional): medir similitudes contra
      caras de otras personas (FAR) y propias en distintas luces (FRR).

## Fase 5: liveness

- [x] Heurística actual: microvariaciones del recuadro y de los embeddings.
- [x] ~~Desafío activo (parpadeo o giro de cabeza)~~: descartado, ver D10.
- [ ] Probar qué pasa con una foto en el celular, para saber el riesgo real.

## Fase 6: Event Bus

- [x] Bus sincrónico y thread-safe.
- [x] Que `AuthService` publique `FACE_RECOGNIZED`, `AUTH_SUCCESS`,
      `AUTH_FAILED` y `UNLOCK_REQUESTED` (si recibe un `event_bus`).

## Fase 7: servicio residente

- [x] La cámara se enciende solo con la sesión bloqueada (D13).
- [x] Estados: espera, verificando y verificado (15 s, se entrega una sola
      vez), con pausas tras fallos.
- [x] Servicio de Windows: `scripts/visionauth_service.py` (`--console` para
      correrlo en primer plano).

## Fase 8: integración con Windows

En este orden, porque el primer paso puede cambiar el diseño del resto:

1. [x] **Prueba de concepto: cámara con la sesión bloqueada.** Un proceso de
       la sesión del usuario recibe frames y detecta la cara con la pantalla
       bloqueada, también si abre la cámara después de bloquear (D11).
       Desde SYSTEM también funciona, y al prender la PC Windows ya deja una
       sesión bloqueada (D12). Scripts: `scripts/dev/lock_screen_camera_probe.py`,
       `scripts/dev/boot_camera_probe.py`.
2. [ ] Detectar bloqueo y desbloqueo de la sesión. Ya existe la consulta
       puntual (`integration/windows/session.py`); falta la notificación
       (`WTSRegisterSessionNotification`).
3. [x] Named pipe `\\.\pipe\VisionAuth`, solo SYSTEM (D13).
4. [x] Contraseña en un secreto LSA (`scripts/set_password.py`).
5. [x] Credential Provider en C++ (`credential_provider/`), con arnés de
       pruebas. No hay máquina virtual (Windows 11 Home): se prueba en el
       equipo real, con el PIN de respaldo y la guía de recuperación del
       README.
6. [x] `scripts/install.ps1`, `scripts/uninstall.ps1` y guía de recuperación.
7. [x] Desbloqueo real con Win+L (2026-11-14): de 6 a 7.5 s desde el
       bloqueo. Falta probarlo al prender la PC.
8. [ ] Medir y acortar el tiempo hasta que la cámara está lista al prender.

## Fase 9: GUI

- [x] Pantalla de enrollment tipo Face ID.
- [ ] Animación de reconocimiento en la demo de reconocimiento.
- [ ] En la pantalla de bloqueo: solo un ícono y texto de estado. El
      Credential Provider no permite video ni animaciones fluidas.

## Próximos pasos

1. Acortar el tiempo hasta desbloquear.
2. Feedback visual en la pantalla de bloqueo.
3. Calibrar el umbral de reconocimiento.
