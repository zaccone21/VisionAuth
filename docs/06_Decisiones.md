# Decisiones

Registro de decisiones del proyecto: qué se decidió, por qué y qué implica.
Fecha de todas las entradas: 2026-11-14.

## D1. Núcleo en Python más un Credential Provider nativo mínimo

**Decisión.** El reconocimiento corre en Python. Para desbloquear la pantalla
de inicio de sesión se escribirá un Credential Provider mínimo en C++ que le
pide la verificación al núcleo por un canal local (named pipe).

**Por qué.** Es la única forma soportada de desbloquear la pantalla de bloqueo
de Windows. Python no puede implementar un Credential Provider, que es una DLL
COM que carga `LogonUI.exe`. Se descartaron dos alternativas: quedarse solo con
el núcleo (no desbloquea nada) y escribir la contraseña con teclado simulado
(frágil e inseguro).

**Implica.**
- Cambia el PRD, que dejaba el Credential Provider fuera de la v1.
- Windows exige la contraseña real para iniciar sesión, así que habrá que
  guardarla cifrada en el equipo (DPAPI o secreto LSA).
- Un Credential Provider con bugs puede romper la pantalla de login, así que
  se desarrolla y prueba en una máquina virtual.

## D2. Webcam RGB común

**Decisión.** El sistema funciona con una webcam común, no con una cámara IR
de Windows Hello.

**Implica.** El liveness tiene que hacerse por software, y con RGB es más
fácil de engañar con una foto o un video. Un desafío activo (parpadeo o giro de
cabeza) es lo mínimo razonable antes de usarlo en serio.

## D3. Modelo de reconocimiento: SFace en lugar de FaceNet

**Decisión.** Los embeddings se generan con SFace (OpenCV Model Zoo,
Apache-2.0, 128 dimensiones), alineando la cara con los 5 puntos que da YuNet.
`scripts/download_models.py` descarga ambos modelos y verifica sus checksums.

**Por qué.** El modelo original `facenet.onnx` nunca se subió al repo y no
había registro de dónde salió, así que ningún clon nuevo podía reconocer caras.
SFace tiene una fuente oficial y una licencia clara, corre en OpenCV (que ya
era dependencia) y es preciso.

**Implica.**
- Los perfiles anteriores (`FaceNet-512`, versión 2) son incompatibles: hay que
  volver a enrolarse. Los perfiles nuevos son `SFace-128`, versión 3.
- El umbral de coincidencia pasa a 0.45. OpenCV recomienda 0.363 para SFace;
  se usa uno algo más estricto. Es provisional hasta calibrarlo.
- El SDD y el ARCHITECTURE_LOCK nombran InsightFace y ONNX Runtime y no están
  actualizados. Actualizarlos requiere el OK del dueño del proyecto, porque el
  Lock se declara inmutable.

## D4. Detección con MediaPipe BlazeFace, con el modelo resuelto dentro del proyecto

**Decisión.** La detección usa `models/blaze_face_short_range.tflite`, que se
busca dentro del proyecto y no relativo al directorio de ejecución.

**Por qué.** Lanzada desde otra carpeta, la detección caía al detector de
respaldo Haar, que OpenCV 5 ya no incluye. Resultado: nunca detectaba una cara
y no avisaba. Ahora, si no hay ningún detector disponible, se registra un error.

## D5. Los datos biométricos nunca van a git

**Decisión.** `**/data/users/` está ignorado en cualquier carpeta.

**Por qué.** Fotos y embeddings del enrollment se habían subido en
`examples/data/users/`, en un repo público. El 2026-11-14 se reescribió el
historial para quitarlos y se forzó el push de la rama `latest-code`.

**Implica.** El commit viejo (`4cc992d`) puede seguir accesible en GitHub por su
hash hasta que GitHub lo limpie. Para borrarlo del todo hay que pedirlo a
GitHub Support. Quien haya clonado el repo antes de esa fecha puede tener una
copia.

## D6. Enrollment por pose real de la cabeza

**Decisión.** El enrollment estima hacia dónde mira la cabeza (yaw y pitch) a
partir de los ojos, la nariz y la boca, y reparte las muestras entre CENTER
(hasta 4), LEFT, RIGHT, UP y DOWN (hasta 2 cada una). Cada muestra guarda su
pose en `profile.json`.

**Por qué.** Antes la "pose" era la posición de la cara en el cuadro, así que
todas las muestras salían frontales. Además, el filtro de outliers descartaba
las muestras más distintas al promedio, que eran justo las de costado. Con la
cámara al costado del monitor, eso perjudica el reconocimiento.

**Implica.**
- El movimiento entre muestras se mide en rotación de la cabeza
  (`min_pose_change`), no en desplazamiento del recuadro.
- El filtro de calidad usa un umbral absoluto (`min_sample_similarity` = 0.4):
  solo descarta muestras que no parecen de la misma persona.
- Lo más importante es enrolarse en el setup final, con la cámara donde va a
  quedar. Para eso existe el modo `append`, que agrega muestras a un usuario
  existente sin perder las anteriores.
- Los umbrales de pose son provisionales hasta calibrarlos con datos reales.

## D7. Comparar contra la muestra más parecida, no contra el promedio

**Decisión.** La autenticación toma la mayor similitud contra las muestras
enroladas, en lugar de compararse contra su promedio (centroide).

**Por qué.** Con muestras de distintos ángulos, el promedio queda "en el medio"
de todas. Una cara de costado puede parecerse poco al promedio y mucho a la
muestra de costado.

## D8. Interfaz tipo Face ID

**Decisión.** El enrollment muestra la cámara en espejo dentro de un círculo
sobre fondo negro, con un anillo de marcas que se alargan hacia donde mira el
usuario y quedan en verde al cubrir cada dirección (`visionauth/ui`).

**Implica.** En la pantalla de bloqueo esto no es posible: el Credential
Provider solo admite un ícono y texto. Ahí la experiencia será como la de
Windows Hello.

## D9. Persistencia en `profile.json`

**Decisión.** Cada usuario se guarda en `data/users/<usuario>/` con
`profile.json` (embeddings, poses, centroide, modelo y versión),
`metadata.json` y las fotos de las muestras.

**Por qué.** Es lo que ya implementaba el código. Difiere del SDD, que pedía
`embedding.npy`. Las fotos permiten volver a generar los embeddings si se cambia
de modelo.
