# Repo público, documentación y menú de administración

Fecha: 2026-11-14

## Intención

Publicar VisionAuth en GitHub para que otra persona pueda instalarlo y usarlo
sin ayuda. Para eso hacen falta:

- documentación con la instalación paso a paso, los requisitos, el uso y la
  configuración;
- un menú en PowerShell para administrar VisionAuth sin tocar archivos: las
  caras registradas, la contraseña guardada y los ajustes.

## Objetivos

1. Repo listo para ser público: licencia, sin datos personales en el código,
   sin herramientas de desarrollo sueltas, documentación ordenada.
2. Documentación en español (como los textos de la isla), clara para alguien
   que nunca vio el proyecto.
3. Menú `visionauth.ps1` con encabezado "VISIONAUTH" en letras grandes.
4. Varias caras registradas desbloquean la misma cuenta de Windows, y cada
   una es saludada por su nombre.

## No objetivos

- Varias cuentas de Windows (cada persona con su cuenta y su contraseña).
  Queda a futuro: hoy la contraseña es un único secreto LSA.
- Publicar la DLL compilada en GitHub Releases o firmarla. Queda a futuro.
- Traducir la documentación al inglés.

## Anti-objetivos

- Que el menú o la reinstalación dejen la pantalla de inicio sin forma de
  entrar: el PIN siempre tiene que seguir disponible.
- Que la contraseña se muestre o quede escrita en algún lado fuera del
  secreto LSA.
- Que se suban datos biométricos o la configuración local al repo.

## Enfoques considerados

- **A. Menú en PowerShell, lógica en Python (elegido).** PowerShell dibuja el
  menú y maneja lo propio de Windows (elevación, servicio, registro). Las
  operaciones sobre caras y configuración son comandos de Python que el menú
  llama. La lógica queda testeable con pytest y los comandos sirven sueltos.
- B. Todo en Python con una interfaz de terminal (`rich`). Un solo lenguaje,
  pero agrega dependencia y deja de ser un menú de PowerShell.
- C. Todo en PowerShell editando JSON y carpetas. Duplica la lógica de
  perfiles y no se puede testear bien.

## Diseño

### 1. Caras: varias por cuenta, saludo con su nombre

- Una "cara" es un perfil en `data/users/<nombre>/`. El nombre del perfil es
  el que se muestra en el saludo ("Hola, <nombre>"), así que puede tener
  tildes y espacios. No puede tener `\ / : * ? " < > |` ni ser vacío.
- Todas las caras registradas desbloquean la cuenta configurada. El servicio
  compara cada intento contra las muestras de todas las caras y gana la de
  mayor similitud si supera el umbral; el `MATCH` lleva el nombre de esa cara.
- Las caras se leen en cada intento (como hoy), así que agregar o borrar una
  no requiere reiniciar el servicio.
- Una cara con un modelo de embeddings incompatible se ignora con un aviso en
  el log, sin frenar a las demás.
- Se elimina `display_name` de la configuración y el parámetro `-DisplayName`
  del instalador: el saludo sale siempre del nombre de la cara.

Configuración (`C:\ProgramData\VisionAuth\config.json`):

```json
{
  "account": "joaqu",
  "site": ["..."],
  "data_dir": "C:\\...\\VisionAuth\\data",
  "camera": 0,
  "sensitivity": "normal"
}
```

`account` reemplaza al mapa `profiles`. Una configuración vieja con
`profiles` se sigue leyendo: la cuenta es su única clave.

### 2. Comandos de Python (`python -m visionauth.cli`)

