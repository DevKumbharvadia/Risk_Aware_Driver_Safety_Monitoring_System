
"use strict";

/* Model configuration */

const MODEL_URL = "/models/driver_mobilenetv3_small.onnx";

const CLASS_NAMES = [
    "other_activities",
    "safe_driving",
    "talking_phone",
    "texting_phone",
    "turning"
];

/* Must match the ONNX model input dimensions */
const SIZE = 256;

/* AI inference remains unchanged */

const INFERENCE_INTERVAL = 250;

/* Camera transmission configuration */

const PREVIEW_FPS = 12;
const PREVIEW_INTERVAL = 1000 / PREVIEW_FPS;

const PREVIEW_CONTROL_INTERVAL = 1000;

const PREVIEW_WIDTH = 480;
const PREVIEW_QUALITY = 0.48;
const PREVIEW_MAX_BYTES = 200000;

/* Server clock */

const CLOCK_INTERVAL = 30000;

/* Model normalization */

const MEAN = [.485, .456, .406];
const STD = [.229, .224, .225];

/* DOM references */

const $ = id => document.getElementById(id);

const video = $("camera");
const token = location.hash.slice(1);

/* Application state */

let session = null;
let stream = null;

let running = false;
let starting = false;

let inferenceBusy = false;
let inferenceTimer = null;

let startAttempt = 0;

/* Sensor state */

let gpsPosition = null;
let gpsStatus = "estimating";
let gpsWatchId = null;

let acceleration = [0, 0, 0];
let gyroscope = [0, 0, 0];

/* Timing and trip state */

let clockOffset = 0;
let lastClockSync = 0;

let activeTripId = null;

/* Preview state */

let previewEnabled = false;
let previewTimer = null;
let previewBusy = false;

let lastPreviewControlCheck = 0;

let inputCanvas = null;
let previewCanvas = null;

let lastClientPrediction = null;

/* Speed simulator */

let manualSpeedEnabled = false;
let manualSpeedKmh = 60;
