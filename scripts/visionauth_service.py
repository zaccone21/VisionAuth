"""Entry point of the VisionAuth Windows service.

The Service Control Manager runs this script with python.exe as SYSTEM (see
install.ps1). It reads C:\\ProgramData\\VisionAuth\\config.json, makes the
user's site-packages visible (SYSTEM does not see packages installed for a
user), logs to C:\\ProgramData\\VisionAuth\\service.log and runs the unlock
loop until the service is stopped.

Usage:
    python scripts/visionauth_service.py            (started by the SCM)
    python scripts/visionauth_service.py --console  (foreground, Ctrl+C to stop)
"""

import argparse
import json
import logging
import logging.handlers
import site
import sys
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROGRAM_DATA = Path(r"C:\ProgramData\VisionAuth")
SERVICE_NAME = "VisionAuth"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--console", action="store_true", help="Run in the foreground instead of as a service.")
    parser.add_argument("--config", type=Path, default=PROGRAM_DATA / "config.json")
    parser.add_argument("--log", type=Path, default=PROGRAM_DATA / "service.log")
    args = parser.parse_args()

    # utf-8-sig: PowerShell 5.1 writes the config with a byte order mark
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    for directory in config.get("site", []):
        site.addsitedir(directory)
    sys.path.insert(0, str(PROJECT_ROOT))

    args.log.parent.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        logging.handlers.RotatingFileHandler(args.log, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    ]
    if args.console:
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", handlers=handlers
    )
    # Per-frame stability and detection chatter would flood the log
    for noisy in ("visionauth.recognition", "visionauth.enrollment.stability", "visionauth.liveness", "visionauth.events"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    from integration.windows import unlock_daemon

    if args.console:
        stop = threading.Event()
        try:
            unlock_daemon.run(config, stop)
        except KeyboardInterrupt:
            stop.set()
        return

    from integration.windows.service_host import run_as_service

    run_as_service(SERVICE_NAME, lambda stop: unlock_daemon.run(config, stop))


if __name__ == "__main__":
    main()
