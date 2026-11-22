"""Complement the driving classifier with observable eye and head movements."""
import math
import statistics
import time
from pathlib import Path


class FaceActivity:
    def __init__(self):
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision
        path = Path(__file__).resolve().parents[2] / "models" / "face_landmarker.task"
        options = vision.FaceLandmarkerOptions(base_options=BaseOptions(model_asset_path=str(path)),
            output_face_blendshapes=True, output_facial_transformation_matrixes=True)
        self.model = vision.FaceLandmarker.create_from_options(options)
        hand_options = vision.HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(path.with_name("hand_landmarker.task"))),
            num_hands=2)
        self.hands = vision.HandLandmarker.create_from_options(hand_options)
        self.mp = mp
        self.reset_mount()

    def reset_mount(self):
        self.call_since = None
        self.last_call_pose = None
        self.forward_yaw = None
        self.samples = []
        self.calibrating = False
        self.last_pose = 0
        self.calibration_id = None
        self.mount_note = ""

    def start_calibration(self, request_id):
        if request_id and request_id != self.calibration_id:
            self.reset_mount()
            self.calibration_id = request_id
            self.calibrating = True
            self.mount_note = "Look at the road and hold your head still."

    def relative_yaw(self, yaw):
        if self.calibrating:
            now = time.monotonic()
            if now - self.last_pose > 2:
                self.samples.clear()
            self.last_pose = now
            self.samples = (self.samples + [yaw])[-5:]
            if len(self.samples) == 5 and max(self.samples)-min(self.samples) <= 8:
                self.forward_yaw = statistics.median(self.samples)
                self.calibrating = False
                self.mount_note = "Road-facing position saved"
            else:
                return None
        return yaw if self.forward_yaw is None else (yaw-self.forward_yaw+180)%360-180

    def close(self):
        self.model.close()
        self.hands.close()

    def sustained_call_pose(self, near_ear, now):
        if not near_ear:
            self.call_since = self.last_call_pose = None
            return False
        if self.last_call_pose is None or now - self.last_call_pose > 2:
            self.call_since = now
        self.last_call_pose = now
        return now - self.call_since >= 1.25

    @staticmethod
    def hand_near_ear(face, hands, width, height):
        # Face landmarks 234 and 454 lie on opposite sides of the face.
        def point(mark):
            return (mark.x * width, mark.y * height)
        sides = [point(face[i]) for i in (234, 454)]
        radius = .4 * math.dist(*sides)
        for hand in hands:
            for side in sides:
                nearby = sum(math.dist(point(hand[i]), side) <= radius for i in (5, 6, 9, 10, 13, 14, 17, 18))
                if nearby >= 3:
                    return True
        return False

    def observe(self, jpeg, readings):
        import cv2
        import numpy as np
        frame = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=rgb)
        result = self.model.detect(image)
        if not result.face_blendshapes or not result.facial_transformation_matrixes:
            self.sustained_call_pose(False, time.monotonic())
            if self.calibrating:
                self.samples.clear()
                self.mount_note = "Face unavailable. Adjust the mount so the camera sees both eyes."
            self.resolve_turn(readings, None)
            return
        scores = {s.category_name: s.score for s in result.face_blendshapes[0]}
        rotation = result.facial_transformation_matrixes[0]
        yaw = math.degrees(math.atan2(rotation[0, 2], rotation[2, 2]))
        yaw = self.relative_yaw(yaw)
        if self.calibrating:
            self.mount_note = f"Look at the road and hold still ({len(self.samples)}/5)"
        self.resolve_turn(readings, yaw)
        self.apply(readings, scores["eyeBlinkLeft"], scores["eyeBlinkRight"], yaw)
        candidate = (readings.classifier_label == "talking_phone" and readings.classifier_score >= .90
                     and readings.handset_visible is False)
        near_ear = False
        if candidate:
            hands = self.hands.detect(image).hand_landmarks
            near_ear = self.hand_near_ear(result.face_landmarks[0], hands, rgb.shape[1], rgb.shape[0])
        if self.sustained_call_pose(near_ear, time.monotonic()):
            # Display a possible call. This evidence does not confirm phone use.
            readings.behavior = "possible_call"

    def resolve_turn(self, readings, yaw):
        # The image classifier sees camera-relative turns. Once calibrated,
        # only road-relative pose can confirm its turning prediction.
        if readings.behavior == "turning" and (self.calibrating or self.forward_yaw is not None):
            if yaw is None or abs(yaw) < 25:
                readings.behavior = "unconfirmed_activity"
                readings.confidence = 0
                readings.assessment_available = yaw is not None
                readings.assessment_note = "" if yaw is not None else "Waiting for a reliable road-relative head position"

    @staticmethod
    def apply(readings, left_blink, right_blink, yaw):
        readings.face_activity = "Facing forward" if yaw is not None else ""
        if min(left_blink, right_blink) >= .55:
            readings.face_activity = "Eyes closed"
            readings.eyes_closed = True
        elif yaw is not None and abs(yaw) >= 25:
            readings.face_activity = "Looking aside"
            readings.looking_away = True
        if readings.eyes_closed or readings.looking_away:
            readings.assessment_available = True
            readings.assessment_note = ""
