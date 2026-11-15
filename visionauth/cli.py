"""VisionAuth command line: enrolled faces and settings.

    python -m visionauth.cli faces list
    python -m visionauth.cli faces add <nombre>
    python -m visionauth.cli faces add-samples <nombre>
    python -m visionauth.cli faces rename <nombre> <nuevo nombre>
    python -m visionauth.cli faces remove <nombre>
    python -m visionauth.cli config show
    python -m visionauth.cli config set camera|sensitivity <valor>
    python -m visionauth.cli cameras
    python -m visionauth.cli test

Lists are printed one item per line with tab-separated fields, so the menu
(visionauth.ps1) can read them. Errors go to stderr in Spanish, exit code 1.
Changing settings writes config.json; the service reads it when it starts.
"""

import argparse
import sys
from pathlib import Path

from visionauth.faces import (
    FaceExists,
    FaceNotFound,
    InvalidFaceName,
    list_faces,
    remove_face,
    rename_face,
    validate_face_name,
)
from visionauth.settings import (
    CONFIG_PATH,
    DEFAULT_SENSITIVITY,
    SettingError,
    configured_account,
    load_config,
    match_threshold,
    save_config,
    set_setting,
)

MAX_CAMERAS_PROBED = 5


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="visionauth", description="Caras registradas y ajustes de VisionAuth.")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH, help="config.json del servicio")
    parser.add_argument("--data-dir", help="carpeta de datos (por defecto, la de la configuración)")
    commands = parser.add_subparsers(dest="command", required=True)

    faces = commands.add_parser("faces", help="caras registradas").add_subparsers(dest="action", required=True)
    faces.add_parser("list", help="listar las caras")
    faces.add_parser("add", help="registrar una cara nueva").add_argument("name")
    faces.add_parser("add-samples", help="sumar muestras a una cara").add_argument("name")
    rename = faces.add_parser("rename", help="renombrar una cara")
    rename.add_argument("old")
    rename.add_argument("new")
    faces.add_parser("remove", help="eliminar una cara").add_argument("name")

    config = commands.add_parser("config", help="ajustes").add_subparsers(dest="action", required=True)
    config.add_parser("show", help="mostrar los ajustes")
    setting = config.add_parser("set", help="cambiar un ajuste")
    setting.add_argument("key", choices=["camera", "sensitivity"])
    setting.add_argument("value")

    commands.add_parser("cameras", help="cámaras que se pueden abrir")
    commands.add_parser("test", help="probar el reconocimiento con la cámara")
    return parser


def _faces(args: argparse.Namespace, data_dir: str, config: dict) -> None:
    if args.action == "list":
        for face in list_faces(data_dir):
            print(f"{face.name}\t{face.samples}\t{face.created or ''}")
    elif args.action in ("add", "add-samples"):
        name = validate_face_name(args.name)
        exists = any(face.name.casefold() == name.casefold() for face in list_faces(data_dir))
        if args.action == "add" and exists:
            raise FaceExists(f"Ya hay una cara registrada como '{name}'. Para sumarle muestras usá add-samples.")
        if args.action == "add-samples" and not exists:
            raise FaceNotFound(f"No hay ninguna cara registrada como '{name}'.")
        from visionauth.ui.enrollment_window import run_enrollment

        if not run_enrollment(name, args.action == "add-samples", data_dir, int(config.get("camera", 0))):
            raise RuntimeError("No se guardó la cara.")
    elif args.action == "rename":
        rename_face(data_dir, args.old, args.new)
        print("Listo.")
    elif args.action == "remove":
        remove_face(data_dir, args.name)
        print("Listo.")


def _config(args: argparse.Namespace, config: dict) -> None:
    if args.action == "show":
        print(f"account\t{configured_account(config) or ''}")
        print(f"camera\t{config.get('camera', 0)}")
        print(f"sensitivity\t{config.get('sensitivity', DEFAULT_SENSITIVITY)}")
    else:
        save_config(args.config, set_setting(config, args.key, args.value))
        print("Listo.")


def _cameras() -> None:
    import cv2

    # Probing an index with no camera behind it logs a warning
    cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
    for index in range(MAX_CAMERAS_PROBED):
        capture = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        try:
            if capture.isOpened() and capture.read()[0]:
                print(index)
        finally:
            capture.release()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = load_config(args.config)
        data_dir = args.data_dir or config.get("data_dir") or "data"
        if args.command == "faces":
            _faces(args, data_dir, config)
        elif args.command == "config":
            _config(args, config)
        elif args.command == "cameras":
            _cameras()
        elif args.command == "test":
            from visionauth.ui.recognition_window import run_recognition_test

            run_recognition_test(data_dir, int(config.get("camera", 0)), match_threshold(config))
    except (InvalidFaceName, FaceNotFound, FaceExists, SettingError, RuntimeError) as e:
        print(e, file=sys.stderr)
        return 1
    except PermissionError:
        print("Hace falta ejecutarlo como administrador.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
