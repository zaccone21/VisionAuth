# Seguridad

VisionAuth prioriza la comodidad: que la PC se abra sola cuando te sentás.
Antes de instalarlo, conviene saber qué protege y qué no.

## Lo que no protege

**Fotos y videos.** Una webcam común ve una imagen plana, igual que un
celular mostrando una foto. VisionAuth tiene un chequeo de "cara viva"
(movimiento natural entre cuadros) que frena una foto quieta, pero una foto
o un video tuyo bien hechos podrían llegar a desbloquear la PC. Windows Hello
con cámara infrarroja mide profundidad y es mucho más difícil de engañar;
VisionAuth no lo reemplaza.

**Personas muy parecidas.** Un familiar muy parecido (por ejemplo, un
gemelo) podría ser reconocido. La sensibilidad `estricta` lo hace menos
probable.

**Quien ya es administrador de la PC.** La contraseña de tu cuenta queda
guardada en un secreto del sistema (LSA) que solo pueden leer el sistema y
los administradores. Cualquier persona con permisos de administrador en esa
PC puede leerla.

## Lo que sí cuida

- **El PIN y la contraseña siguen disponibles** en "Opciones de inicio de
  sesión". VisionAuth es una opción más.
- **La contraseña nunca se muestra ni se escribe en un archivo.** Se pide al
  instalar, se verifica con Windows y va directo al secreto LSA.
- **Solo el servicio puede autorizar la entrada.** La pantalla de inicio le
  pregunta al servicio por un canal (`\\.\pipe\VisionAuth`) que solo SYSTEM
  puede abrir, y comprueba que quien responde corre como SYSTEM.
- **Cada reconocimiento sirve una sola vez** y vence a los 15 segundos.
- **Si la contraseña guardada falla**, deja de intentarlo hasta el próximo
  bloqueo, para no bloquear tu cuenta por intentos fallidos.
- **Tus datos quedan en tu PC.** No se envía nada a internet; las caras
  registradas están en la carpeta `data\` y nunca se suben a git.

## Recomendaciones

- Usalo en una PC personal, no en una compartida ni de trabajo con datos
  sensibles.
- No le des permisos de administrador a otras personas en esa PC.
- Si pensás que alguien pudo entrar con una foto, subí la sensibilidad a
  `estricta` y revisá el log (`.\visionauth.ps1`, opción 13): cada entrada
  queda registrada con la similitud.

## Sin garantía

VisionAuth se distribuye con licencia MIT, "tal cual", sin garantía. Si algo
falla en la pantalla de inicio, [la guía de recuperación](recuperacion.md)
explica cómo entrar y sacarlo.
