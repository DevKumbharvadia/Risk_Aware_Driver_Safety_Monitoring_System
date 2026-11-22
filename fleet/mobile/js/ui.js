
function status(message) {
    $("status").textContent = message;
}

function connection(message) {
    $("connection").textContent = message;
}

function setRisk(level) {
    const element = $("risk");
    const value = String(level || "UNKNOWN").toUpperCase();

    element.textContent = value;
    element.dataset.level = value;
}

function showClientPrediction(prediction) {
    lastClientPrediction = prediction;

    $("modelPrediction").hidden = false;

    $("modelPrediction").textContent =
        prediction.label + " · " +
        (prediction.confidence * 100).toFixed(1) + "%";
}

/* Sensor display */

function updateSensors() {
    const gps = manualSpeedEnabled
        ? `manual test speed ${manualSpeedKmh} km/h`
        : (gpsPosition ? "available" : gpsStatus);

    const a = acceleration
        .map(v => v.toFixed(2))
        .join(", ");

    const g = gyroscope
        .map(v => v.toFixed(2))
        .join(", ");

    $("sensorDetails").textContent =
        `GPS: ${gps} | Accelerometer: [${a}] | Gyroscope: [${g}]`;
}

/* Speed simulator */

function updateSpeedUI() {
    const panel = $("speedTest");
    const badge = $("speedModeBadge");
    const button = $("speedModeButton");

    panel.dataset.active = String(manualSpeedEnabled);

    badge.textContent = manualSpeedEnabled
        ? "TEST MODE"
        : "LIVE GPS";

    badge.dataset.mode = manualSpeedEnabled
        ? "manual"
        : "gps";

    button.textContent = manualSpeedEnabled
        ? "Disable Manual Speed"
        : "Enable Manual Speed";

    $("speedDisplay").textContent =
        `${manualSpeedKmh} km/h`;

    $("speedInput").value = manualSpeedKmh;
    $("speedSlider").value = manualSpeedKmh;

    $("speedTestNote").textContent = manualSpeedEnabled
        ? "TEST MODE active: this simulated value is uploaded as telemetry."
        : "Live GPS is used for telemetry. Manual speed is test-only.";

    updateSensors();
}

function applyManualSpeed() {
    const value = Number($("speedInput").value);

    if (
        !Number.isFinite(value) ||
        value < 0 ||
        value > 160
    ) {
        status("Enter a speed from 0 to 160 km/h.");
        return;
    }

    manualSpeedKmh = Math.round(value);

    updateSpeedUI();

    if (manualSpeedEnabled) {
        $("speed").textContent = manualSpeedKmh.toFixed(1);
    }

    status(
        manualSpeedEnabled
            ? `Testing at ${manualSpeedKmh} km/h`
            : `Speed set to ${manualSpeedKmh} km/h. Enable test mode to use it.`
    );
}

function toggleManualSpeed() {
    manualSpeedEnabled = !manualSpeedEnabled;

    updateSpeedUI();

    if (manualSpeedEnabled) {
        $("speed").textContent = manualSpeedKmh.toFixed(1);

        status(
            `Manual speed testing enabled: ${manualSpeedKmh} km/h`
        );

    } else {
        $("speed").textContent =
            gpsPosition &&
            Number.isFinite(gpsPosition.coords.speed)
                ? (gpsPosition.coords.speed * 3.6).toFixed(1)
                : "—";

        status("Live GPS speed restored.");
    }
}

/* Speed controls */

$("speedInput").addEventListener("input", () => {
    const value = Number($("speedInput").value);

    if (
        Number.isFinite(value) &&
        value >= 0 &&
        value <= 160
    ) {
        $("speedSlider").value = value;

        $("speedDisplay").textContent =
            `${value} km/h`;
    }
});

$("speedSlider").addEventListener("input", () => {
    $("speedInput").value = $("speedSlider").value;

    $("speedDisplay").textContent =
        `${$("speedSlider").value} km/h`;
});

$("applySpeed").addEventListener(
    "click",
    applyManualSpeed
);

$("speedModeButton").addEventListener(
    "click",
    toggleManualSpeed
);

/* Dashboard updates */

function updateDashboard(data) {
    setRisk(data.risk || "UNKNOWN");

    if (manualSpeedEnabled) {
        $("speed").textContent =
            manualSpeedKmh.toFixed(1);

    } else {
        $("speed").textContent =
            Number.isFinite(data.speed)
                ? data.speed.toFixed(1)
                : "—";
    }

    if (data.driver || data.route) {
        $("trip").textContent = [
            data.driver,
            data.route
        ].filter(Boolean).join(" · ");
    }

    const label =
        data.classifier_label ||
        data.behavior ||
        data.prediction ||
        data.label;

    if (label) {
        $("modelPrediction").hidden = false;
        $("modelPrediction").textContent = label;

    } else if (lastClientPrediction) {
        showClientPrediction(lastClientPrediction);
    }

    status(
        data.assessment_note ||
        data.reason ||
        "Monitoring active"
    );
}

updateSpeedUI();
