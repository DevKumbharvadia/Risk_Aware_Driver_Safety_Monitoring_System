
"use strict";

/*
 * Fleet Guardian
 * MobileNetV3-Small ONNX Driver Behaviour Inference
 *
 * Model:
 *   Architecture: MobileNetV3-Small
 *   Input: RGB, 256x256
 *   Tensor: [1, 3, 256, 256]
 *   Output: 9 logits
 *   ONNX opset: 17
 *
 * Preprocessing:
 *   ImageNet normalization
 *
 * Existing drowsiness, GPS, sensor,
 * authentication and API functionality preserved.
 */


/* =========================================================
   MODEL CONFIGURATION
========================================================= */

const DRIVER_CLASS_NAMES = [
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

const DRIVER_CLASS_COUNT = 9;

const DRIVER_INPUT_SIZE = 256;

const DRIVER_INPUT_CHANNELS = 3;

const DRIVER_MEAN = [
    0.485,
    0.456,
    0.406
];

const DRIVER_STD = [
    0.229,
    0.224,
    0.225
];


/* =========================================================
   LOAD ONNX MODEL
========================================================= */

async function loadModel() {

    if (!window.ort) {
        throw Error("ONNX Runtime could not load.");
    }

    status("Loading driver AI model...");

    ort.env.wasm.wasmPaths =
        "https://cdn.jsdelivr.net/npm/onnxruntime-web@1.20.1/dist/";

    ort.env.wasm.numThreads = 1;

    try {

        session = await ort.InferenceSession.create(
            MODEL_URL,
            {
                executionProviders: ["wasm"],
                graphOptimizationLevel: "all"
            }
        );

    } catch (error) {

        console.error(
            "ONNX model loading error:",
            error
        );

        throw Error(
            `Could not load ${MODEL_URL}: ${error.message || error}`
        );
    }

    if (
        !session.inputNames.length ||
        !session.outputNames.length
    ) {
        throw Error(
            "Model input/output metadata is missing."
        );
    }

    if (typeof SIZE !== "undefined" &&
        SIZE !== DRIVER_INPUT_SIZE) {

        throw Error(
            `Incorrect configured image size: ${SIZE}. Expected 256.`
        );
    }

    if (
        typeof CLASS_NAMES !== "undefined" &&
        (
            CLASS_NAMES.length !== DRIVER_CLASS_COUNT ||
            CLASS_NAMES.some(
                (name, index) =>
                    name !== DRIVER_CLASS_NAMES[index]
            )
        )
    ) {

        throw Error(
            "CLASS_NAMES does not match the new 9-class model mapping."
        );
    }

    if (
        typeof MEAN !== "undefined" &&
        MEAN.some(
            (value, index) =>
                Math.abs(value - DRIVER_MEAN[index]) > 0.000001
        )
    ) {
        throw Error(
            "Configured normalization MEAN does not match ImageNet."
        );
    }

    if (
        typeof STD !== "undefined" &&
        STD.some(
            (value, index) =>
                Math.abs(value - DRIVER_STD[index]) > 0.000001
        )
    ) {
        throw Error(
            "Configured normalization STD does not match ImageNet."
        );
    }

    console.info(
        "MobileNetV3-Small ONNX model loaded.",
        {
            inputs: session.inputNames,
            outputs: session.outputNames,
            inputMetadata: session.inputMetadata?.[0],
            outputMetadata: session.outputMetadata?.[0],
            imageSize: DRIVER_INPUT_SIZE,
            classes: DRIVER_CLASS_NAMES
        }
    );
}


/* =========================================================
   IMAGE PREPROCESSING
========================================================= */

function makeTensor() {

    if (!video.videoWidth || !video.videoHeight) {

        throw Error(
            "Camera frame is not ready."
        );
    }

    if (!inputCanvas) {

        inputCanvas = document.createElement("canvas");

        inputCanvas.width = DRIVER_INPUT_SIZE;
        inputCanvas.height = DRIVER_INPUT_SIZE;
    }

    if (
        inputCanvas.width !== DRIVER_INPUT_SIZE ||
        inputCanvas.height !== DRIVER_INPUT_SIZE
    ) {

        inputCanvas.width = DRIVER_INPUT_SIZE;
        inputCanvas.height = DRIVER_INPUT_SIZE;
    }

    const context = inputCanvas.getContext(
        "2d",
        {
            willReadFrequently: true
        }
    );

    if (!context) {

        throw Error(
            "Could not create image processing context."
        );
    }

    /*
     * Resize camera frame to 256x256.
     *
     * Keep RGB channel order.
     * Do not convert to BGR.
     */

    context.drawImage(
        video,
        0,
        0,
        DRIVER_INPUT_SIZE,
        DRIVER_INPUT_SIZE
    );

    const pixels = context.getImageData(
        0,
        0,
        DRIVER_INPUT_SIZE,
        DRIVER_INPUT_SIZE
    ).data;

    const plane =
        DRIVER_INPUT_SIZE * DRIVER_INPUT_SIZE;

    const values = new Float32Array(
        DRIVER_INPUT_CHANNELS * plane
    );

    /*
     * ONNX input format: NCHW
     *
     * [1, 3, 256, 256]
     *
     * RGB channel planes.
     *
     * Normalization:
     * (pixel / 255 - mean) / std
     */

    for (let i = 0; i < plane; i++) {

        const pixel = i * 4;

        const red = pixels[pixel] / 255;
        const green = pixels[pixel + 1] / 255;
        const blue = pixels[pixel + 2] / 255;

        values[i] =
            (red - DRIVER_MEAN[0]) / DRIVER_STD[0];

        values[plane + i] =
            (green - DRIVER_MEAN[1]) / DRIVER_STD[1];

        values[2 * plane + i] =
            (blue - DRIVER_MEAN[2]) / DRIVER_STD[2];
    }

    return new ort.Tensor(
        "float32",
        values,
        [
            1,
            DRIVER_INPUT_CHANNELS,
            DRIVER_INPUT_SIZE,
            DRIVER_INPUT_SIZE
        ]
    );
}


/* =========================================================
   SOFTMAX
========================================================= */

function softmax(values) {

    if (
        !Array.isArray(values) ||
        values.length !== DRIVER_CLASS_COUNT
    ) {

        throw Error(
            "Invalid classification values."
        );
    }

    const maximum = Math.max(...values);

    const exponentials = values.map(
        value => Math.exp(value - maximum)
    );

    const sum = exponentials.reduce(
        (a, b) => a + b,
        0
    );

    if (
        !Number.isFinite(sum) ||
        sum <= 0
    ) {

        throw Error(
            "Invalid model output: softmax failed."
        );
    }

    return exponentials.map(
        value => value / sum
    );
}


/* =========================================================
   PROBABILITY VALIDATION
========================================================= */

function probabilities(values) {

    if (
        !Array.isArray(values) ||
        values.length !== DRIVER_CLASS_COUNT
    ) {

        throw Error(
            "Model returned an incorrect number of classes."
        );
    }

    if (!values.every(Number.isFinite)) {

        throw Error(
            "Model output contains invalid numeric values."
        );
    }

    /*
     * The trained model outputs logits.
     *
     * Apply softmax to convert logits into
     * class probabilities.
     *
     * Also supports an already normalized
     * probability output if the ONNX graph
     * includes softmax.
     */

    const sum = values.reduce(
        (a, b) => a + b,
        0
    );

    const alreadyProbabilities =
        values.every(
            value =>
                value >= 0 &&
                value <= 1
        ) &&
        Math.abs(sum - 1) < 0.0001;

    return alreadyProbabilities
        ? values
        : softmax(values);
}


/* =========================================================
   DECODE MODEL OUTPUT
========================================================= */

function decode(output) {

    if (!output || !output.data) {

        throw Error(
            "ONNX output tensor is missing."
        );
    }

    const values = Array.from(
        output.data
    );

    const shape = output.dims || [];

    /*
     * Expected output:
     *
     * [1, 9]
     *
     * Some exported models may expose:
     *
     * [9]
     */

    const validShape =
        (
            shape.length === 2 &&
            shape[0] === 1 &&
            shape[1] === DRIVER_CLASS_COUNT
        ) ||
        (
            shape.length === 1 &&
            shape[0] === DRIVER_CLASS_COUNT
        );

    if (
        !validShape ||
        values.length !== DRIVER_CLASS_COUNT
    ) {

        console.error(
            "Unexpected ONNX output shape.",
            {
                shape,
                valueCount: values.length,
                expectedClasses: DRIVER_CLASS_COUNT
            }
        );

        throw Error(
            `Expected ONNX output [1, 9], received ${JSON.stringify(shape)}.`
        );
    }

    if (!values.every(Number.isFinite)) {

        throw Error(
            "ONNX output contains invalid numeric values."
        );
    }

    const probs = probabilities(values);

    let best = 0;

    for (
        let i = 1;
        i < probs.length;
        i++
    ) {

        if (probs[i] > probs[best]) {
            best = i;
        }
    }

    return {

        index: best,

        label: DRIVER_CLASS_NAMES[best],

        confidence: probs[best],

        scores: probs,

        raw: values,

        shape
    };
}


/* =========================================================
   BROWSER-SIDE DROWSINESS MEASUREMENT
========================================================= */

function getDrowsinessMeasurement() {

    const unavailable = {

        available: false,

        face_detected: false,

        eyes_closed: false,

        ear: null,

        left_ear: null,

        right_ear: null,

        perclos: null,

        alert_level: "UNKNOWN",

        closed_duration: 0
    };

    if (!window.drowsinessDetector) {

        console.error(
            "MediaPipe drowsiness detector is missing."
        );

        return unavailable;
    }

    try {

        const result =
            window.drowsinessDetector.detect(video);

        if (
            !result ||
            result.available !== true
        ) {

            console.warn(
                "MediaPipe returned unavailable measurements.",
                result
            );

            updateDrowsinessDisplay(unavailable);

            return unavailable;
        }

        const measurement = {

            available: true,

            face_detected:
                result.face_detected === true,

            eyes_closed:
                result.eyes_closed === true,

            ear:
                Number.isFinite(result.ear)
                    ? result.ear
                    : null,

            left_ear:
                Number.isFinite(result.left_ear)
                    ? result.left_ear
                    : null,

            right_ear:
                Number.isFinite(result.right_ear)
                    ? result.right_ear
                    : null,

            perclos:
                Number.isFinite(result.perclos)
                    ? result.perclos
                    : null,

            alert_level:
                typeof result.alert_level === "string"
                    ? result.alert_level
                    : "UNKNOWN",

            closed_duration:
                Number.isFinite(result.closed_duration)
                    ? result.closed_duration
                    : 0
        };

        updateDrowsinessDisplay({
            ...measurement
        });

        return measurement;

    } catch (error) {

        console.error(
            "MediaPipe detection error:",
            error
        );

        updateDrowsinessDisplay(unavailable);

        return unavailable;
    }
}


/* =========================================================
   UPLOAD PREDICTION TO SERVER
========================================================= */

async function sendPrediction(
    prediction,
    inferenceMs,
    capturedAt,
    drowsiness
) {

    const payload = {

        behavior: prediction.label,

        confidence: prediction.confidence,

        classifier_label: prediction.label,

        classifier_score: prediction.confidence,

        inference_ms: inferenceMs,

        server_capture: captureTime(),

        captured: capturedAt,

        gps: gpsPayload(),

        gps_status: manualSpeedEnabled
            ? "simulated"
            : gpsStatus,

        accelerometer: acceleration,

        gyroscope: gyroscope,

        speed_override: manualSpeedEnabled,

        test_speed_kmh: manualSpeedEnabled
            ? manualSpeedKmh
            : null,

        /* Drowsiness measurements */

        drowsiness_available:
            drowsiness.available,

        face_detected:
            drowsiness.face_detected,

        eyes_closed:
            drowsiness.eyes_closed,

        ear:
            drowsiness.ear,

        left_ear:
            drowsiness.left_ear,

        right_ear:
            drowsiness.right_ear,

        perclos:
            drowsiness.perclos,

        drowsiness_alert_level:
            drowsiness.alert_level,

        closed_duration:
            drowsiness.closed_duration
    };

    const response = await fetch(
        "/prediction",
        {
            method: "POST",

            headers: authHeaders(),

            body: JSON.stringify(payload),

            cache: "no-store"
        }
    );

    const responseText =
        await response.text();

    if (
        response.status === 401 ||
        response.status === 403
    ) {

        throw Error(
            "Vehicle authentication failed. Get a fresh vehicle link."
        );
    }

    if (!response.ok) {

        console.error(
            "Prediction upload rejected",
            {
                status: response.status,
                response: responseText
            }
        );

        const error = Error(
            `Prediction rejected (${response.status}): ${responseText.slice(0, 200)}`
        );

        error.status = response.status;

        error.responseText = responseText;

        throw error;
    }

    let result;

    try {

        result = JSON.parse(responseText);

    } catch {

        throw Error(
            "Server returned an invalid prediction response."
        );
    }

    if (!running) {
        return;
    }

    if (result.trip_id != null) {
        activeTripId = result.trip_id;
    }

    updateDashboard(result);

    /*
     * Preserve the latest local drowsiness reading.
     */

    updateDrowsinessDisplay({

        available: drowsiness.available,

        face_detected: drowsiness.face_detected,

        alert_level: drowsiness.alert_level,

        ear: drowsiness.ear,

        perclos: drowsiness.perclos
    });
}


/* =========================================================
   RUN ONE INFERENCE
========================================================= */

async function predict() {

    if (
        !session ||
        !running ||
        inferenceBusy ||
        video.readyState < 2
    ) {
        return;
    }

    inferenceBusy = true;

    try {

        await ensureClock();

        if (!running) {
            return;
        }

        const capturedAt =
            Date.now() / 1000;

        const started =
            performance.now();

        /*
         * Independent facial analysis.
         */

        const drowsiness =
            getDrowsinessMeasurement();

        /*
         * Driver behaviour classification.
         */

        const tensor = makeTensor();

        const input =
            session.inputNames[0];

        const outputName =
            session.outputNames[0];

        const results = await session.run({

            [input]: tensor

        });

        if (!running) {
            return;
        }

        const output =
            results[outputName];

        if (!output) {

            throw Error(
                "Expected ONNX output not found: " + outputName
            );
        }

        const prediction =
            decode(output);

        const duration =
            performance.now() - started;

        /*
         * Update local interface.
         */

        showClientPrediction(prediction);

        /*
         * Reject stale predictions.
         */

        const ageMs =
            Date.now() - capturedAt * 1000;

        if (ageMs > 2000) {

            console.warn(
                "Skipping stale local prediction:",
                ageMs
            );

            return;
        }

        /*
         * Upload to existing Fleet Guardian API.
         */

        await sendPrediction(
            prediction,
            duration,
            capturedAt,
            drowsiness
        );

    } finally {

        inferenceBusy = false;
    }
}


/* =========================================================
   INFERENCE SCHEDULER
========================================================= */

async function inferenceLoop() {

    if (!running) {
        return;
    }

    try {

        await predict();

    } catch (error) {

        console.error(
            "Inference or upload error:",
            error
        );

        if (
            error.status === 400 &&
            /delayed prediction/i.test(
                error.responseText || error.message
            )
        ) {

            status(
                "Skipping delayed prediction. Monitoring continues."
            );

            if (running) {

                inferenceTimer = setTimeout(
                    inferenceLoop,
                    INFERENCE_INTERVAL
                );
            }

            return;
        }

        cleanup();

        connection("Error");

        status(
            error.message || "Monitoring failed."
        );

        return;
    }

    if (running) {

        inferenceTimer = setTimeout(
            inferenceLoop,
            INFERENCE_INTERVAL
        );
    }
}
