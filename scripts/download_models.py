"""Downloads the ONNX models VisionAuth needs into the project's models/ directory.

Models come from the OpenCV Model Zoo (Apache-2.0):
https://github.com/opencv/opencv_zoo

Usage:
    python scripts/download_models.py
"""

import hashlib
import logging
import sys
import urllib.request
from pathlib import Path

logger = logging.getLogger("download_models")

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
ZOO_URL = "https://github.com/opencv/opencv_zoo/raw/main/models"

MODELS = {
    "face_recognition_sface_2021dec.onnx": (
        f"{ZOO_URL}/face_recognition_sface/face_recognition_sface_2021dec.onnx",
        "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
    ),
    "face_detection_yunet_2023mar.onnx": (
        f"{ZOO_URL}/face_detection_yunet/face_detection_yunet_2023mar.onnx",
        "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    ),
}


def sha256_of(path: Path) -> str:
    """Returns the hex SHA-256 digest of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(name: str, url: str, expected_sha256: str) -> None:
    """Downloads one model, skipping it if a verified copy already exists.

    Raises:
        ValueError: If the downloaded file does not match the expected checksum.
    """
    target = MODELS_DIR / name
    if target.exists() and sha256_of(target) == expected_sha256:
        logger.info("%s already present and verified.", name)
        return

    partial = target.with_suffix(".part")
    logger.info("Downloading %s ...", name)
    urllib.request.urlretrieve(url, partial)

    actual = sha256_of(partial)
    if actual != expected_sha256:
        partial.unlink()
        raise ValueError(f"Checksum mismatch for {name}: expected {expected_sha256}, got {actual}")

    partial.replace(target)
    logger.info("Saved %s", target)


def main() -> int:
    """Downloads every model in MODELS and returns a process exit code."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    MODELS_DIR.mkdir(exist_ok=True)
    try:
        for name, (url, sha256) in MODELS.items():
            download(name, url, sha256)
    except Exception as e:
        logger.error("Model download failed: %s", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
