
"use strict";

/* =========================================================
   MODEL CONFIGURATION
========================================================= */

const MODEL_URL = "/models/driver_behavior_mobilenetv3.onnx";

/*
 * MobileNetV3-Small
 *
 * 9 driver behaviour classes.
 * Class indices MUST match training order.
 */

const CLASS_NAMES = [
    "safe_driving",          // 0
    "texting_right",         // 1
    "talking_phone_right",   // 2
    "texting_left",          // 3
    "talking_phone_left",    // 4
    "operating_radio",       // 5
    "drinking",              // 6
    "reaching_behind",       // 7
    "talking_to_passenger"   // 8
];

/* Must match ONNX model input dimensions */

const SIZE = 256;

/* Expected output classes */

const NUM_CLASSES = 9;


/* =========================================================
   AI INFERENCE CONFIGURATION
========================================================= */

const INFERENCE_INTERVAL = 250;


/* =========================================================
   CAMERA TRANSMISSION CONFIGURATION
========================================================= */

const PREVIEW_FPS = 12;

const PREVIEW_INTERVAL = 1000 / PREVIEW_FPS;

const PREVIEW_CONTROL_INTERVAL = 1000;

const PREVIEW_WIDTH = 480;

const PREVIEW_QUALITY = 0.48;

const PREVIEW_MAX_BYTES = 200000;


/* =========================================================
   SERVER CLOCK
========================================================= */

const CLOCK_INTERVAL = 30000;


/* =========================================================
   IMAGENET NORMALIZATION
========================================================= */

/*
 * RGB normalization:
 *
 * mean = [0.485, 0.456, 0.406]
 * std  = [0.229, 0.224, 0.225]
 */

const MEAN = [
    0.485,
    0.456,
    0.406
];

const STD = [
    0.229,
    0.224,
    0.225
];


/* =========================================================
   DOM REFERENCES
========================================================= */

const $ = id => document.getElementById(id);

const video = $("camera");

const token = location.hash.slice(1);


/* =========================================================
   APPLICATION STATE
========================================================= */

let session = null;

let stream = null;

let running = false;

let starting = false;

let inferenceBusy = false;

let inferenceTimer = null;

let startAttempt = 0;


/* =========================================================
   SENSOR STATE
========================================================= */

let gpsPosition = null;

let gpsStatus = "estimating";

let gpsWatchId = null;

let acceleration = [0, 0, 0];

let gyroscope = [0, 0, 0];


/* =========================================================
   TIMING AND TRIP STATE
========================================================= */

let clockOffset = 0;

let lastClockSync = 0;

let activeTripId = null;


/* =========================================================
   CAMERA PREVIEW STATE
========================================================= */

let previewEnabled = false;

let previewTimer = null;

let previewBusy = false;

let lastPreviewControlCheck = 0;


/* =========================================================
   CANVAS STATE
========================================================= */

let inputCanvas = null;

let previewCanvas = null;


/* =========================================================
   PREDICTION STATE
========================================================= */

let lastClientPrediction = null;


/* =========================================================
   SPEED SIMULATOR
========================================================= */

let manualSpeedEnabled = false;

let manualSpeedKmh = 60;
