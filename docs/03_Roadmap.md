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
| 3 | Enrollment | Hecha, falta calibrar en el setup real |
| 4 | Reconocimiento | Hecha, falta calibrar el umbral |
| 5 | Liveness | Pasivo, sin gestos (ver D10) |
| 6 | Event Bus | Hecha |
| 7 | Servicio residente | No empezada |
| 8 | Integración con Windows | No empezada |
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
- [ ] Enrolarse en el setup final, con la cámara de costado.

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

- [ ] Loop de bajo consumo: la cámara se enciende solo con la sesión bloqueada
      o ante un pedido.
- [ ] Máquina de estados: espera, verificando, éxito o fallo, con espera entre
      intentos y límite de reintentos.
- [ ] Entry point de línea de comandos.

## Fase 8: integración con Windows

En este orden, porque el primer paso puede cambiar el diseño del resto:

1. [ ] **Prueba de concepto: cámara con la sesión bloqueada.** Comprobar si un
       proceso (servicio en Session 0 o tarea de la sesión) puede abrir la
       webcam mientras está la pantalla de bloqueo. Para el proceso de la
       sesión: `python scripts/lock_screen_camera_probe.py`.
2. [ ] Detectar bloqueo y desbloqueo de la sesión (`WTSRegisterSessionNotification`).
3. [ ] Comunicación local entre el servicio y el Credential Provider (named pipe).
4. [ ] Guardar la contraseña cifrada (DPAPI o secreto LSA). Windows exige la
       contraseña real para iniciar sesión.
5. [ ] Credential Provider mínimo en C++: tile "VisionAuth", pide la
       verificación por el pipe y arma las credenciales para el desbloqueo.
       **Desarrollar y probar en una máquina virtual.**
6. [ ] Instalación como servicio, instalador y guía de desinstalación y
       recuperación.

## Fase 9: GUI

- [x] Pantalla de enrollment tipo Face ID.
- [ ] Animación de reconocimiento en la demo de reconocimiento.
- [ ] En la pantalla de bloqueo: solo un ícono y texto de estado. El
      Credential Provider no permite video ni animaciones fluidas.

## Próximos pasos

1. Probar el enrollment en el desktop con Windows y la cámara de costado.
2. Prueba de concepto de la cámara con la sesión bloqueada.
3. Calibrar el umbral de reconocimiento.
4. Servicio residente y comunicación con el Credential Provider.
