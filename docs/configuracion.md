# Configuración

Lo más cómodo es cambiar todo desde el menú (`.\visionauth.ps1`). Esta página
explica dónde queda cada ajuste.

## config.json

`C:\ProgramData\VisionAuth\config.json`, escrito por el instalador:

```json
{
  "account": "ana",
  "site": ["C:\\Users\\ana\\AppData\\Roaming\\Python\\Python312\\site-packages"],
  "data_dir": "C:\\Users\\ana\\VisionAuth\\data",
  "camera": 0,
  "sensitivity": "normal"
}
```

| Clave | Qué es |
|---|---|
| `account` | La cuenta de Windows que VisionAuth desbloquea: la del usuario que corrió el instalador. |
| `site` | Dónde están las dependencias de Python del usuario (el servicio corre como SYSTEM y no las ve por su cuenta). |
| `data_dir` | Carpeta con las caras registradas (`data_dir\users\<nombre>\`). |
| `camera` | Número de cámara (0 es la primera). |
| `sensitivity` | `estricta`, `normal` o `permisiva`. |

El servicio la lee al arrancar: después de editarla a mano, reiniciá el
servicio (`Restart-Service VisionAuth`, como administrador).

## Sensibilidad

VisionAuth compara tu cara con las muestras registradas y obtiene una
similitud entre 0 y 1. Entra si supera el umbral del nivel elegido:

| Nivel | Umbral | Cuándo usarlo |
|---|---|---|
| `estricta` | 0.55 | Querés menos riesgo de que entre otra persona parecida; puede rechazarte más con poca luz. |
| `normal` | 0.45 | Recomendado. |
| `permisiva` | 0.38 | Te rechaza seguido (luz difícil, cámara de costado). |

Una cara registrada suele medir entre 0.65 y 0.80. Para ver cuánto medís vos,
usá "Probar reconocimiento" en el menú. Si te rechaza seguido, antes de bajar
la sensibilidad probá sumar muestras desde donde desbloqueás.

## Espera al despertar

Al volver del reposo, un monitor externo tarda unos segundos en mostrar la
imagen. VisionAuth espera, después de que la PC despierta o se prende la
pantalla, antes de entrar, para que veas la pantalla de inicio:

```
HKLM\SOFTWARE\VisionAuth\DisplaySettleMs   (DWORD, milisegundos, por defecto 4000)
```

Con un bloqueo normal (Win+L) no agrega demora. Vale desde el próximo
bloqueo.

## Pantalla del reloj

`install.ps1 -SkipLockScreen` (o la opción 10 del menú) activa la política:

```
HKLM\SOFTWARE\Policies\Microsoft\Windows\Personalization\NoLockScreen = 1
```

Así, al bloquear se va directo a la pantalla de inicio de sesión, con la isla.
Mientras esté activa, Configuración > Personalización > Pantalla de bloqueo
muestra "Algunos de estos ajustes son administrados por su organización" y
algunas opciones quedan en gris: es por esta política, no hay ninguna
organización.

## Fondo de la pantalla de inicio

Si la pantalla de inicio muestra una foto distinta cada vez, es Windows
Spotlight. Para elegir una imagen fija:

1. Quitá la política un momento (como administrador):
   ```powershell
   reg delete "HKLM\SOFTWARE\Policies\Microsoft\Windows\Personalization" /v NoLockScreen /f
   ```
2. En Configuración > Personalización > Pantalla de bloqueo, elegí **Imagen**
   y tu foto, y dejá activado "Mostrar la imagen de fondo de la pantalla de
   bloqueo en la pantalla de inicio de sesión".
3. Volvé a poner la política:
   ```powershell
   reg add "HKLM\SOFTWARE\Policies\Microsoft\Windows\Personalization" /v NoLockScreen /t REG_DWORD /d 1 /f
   ```

Para un color liso en vez de una imagen:

```powershell
reg add "HKLM\SOFTWARE\Policies\Microsoft\Windows\System" /v DisableLogonBackgroundImage /t REG_DWORD /d 1 /f
```

## Archivos

| Ruta | Qué hay |
|---|---|
| `data\users\<nombre>\` (en la carpeta de VisionAuth) | Cada cara: `profile.json` (las muestras como vectores), `metadata.json` y las fotos. Nunca se suben a git. |
| `C:\ProgramData\VisionAuth\config.json` | La configuración del servicio. |
| `C:\ProgramData\VisionAuth\service.log` | El log del servicio. |
| `C:\Program Files\VisionAuth\` | La DLL de la pantalla de inicio. |
| Secreto LSA `L$VisionAuthCredential` | La contraseña guardada. |
