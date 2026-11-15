# Uso

## El menú

Desde la carpeta de VisionAuth:

```powershell
.\visionauth.ps1
```

Pide permisos de administrador si no los tiene. Arriba muestra si el servicio
está activo, la cuenta que desbloquea y cuántas caras hay registradas.

### Caras

Cada cara registrada desbloquea tu cuenta. Su nombre es el que aparece en el
saludo: si se sienta Ana, la isla dice "Hola, Ana". Los nombres pueden tener
tildes y espacios.

| Opción | Qué hace |
|---|---|
| 1 Ver caras registradas | Nombre, cantidad de muestras y fecha. |
| 2 Agregar cara | Pide el nombre y abre la cámara para registrarla. |
| 3 Sumar muestras a una cara | Vuelve a registrar sobre una cara existente. Sirve si no te reconoce bien: hacelo sentado donde desbloqueás, con la luz de siempre. |
| 4 Renombrar cara | Cambia el nombre (y el saludo). |
| 5 Eliminar cara | Borra la cara y sus fotos. Pide escribir el nombre para confirmar. |

Agregar o eliminar caras vale desde el próximo intento: no hace falta
reiniciar nada.

### Cuenta

**6 Cambiar contraseña guardada.** Si cambiás la contraseña de tu cuenta de
Windows (o de Microsoft), VisionAuth deja de poder entrar hasta que guardes
la nueva acá. La verifica con Windows antes de guardarla.

### Ajustes

| Opción | Qué hace |
|---|---|
| 7 Cámara | Lista las cámaras que se pueden abrir y elige una. |
| 8 Sensibilidad | `estricta`, `normal` (recomendada) o `permisiva`. Ver [Configuración](configuracion.md#sensibilidad). |
| 9 Espera al despertar | Segundos que espera después de despertar la PC antes de entrar, para que llegues a ver la pantalla (por defecto 4). |
| 10 Pantalla del reloj | Muestra u omite la pantalla del reloj al bloquear. |

### Servicio

| Opción | Qué hace |
|---|---|
| 11 Pausar / Reanudar | En pausa, VisionAuth no usa la cámara y se entra con el PIN, también después de reiniciar, hasta que lo reanudes. |
| 12 Probar reconocimiento | Abre la cámara y muestra, para cada cara, a quién se parece más y con qué similitud. Q para salir. |
| 13 Ver log | Las últimas 40 líneas del log del servicio. |

## La isla

Mientras la PC está bloqueada, la isla arriba de la pantalla de inicio de
sesión muestra:

| La isla dice | Qué pasa |
|---|---|
| Preparando la cámara | El servicio está abriendo la cámara. |
| Mirá a la cámara | Busca una cara. |
| VisionAuth, en gris | Nadie frente a la cámara hace 10 s: espera. Apenas te sentás, sigue. |
| Verificando… (ámbar) | Hay una cara y la está comparando. |
| No te reconozco (rojo) | La cara no coincide con ninguna registrada. Sigue intentando. |
| Hola, <nombre> (verde) | Te reconoció y entra. |
| VisionAuth no está activo | El servicio no responde (o está en pausa): entrá con el PIN. |
| Entrá con tu PIN | La contraseña guardada no funcionó (por ejemplo, la cambiaste). |

## Línea de comandos

El menú usa estos comandos, que también se pueden correr directo desde la
carpeta de VisionAuth (los que cambian ajustes necesitan administrador):

```powershell
python -m visionauth.cli faces list
python -m visionauth.cli faces add "Ana"
python -m visionauth.cli faces add-samples "Ana"
python -m visionauth.cli faces rename "Ana" "Ana María"
python -m visionauth.cli faces remove "Ana María"
python -m visionauth.cli config show
python -m visionauth.cli config set sensitivity permisiva
python -m visionauth.cli config set camera 1
python -m visionauth.cli cameras
python -m visionauth.cli test
```

Los cambios de cámara o sensibilidad valen cuando el servicio se reinicia
(el menú lo hace solo): `Restart-Service VisionAuth`.
