
/* Authentication headers */

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

/* Check server compatibility */

async function checkServer() {

    status("Checking server connection...");

    const response = await fetch(
        "/version",
        { cache: "no-store" }
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

/* Synchronize clocks */

async function syncClock() {

    const before = performance.now();

    const response = await fetch(
        "/clock",
        { cache: "no-store" }
    );

    if (!response.ok) {
        throw Error("Could not synchronize server clock.");
    }

    const data = await response.json();

    const after = performance.now();

    if (!Number.isFinite(data.monotonic)) {
        throw Error("Invalid server clock response.");
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

/* Start camera monitoring */

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

    $("start").disabled = true;

    const attempt = ++startAttempt;

    try {

        connection("Connecting");

        await checkServer();

        if (attempt !== startAttempt) return;

        await syncClock();

        if (attempt !== startAttempt) return;

        if (!session) {
            await loadModel();
        }

        if (attempt !== startAttempt) return;

        await requestMotionPermission();

        if (attempt !== startAttempt) return;

        status("Requesting camera permission...");

        stream = await navigator.mediaDevices.getUserMedia({

            audio: false,

            video: {
                facingMode: "user",
                width: { ideal: 640 },
                height: { ideal: 480 }
            }
        });

        if (attempt !== startAttempt) {

            stream.getTracks().forEach(
                track => track.stop()
            );

            stream = null;

            return;
        }

        video.srcObject = stream;

        await video.play();

        if (attempt !== startAttempt) return;

        if (!video.videoWidth || !video.videoHeight) {
            throw Error("Camera produced no video frames.");
        }

        startSensors();

        running = true;
        starting = false;

        connection("Monitoring");

        status("Driver monitoring started");

        setRisk("UNKNOWN");

        $("cameraState").textContent = "Private";

        $("stop").disabled = false;

        $("start").disabled = true;

        // Start independent preview and AI loops.
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
            error.message || "Unable to start monitoring."
        );
    }
}

/* Stop and release resources */

function cleanup() {

    running = false;
    starting = false;

    startAttempt++;

    clearTimeout(inferenceTimer);
    clearTimeout(previewTimer);

    inferenceTimer = null;
    previewTimer = null;

    stopPreview();

    stopSensors();

    if (stream) {

        stream.getTracks().forEach(
            track => track.stop()
        );

        stream = null;
    }

    video.srcObject = null;

    $("cameraState").textContent = "Off";

    $("stop").disabled = true;

    $("start").disabled = false;

    inferenceBusy = false;
}

/* User stop action */

function stopMonitoring() {

    cleanup();

    connection("Stopped");

    status("Monitoring stopped");
}

/* Event listeners */

$("start").addEventListener(
    "click",
    startMonitoring
);

$("stop").addEventListener(
    "click",
    stopMonitoring
);

window.addEventListener(
    "beforeunload",
    cleanup
);

/* Initial UI */

updateSensors();
