"""Face ID style enrollment screen rendered with OpenCV and Pillow.

The camera is shown mirrored inside a circle on a black background, surrounded
by a ring of ticks. Ticks in the direction the user is looking grow longer, and
ticks the user has already looked towards turn green, which guides them to move
their head in a circle as Apple's Face ID enrollment does.
"""

import math
import os
import time

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from visionauth.recognition.head_pose import (
    DEFAULT_PITCH_THRESHOLD,
    DEFAULT_YAW_THRESHOLD,
    HeadPose,
)

# BGR colors
GREEN = (88, 209, 48)
RED = (58, 69, 255)
TICK_IDLE = (85, 85, 85)
TEXT_PRIMARY = (255, 255, 255)
TEXT_SECONDARY = (160, 160, 160)

FONT_CANDIDATES = (
    r"C:\Windows\Fonts\segoeui.ttf",
    "/System/Library/Fonts/SFNS.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)

COMPLETION_SWEEP_SECONDS = 0.7


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Loads the first available system UI font, falling back to Pillow's default."""
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


class FaceIdOverlay:
    """Renders the enrollment screen for each camera frame.

    Typical use: call update() with the current head pose, then render() with the
    raw frame and the message to show. Call mark_complete() once enrollment succeeds.
    """

    def __init__(
        self,
        canvas_size: tuple[int, int] = (720, 760),
        tick_count: int = 72,
        yaw_threshold: float = DEFAULT_YAW_THRESHOLD,
        pitch_threshold: float = DEFAULT_PITCH_THRESHOLD,
    ) -> None:
        """Initializes the overlay.

        Args:
            canvas_size: Output image size as (width, height).
            tick_count: Number of ticks around the circle.
            yaw_threshold: Yaw at which a look direction counts as reached.
            pitch_threshold: Pitch at which a look direction counts as reached.
        """
        self.width, self.height = canvas_size
        self.tick_count = tick_count
        self.yaw_threshold = yaw_threshold
        self.pitch_threshold = pitch_threshold

        self.center = (self.width // 2, int(self.height * 0.46))
        self.radius = int(min(self.width, self.height) * 0.29)

        self.covered = np.zeros(tick_count, dtype=bool)
        self._direction = (0.0, 0.0)
        self._complete_since: float | None = None

        self._title_font = _load_font(30)
        self._subtitle_font = _load_font(20)

        yy, xx = np.ogrid[: 2 * self.radius, : 2 * self.radius]
        distance = np.sqrt((xx - self.radius + 0.5) ** 2 + (yy - self.radius + 0.5) ** 2)
        self._circle_alpha = np.clip(self.radius - distance, 0.0, 1.0)[..., None]

    @property
    def coverage(self) -> float:
        """Fraction of ring ticks the user has looked towards."""
        return float(self.covered.mean())

    def reset(self) -> None:
        """Clears coverage and completion state for a new enrollment."""
        self.covered[:] = False
        self._direction = (0.0, 0.0)
        self._complete_since = None

    def update(self, head_pose: HeadPose | None) -> None:
        """Feeds the latest head pose, marking the ticks the user is looking towards.

        Args:
            head_pose: Pose estimated on the unmirrored frame, or None if no face.
        """
        if head_pose is None:
            target = (0.0, 0.0)
        else:
            # Screen coordinates of the mirrored preview: looking to the user's
            # left points left on screen, looking up points up (negative y).
            target = (
                -head_pose.yaw / self.yaw_threshold,
                -head_pose.pitch / self.pitch_threshold,
            )
        smoothing = 0.45
        self._direction = (
            self._direction[0] + smoothing * (target[0] - self._direction[0]),
            self._direction[1] + smoothing * (target[1] - self._direction[1]),
        )

        dx, dy = self._direction
        if math.hypot(dx, dy) >= 1.0:
            tick = round(math.atan2(dy, dx) / (2 * math.pi) * self.tick_count)
            for offset in range(-3, 4):
                self.covered[(tick + offset) % self.tick_count] = True

    def mark_complete(self) -> None:
        """Starts the completion animation: the ring fills and a checkmark appears."""
        if self._complete_since is None:
            self._complete_since = time.monotonic()

    @property
    def completion_finished(self) -> bool:
        """True once the completion animation has fully played."""
        return (
            self._complete_since is not None
            and time.monotonic() - self._complete_since > COMPLETION_SWEEP_SECONDS + 0.8
        )

    def render(self, frame: np.ndarray, title: str, subtitle: str = "", error: bool = False) -> np.ndarray:
        """Draws the enrollment screen for one camera frame.

        Args:
            frame: Raw (unmirrored) BGR camera frame.
            title: Main instruction shown below the circle.
            subtitle: Secondary line shown under the title.
            error: If True, draws the ring in red.

        Returns:
            The BGR canvas to display.
        """
        canvas = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        completion = self._completion_progress()

        self._draw_camera(canvas, frame, dimmed=completion is not None)
        self._draw_ticks(canvas, completion, error)
        if completion is not None and completion >= 1.0:
            self._draw_checkmark(canvas)

        return self._draw_text(canvas, title, subtitle)

    def _completion_progress(self) -> float | None:
        if self._complete_since is None:
            return None
        return min(1.0, (time.monotonic() - self._complete_since) / COMPLETION_SWEEP_SECONDS)

    def _draw_camera(self, canvas: np.ndarray, frame: np.ndarray, dimmed: bool) -> None:
        """Pastes the mirrored, square-cropped camera view inside the circle."""
        mirrored = cv2.flip(frame, 1)
        h, w = mirrored.shape[:2]
        side = min(h, w)
        x0, y0 = (w - side) // 2, (h - side) // 2
        view = cv2.resize(mirrored[y0 : y0 + side, x0 : x0 + side], (2 * self.radius, 2 * self.radius))
        if dimmed:
            view = (cv2.GaussianBlur(view, (0, 0), 6) * 0.35).astype(np.uint8)

        cx, cy = self.center
        top, left = cy - self.radius, cx - self.radius
        region = canvas[top : top + 2 * self.radius, left : left + 2 * self.radius]
        region[:] = (view * self._circle_alpha + region * (1.0 - self._circle_alpha)).astype(np.uint8)

    def _draw_ticks(self, canvas: np.ndarray, completion: float | None, error: bool) -> None:
        """Draws the ring, lengthening ticks in the direction the user is looking."""
        cx, cy = self.center
        inner = self.radius + 16
        dx, dy = self._direction
        strength = min(math.hypot(dx, dy), 1.5) / 1.5
        look_angle = math.atan2(dy, dx)

        for i in range(self.tick_count):
            angle = 2 * math.pi * i / self.tick_count
            length = 12.0
            if completion is None and strength > 0.05:
                falloff = max(0.0, math.cos(angle - look_angle)) ** 6
                length += 20.0 * strength * falloff

            if error:
                color = RED
            elif completion is not None:
                filled = i / self.tick_count <= completion or self.covered[i]
                color = GREEN if filled else TICK_IDLE
            else:
                color = GREEN if self.covered[i] else TICK_IDLE

            start = (int(cx + inner * math.cos(angle)), int(cy + inner * math.sin(angle)))
            end = (
                int(cx + (inner + length) * math.cos(angle)),
                int(cy + (inner + length) * math.sin(angle)),
            )
            cv2.line(canvas, start, end, color, 4, cv2.LINE_AA)

    def _draw_checkmark(self, canvas: np.ndarray) -> None:
        cx, cy = self.center
        r = self.radius
        points = np.array(
            [
                (cx - int(0.38 * r), cy + int(0.02 * r)),
                (cx - int(0.10 * r), cy + int(0.30 * r)),
                (cx + int(0.42 * r), cy - int(0.28 * r)),
            ],
            dtype=np.int32,
        )
        cv2.polylines(canvas, [points], False, GREEN, 14, cv2.LINE_AA)

    def _draw_text(self, canvas: np.ndarray, title: str, subtitle: str) -> np.ndarray:
        """Draws centered title and subtitle lines below the ring using a TrueType font."""
        image = Image.fromarray(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(image)
        y = self.center[1] + self.radius + 70
        for text, font, color in (
            (title, self._title_font, TEXT_PRIMARY),
            (subtitle, self._subtitle_font, TEXT_SECONDARY),
        ):
            if not text:
                continue
            for line in self._wrap(draw, text, font, self.width - 80):
                text_width = draw.textlength(line, font=font)
                draw.text(((self.width - text_width) / 2, y), line, font=font, fill=color[::-1])
                y += int(font.size * 1.35) if hasattr(font, "size") else 24
            y += 8
        return cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)

    @staticmethod
    def _wrap(
        draw: ImageDraw.ImageDraw,
        text: str,
        font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
        max_width: int,
    ) -> list[str]:
        """Splits text into lines that fit within max_width pixels."""
        lines: list[str] = []
        current = ""
        for word in text.split():
            candidate = f"{current} {word}".strip()
            if current and draw.textlength(candidate, font=font) > max_width:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        return lines
