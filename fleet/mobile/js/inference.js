
"use strict";

/* Load ONNX model */

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

        console.error("ONNX model loading error:", error);

        throw Error(
            `Could not load ${MODEL_URL}: ${error.message || error}`
        );
    }

    if (
        !session.inputNames.length ||
        !session.outputNames.length
    ) {
        throw Error("Model input/output metadata is missing.");
    }

    const inputMetadata = session.inputMetadata?.[0];

    console.info(
        "ONNX model loaded.",
        {
            inputs: session.inputNames,
            outputs: session.outputNames,
            inputMetadata,
            expectedSize: SIZE,
            classes: CLASS_NAMES
        }
    );
}

/* Convert camera image into model tensor */

function makeTensor() {

    if (!video.videoWidth || !video.videoHeight) {
        throw Error("Camera frame is not ready.");
    }

    if (!inputCanvas) {

        inputCanvas = document.createElement("canvas");

        inputCanvas.width = SIZE;
        inputCanvas.height = SIZE;
    }

    const context = inputCanvas.getContext(
        "2d",
        { willReadFrequently: true }
    );

    if (!context) {
        throw Error("Could not create image processing context.");
    }

    context.drawImage(
        video,
        0,
        0,
        SIZE,
        SIZE
    );

    const pixels = context.getImageData(
        0,
        0,
        SIZE,
        SIZE
    ).data;

    const plane = SIZE * SIZE;

    const values = new Float32Array(3 * plane);

    for (let i = 0; i < plane; i++) {

        const p = i * 4;

        values[i] =
            (pixels[p] / 255 - MEAN[0]) / STD[0];

        values[plane + i] =
            (pixels[p + 1] / 255 - MEAN[1]) / STD[1];

        values[2 * plane + i] =
            (pixels[p + 2] / 255 - MEAN[2]) / STD[2];
    }

    return new ort.Tensor(
        "float32",
        values,
        [1, 3, SIZE, SIZE]
    );
}

/* Probability calculation */

function softmax(values) {

    const maximum = Math.max(...values);

    const exponentials = values.map(
        value => Math.exp(value - maximum)
    );

    const sum = exponentials.reduce(
        (a, b) => a + b,
        0
    );

    if (!Number.isFinite(sum) || sum <= 0) {
        throw Error("Invalid model output: softmax failed.");
    }

    return exponentials.map(
        value => value / sum
    );
}

function probabilities(values) {

    const sum = values.reduce(
        (a, b) => a + b,
        0
    );

    const isProbability =
        values.every(
            value =>
                value >= 0 &&
                value <= 1 &&
                Number.isFinite(value)
        ) &&
        Math.abs(sum - 1) < 0.02;

    return isProbability
        ? values
        : softmax(values);
}

/* Decode ONNX result */

function decode(output) {

    if (!output || !output.data) {
        throw Error("ONNX output tensor is missing.");
    }

    const values = Array.from(output.data);

    const shape = output.dims || [];

    if (values.length !== CLASS_NAMES.length) {

        console.error(
            "Unexpected ONNX output shape",
            {
                shape,
                valueCount: values.length,
                expectedClasses: CLASS_NAMES.length,
                outputNames: session?.outputNames || []
            }
        );

        throw Error(
            `ONNX output has ${values.length} values, but ${CLASS_NAMES.length} classes are configured.`
        );
    }

    if (!values.every(Number.isFinite)) {
        throw Error("ONNX output contains invalid numeric values.");
    }

    const probs = probabilities(values);

    let best = 0;

    for (let i = 1; i < probs.length; i++) {

        if (probs[i] > probs[best]) {
            best = i;
        }
    }

    const prediction = {
        index: best,
        label: CLASS_NAMES[best],
        confidence: probs[best],
        scores: probs,
        raw: values,
        shape
    };

    return prediction;
}

/* Upload prediction to server */

async function sendPrediction(
    prediction,
    inferenceMs,
    capturedAt
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
            : null
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

    const responseText = await response.text();

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
                response: responseText,
                captured: capturedAt,
                payload
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

        console.error(
            "Invalid server JSON response:",
            responseText
        );

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
}

/* Run one inference */

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

        /*
         * Synchronize the clock before capturing the frame.
         * The capture timestamp must represent the actual
         * observation time, not the upload completion time.
         */

        await ensureClock();

        if (!running) {
            return;
        }

        const capturedAt = Date.now() / 1000;

        const started = performance.now();

        const tensor = makeTensor();

        const input = session.inputNames[0];

        const outputName = session.outputNames[0];

        const results = await session.run({
            [input]: tensor
        });

        if (!running) {
            return;
        }

        const output = results[outputName];

        if (!output) {
            throw Error(
                "Expected ONNX output not found: " + outputName
            );
        }

        const prediction = decode(output);

        const duration =
            performance.now() - started;

        showClientPrediction(prediction);

        /*
         * Discard observations that have already become
         * too old locally instead of uploading stale data.
         */

        const ageMs =
            Date.now() - capturedAt * 1000;

        if (ageMs > 2000) {

            console.warn(
                "Skipping stale local prediction:",
                ageMs,
                "ms"
            );

            return;
        }

        await sendPrediction(
            prediction,
            duration,
            capturedAt
        );

    } finally {

        inferenceBusy = false;
    }
}

/* Inference scheduler */

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

        /*
         * A delayed prediction is not automatically
         * an authentication or connection failure.
         */

        if (
            error.status === 400 &&
            /delayed prediction/i.test(
                error.responseText || error.message
            )
        ) {

            console.warn(
                "Manager rejected an outdated observation. Monitoring will continue."
            );

            status("Skipping delayed prediction. Monitoring continues.");

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
