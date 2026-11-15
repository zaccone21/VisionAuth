"""Checks whether a SYSTEM process can use the webcam before anyone signs in.

Meant to run as a SYSTEM scheduled task at startup (see
boot_camera_probe_task.ps1). For a few minutes it logs once per second whether
someone is signed in at the console, whether the camera delivers frames, their
brightness and how many faces were detected. Each line is flushed right away,
so the log survives a reboot or a killed task.

Usage (normally run by the scheduled task):
    python scripts/dev/boot_camera_probe.py --site <user site-packages> --seconds 300
"""

import argparse
import site
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOG_FILE = Path(r"C:\ProgramData\VisionAuth\boot_camera_probe.log")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--site", action="append", default=[], help="Extra site-packages directory (repeatable).")
    parser.add_argument("--seconds", type=int, default=300, help="How long to probe.")
    parser.add_argument("--camera", type=int, default=0, help="Camera index (default 0).")
    args = parser.parse_args()

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    log_file = LOG_FILE.open("a", encoding="utf-8")

    def log(message: str) -> None:
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}"
        print(line, flush=True)
        log_file.write(line + "\n")
        log_file.flush()

    # A SYSTEM process does not see the packages installed for the user
    for directory in args.site:
        site.addsitedir(directory)
    sys.path.insert(0, str(PROJECT_ROOT))

    try:
        import getpass

        import cv2

        from integration.windows.session import console_session_id, session_locked, session_user
        from visionauth.events.event_bus import EventBus
        from visionauth.recognition.recognition import Recognition
    except Exception as e:
        log(f"IMPORT FAILED: {type(e).__name__}: {e}")
        return

    log(f"=== start: process user={getpass.getuser()} python={sys.executable}")
    recognition = Recognition(EventBus())
    camera = None
    stats = {"before_signin": 0, "frames": 0, "faces": 0}
    start = time.monotonic()

    while time.monotonic() - start < args.seconds:
        console = console_session_id()
        user = session_user(console)
        locked = session_locked(console) if user else None

        if camera is None or not camera.isOpened():
            camera = cv2.VideoCapture(args.camera, cv2.CAP_DSHOW)
            camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        opened = camera.isOpened()
        ok, frame = camera.read() if opened else (False, None)
        ok = ok and frame is not None
        faces = len(recognition.process_frame(frame)) if ok else 0
        brightness = f"{frame.mean():.0f}" if ok else "-"
        log(f"console_session={console} signed_in={user or '-'} locked={locked} opened={opened} frame={ok} brightness={brightness} faces={faces}")

        if user is None:
            stats["before_signin"] += 1
            stats["frames"] += ok
            stats["faces"] += faces > 0
        if not ok and camera is not None:
            camera.release()
            camera = None
        time.sleep(1)

    if camera is not None:
        camera.release()
    log(
        f"=== SUMMARY before sign-in: {stats['before_signin']} checks, "
        f"{stats['frames']} with a frame, {stats['faces']} with a face"
    )
    log_file.close()


if __name__ == "__main__":
    main()
