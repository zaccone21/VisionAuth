"""Live recognition demo for VisionAuth.

Shows the camera with the closest enrolled face and its similarity for each
face in view. The menu (visionauth.ps1) and the command line
(python -m visionauth.cli test) do the same with the installed settings.
"""

import logging
import sys

from visionauth.recognition.recognition_embeddings import DEFAULT_MATCH_THRESHOLD
from visionauth.ui.recognition_window import run_recognition_test

logging.basicConfig(level=logging.WARNING, handlers=[logging.StreamHandler(sys.stdout)])

if __name__ == "__main__":
    run_recognition_test("data", camera_index=0, threshold=DEFAULT_MATCH_THRESHOLD)