| Comando | Qué hace |
|---|---|
| `faces list` | Lista las caras: nombre, cantidad de muestras, fecha. |
| `faces add <nombre>` | Abre la ventana de enrollment (la de `examples/enrollment_demo.py`) para una cara nueva. |
| `faces add-samples <nombre>` | Lo mismo, sumando muestras a una cara existente. |
| `faces rename <viejo> <nuevo>` | Renombra la carpeta y el campo `user` de `profile.json` y `metadata.json`. |
| `faces remove <nombre>` | Borra la carpeta de la cara. |
| `config show` | Muestra la configuración actual. |
| `config set <clave> <valor>` | Cambia `camera` o `sensitivity`, validando el valor. |
| `cameras` | Prueba los índices 0 a 4 e informa cuáles abren. |
| `test` | Reconocimiento en vivo con ventana (lo de `camera_recognition_demo.py`). |

Los comandos usan el `data_dir` de la configuración instalada y, si no
hay instalación, `data/` en la raíz del proyecto. Los mensajes para la
persona van en español. Códigos de salida: 0 bien,
1 error (con el motivo en stderr).

Sensibilidad (umbral de similitud coseno de SFace):

| Nivel | Umbral |
|---|---|
| `estricta` | 0.55 |
| `normal` | 0.45 (el actual) |
| `permisiva` | 0.38 |

El servicio lee `sensitivity` al arrancar y la pasa a `AuthService` como
`auth_threshold`. Como referencia, el dueño mide entre 0.67 y 0.78.

### 3. Menú `visionauth.ps1` (en la raíz del repo)

- Se re-lanza como administrador si no lo es (UAC).
- Archivo en UTF-8 con BOM y `[Console]::OutputEncoding = UTF8`, para que el
  encabezado y las tildes se vean bien en PowerShell 5.1.
- Encabezado en color coral (el del logo) si la terminal lo soporta:

```
██╗   ██╗██╗███████╗██╗ ██████╗ ███╗   ██╗ █████╗ ██╗   ██╗████████╗██╗  ██╗
██║   ██║██║██╔════╝██║██╔═══██╗████╗  ██║██╔══██╗██║   ██║╚══██╔══╝██║  ██║
██║   ██║██║███████╗██║██║   ██║██╔██╗ ██║███████║██║   ██║   ██║   ███████║
╚██╗ ██╔╝██║╚════██║██║██║   ██║██║╚██╗██║██╔══██║██║   ██║   ██║   ██╔══██║
 ╚████╔╝ ██║███████║██║╚██████╔╝██║ ╚████║██║  ██║╚██████╔╝   ██║   ██║  ██║
  ╚═══╝  ╚═╝╚══════╝╚═╝ ╚═════╝ ╚═╝  ╚═══╝╚═╝  ╚═╝ ╚═════╝    ╚═╝   ╚═╝  ╚═╝
```

```
 servicio: activo   cuenta: joaqu   caras: 1
 ──────────────────────────────────────────────
 Caras
   1  Ver caras registradas
   2  Agregar cara
   3  Sumar muestras a una cara
   4  Renombrar cara
   5  Eliminar cara
 Cuenta
   6  Cambiar contraseña guardada
 Ajustes
   7  Cámara                 0
   8  Sensibilidad           normal
   9  Espera al despertar    4 s
  10  Pantalla del reloj     omitida
 Servicio
  11  Pausar / reanudar
  12  Probar reconocimiento
  13  Ver log
   0  Salir
```

- Si VisionAuth no está instalado, el menú lo dice y ofrece instalarlo
  (llama a `scripts/install.ps1`).
- Eliminar una cara pide confirmación escribiendo su nombre. Eliminar la
  última avisa que VisionAuth deja de desbloquear hasta registrar otra.
- Cambiar contraseña llama a `scripts/set_password.py` (que la verifica con
  `LogonUserW`).
- Cámara y sensibilidad se cambian con la CLI y reinician el servicio.
- Espera al despertar escribe `DisplaySettleMs` en `HKLM\SOFTWARE\VisionAuth`
  (efecto en el próximo bloqueo; no hace falta reiniciar nada).
- Pantalla del reloj activa o quita la política `NoLockScreen`, y avisa que
  con la política activa Windows muestra "administrado por su organización"
  en la configuración de la pantalla de bloqueo.
