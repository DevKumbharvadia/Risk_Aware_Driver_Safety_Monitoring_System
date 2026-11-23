
"use strict";

/* =========================================================
   AUTHENTICATION HEADERS
========================================================= */

function authHeaders(json = true) {

    const headers = {};

    if (json) {
        headers["Content-Type"] = "application/json";
    }

    if (token) {
        headers.Authorization = "Bearer " + token;
    }

    return headers;
}


/* =========================================================
   CHECK SERVER COMPATIBILITY
========================================================= */

async function checkServer() {

    status("Checking server connection...");

    const response = await fetch(
        "/version",
        {
            cache: "no-store"
        }
    );

    if (!response.ok) {
        throw Error("Server connection failed.");
    }

    const data = await response.json();

    if (data.mobile !== 7) {

        throw Error(
            "Mobile/server version mismatch. Refresh the vehicle link."
        );
    }
}


/* =========================================================
   SYNCHRONIZE CLOCKS
========================================================= */

async function syncClock() {

    const before = performance.now();

    const response = await fetch(
        "/clock",
        {
            cache: "no-store"
        }
    );

    if (!response.ok) {

        throw Error(
            "Could not synchronize server clock."
        );
    }

    const data = await response.json();

    const after = performance.now();

    if (!Number.isFinite(data.monotonic)) {

        throw Error(
            "Invalid server clock response."
        );
    }

    clockOffset =
        data.monotonic -
        (before + after) / 2000;

    lastClockSync = performance.now();
}


async function ensureClock() {

    if (
        !lastClockSync ||
        performance.now() - lastClockSync > CLOCK_INTERVAL
    ) {
        await syncClock();
    }
}


function captureTime() {

    return performance.now() / 1000 + clockOffset;
}


/* =========================================================
   UPDATE DROWSINESS INDICATOR
========================================================= */

function updateDrowsinessDisplay(data) {

    const element = $("drowsiness");

    if (!element) {
        return;
    }

    const level = String(
        data?.alert_level || "UNKNOWN"
    ).toUpperCase();

    const labels = {

        NORMAL: "Normal",

        WARNING: "Warning",

        CRITICAL: "Drowsy",

        UNKNOWN: "Unavailable"
    };

    element.dataset.level = level;

    element.textContent =
        labels[level] || "Unavailable";
}


/* =========================================================
   VALIDATE NEW DRIVER MODEL
========================================================= */

function validateDriverModel() {

    if (!session) {

        throw Error(
            "Driver behaviour ONNX model is not loaded."
        );
    }

    if (
        typeof CLASS_NAMES === "undefined" ||
        CLASS_NAMES.length !== 9
    ) {

        throw Error(
            "Driver model must have exactly nine configured classes."
        );
    }

    if (
        typeof SIZE === "undefined" ||
        SIZE !== 256
    ) {

        throw Error(
            "Driver model input size must be 256x256."
        );
    }

    const expectedClasses = [

        "safe_driving",

        "texting_right",

        "talking_phone_right",

        "texting_left",

        "talking_phone_left",

        "operating_radio",

        "drinking",

        "reaching_behind",

        "talking_to_passenger"
    ];

    for (
        let i = 0;
        i < expectedClasses.length;
        i++
    ) {

        if (CLASS_NAMES[i] !== expectedClasses[i]) {

            throw Error(
                `Driver model class mismatch at index ${i}. Expected ${expectedClasses[i]}, received ${CLASS_NAMES[i]}.`
            );
        }
    }

    console.info(
        "Driver behaviour model configuration verified.",
        {
            model: MODEL_URL,
            inputSize: SIZE,
            classes: CLASS_NAMES
        }
    );
}


/* =========================================================
   INITIALIZE DROWSINESS DETECTOR
========================================================= */

async function initializeDrowsinessDetector() {

    if (!window.drowsinessDetector) {

        throw Error(
            "Drowsiness detector script did not load. Check drowsiness.js."
        );
    }

    status(
        "Loading drowsiness detection model..."
    );

    const initialized =
        await window.drowsinessDetector.initialize();

    if (initialized !== true) {

        throw Error(
            "MediaPipe drowsiness detector could not initialize."
        );
    }

    window.drowsinessDetector.reset();

    console.info(
        "Drowsiness detector initialized successfully."
    );
}


/* =========================================================
   VERIFY DROWSINESS DETECTOR
========================================================= */

function verifyDrowsinessDetector() {

    if (!window.drowsinessDetector) {

        throw Error(
            "Drowsiness detector is unavailable."
        );
    }

    const result =
        window.drowsinessDetector.detect(video);

    if (
        !result ||
        result.available !== true
    ) {

        throw Error(
            "Drowsiness detector cannot process camera frames."
        );
    }

    console.info(
        "Drowsiness detector camera test:",
        {
            faceDetected: result.face_detected,
            eyeAspectRatio: result.ear,
            alertLevel: result.alert_level
        }
    );

    return result;
}


/* =========================================================
   START CAMERA MONITORING
========================================================= */

