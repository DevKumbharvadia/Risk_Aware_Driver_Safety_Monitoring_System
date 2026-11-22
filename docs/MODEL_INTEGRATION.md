# Integrated driver behavior model

On the browser phone client, a talking score of at least 0.90 with a hidden handset triggers a [hand landmark check](https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task). Repeated observations of a hand beside the ear spanning at least 1.25 seconds display **Possible call**. This cue alone adds no phone-use risk points. Touching the ear can also produce this pose.

The browser-phone launcher also runs Google's [Face Landmarker](https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task) on the manager PC. Both eye-blink scores above the threshold (0.55 or higher) indicate closed eyes. An absolute head yaw of at least 25 degrees indicates looking aside. This measures head direction, not eye gaze. Phone and owner display the camera observation independently of GPS. Missing speed leaves motion-dependent alerts pending. With speed available the existing temporal rules apply, including the two-second eye closure rule and the low-speed turning allowance. Test thresholds on the camera, particularly when wearing glasses.

Live phone-use predictions also require a visible handset in the same frame. The PC runs TorchVision SSDLite320 on each assessed frame. An ambiguous handset candidate gets a second pass on enlarged crops. An independently detected handset displays as "Phone visible" unless the behavior model also supports a specific use. Its [COCO weights](https://download.pytorch.org/models/ssdlite320_mobilenet_v3_large_coco-a79551df.pth) ship in the models folder. The 0.5 handset score cutoff is a prototype setting. An unconfirmed candidate displays as "Observing driver" and cannot accumulate phone-use risk. Small or hidden handsets may be missed, and the detector cannot establish who owns a phone elsewhere in the image. The Colab accuracy refers to the original behavior classifier.

The team trained MobileNetV3 Small in Colab using transfer learning, then partially fine-tuned its final feature blocks. The export is now used by `fleet/perception/trained_model.py`. Predictions run on the CPU without a GPU or model download at startup.

## Export and results

- Original archive: `driver_behavior_model.zip`, retained unchanged.
- Installed checkpoint: `models/driver_behavior/driver_behavior.pth`.
- Supporting files: `metadata.json` and `test_report.json` beside the checkpoint.
- SHA-256: `043814d26d881d762ea72f28395802381ee8c99a3faba5f52f4a2d716ba4d484`.
- Dataset: https://zenodo.org/records/14908802 (7,276 downloaded images).
- Split: 5,091 training, 1,088 validation, 1,097 test images, stratified by class.
- Selected model: partial fine-tuning stage, epoch 4; validation macro-F1 approximately 0.920.
- Supplied test results: accuracy 0.9124886053, macro-F1 0.9093657732.

These metrics came from the user's Colab run. Local tests check loading and integration, not a repeat of dataset evaluation. No exact duplicate files were found, but driver/session independence is not established. Similar images could occur in different splits. Webcam, vehicle, lighting and camera-position performance need separate evaluation. The local bundle contains model artifacts, not training images.

## Exact inference pipeline

1. Read an OpenCV BGR camera frame and convert it to a PIL RGB image.
2. Resize the whole image to 224×224 with torchvision's PIL resize, matching Colab validation. Do not center-crop or apply random augmentation.
3. Convert to a tensor scaled to 0–1.
4. Normalize with mean `[0.485, 0.456, 0.406]` and standard deviation `[0.229, 0.224, 0.225]`.
5. Run the exported five-output model in evaluation/inference mode on the CPU.
6. Apply softmax and preserve the top label and score.

The checkpoint loads with `weights_only=True`, strict state-dictionary matching, and validated architecture, labels and preprocessing. Constructing with `weights=None` avoids replacing the trained weights or downloading ImageNet weights. Imports are lazy, so the owner console does not require PyTorch.

## Class mapping and decisions

| ID | Training label | Use in risk rules |
| --- | --- | --- |
| 0 | other_activities | UNKNOWN; too broad to infer a particular hazard |
| 1 | safe_driving | No modeled behavior flag; drowsiness is unmeasured |
| 2 | talking_phone | Predicted phone use; duration-based caution/high alerts |
| 3 | texting_phone | Predicted phone use; duration-based caution/high alerts |
| 4 | turning | Speed-aware attention rule: suppressed at low speed, 5/10-second caution/high at moderate speed, 3/6 seconds at faster speed |

The classifier cannot identify a missing driver, yawning or eye closure. `face_visible` is `None`, not `True`, in model mode. The UI explicitly says driver presence is unmeasured. A classifier can be confidently wrong on an empty or unfamiliar scene; a score cutoff cannot replace a driver-presence detector.

Scores below 0.65 produce UNKNOWN. This is an uncalibrated threshold, not a calibrated confidence claim. Temporal rules are prototype settings too. No thresholds were selected using the test set.

`fleet/risk/attention.py` defines the speed policy: manoeuvring at up to 10 km/h, moderate speed through 30 km/h, and faster travel above that. Band changes use a 2 km/h hysteresis margin and two-second confirmation. Attention duration resets on a confirmed change, so manoeuvring time cannot cause an immediate alert after acceleration. This changes the risk layer, not the trained model. Phone use remains subject to its own duration rules. Speed does not establish reverse gear or road geometry.

## Threading and freshness

The manager PC's `MobileHandler` runs each phone POST on a server thread and hands the frame to that vehicle's `VehicleLink`, which calls the trained detector and the risk engine under a per-vehicle lock. `LatestObservation` holds one result and its monotonic capture time; a generation counter discards in-flight results after a source change, and results older than 2.5 seconds produce UNKNOWN. Repainting the same result does not add observed duration, and a confirmed source or trip change resets the risk engine.

Neural inference never runs on the owner UI thread. The owner app polls the fleet API for live monitoring; it never blocks on a phone frame. The phone uploads preview JPEGs separately, so a slow preview cannot block classification.

## Telemetry

The existing JSON and SQLite readings retain `source`, `motion_source`, `behavior`, `confidence`, `inference_ms`, `assessment_available`, and `assessment_note`. Owner live monitoring displays the class, score, inference time, and separate behavior/motion sources. UNKNOWN explanations appear in the event log.

## Future work

- Driver-presence detection and a dedicated eye-closure/drowsiness detector.
- Additional motion inputs beyond phone GPS (for example OBD-II).
- Driver/session-independent evaluation and confidence calibration on separate footage.
- Bounding boxes only if an object detector is trained; this is a whole-image classifier.
- A complete native mobile monitoring client; the browser phone page is a sensor terminal, not a standalone app.

## GPS motion source

The phone supplies speed from its GPS. `motion_source` is `phone_gps`; acceleration is unmeasured and its zero field is a placeholder. Missing, poor or stale fixes force UNKNOWN before stopped-vehicle suppression. The phone browser estimates slow speeds from displacement when the GPS speed field is unavailable.