- Pausar detiene el servicio y lo pasa a inicio manual; reanudar lo vuelve a
  automático y lo inicia. En pausa, la isla dice que VisionAuth no está
  activo y se entra con el PIN.
- Probar reconocimiento y agregar cara abren ventanas: el menú corre en la
  sesión del usuario (la elevación no cambia de sesión), así que se ven.
- Ver log muestra las últimas 40 líneas de `service.log`.

### 4. Instalador

- `install.ps1` ya no pide `-ProfileName` ni `-DisplayName`. Si no hay
  ninguna cara registrada, abre el enrollment de la primera antes de seguir.
  Se mantienen `-Camera` y `-SkipLockScreen`.
- La cuenta configurada es la del usuario que corre el instalador.
- El Python del servicio y el de las instrucciones tienen que ser el mismo
  entorno con las dependencias instaladas (hoy el servicio usa el `python`
  del PATH con el site-packages del usuario y el README habla de un `.venv`:
  hay que alinearlo, ver "Lo que queda al builder").

### 5. Repo público

- `LICENSE` MIT, a nombre de `zaccone21` (el usuario de GitHub, para no
  publicar el nombre completo; se puede cambiar).
- Reemplazar "Joaquin" en `island_preview.cpp` y `event_bus.py` por un
  nombre genérico.
- Mover las sondas de desarrollo (`scripts/boot_camera_probe.py`,
  `scripts/boot_camera_probe_task.ps1`, `scripts/lock_screen_camera_probe.py`)
  a `scripts/dev/`, mencionadas solo en la documentación de desarrollo.
- `pyproject.toml`: descripción en español acorde al proyecto.
- Descripción y temas del repo en GitHub (la persona hace público el repo).

### 6. Documentación

| Archivo | Contenido |
|---|---|
| `README.md` | Qué es, captura/logo, advertencia de seguridad corta, requisitos, instalación rápida, enlaces. |
| `docs/instalacion.md` | Paso a paso desde cero: Python, Git, WinLibs, clonar, dependencias, modelos, compilar, instalar, registrar la cara, probar. Incluye Smart App Control. |
| `docs/uso.md` | El menú, opción por opción, y los comandos de la CLI. |
| `docs/configuracion.md` | `config.json`, `DisplaySettleMs`, sensibilidad, pantalla del reloj, fondo de la pantalla de inicio (Spotlight). |
| `docs/seguridad.md` | Qué protege y qué no: fotos/videos con webcam RGB, la contraseña en LSA legible por administradores, sin garantía. |
| `docs/recuperacion.md` | Qué hacer si la pantalla de inicio falla (PIN, WinRE, borrar la DLL), desinstalar. |
| `docs/desarrollo/` | Los documentos de diseño actuales (01–06), tests, compilar la DLL, vista previa de la isla, sondas. |

Requisitos a documentar: Windows 10/11, webcam, Python 3.12 o más nuevo,
Git, WinLibs (MinGW-w64) para compilar la DLL, cuenta con contraseña (para
una cuenta de Microsoft, la de Microsoft; el PIN no alcanza), permisos de
administrador.

## Lo que queda al builder

- Cómo `AuthService` compara contra varias caras (por ejemplo un
  `authenticate_any(nombres)`), manteniendo los eventos y los tests actuales.
- Alinear el entorno de Python del servicio con el de las instrucciones,
  probándolo en esta PC (el servicio corre como SYSTEM).
- Reusar el código de `examples/` desde la CLI sin duplicarlo (moverlo al
  paquete y dejar los ejemplos como envoltorios finos, o similar).
- Cómo el menú lee el estado (servicio, cantidad de caras, ajustes) para el
  encabezado.
- Tests de la CLI de caras y configuración con pytest.

## Después de construirlo

1. La persona reinstala con el instalador nuevo y renombra su cara
   "Zaccone" a "Joaquín" desde el menú.
2. La persona revisa el repo y lo hace público ella misma.
3. Opcional: configurar el email noreply de GitHub para los commits futuros.