async function startMonitoring() {

    if (running || starting) {
        return;
    }

    if (!token) {

        connection("Error");

        status(
            "Missing vehicle token. Open the complete link from the manager."
        );

        return;
    }

    if (!navigator.mediaDevices?.getUserMedia) {

        connection("Error");

        status(
            "Camera access requires HTTPS and a supported browser."
        );

        return;
    }

    starting = true;

    const startButton = $("start");

    const stopButton = $("stop");

    if (startButton) {
        startButton.disabled = true;
    }

    const attempt = ++startAttempt;

    try {

        connection("Connecting");

        /* Check backend */

        await checkServer();

        if (attempt !== startAttempt) return;

        /* Synchronize clocks */

        await syncClock();

        if (attempt !== startAttempt) return;

        /* Load ONNX behaviour model */

        if (!session) {

            status(
                "Loading driver behaviour model..."
            );

            await loadModel();
        }

        if (attempt !== startAttempt) return;

        /* Verify the new nine-class model */

        validateDriverModel();

        /* Initialize MediaPipe */

        await initializeDrowsinessDetector();

        if (attempt !== startAttempt) return;

        /* Request motion permissions */

        await requestMotionPermission();

        if (attempt !== startAttempt) return;

        /* Request camera */

        status(
            "Requesting camera permission..."
        );

        stream =
            await navigator.mediaDevices.getUserMedia({

                audio: false,

                video: {

                    facingMode: "user",

                    width: {
                        ideal: 640
                    },

                    height: {
                        ideal: 480
                    }
                }
            });

        if (attempt !== startAttempt) {

            stream.getTracks().forEach(
                track => track.stop()
            );

            stream = null;

            return;
        }

        /* Start video */

        video.srcObject = stream;

        await video.play();

        if (attempt !== startAttempt) return;

        /* Wait for valid camera dimensions */

        if (
            !video.videoWidth ||
            !video.videoHeight
        ) {

            await new Promise((resolve, reject) => {

                const timeout = setTimeout(
                    () => {

                        reject(
                            Error(
                                "Camera did not produce video frames."
                            )
                        );

                    },
                    5000
                );

                video.addEventListener(
                    "loadeddata",
                    () => {

                        clearTimeout(timeout);

                        resolve();
                    },
                    {
                        once: true
                    }
                );
            });
        }

        if (attempt !== startAttempt) return;

        if (
            !video.videoWidth ||
            !video.videoHeight
        ) {

            throw Error(
                "Camera produced no usable video frames."
            );
        }

        /* Reset temporal drowsiness history */

        window.drowsinessDetector.reset();

        /* Verify MediaPipe against live camera */

        const drowsinessTest =
            verifyDrowsinessDetector();

        console.info(
            "Initial drowsiness result:",
            drowsinessTest
        );

        /* Start sensors */

        startSensors();

        running = true;

        starting = false;

        connection("Monitoring");

        status(
            "Driver monitoring started"
        );

        setRisk("UNKNOWN");

        updateDrowsinessDisplay({

            alert_level: "UNKNOWN"
        });

        const cameraState = $("cameraState");

        if (cameraState) {
            cameraState.textContent = "Private";
        }

        if (stopButton) {
            stopButton.disabled = false;
        }

        if (startButton) {
            startButton.disabled = true;
        }

        /* Start preview and inference */

        previewLoop();

        inferenceLoop();

    } catch (error) {

        console.error(
            "Start monitoring error:",
            error
        );

        cleanup();

        connection("Error");

        status(
            error.message ||
            "Unable to start monitoring."
        );
    }
}


/* =========================================================
   STOP AND RELEASE RESOURCES
========================================================= */

function cleanup() {

    running = false;

    starting = false;

    startAttempt++;

    /* Stop scheduled loops */

    clearTimeout(inferenceTimer);

    clearTimeout(previewTimer);

    inferenceTimer = null;

    previewTimer = null;

    /* Stop preview */

    stopPreview();

    /* Stop sensors */

    stopSensors();

    /* Reset drowsiness history */

    if (window.drowsinessDetector) {

        window.drowsinessDetector.reset();
    }

    /* Release camera */

    if (stream) {

        stream.getTracks().forEach(
            track => track.stop()
        );

        stream = null;
    }

    if (video) {
        video.srcObject = null;
    }

    /* Reset UI */

    const cameraState = $("cameraState");

    if (cameraState) {
        cameraState.textContent = "Off";
    }

    const stopButton = $("stop");

    const startButton = $("start");

    if (stopButton) {
        stopButton.disabled = true;
    }

    if (startButton) {
        startButton.disabled = false;
    }

    inferenceBusy = false;

    updateDrowsinessDisplay({

        alert_level: "UNKNOWN"
    });
}


/* =========================================================
   USER STOP ACTION
========================================================= */

function stopMonitoring() {

    cleanup();

    connection("Stopped");

    status(
        "Monitoring stopped"
    );
}


/* =========================================================
   EVENT LISTENERS
========================================================= */

const startButtonElement = $("start");

if (startButtonElement) {

    startButtonElement.addEventListener(
        "click",
        startMonitoring
    );
}


const stopButtonElement = $("stop");

if (stopButtonElement) {

    stopButtonElement.addEventListener(
        "click",
        stopMonitoring
    );
}


window.addEventListener(
    "beforeunload",
    cleanup
);


/* =========================================================
   INITIAL UI
========================================================= */

updateSensors();

updateDrowsinessDisplay({

    alert_level: "UNKNOWN"
});
