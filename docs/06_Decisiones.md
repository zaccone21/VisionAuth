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

## D10. Sin gestos: liveness pasivo y seguridad mínima

**Decisión.** El desbloqueo no pide gestos (ni parpadeo ni giro de cabeza).
El objetivo es sentarse frente a la PC y que se abra si es el dueño. Se
mantiene la verificación pasiva actual (microvariaciones del recuadro y de los
embeddings).

**Por qué.** El dueño del proyecto prioriza la comodidad y pidió solo la
seguridad mínima.

**Implica.** Una foto o un video del dueño frente a la cámara probablemente
desbloquee la PC. La contraseña de Windows sigue funcionando como alternativa.

## D11. La cámara funciona con la sesión bloqueada desde la sesión del usuario

**Resultado.** El 2026-11-14, `scripts/lock_screen_camera_probe.py` bloqueó la
sesión y siguió leyendo la webcam desde un proceso común de la sesión del
usuario: recibió frames y detectó la cara durante todo el bloqueo, también
tras cerrar y volver a abrir la cámara con la pantalla de contraseña visible.

**Implica.**
- El servicio residente puede correr en la sesión del usuario (por ejemplo,
  una tarea programada al iniciar sesión), sin necesidad de un servicio de
  Windows en Session 0.
- Así solo se puede desbloquear una sesión ya iniciada. El primer inicio de
  sesión después de reiniciar no tiene sesión de usuario: para eso haría
  falta un servicio en Session 0, que no se probó.
- Para saber si la sesión está bloqueada no sirve mirar el escritorio activo:
  la pantalla de bloqueo corre en el escritorio normal y el escritorio seguro
  solo aparece al pedir la contraseña. Se usa `WTSSessionInfoEx`
  (`integration/windows/session.py`).
- Los datos de usuario se guardan siempre en `data/` de la raíz del proyecto,
  sin importar desde dónde se ejecute (`visionauth/paths.py`).

## D12. Al prender la PC, Windows inicia la sesión solo y la bloquea

**Resultado.** El 2026-11-14 se probó con `scripts/boot_camera_probe.py` como
tarea de SYSTEM al arrancar. En dos reinicios y en un arranque en frío
(apagar y prender, tipo de arranque `0x0`), Windows inició la sesión del
usuario sin el PIN unos 14 a 16 segundos después de arrancar y la dejó
bloqueada. Es la opción "Usar mi información de inicio de sesión para
terminar de configurar automáticamente" (ARSO). Con la sesión bloqueada, el
proceso de SYSTEM recibió frames y detectó la cara.

**Implica.**
- En este equipo, el caso "prendo la PC y entro" es desbloquear una sesión
  bloqueada. Igual hace falta el Credential Provider, que es la única forma
  soportada de desbloquear, y la contraseña de la cuenta de Microsoft.
- Depende de que esa opción de Windows siga activa. Si se desactiva, al
  prender no hay sesión y el Credential Provider tendría que iniciarla.
- La tarea programada "al iniciar" arranca unos 35 segundos después del
  boot. Cargar Python, los modelos y la cámara lleva unos 3 segundos, así que
  la demora es del Programador de tareas: el servicio final tiene que ser un
  servicio de Windows de inicio automático.

## D13. Cómo se desbloquea: servicio de Windows, pipe y Credential Provider

**Decisión.**
- Un servicio de Windows (`VisionAuth`, SYSTEM, inicio automático) corre el
  núcleo en Python. Mientras la sesión de la consola está bloqueada, o no hay
  nadie con sesión iniciada, mantiene la cámara abierta e intenta autenticar
  al dueño. Con la sesión desbloqueada la cámara queda cerrada. El servicio
  habla con el SCM por `ctypes`, sin `pywin32`.
- Una verificación exitosa dura 15 segundos y se entrega una sola vez por el
  named pipe `\\.\pipe\VisionAuth`, que solo puede abrir SYSTEM.
- El Credential Provider (C++, `credential_provider/`) consulta el pipe cada
  300 ms desde LogonUI y solo acepta la respuesta si el servidor del pipe
  corre como SYSTEM. Con `MATCH`, le pide a LogonUI entrar solo y arma las
  credenciales con la contraseña guardada en el secreto LSA
  `L$VisionAuthCredential` (`scripts/set_password.py`).
- Si Windows rechaza la contraseña guardada, no vuelve a intentar hasta el
  próximo bloqueo, para no repetir inicios de sesión fallidos.
- Se compila con MinGW-w64 (WinLibs, sin Visual Studio), con la biblioteca
  estándar enlazada estáticamente.

