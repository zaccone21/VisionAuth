"""Interactive enrollment demo for VisionAuth.

Asks for a name, then opens the Face ID style enrollment window. If the face
already exists, the new samples can be added to it, e.g. to enroll again from
the final camera position. The menu (visionauth.ps1) and the command line
(python -m visionauth.cli faces add) do the same.
"""

import logging
import sys

from visionauth.faces import list_faces
from visionauth.ui.enrollment_window import run_enrollment

logging.basicConfig(level=logging.WARNING, handlers=[logging.StreamHandler(sys.stdout)])


def ask_name() -> tuple[str, bool] | None:
    """Prompts for the name and whether to add samples to an existing face.

    Returns:
        (name, append), or None if the person cancels.
    """
    try:
        name = input("Nombre de la cara a registrar: ").strip()
        append = False
        if name and any(face.name.casefold() == name.casefold() for face in list_faces("data")):
            answer = input(f"'{name}' ya existe. ¿Agregar muestras a su perfil? (s/n): ")
            if answer.strip().lower() not in ("s", "si", "sí", "y", "yes"):
                return None
            append = True
        return name, append
    except (KeyboardInterrupt, EOFError):
        return None


def main() -> None:
    answer = ask_name()
    if answer is None:
        print("Operación cancelada.")
        return
    name, append = answer
    run_enrollment(name, append, "data", camera_index=0)


if __name__ == "__main__":
    main()
