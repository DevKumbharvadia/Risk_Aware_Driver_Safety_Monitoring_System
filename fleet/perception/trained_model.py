"""CPU inference for the team's Colab model, with the exact training transform."""
from dataclasses import replace
import math
import os
from pathlib import Path
import threading
import time

from .base import Detector
from ..risk.engine import Measurements

DEFAULT_MODEL = Path(__file__).resolve().parents[2] / "models" / "driver_behavior" / "driver_behavior.pth"
CLASS_NAMES = {"other_activities", "safe_driving", "talking_phone", "texting_phone", "turning"}
DEFAULT_THRESHOLD = 0.65  # Decision threshold, not a calibrated probability of correctness.
PHONE_WEIGHTS = DEFAULT_MODEL.parents[1] / "ssdlite320_mobilenet_v3_large_coco-a79551df.pth"


def unavailable_readings(note):
    return Measurements(source="trained_model", face_visible=None,
                        assessment_available=False, assessment_note=note)


def prediction_to_readings(label, confidence, inference_ms=0.0, threshold=DEFAULT_THRESHOLD):
    """Do not turn a broad activity label into an invented eye/yawn measurement."""
    if label not in CLASS_NAMES or not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise ValueError("Invalid model prediction.")
    readings = Measurements(source="trained_model", face_visible=None, behavior=label,
                            confidence=float(confidence), inference_ms=float(inference_ms))
    if confidence < threshold:
        readings.assessment_available = False
        readings.assessment_note = "Class score below decision threshold; behavior uncertain"
    elif label == "other_activities":
        readings.assessment_available = False
        readings.assessment_note = "Other activities predicted; specific hazard cannot be determined"
    else:
        readings.phone_use = label in ("talking_phone", "texting_phone")
    return readings


