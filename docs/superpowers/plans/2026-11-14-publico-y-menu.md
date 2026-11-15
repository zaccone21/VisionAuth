# Repo público, documentación y menú: plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dejar VisionAuth listo para publicar: varias caras por cuenta con saludo por nombre, una CLI de Python para caras y ajustes, un menú `visionauth.ps1`, el instalador simplificado y la documentación para usuarios.

**Architecture:** La lógica de caras y configuración vive en Python (`visionauth/faces.py`, `visionauth/settings.py`, `visionauth/cli.py`) y se testea con pytest. El servicio compara contra todas las caras en cada intento. El menú de PowerShell solo dibuja, eleva y maneja servicio y registro, llamando a la CLI para todo lo demás.

**Tech Stack:** Python 3.12+ (pytest), PowerShell 5.1, C++ (MinGW-w64) para un cambio menor en la DLL.

**Spec:** `docs/superpowers/specs/2026-11-14-publico-y-menu-design.md`

## Global Constraints

- Textos para la persona en español rioplatense (como la isla). Código, comentarios y commits en inglés.
- Python ejecutable: el `python` del PATH, con dependencias en el site-packages del usuario (`python -m pip install --user -e ".[dev]"`). No `.venv`.
- Config: `C:\ProgramData\VisionAuth\config.json`, leída con `utf-8-sig` (PowerShell 5.1 escribe BOM).
- Sensibilidad: `estricta` 0.55, `normal` 0.45, `permisiva` 0.38. Por defecto `normal`.
- Nombre de cara: sin `\ / : * ? " < > |` ni caracteres de control, no vacío, no `.`/`..`, sin punto final, máximo 40 caracteres; se recortan espacios a los costados. Tildes y espacios internos permitidos.
- `DisplaySettleMs` en `HKLM\SOFTWARE\VisionAuth`, por defecto 4000.
- Scripts `.ps1` en UTF-8 con BOM.
- Antes de instalar una DLL nueva: `ctypes.WinDLL(r"credential_provider\build\VisionAuthCredentialProvider.dll")` tiene que cargar (Smart App Control).
- Commits en `main`, con push; terminan con `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Correr Python como `"/c/Users/joaqu/AppData/Local/Python/pythoncore-3.14-64/python.exe"` desde bash en esta PC.

## Review Focus

1. Nombres con tildes y espacios ("José María") llegan intactos al `MATCH` en UTF-8 → test en Task 4 (`status_reply`).
2. Una cara borrada o renombrada mientras el servicio está en un intento: se ignora y las demás siguen funcionando → test en Task 3.
3. `config.json` con BOM escrito por PowerShell: la CLI lo lee y lo reescribe sin romperlo → test en Task 2.
4. Renombrar cambiando solo mayúsculas ("joaquín" → "Joaquín") en NTFS, que no distingue mayúsculas → test en Task 1.
5. Valores inválidos en `config set` (cámara "abc" o 12, sensibilidad "alta") se rechazan sin tocar el archivo → test en Task 2.

---

### Task 1: Nombres de cara y operaciones sobre caras

**Files:**
- Create: `visionauth/faces.py`
- Modify: `visionauth/enrollment/enrollment.py:92-110` (`_validate_username` usa `validate_face_name`)
- Test: `tests/faces/__init__.py`, `tests/faces/test_faces.py`
- Modify: `tests/enrollment/test_enrollment.py` (agregar casos válidos con tilde y espacio)

**Interfaces:**
- Produces:
  - `class InvalidFaceName(ValueError)`
  - `validate_face_name(name: str) -> str` (devuelve el nombre recortado)
  - `@dataclass FaceInfo(name: str, samples: int, created: str | None)`
  - `list_faces(data_dir: str) -> list[FaceInfo]` (ordenadas por nombre, ignora carpetas sin `profile.json`)
  - `rename_face(data_dir: str, old: str, new: str) -> None` (renombra carpeta y campo `user` de `profile.json` y `metadata.json`)
  - `remove_face(data_dir: str, name: str) -> None`
  - `class FaceNotFound(LookupError)`, `class FaceExists(FileExistsError)`

- [ ] **Step 1: Write the failing tests** in `tests/faces/test_faces.py`, con un helper que crea `tmp_path/users/<nombre>/profile.json` (`{"user": nombre, "embeddings": [[...]]}`) y `metadata.json` (`{"user": nombre, "sample_count": 8, "created_at": "2026-11-14T10:00:00"}`):
  - `test_validate_accepts_accents_and_spaces`: `validate_face_name("  José María ") == "José María"`.
  - `test_validate_rejects` parametrizado con `"", "   ", "a/b", "a\\b", "a:b", "a*b", "a?b", 'a"b', "a<b", "a|b", ".", "..", "nombre.", "x" * 41, "a\tb"` → `pytest.raises(InvalidFaceName)`.
  - `test_list_faces_reports_samples_and_skips_folders_without_profile`: dos caras + una carpeta vacía → `[FaceInfo("Ana", 8, "2026-11-14T10:00:00"), FaceInfo("Joaquín", 8, ...)]`.
  - `test_rename_updates_folder_and_profile_user`: tras `rename_face(d, "Zaccone", "Joaquín")` existe `users/Joaquín/profile.json` con `"user": "Joaquín"` y no existe `users/Zaccone`.
  - `test_rename_case_only_is_allowed`: `rename_face(d, "joaquín", "Joaquín")` → `list_faces` devuelve `"Joaquín"`.
  - `test_rename_to_existing_face_fails`: `pytest.raises(FaceExists)`.
  - `test_rename_or_remove_missing_face_fails`: `pytest.raises(FaceNotFound)`.
  - `test_remove_deletes_the_folder`.

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/faces -q`
Expected: FAIL (`ModuleNotFoundError: visionauth.faces`)