**Implica (seguridad mínima, a pedido del dueño):**
- Cualquier administrador del equipo puede leer la contraseña guardada.
- El servicio ejecuta como SYSTEM el código del proyecto y las librerías de
  Python del usuario, que el usuario puede modificar. En un equipo de un solo
  usuario administrador no agrega un riesgo real.
- Una foto o un video del dueño probablemente desbloquea (D10).


## D14. Velocidad del desbloqueo y estado en la pantalla de bloqueo

**Mediciones (2026-11-14).** Con la versión v0.1.0, del bloqueo al desbloqueo
pasaban de 6 a 7.5 segundos. La cámara de este equipo:
- Abre y da un frame con imagen en ~1.3 s si no se le pide nada. Pedirle
  resolución o fps por DirectShow suma ~2.5 s, y igual entrega 1280x720.
- Da ~14.5 frames reales por segundo con cualquier backend o resolución.
  Media Foundation devuelve cada frame dos veces, y DirectShow, al leerse
  rápido, también puede repetirlos.
- Procesar un frame (BlazeFace + YuNet + SFace) cuesta ~23 ms.

**Decisión.**
- La cámara del servicio se abre sin pedir resolución ni fps.
- Los frames repetidos se descartan antes del liveness: comparan dos frames
  idénticos y lo hacían rechazar caras reales.
- La sesión se revisa cada 0.2 s y la pantalla consulta al servicio cada
  0.2 s. Tras un rechazo del liveness se reintenta a los 0.3 s, no a los 2 s.
- El servicio informa su estado (cámara encendiéndose, buscando, cara a la
  vista, cara no reconocida) y la opción VisionAuth de la pantalla de
  bloqueo lo muestra con un ícono de color y un texto. La opción queda
  seleccionada por defecto, como el rostro de Windows Hello; el PIN sigue en
  "Opciones de inicio de sesión".

## D15. La isla de VisionAuth en la pantalla de inicio de sesión

**Decisión.** El estado se muestra en una "isla": una píldora oscura arriba al
centro de la pantalla de inicio de sesión, con un indicador animado (gris
buscando, azul al ver una cara, ámbar si no la reconoce, verde con un check
al reconocerla) y el estado en letra grande. La dibuja el Credential
Provider en una ventana propia, transparente y que no toma clics ni el foco,
creada en el hilo de LogonUI sobre su ventana (`credential_provider/island.cpp`).
Al reconocer al dueño espera 0.45 s antes de entrar, para que el check se vea.

**Por qué.** Windows no deja que otro programa dibuje sobre la pantalla del
reloj (solo Windows Hello lo hace), y el tile estándar no permite cambiar la
tipografía ni animar. Por eso se desactiva la pantalla del reloj
(`install.ps1 -SkipLockScreen`, política `NoLockScreen`, que funcionó en este
Windows 11 Home) y la isla se dibuja sobre la de inicio de sesión.

**Cómo revisarla sin bloquear:** `credential_provider/build/island_preview.exe
salida.png` renderiza la animación cuadro por cuadro en una imagen.

## D16. Isla estilo Apple/Claude, logo y saludo con el nombre

**Decisión.**
- La isla se dibuja con Direct2D y DirectWrite (Segoe UI Variable en peso
  semibold) desde un hilo propio, sincronizado con el refresco de la pantalla
  (`DwmFlush`), con animaciones de resortes. Con GDI+ y `WM_TIMER` el
  movimiento se veía entrecortado aunque cada cuadro tardaba 1.6 ms.
- Estética: píldora negra pura como la Dynamic Island, texto crema cálido,
  acento coral al verificar, verde al reconocer. El indicador es un glifo
  estilo Face ID (esquinas de visor y una cara) que mira alrededor mientras
  busca y se convierte en un check al reconocer.
- El logo de VisionAuth es ese glifo en coral sobre un cuadrado negro
  redondeado (`assets/logo.png`); también es el ícono de la opción en la
  pantalla de inicio de sesión.
- Al reconocer, la isla dice "Hola, <nombre>". El nombre sale del nombre
  completo de la cuenta de Windows o de `install.ps1 -DisplayName`, y el
  servicio lo manda con el `MATCH`.

**Implica.** Smart App Control está activo en este equipo y bloquea, según
reputación, algunos binarios recién compilados sin firma (bloqueó la vista
previa y una vez la DLL de prueba). Antes de instalar una DLL nueva hay que
comprobar que Windows la deja cargar; si alguna vez la bloquea, VisionAuth
no aparece y se entra con el PIN.

