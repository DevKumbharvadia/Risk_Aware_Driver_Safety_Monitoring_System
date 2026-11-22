"""Locate the largest visible face and annotate only the preview copy."""
from io import BytesIO
from pathlib import Path
import threading
import time

from .trained_model import DEFAULT_THRESHOLD


def classifier_summary(label, score, handset_visible=None):
    names = {"safe_driving": "Normal driving", "turning": "Turning",
             "texting_phone": "Texting", "talking_phone": "Talking on phone",
             "other_activities": "Other activity"}
    if label not in names:
        return ""
    if label in ("talking_phone", "texting_phone") and handset_visible is False:
        return "Phone-use prediction rejected · no handset detected"
    return names[label] + (" (uncertain)" if score < DEFAULT_THRESHOLD else "")


def behavior_label(behavior, confidence, face_activity="", handset_visible=None):
    labels = {"safe_driving": "Normal driving", "turning": "Looking aside",
              "texting_phone": "Texting", "talking_phone": "Talking on phone",
              "other_activities": "Other activity"}
    if face_activity == "Eyes closed":
        return face_activity
    if behavior == "possible_call":
        return "Possible call · Looking aside" if face_activity == "Looking aside" else "Possible call"
    if handset_visible and (behavior not in ("talking_phone", "texting_phone") or confidence < DEFAULT_THRESHOLD):
        return "Phone visible · Looking aside" if face_activity == "Looking aside" else "Phone visible"
    if face_activity == "Looking aside":
        if behavior in ("talking_phone", "texting_phone") and handset_visible and confidence >= DEFAULT_THRESHOLD:
            return labels[behavior] + " · Looking aside"
        return face_activity
    if not behavior:
        return "Waiting for camera"
    if behavior == "unconfirmed_activity":
        return face_activity or "Activity unclear"
    if confidence < DEFAULT_THRESHOLD:
        return face_activity or "Unclear view"
    return labels.get(behavior, "Unclear view")


class FacePreview:
    def __init__(self):
        import cv2
        folder = Path(cv2.data.haarcascades)
        self.front = cv2.CascadeClassifier(str(folder / "haarcascade_frontalface_default.xml"))
        self.profile = cv2.CascadeClassifier(str(folder / "haarcascade_profileface.xml"))
        self.previous = None
        self.last_seen = 0
        self.lock = threading.Lock()

    def annotate(self, jpeg, level):
        import cv2
        import numpy as np
        from PIL import Image
        with Image.open(BytesIO(jpeg)) as image:
            if image.format != "JPEG" or max(image.size) > 1024:
                raise ValueError("Invalid preview dimensions")
        frame = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError("Invalid preview frame")
        height, width = frame.shape[:2]
        scale = min(1, 320 / max(width, height))
        small = cv2.resize(frame, None, fx=scale, fy=scale)
        gray = cv2.equalizeHist(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY))
        with self.lock:
            faces = self.front.detectMultiScale(gray, 1.15, 5, minSize=(24, 24))
            if not len(faces):
                faces = self.profile.detectMultiScale(gray, 1.15, 5, minSize=(24, 24))
            if not len(faces):
                mirrored = self.profile.detectMultiScale(cv2.flip(gray, 1), 1.15, 5, minSize=(24, 24))
                faces = [(gray.shape[1]-x-w, y, w, h) for x, y, w, h in mirrored]
            now = time.monotonic()
            if len(faces):
                x, y, w, h = max(faces, key=lambda box: box[2]*box[3])
                side = min(min(width,height), max(w,h)*1.12/scale)
                left = max(0,min(width-side,(x+w/2)/scale-side/2))
                top = max(0,min(height-side,(y+h/2)/scale-side/2))
                box = [left/width, top/height, side/width, side/height]
                if self.previous and now-self.last_seen<.4 and abs(box[0]-self.previous[0])<.12:
                    box = [.25*old+.75*new for old,new in zip(self.previous,box)]
                self.previous, self.last_seen = box, now
            elif now-self.last_seen>.25:
                self.previous = None
            box = self.previous
        if box is None:
            return jpeg, None
        x,y,w,h = box
        colors = {"LOW": (100,210,68), "CAUTION": (35,155,255), "HIGH": (60,65,245)}
        cv2.rectangle(frame,(round(x*width),round(y*height)),(round((x+w)*width),round((y+h)*height)),
                      colors.get(level,(190,190,190)),2,cv2.LINE_AA)
        ok, encoded = cv2.imencode(".jpg",frame,[cv2.IMWRITE_JPEG_QUALITY,75])
        return (encoded.tobytes() if ok else jpeg), box