- [ ] **Step 3: Implement `visionauth/faces.py`.** Rutas con `os.path.join(resolve_data_dir(data_dir), "users", name)`. Renombrado solo de mayúsculas: `os.rename` directo cuando `old.casefold() == new.casefold()`. Escribir JSON con `ensure_ascii=False`, `indent=4`.

- [ ] **Step 4: Make enrollment use it.** `_validate_username` llama a `validate_face_name` y convierte `InvalidFaceName` en `InvalidUserError` con el mismo mensaje. Agregar a `tests/enrollment/test_enrollment.py` un test `test_enrollment_accepts_accented_name` que verifica que `"Joaquín"` no levanta `InvalidUserError` en la validación.

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/faces tests/enrollment -q`
Expected: PASS (los casos inválidos existentes siguen rechazados)

- [ ] **Step 6: Commit** — `git commit -m "Allow accented face names and add face list, rename and remove"`

---

### Task 2: Ajustes (config.json y sensibilidad)

**Files:**
- Create: `visionauth/settings.py`
- Test: `tests/settings/__init__.py`, `tests/settings/test_settings.py`

**Interfaces:**
- Produces:
  - `CONFIG_PATH = Path(r"C:\ProgramData\VisionAuth\config.json")`
  - `SENSITIVITY_THRESHOLDS: dict[str, float] = {"estricta": 0.55, "normal": 0.45, "permisiva": 0.38}`
  - `class SettingError(ValueError)`
  - `load_config(path: Path) -> dict` (`utf-8-sig`; `{}` si no existe)
  - `save_config(path: Path, config: dict) -> None` (UTF-8 sin BOM, `indent=2`, `ensure_ascii=False`)
  - `configured_account(config: dict) -> str | None` (`account`, o la única clave de `profiles` en configs viejas)
  - `match_threshold(config: dict) -> float` (de `sensitivity`, default `normal`)
  - `set_setting(config: dict, key: str, value: str) -> dict` (devuelve una copia; claves `camera` (int 0–9) y `sensitivity` (una de las tres); otra clave o valor → `SettingError` con mensaje en español)

- [ ] **Step 1: Write the failing tests:**
  - `test_load_config_reads_powershell_bom`: archivo escrito con `encoding="utf-8-sig"` → se lee bien.
  - `test_load_missing_config_is_empty`.
  - `test_save_then_load_round_trips_accents`: `{"account": "joaqu", "x": "Joaquín"}`.
  - `test_configured_account_new_and_old_formats`: `{"account": "joaqu"}` → `"joaqu"`; `{"profiles": {"joaqu": "Zaccone"}}` → `"joaqu"`; `{}` → `None`.
  - `test_match_threshold_levels`: `estricta` 0.55, `normal` 0.45, `permisiva` 0.38, ausente 0.45.
  - `test_set_setting_valid`: `set_setting({}, "camera", "1") == {"camera": 1}`; `set_setting({}, "sensitivity", "permisiva")`.
  - `test_set_setting_rejects` parametrizado: `("camera", "abc")`, `("camera", "12")`, `("sensitivity", "alta")`, `("account", "otro")` → `SettingError`; y el dict original no cambia.

- [ ] **Step 2: Run to verify they fail** — `python -m pytest tests/settings -q` → FAIL.
- [ ] **Step 3: Implement `visionauth/settings.py`.**
- [ ] **Step 4: Run** — `python -m pytest tests/settings -q` → PASS.
- [ ] **Step 5: Commit** — `git commit -m "Add settings: config file, account and sensitivity levels"`

---

### Task 3: Autenticar contra varias caras

**Files:**
- Modify: `visionauth/auth/auth_service.py` (`authenticate`, `_publish`, `_authenticate`)
- Test: `tests/auth/test_auth_service_any_face.py`

**Interfaces:**
- Consumes: nada nuevo.
- Produces: `AuthService.authenticate_any(usernames: list[str], visualize: bool = False) -> AuthResult`. En éxito, `result.user` es la cara con mayor similitud entre las que superan el umbral. `authenticate(username)` pasa a ser `authenticate_any([username])`. En fallo, `AUTH_FAILED` lleva `{"user": ", ".join(usernames), "reason": ...}`.

- [ ] **Step 1: Write the failing tests**, con los mismos mocks que `tests/auth/test_auth_service_success.py` (11 cuadros, una detección con micro-movimiento, embeddings cercanos a `e0`):
  - `test_matches_the_closest_face`: `Ana` con muestra `e1`, `Joaquín` con muestra `e0` → `authenticate_any(["Ana", "Joaquín"]).user == "Joaquín"` y `success`.
  - `test_missing_or_incompatible_face_is_skipped`: `["Borrada", "Vieja", "Joaquín"]` con `Borrada` sin perfil (`None`) y `Vieja` con `embedding_model` distinto → éxito con `"Joaquín"`.
  - `test_no_usable_face_fails_without_camera`: todas sin perfil → `reason == "user_not_found"` y `camera.start` no llamado.
  - `test_empty_list_fails_without_camera`: `[]` → `reason == "user_not_found"`.

- [ ] **Step 2: Run to verify they fail** — `python -m pytest tests/auth/test_auth_service_any_face.py -q` → FAIL (`authenticate_any` no existe).
- [ ] **Step 3: Implement.** Cargar las referencias de cada cara usable en una sola matriz con un vector paralelo de dueños; la similitud por cara es el máximo de sus filas. Una cara incompatible se loguea con `logger.warning` y se saltea. Si ninguna queda: `user_not_found` si ninguna tenía perfil, si no `incompatible_profile` o `invalid_profile_data` como hoy.
- [ ] **Step 4: Run** — `python -m pytest tests/auth -q` → PASS (incluidos los tests existentes).
- [ ] **Step 5: Commit** — `git commit -m "Authenticate against every enrolled face and report the closest"`

---

### Task 4: El servicio usa la cuenta, todas las caras y la sensibilidad

**Files:**
- Modify: `integration/windows/unlock_daemon.py`
- Modify: `credential_provider/VisionAuthCredentialProvider.cpp` (fase `idle` → `PH_AWAY`)
- Test: `tests/services/test_unlock_daemon.py`

**Interfaces:**
- Consumes: `configured_account`, `match_threshold` (Task 2); `list_faces` (Task 1); `authenticate_any` (Task 3).
- Produces:
  - `console_waiting(account: str | None) -> bool` (reemplaza `resolve_target`: sin nadie logueado → `True` si hay cuenta; con alguien → bloqueada y es la cuenta, sin distinguir mayúsculas)
  - `status_reply(service: UnlockService) -> str` (`"MATCH <cara>"` si hay verificación, si no `"STATE <fase>"`)
  - `build(config)` usa `AuthService(..., auth_threshold=match_threshold(config))`; `is_locked` es `console_waiting(account) and list_faces(data_dir) != []`; `authenticate` llama `authenticate_any([f.name for f in list_faces(data_dir)])`. Se deja de leer `display_name`.

- [ ] **Step 1: Write the failing tests** (sin APIs de Windows: `status_reply` con un `UnlockService` armado como en `tests/services/test_unlock_service.py`; `console_waiting` con `monkeypatch` de `console_session_id`, `session_user`, `session_locked`):
  - `test_status_reply_greets_the_face_by_name`: verificación de `"José María"` → `"MATCH José María"` y `.encode("utf-8")` sin error.
  - `test_status_reply_reports_phase`: sin verificación → `"STATE searching"` (u otra fase actual).
  - `test_console_waiting` parametrizado: nadie logueado + cuenta → `True`; nadie + `None` → `False`; `"JOAQU"` bloqueado con cuenta `"joaqu"` → `True`; otro usuario → `False`; desbloqueado → `False`.

- [ ] **Step 2: Run to verify they fail** — `python -m pytest tests/services/test_unlock_daemon.py -q` → FAIL.
- [ ] **Step 3: Implement the daemon changes.** Un import de `integration.windows.session` que falle fuera de Windows no debe romper la colección del test: los tests corren en Windows, no hace falta más.
- [ ] **Step 4: CP: con "idle" la isla queda en espera.** En `ParseReply`, `strncmp(phase, "idle", 4) == 0` → `PH_AWAY` (sin caras registradas el servicio queda en `idle` y la isla no debe pedir que mires a la cámara).
- [ ] **Step 5: Run everything** — `python -m pytest -q` → PASS; `sh credential_provider/build.sh --test` → `ALL PASSED` dos veces; la DLL carga con `ctypes.WinDLL`.
- [ ] **Step 6: Commit** — `git commit -m "Unlock the configured account with any enrolled face at the chosen sensitivity"`

---

### Task 5: CLI `python -m visionauth.cli`

**Files:**
- Create: `visionauth/cli.py` (se invoca como `python -m visionauth.cli`)
- Create: `visionauth/ui/enrollment_window.py` (el flujo de `examples/enrollment_demo.py` desde `main()` hasta el final, sin `input()`)
- Create: `visionauth/ui/recognition_window.py` (el loop de `examples/camera_recognition_demo.py`, mostrando nombre de cara y similitud)
- Modify: `examples/enrollment_demo.py`, `examples/camera_recognition_demo.py` (envoltorios finos)
- Test: `tests/cli/__init__.py`, `tests/cli/test_cli.py`

**Interfaces:**
- Consumes: Tasks 1 y 2.
- Produces:
  - `run_enrollment(name: str, append: bool, data_dir: str, camera_index: int) -> bool` en `enrollment_window.py`
  - `run_recognition_test(data_dir: str, camera_index: int, threshold: float) -> None` en `recognition_window.py`
  - `main(argv: list[str] | None = None) -> int` en `cli.py`, con opciones globales `--config PATH` (default `CONFIG_PATH`) y `--data-dir PATH` (default: `data_dir` de la config, o `"data"`).
  - Subcomandos y salidas (stdout, una línea por dato, para que el menú las lea):
    - `faces list` → `nombre<TAB>muestras<TAB>fecha` por cara; nada si no hay.
    - `faces add NOMBRE` / `faces add-samples NOMBRE` → abre la ventana; exit 0 si se guardó.
    - `faces rename VIEJO NUEVO`, `faces remove NOMBRE` → `Listo.`
    - `config show` → `clave<TAB>valor` para `account`, `camera`, `sensitivity`.
    - `config set CLAVE VALOR` → guarda con `save_config`; `Listo.`
    - `cameras` → índice por línea de las cámaras 0–4 que abren.
    - `test` → ventana de reconocimiento.
  - Errores: mensaje en español a stderr, exit 1 (`InvalidFaceName`, `FaceNotFound`, `FaceExists`, `SettingError`).

- [ ] **Step 1: Write the failing tests** con `tmp_path` para `--config` y `--data-dir` y `capsys`:
  - `test_faces_list_prints_tab_separated_rows`.
  - `test_faces_rename_and_remove`.
  - `test_invalid_name_exits_1_with_spanish_message`: `faces rename Ana "a/b"` → `1` y stderr contiene `"nombre"`.
  - `test_config_set_and_show`: `config set sensitivity estricta` y luego `config show` incluye `sensitivity\testricta`.
  - `test_config_set_invalid_leaves_file_unchanged`: `config set camera abc` → `1` y el archivo igual byte a byte.

- [ ] **Step 2: Run to verify they fail** — `python -m pytest tests/cli -q` → FAIL.
- [ ] **Step 3: Move the windows into `visionauth/ui/` and implement `cli.py`.** Los ejemplos quedan como `ask_username` + llamada a `run_enrollment` / `run_recognition_test`.
- [ ] **Step 4: Run** — `python -m pytest -q` → PASS.
- [ ] **Step 5: Manual check** — `python -m visionauth.cli faces list` muestra `Zaccone`; `python -m visionauth.cli test` abre la ventana y reconoce (cerrar con Q).
- [ ] **Step 6: Commit** — `git commit -m "Add the visionauth command line for faces and settings"`

---

### Task 6: Instalador y desinstalador

**Files:**
- Modify: `scripts/install.ps1`, `scripts/uninstall.ps1`

**Interfaces:**
- Consumes: CLI (Task 5), `config.json` con `account`, `site`, `data_dir`, `camera`, `sensitivity`.

- [ ] **Step 1: install.ps1.** Parámetros: `-Camera` (int, 0) y `-SkipLockScreen`; se quitan `-ProfileName` y `-DisplayName`. Orden:
  1. Verifica admin y la DLL compilada.
  2. Verifica dependencias con `python -c "import cv2, mediapipe"`; si falla, indica `python -m pip install --user -e ".[dev]"` y corta.
  3. Si `python -m visionauth.cli --data-dir <repo>\data faces list` no devuelve caras, pide un nombre y corre `faces add`; si se cancela, corta sin instalar.
  4. Escribe la config (`account = $env:USERNAME`, conservando `sensitivity` y `camera` de una config previa si existe).
  5. Servicio, DLL y política como hoy; contraseña como hoy.
- [ ] **Step 2: uninstall.ps1** también borra `HKLM:\SOFTWARE\VisionAuth`.
- [ ] **Step 3: Parse check** — para cada script: `powershell -NoProfile -Command "$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile('<ruta>', [ref]$null, [ref]$e); $e.Count"` → `0`.
- [ ] **Step 4: Commit** — `git commit -m "Simplify the installer: enroll the first face and keep settings"`

---

### Task 7: Menú `visionauth.ps1`

**Files:**
- Create: `visionauth.ps1` (raíz, UTF-8 con BOM)

**Interfaces:**
- Consumes: CLI (Task 5), `scripts/install.ps1`, `scripts/set_password.py`, servicio `VisionAuth`, `HKLM:\SOFTWARE\VisionAuth\DisplaySettleMs`, `HKLM:\SOFTWARE\Policies\Microsoft\Windows\Personalization\NoLockScreen`.

- [ ] **Step 1: Write the menu** según la sección 3 del spec (encabezado y opciones exactas, en ese orden):
  - Auto-elevación: si no es admin, `Start-Process powershell -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""` y salir.
  - `[Console]::OutputEncoding = [Text.Encoding]::UTF8`; `$env:PYTHONIOENCODING = "utf-8"` para leer la CLI.
  - Encabezado del spec en coral `ESC[38;2;217;119;87m` (con `[char]27`), y línea de estado: servicio (activo / en pausa / no instalado), cuenta, cantidad de caras.
  - Si el servicio no existe: ofrece instalar (`scripts\install.ps1`) y no muestra el resto.
  - 5 Eliminar: pide escribir el nombre exacto; si es la última cara, avisa antes.
  - 7 y 8: muestran opciones (cámaras de `cameras`; los tres niveles), llaman a `config set` y reinician el servicio.
  - 9: segundos enteros 0–30 → `DisplaySettleMs` en ms.
  - 10: alterna `NoLockScreen` y avisa lo de "administrado por su organización".
  - 11: en pausa → `Set-Service -StartupType Manual` + `Stop-Service`; reanudar → `Automatic` + `Start-Service`.
  - 13: `Get-Content C:\ProgramData\VisionAuth\service.log -Tail 40`.
  - Tras cada acción: "Enter para volver".
- [ ] **Step 2: Parse check** como en Task 6 → `0`.
- [ ] **Step 3: Manual check** — abrir `.\visionauth.ps1`, ver el encabezado y el estado, listar caras, cambiar la espera al despertar a 4 y salir.
- [ ] **Step 4: Commit** — `git commit -m "Add the VisionAuth management menu"`

---

### Task 8: Limpieza para publicar

**Files:**
- Create: `LICENSE` (MIT, `Copyright (c) 2026 zaccone21`)
- Modify: `credential_provider/island_preview.cpp:128` (`L"Joaquin"` → `L"Ana"`), `visionauth/events/event_bus.py:129` (`"Joaquin"` → `"Ana"`)
- Move: `scripts/boot_camera_probe.py`, `scripts/boot_camera_probe_task.ps1`, `scripts/lock_screen_camera_probe.py` → `scripts/dev/` (arreglar sus rutas a `PROJECT_ROOT` si las calculan desde `__file__`)
- Modify: `pyproject.toml` (`description = "Desbloqueo de Windows con la cara usando una webcam común."`)

- [ ] **Step 1: Apply the changes.**
- [ ] **Step 2: Check** — `git grep -n -i "joaquin\|zaccone" -- ':!docs/superpowers'` solo muestra la URL del repo; `python -m pytest -q` → PASS; `sh credential_provider/build.sh --test` → PASS.
- [ ] **Step 3: Commit** — `git commit -m "Prepare the repository for publishing: license, generic names, dev scripts"`

---

### Task 9: Documentación

**Files:**
- Rewrite: `README.md`
- Create: `docs/instalacion.md`, `docs/uso.md`, `docs/configuracion.md`, `docs/seguridad.md`, `docs/recuperacion.md`, `docs/desarrollo/README.md`
- Move: `docs/01_PRD.md` … `docs/06_Decisiones.md` → `docs/desarrollo/` (y arreglar los enlaces)

- [ ] **Step 1: Write the docs** con el contenido de la tabla de la sección 6 del spec y los requisitos listados allí. La instalación usa exactamente los comandos de las Tasks 6 y 7 (`python -m pip install --user -e ".[dev]"`, `python scripts\download_models.py`, `sh credential_provider/build.sh`, `.\scripts\install.ps1 -SkipLockScreen`, `.\visionauth.ps1`). `docs/configuracion.md` incluye el fondo de Spotlight (quitar `NoLockScreen`, elegir Imagen, volver a ponerla) y `DisableLogonBackgroundImage`. `docs/desarrollo/README.md`: tests, compilar, `island_preview.exe`, sondas en `scripts/dev/`, el flujo de decisiones.
- [ ] **Step 2: Check links** — cada enlace relativo `](...)` de `README.md` y `docs/**/*.md` apunta a un archivo existente (script de una línea con `re.findall`).
- [ ] **Step 3: Commit** — `git commit -m "Write the user documentation and move the design docs under docs/desarrollo"`

---

### Task 10: Verificación final

- [ ] **Step 1:** `python -m pytest -q` → todo PASS.
- [ ] **Step 2:** `sh credential_provider/build.sh --test` → `ALL PASSED` ×2; la DLL de producción carga.
- [ ] **Step 3:** Parse check de los tres `.ps1` → `0` errores.
- [ ] **Step 4:** Pedirle a la persona: reinstalar con `.\scripts\install.ps1 -SkipLockScreen`, renombrar "Zaccone" a "Joaquín" desde el menú, bloquear con Win+L y confirmar el saludo; después, revisar el repo y hacerlo público.