class LatestObservation:
    """One recent result; old frames never build up in an inference queue."""
    def __init__(self):
        self.lock = threading.Lock()
        self.generation = 0
        self.value = None
        self.note = "Waiting for a camera prediction"

    def reset(self, note):
        with self.lock:
            self.generation += 1
            self.value = None
            self.note = note

    def ticket(self):
        with self.lock:
            return self.generation

    def publish(self, readings, captured_at, ticket):
        with self.lock:
            if ticket == self.generation:
                self.value = (replace(readings), captured_at)

    def read(self, now=None):
        return self.read_with_time(now)[0]

    def read_with_time(self, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            if self.value is None:
                return unavailable_readings(self.note), None
            readings, captured_at = self.value
            if now - captured_at > 2.5:
                return unavailable_readings("Camera prediction is stale; waiting for a fresh frame"), None
            return replace(readings), captured_at


class TrainedDetector(Detector):
    def __init__(self, model_path=DEFAULT_MODEL, threshold=DEFAULT_THRESHOLD):
        if not 0 < threshold <= 1:
            raise ValueError("Threshold must be greater than zero and at most one.")
        if not Path(model_path).is_file():
            raise FileNotFoundError(f"Model file missing: {model_path}")
        # Lazy imports keep the simulation and owner console usable without PyTorch.
        import torch
        from torchvision import transforms
        from torchvision.models import mobilenet_v3_small

        self.torch = torch
        self.threshold = threshold
        torch.set_num_threads(min(4, os.cpu_count() or 1))
        saved = torch.load(model_path, map_location="cpu", weights_only=True)
        if saved.get("architecture") != "mobilenet_v3_small":
            raise ValueError("Expected the exported MobileNetV3 Small model.")
        mapping = saved.get("class_to_idx", {})
        if set(mapping) != CLASS_NAMES or sorted(mapping.values()) != list(range(5)):
            raise ValueError("Model class mapping does not match the supported five classes.")
        self.classes = [name for name, index in sorted(mapping.items(), key=lambda item: item[1])]
        preprocessing = saved.get("preprocessing", {})
        expected = {"resize": [224, 224], "mean": [0.485, 0.456, 0.406], "std": [0.229, 0.224, 0.225]}
        if preprocessing != expected:
            raise ValueError("Unexpected preprocessing. Review the model export before using it.")
        self.transform = transforms.Compose([
            transforms.Resize(tuple(preprocessing["resize"])),
            transforms.ToTensor(),
            transforms.Normalize(preprocessing["mean"], preprocessing["std"]),
        ])
        # weights=None prevents downloads and avoids replacing the student's trained weights.
        self.model = mobilenet_v3_small(weights=None)
        self.model.classifier[-1] = torch.nn.Linear(self.model.classifier[-1].in_features, 5)
        self.model.load_state_dict(saved["model_state"], strict=True)
        self.model.eval()
        self.phone_detector = None

    def handset_visible(self, rgb, check_texting_region=False):
        """Check the same camera frame for a COCO cell-phone object."""
        from torchvision.models.detection import ssdlite320_mobilenet_v3_large, SSDLite320_MobileNet_V3_Large_Weights
        from torchvision.transforms.functional import to_tensor
        if self.phone_detector is None:
            detector = ssdlite320_mobilenet_v3_large(weights=None, weights_backbone=None)
            detector.load_state_dict(self.torch.load(PHONE_WEIGHTS, map_location="cpu", weights_only=True))
            self.phone_detector = detector.eval()
        phone_class = SSDLite320_MobileNet_V3_Large_Weights.DEFAULT.meta["categories"].index("cell phone")
        def best_phone(objects):
            scores = objects["scores"][objects["labels"] == phone_class]
            return scores.max().item() if scores.numel() else 0

        with self.torch.inference_mode():
            score = best_phone(self.phone_detector([to_tensor(rgb)])[0])
            if score >= .5:
                return True
            if score < .10:
                if not check_texting_region:
                    return False
                # A handset held by the wheel or lap may occupy few pixels in
                # the full view. Check one enlarged lower-centre crop.
                width, height = rgb.size
                lower = rgb.crop((width//6,height//3,width-width//6,height))
                return best_phone(self.phone_detector([to_tensor(lower)])[0]) >= .5
            # Zoom into overlapping regions if the first pass sees a possible
            # small handset. Crops still need the full confirmation threshold.
            width, height = rgb.size
            w, h = max(1, round(width*.6)), max(1, round(height*.6))
            crops = [to_tensor(rgb.crop((x,y,x+w,y+h)))
                     for x in (0,width-w) for y in (0,height-h)]
            return any(best_phone(objects) >= .5 for objects in self.phone_detector(crops))

    def read(self, frame=None):
        """Accept an OpenCV BGR frame. Resize and normalize exactly as in Colab."""
        if frame is None or frame.ndim != 3 or frame.shape[2] != 3 or frame.size == 0:
            return unavailable_readings("No usable camera frame")
        from PIL import Image

        started = time.perf_counter()
        rgb = Image.fromarray(frame[:, :, ::-1].copy())
        tensor = self.transform(rgb).unsqueeze(0)
        with self.torch.inference_mode():
            scores = self.model(tensor).softmax(dim=1)[0]
        confidence, index = scores.max(dim=0)
        readings = prediction_to_readings(self.classes[index.item()], confidence.item(), threshold=self.threshold)
        readings.classifier_label = readings.behavior
        readings.classifier_score = readings.confidence
        texting_index = self.classes.index("texting_phone")
        # Include plausible second-choice texting predictions in the extra check.
        readings.handset_visible = self.handset_visible(rgb, scores[texting_index].item() >= .15)
        if readings.phone_use and not readings.handset_visible:
            readings.phone_use = False
            readings.behavior = "unconfirmed_activity"
            readings.assessment_available = False
            readings.assessment_note = "No handset detected; activity uncertain"
            readings.confidence = 0.0
        readings.inference_ms = (time.perf_counter() - started) * 1000
        return readings
