
"""Driver drowsiness detection using MediaPipe Face Landmarker and EAR."""

from collections import deque
from pathlib import Path
import time

import cv2
import mediapipe as mp
import numpy as np


class DrowsinessDetector:
    """Detect prolonged eye closure and estimate PERCLOS."""

    LEFT_EYE = (362, 385, 387, 263, 373, 380)
    RIGHT_EYE = (33, 160, 158, 133, 153, 144)

    def __init__(
        self,
        model_path="models/face_landmarker.task",
        ear_threshold=0.21,
        warning_seconds=1.5,
        critical_seconds=2.5,
        perclos_window_seconds=30.0,
        minimum_observation_seconds=5.0,
        maximum_gap_seconds=1.0,
    ):
        if not Path(model_path).is_file():
            raise FileNotFoundError(
                f"Face Landmarker model not found: {model_path}"
            )

        self.ear_threshold = ear_threshold
        self.warning_seconds = warning_seconds
        self.critical_seconds = critical_seconds
        self.perclos_window_seconds = perclos_window_seconds
        self.minimum_observation_seconds = minimum_observation_seconds
        self.maximum_gap_seconds = maximum_gap_seconds

        self.closed_since = None
        self.last_observation_time = None
        self.previous_state = None

        self.segments = deque()

        self.face_landmarker = self._create_landmarker(model_path)

    @staticmethod
    def _create_landmarker(model_path):
        BaseOptions = mp.tasks.BaseOptions
        FaceLandmarker = mp.tasks.vision.FaceLandmarker
        FaceLandmarkerOptions = mp.tasks.vision.FaceLandmarkerOptions
        RunningMode = mp.tasks.vision.RunningMode

        options = FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model_path)),
            running_mode=RunningMode.VIDEO,
            num_faces=1,
            min_face_detection_confidence=0.5,
            min_face_presence_confidence=0.5,
            min_tracking_confidence=0.5,
        )

        return FaceLandmarker.create_from_options(options)

    @staticmethod
    def _distance(p1, p2):
        return float(
            np.linalg.norm(
                np.asarray(p1, dtype=np.float64)
                - np.asarray(p2, dtype=np.float64)
            )
        )

    @classmethod
    def _calculate_ear(cls, landmarks, eye_indices):
        try:
            points = [
                (landmarks[i].x, landmarks[i].y)
                for i in eye_indices
            ]

            if not np.isfinite(points).all():
                return None

            vertical_1 = cls._distance(points[1], points[5])
            vertical_2 = cls._distance(points[2], points[4])
            horizontal = cls._distance(points[0], points[3])

            if horizontal < 1e-6:
                return None

            ear = (
                vertical_1 + vertical_2
            ) / (2.0 * horizontal)

            return ear if np.isfinite(ear) else None

        except (IndexError, AttributeError, TypeError, ValueError):
            return None

    def _add_segment(self, start, end, observed, closed):
        if end <= start:
            return

        self.segments.append(
            (start, end, observed, closed)
        )

    def _advance_timeline(self, now):
        if self.last_observation_time is not None:
            gap = now - self.last_observation_time

            if (
                0 < gap <= self.maximum_gap_seconds
                and self.previous_state is not None
            ):
                self._add_segment(
                    self.last_observation_time,
                    now,
                    self.previous_state[0],
                    self.previous_state[1],
                )

            elif gap > self.maximum_gap_seconds:
                self.closed_since = None

        self.last_observation_time = now

        cutoff = now - self.perclos_window_seconds

        while self.segments and self.segments[0][1] <= cutoff:
            self.segments.popleft()

        if self.segments and self.segments[0][0] < cutoff:
            start, end, observed, closed = self.segments[0]

            self.segments[0] = (
                cutoff,
                end,
                observed,
                closed,
            )

    def _calculate_perclos(self, now):
        cutoff = now - self.perclos_window_seconds

        observed_duration = 0.0
        closed_duration = 0.0

        for start, end, observed, closed in self.segments:
            start = max(start, cutoff)
            end = min(end, now)

            duration = max(0.0, end - start)

            if observed:
                observed_duration += duration

                if closed:
                    closed_duration += duration

        if observed_duration < self.minimum_observation_seconds:
            return None

        return min(
            1.0,
            max(0.0, closed_duration / observed_duration),
        )

    def _unavailable(self, reason):
        return {
            "available": False,
            "face_detected": False,
            "drowsy": False,
            "alert_level": "UNKNOWN",
            "ear": None,
            "left_ear": None,
            "right_ear": None,
            "eyes_closed": False,
            "eye_closed": False,
            "perclos": None,
            "closed_duration": 0.0,
            "reason": reason,
        }

    def process_frame(self, frame):
        """Process one BGR camera frame and return drowsiness status."""

        if frame is None or not isinstance(frame, np.ndarray):
            raise ValueError("Invalid camera frame.")

        if frame.size == 0:
            raise ValueError("Camera frame is empty.")

        now = time.monotonic()

        self._advance_timeline(now)

        rgb = cv2.cvtColor(
            frame,
            cv2.COLOR_BGR2RGB,
        )

        rgb = np.ascontiguousarray(rgb)

        mp_image = mp.Image(
            image_format=mp.ImageFormat.SRGB,
            data=rgb,
        )

        timestamp_ms = int(now * 1000)

        if not hasattr(self, "_last_timestamp_ms"):
            self._last_timestamp_ms = -1

        timestamp_ms = max(
            timestamp_ms,
            self._last_timestamp_ms + 1,
        )

        self._last_timestamp_ms = timestamp_ms

        result = self.face_landmarker.detect_for_video(
            mp_image,
            timestamp_ms,
        )

        if not result.face_landmarks:
            self.closed_since = None
            self.previous_state = (False, False)

            return {
                "available": True,
                "face_detected": False,
                "drowsy": False,
                "alert_level": "UNKNOWN",
                "ear": None,
                "left_ear": None,
                "right_ear": None,
                "eyes_closed": False,
                "eye_closed": False,
                "perclos": self._calculate_perclos(now),
                "closed_duration": 0.0,
                "reason": "Face not detected",
            }

        landmarks = result.face_landmarks[0]

        left_ear = self._calculate_ear(
            landmarks,
            self.LEFT_EYE,
        )

        right_ear = self._calculate_ear(
            landmarks,
            self.RIGHT_EYE,
        )

        if left_ear is None or right_ear is None:
            self.closed_since = None
            self.previous_state = (False, False)

            return self._unavailable(
                "Could not calculate eye aspect ratio"
            )

        avg_ear = (left_ear + right_ear) / 2.0

        eyes_closed = (
            left_ear < self.ear_threshold
            and right_ear < self.ear_threshold
        )

        if eyes_closed:
            if self.closed_since is None:
                self.closed_since = now

            closed_duration = now - self.closed_since

        else:
            self.closed_since = None
            closed_duration = 0.0

        self.previous_state = (True, eyes_closed)

        perclos = self._calculate_perclos(now)

        if closed_duration >= self.critical_seconds:
            alert_level = "CRITICAL"

        elif closed_duration >= self.warning_seconds:
            alert_level = "WARNING"

        else:
            alert_level = "NORMAL"

        return {
            "available": True,
            "face_detected": True,
            "drowsy": alert_level in ("WARNING", "CRITICAL"),
            "alert_level": alert_level,
            "ear": round(avg_ear, 4),
            "left_ear": round(left_ear, 4),
            "right_ear": round(right_ear, 4),
            "eyes_closed": eyes_closed,
            "eye_closed": eyes_closed,
            "perclos": (
                round(perclos, 4)
                if perclos is not None
                else None
            ),
            "closed_duration": round(closed_duration, 2),
            "reason": (
                "Prolonged eye closure"
                if alert_level != "NORMAL"
                else "Normal"
            ),
        }

    def reset(self):
        """Reset temporal measurements."""

        self.closed_since = None
        self.last_observation_time = None
        self.previous_state = None
        self.segments.clear()
        self._last_timestamp_ms = -1

    def close(self):
        """Release MediaPipe resources."""

        if self.face_landmarker is not None:
            self.face_landmarker.close()
            self.face_landmarker = None
