"""Camera capture module for VisionAuth.

This module provides the Camera class that wraps OpenCV's VideoCapture
functionality, allowing frames to be streamed from a webcam or a video source.
"""

import logging
from collections.abc import Generator

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class CameraError(Exception):
    """Custom exception for errors occurring during camera operations."""

    pass


class Camera:
    """Manages video capture from a camera device using OpenCV.

    This class handles the lifecycle of standard webcam capture or video source.
    It provides methods to start, stop, read single frames, and continuously
    yield frames via a generator.
    """

    def __init__(
        self,
        device_index: int | str = 0,
        width: int | None = None,
        height: int | None = None,
        fps: float | None = None,
    ) -> None:
        """Initializes the camera capture instance.

        Args:
            device_index: Camera index (int) or video source path/URL (str). Defaults to 0.
            width: Target frame width. Defaults to None.
            height: Target frame height. Defaults to None.
            fps: Target frames per second. Defaults to None.
        """
        self.device_index: int | str = device_index
        self.width: int | None = width
        self.height: int | None = height
        self.fps: float | None = fps

        self._cap: cv2.VideoCapture | None = None
        self._is_running: bool = False

    @property
    def is_running(self) -> bool:
        """Indicates if the camera is currently running and active.

        Returns:
            True if the camera is capturing frames, False otherwise.
        """
        return self._is_running

    def start(self) -> None:
        """Opens the camera device and configures settings.

        Raises:
            CameraError: If the camera cannot be opened.
        """
        if self._cap is not None and self._cap.isOpened():
            logger.warning("Camera is already started and capture is open.")
            return

        logger.info("Opening camera device index/source: %s", self.device_index)

        self._cap = cv2.VideoCapture(self.device_index)

        if not self._cap.isOpened():
            self._cap = None
            raise CameraError(
                f"Failed to open camera device index/source: {self.device_index}"
            )

        # Configure properties if requested
        if self.width is not None:
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        if self.height is not None:
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        if self.fps is not None:
            self._cap.set(cv2.CAP_PROP_FPS, self.fps)

        # Log active settings
        actual_width = self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)
        actual_height = self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        actual_fps = self._cap.get(cv2.CAP_PROP_FPS)

        logger.info(
            "Camera started successfully. Resolution: %dx%d, FPS: %s",
            actual_width,
            actual_height,
            str(actual_fps),
        )
        self._is_running = True

    def stop(self) -> None:
        """Gracefully stops the frame capture and releases the camera device."""
        self._is_running = False
        if self._cap is not None:
            logger.info("Releasing camera device index/source: %s", self.device_index)
            self._cap.release()
            self._cap = None
            logger.info("Camera device released successfully.")

    def capture_frame(self) -> np.ndarray | None:
        """Captures a single frame from the camera.

        Returns:
            The captured frame as a NumPy array (BGR format), or None if
            capturing fails or the camera is not running.
        """
        if self._cap is None or not self._cap.isOpened():
            logger.warning("Attempted to capture frame but camera is not open.")
            return None

        ret, frame = self._cap.read()
        if not ret or frame is None:
            logger.error("Failed to read frame from camera source.")
            return None

        return frame

    def stream(self) -> Generator[np.ndarray, None, None]:
        """Continuously yields captured frames from the camera.

        If the camera is not already started, it will be started automatically.
        The stream generator exits gracefully when stop() is called or when
        an EOF (end of video file) is reached.

        Yields:
            Captured frames as NumPy arrays (BGR format).

        Raises:
            CameraError: If the camera fails to start.
        """
        if not self._is_running:
            self.start()

        try:
            while self._is_running:
                frame = self.capture_frame()
                if frame is None:
                    logger.warning("Stream ended or frame capture failed.")
                    break
                yield frame
        finally:
            self.stop()

    def read(self) -> tuple[bool, np.ndarray | None]:
        """Captures a single frame, returning a success flag and the frame.

        This conforms to the standard OpenCV VideoCapture.read() interface.

        Returns:
            A tuple of (success_flag, frame_data).
        """
        frame = self.capture_frame()
        if frame is None:
            return False, None
        return True, frame

    def frames(self) -> Generator[np.ndarray, None, None]:
        """Continuously yields captured frames from the camera.

        If the camera is not already started, it will be started automatically.
        The generator exits gracefully when stop() is called or when
        an EOF (end of video file) is reached.

        Yields:
            Captured frames as NumPy arrays (BGR format).

        Raises:
            CameraError: If the camera fails to start.
        """
        yield from self.stream()

    def __enter__(self) -> "Camera":
        """Context manager entry point."""
        self.start()
        return self

    def __exit__(
        self, exc_type: type | None, exc_val: BaseException | None, exc_tb: type | None
    ) -> None:
        """Context manager exit point, ensuring resources are released."""
        self.stop()
