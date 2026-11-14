"""Checks whether the webcam can be used while the Windows session is locked.

Locks the session itself, keeps reading the camera, and writes one line per
second to a log: whether the session is locked, whether a frame arrived, its
brightness and how many faces were detected. Halfway through the locked
period it releases the camera and opens it again, because the resident
service will only turn the camera on once the session is already locked.

Usage:
    python scripts/lock_screen_camera_probe.py

Then stay in front of the camera until the screen locks, wait about a
minute, and unlock with your password. The result is printed and saved to
lock_screen_camera_probe.log in the project root.
"""

import argparse
import ctypes
import sys
import time
from pathlib import Path

import cv2

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from integration.windows.session import session_locked  # noqa: E402
from visionauth.events.event_bus import EventBus  # noqa: E402
from visionauth.recognition.recognition import Recognition  # noqa: E402

LOG_FILE = PROJECT_ROOT / "lock_screen_camera_probe.log"


def open_camera(index: int) -> cv2.VideoCapture:
    camera = cv2.VideoCapture(index, cv2.CAP_DSHOW)
    camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    return camera


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--camera", type=int, default=0, help="Camera index (default 0).")
    parser.add_argument("--locked-seconds", type=int, default=60, help="How long to probe while locked.")
    parser.add_argument("--no-lock", action="store_true", help="Do not lock the session (dry run).")
    args = parser.parse_args()

    recognition = Recognition(EventBus())
    lines: list[str] = []

    def log(message: str) -> None:
        line = f"{time.strftime('%H:%M:%S')} {message}"
        lines.append(line)
        print(line, flush=True)

    camera = open_camera(args.camera)
    log(f"camera opened before locking: {camera.isOpened()}")

    if not args.no_lock:
        log("locking the session in 3 seconds...")
        time.sleep(3)
        ctypes.windll.user32.LockWorkStation()
        time.sleep(2)

    start = time.monotonic()
    reopened = False
    unlocked_streak = 0
    while time.monotonic() - start < args.locked_seconds + 30:
        locked = session_locked()
        elapsed = time.monotonic() - start

        if locked and not reopened and elapsed > args.locked_seconds / 2:
            camera.release()
            camera = open_camera(args.camera)
            reopened = True
            log(f"camera released and reopened while locked: {camera.isOpened()}")

        ok, frame = camera.read()
        faces = len(recognition.process_frame(frame)) if ok and frame is not None else 0
        brightness = f"{frame.mean():.0f}" if ok and frame is not None else "-"
        log(f"locked={locked} frame={ok} brightness={brightness} faces={faces}")

        # Stop a few seconds after the user unlocks, once the locked period is covered
        unlocked_streak = 0 if locked else unlocked_streak + 1
        if (args.no_lock and elapsed > 5) or (not locked and reopened and unlocked_streak >= 3):
            break
        time.sleep(1)

    camera.release()
    recognition.close()

    locked_lines = [line for line in lines if "locked=True" in line]
    frames = sum("frame=True" in line for line in locked_lines)
    with_faces = sum("faces=0" not in line for line in locked_lines)
    summary = (
        f"SUMMARY: {len(locked_lines)} checks while locked, "
        f"{frames} with a frame, {with_faces} with a face detected"
    )
    log(summary)
    LOG_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Log saved to {LOG_FILE}")


if __name__ == "__main__":
    main()
