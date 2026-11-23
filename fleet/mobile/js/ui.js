
"use strict";

/* =========================================================
   DRIVER BEHAVIOUR LABELS
========================================================= */

const BEHAVIOUR_DISPLAY_NAMES = {
    safe_driving: "Safe Driving",
    texting_right: "Texting Right",
    talking_phone_right: "Talking on Phone (Right)",
    texting_left: "Texting Left",
    talking_phone_left: "Talking on Phone (Left)",
    operating_radio: "Operating Radio",
    drinking: "Drinking",
    reaching_behind: "Reaching Behind",
    talking_to_passenger: "Talking to Passenger"
};


/* =========================================================
   STATUS AND CONNECTION
========================================================= */

function status(message) {

    const element = $("status");

    if (element) {
        element.textContent = message;
    }
}

function connection(message) {

    const element = $("connection");

    if (element) {
        element.textContent = message;
    }
}


/* =========================================================
   BEHAVIOUR LABEL FORMATTING
========================================================= */

function formatBehaviourLabel(label) {

    if (typeof label !== "string" || !label.trim()) {
        return "Unknown Behaviour";
    }

    const normalized = label
        .trim()
        .toLowerCase();

    if (BEHAVIOUR_DISPLAY_NAMES[normalized]) {
        return BEHAVIOUR_DISPLAY_NAMES[normalized];
    }

    return normalized
        .split("_")
        .map(
            word =>
                word.charAt(0).toUpperCase() +
                word.slice(1)
        )
        .join(" ");
}


/* =========================================================
   RISK INDICATOR
========================================================= */

function setRisk(level) {

    const element = $("risk");

    if (!element) {
        return;
    }

    const value = String(
        level || "UNKNOWN"
    ).toUpperCase();

    element.textContent = value;

    element.dataset.level = value;
}


/* =========================================================
   DROWSINESS INDICATOR
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

    /* Optional diagnostic details */

    const details = $("drowsinessDetails");

    if (details) {

        if (data?.available === false) {

            details.textContent =
                "Drowsiness detection unavailable";

        } else if (data?.face_detected === false) {

            details.textContent =
                "No face detected";

        } else if (
            Number.isFinite(data?.ear)
        ) {

            details.textContent =
                `EAR: ${data.ear.toFixed(3)}` +
                (
                    Number.isFinite(data?.perclos)
                        ? ` | PERCLOS: ${(data.perclos * 100).toFixed(1)}%`
                        : ""
                );

        } else {

            details.textContent =
                "Waiting for facial measurements";
        }
    }
}


/* =========================================================
   CLIENT-SIDE BEHAVIOUR PREDICTION
========================================================= */

function showClientPrediction(prediction) {

    if (
        !prediction ||
        typeof prediction.label !== "string"
    ) {
        return;
    }

    lastClientPrediction = prediction;

    const element = $("modelPrediction");

    if (!element) {
        return;
    }

    element.hidden = false;

    const label = formatBehaviourLabel(
        prediction.label
    );

    const confidence = Number(
        prediction.confidence
    );

    element.textContent =
        Number.isFinite(confidence) &&
        confidence >= 0 &&
        confidence <= 1
            ? `${label} · ${(confidence * 100).toFixed(1)}%`
            : label;

    element.dataset.behaviour =
        prediction.label;
}


/* =========================================================
   SENSOR DISPLAY
========================================================= */

function updateSensors() {

    const element = $("sensorDetails");

    if (!element) {
        return;
    }

    const gps = manualSpeedEnabled
        ? `manual test speed ${manualSpeedKmh} km/h`
        : (
            gpsPosition
                ? "available"
                : gpsStatus
        );

    const a = acceleration
        .map(v => v.toFixed(2))
        .join(", ");

    const g = gyroscope
        .map(v => v.toFixed(2))
        .join(", ");

    element.textContent =
        `GPS: ${gps} | Accelerometer: [${a}] | Gyroscope: [${g}]`;
}


/* =========================================================
   SPEED SIMULATOR
========================================================= */

function updateSpeedUI() {

    const panel = $("speedTest");
    const badge = $("speedModeBadge");
    const button = $("speedModeButton");

    if (
        !panel ||
        !badge ||
        !button
    ) {
        return;
    }

    panel.dataset.active =
        String(manualSpeedEnabled);

    badge.textContent = manualSpeedEnabled
        ? "TEST MODE"
        : "LIVE GPS";

    badge.dataset.mode = manualSpeedEnabled
        ? "manual"
        : "gps";

    button.textContent = manualSpeedEnabled
        ? "Disable Manual Speed"
        : "Enable Manual Speed";

    const display = $("speedDisplay");

    if (display) {
        display.textContent =
            `${manualSpeedKmh} km/h`;
    }

    const input = $("speedInput");
    const slider = $("speedSlider");

    if (input) {
        input.value = manualSpeedKmh;
    }

    if (slider) {
        slider.value = manualSpeedKmh;
    }

    const note = $("speedTestNote");

    if (note) {

        note.textContent =
            manualSpeedEnabled
                ? "TEST MODE active: this simulated value is uploaded as telemetry."
                : "Live GPS is used for telemetry. Manual speed is test-only.";
    }

    updateSensors();
}


/* =========================================================
   APPLY MANUAL SPEED
========================================================= */

function applyManualSpeed() {

    const input = $("speedInput");

    if (!input) {
        return;
    }

    const value = Number(input.value);

    if (
        !Number.isFinite(value) ||
        value < 0 ||
        value > 160
    ) {

        status(
            "Enter a speed from 0 to 160 km/h."
        );

        return;
    }

    manualSpeedKmh = Math.round(value);

    updateSpeedUI();

    if (manualSpeedEnabled) {

        const speed = $("speed");

        if (speed) {
            speed.textContent =
                manualSpeedKmh.toFixed(1);
        }
    }

    status(
        manualSpeedEnabled
            ? `Testing at ${manualSpeedKmh} km/h`
            : `Speed set to ${manualSpeedKmh} km/h. Enable test mode to use it.`
    );
}


/* =========================================================
   TOGGLE MANUAL SPEED
========================================================= */

function toggleManualSpeed() {

    manualSpeedEnabled = !manualSpeedEnabled;

    updateSpeedUI();

    const speed = $("speed");

    if (manualSpeedEnabled) {

        if (speed) {
            speed.textContent =
                manualSpeedKmh.toFixed(1);
        }

        status(
            `Manual speed testing enabled: ${manualSpeedKmh} km/h`
        );

    } else {

        if (speed) {

            speed.textContent =
                gpsPosition &&
                Number.isFinite(gpsPosition.coords.speed)
                    ? (
                        gpsPosition.coords.speed * 3.6
                    ).toFixed(1)
                    : "—";
        }

        status("Live GPS speed restored.");
    }
}


/* =========================================================
   SPEED CONTROLS
========================================================= */

const speedInputElement = $("speedInput");

if (speedInputElement) {

    speedInputElement.addEventListener(
        "input",
        () => {

            const value =
                Number(speedInputElement.value);

            if (
                Number.isFinite(value) &&
                value >= 0 &&
                value <= 160
            ) {

                const slider = $("speedSlider");
                const display = $("speedDisplay");

                if (slider) {
                    slider.value = value;
                }

                if (display) {
                    display.textContent =
                        `${value} km/h`;
                }
            }
        }
    );
}


const speedSliderElement = $("speedSlider");

if (speedSliderElement) {

    speedSliderElement.addEventListener(
        "input",
        () => {

            const input = $("speedInput");
            const display = $("speedDisplay");

            if (input) {
                input.value = speedSliderElement.value;
            }

            if (display) {
                display.textContent =
                    `${speedSliderElement.value} km/h`;
            }
        }
    );
}


const applySpeedButton = $("applySpeed");

if (applySpeedButton) {

    applySpeedButton.addEventListener(
        "click",
        applyManualSpeed
    );
}


const speedModeButton = $("speedModeButton");

if (speedModeButton) {

    speedModeButton.addEventListener(
        "click",
        toggleManualSpeed
    );
}


/* =========================================================
   DASHBOARD UPDATES
========================================================= */

function updateDashboard(data) {

    if (!data || typeof data !== "object") {
        return;
    }

    /* Risk indicator */

    setRisk(data.risk || "UNKNOWN");


    /* Speed */

    const speedElement = $("speed");

    if (speedElement) {

        if (manualSpeedEnabled) {

            speedElement.textContent =
                manualSpeedKmh.toFixed(1);

        } else {

            speedElement.textContent =
                Number.isFinite(data.speed)
                    ? data.speed.toFixed(1)
                    : "—";
        }
    }


    /* Trip information */

    if (data.driver || data.route) {

        const tripElement = $("trip");

        if (tripElement) {

            tripElement.textContent = [
                data.driver,
                data.route
            ].filter(Boolean).join(" · ");
        }
    }


    /* Behaviour prediction */

    const label =
        data.classifier_label ||
        data.behavior ||
        data.prediction ||
        data.label;

    const confidence =
        Number.isFinite(data.classifier_score)
            ? data.classifier_score
            : (
                Number.isFinite(data.confidence)
                    ? data.confidence
                    : null
            );

    if (label) {

        showClientPrediction({

            label,

            confidence
        });

    } else if (lastClientPrediction) {

        showClientPrediction(
            lastClientPrediction
        );
    }


    /* Drowsiness measurements from server */

    if (
        Object.prototype.hasOwnProperty.call(
            data,
            "drowsiness_alert_level"
        )
    ) {

        updateDrowsinessDisplay({

            available:
                data.drowsiness_available,

            face_detected:
                data.face_detected,

            alert_level:
                data.drowsiness_alert_level,

            ear:
                data.ear,

            perclos:
                data.perclos
        });
    }


    /* Status */

    status(
        data.assessment_note ||
        data.reason ||
        "Monitoring active"
    );
}


/* =========================================================
   INITIAL UI
========================================================= */

updateSpeedUI();

updateDrowsinessDisplay({

    available: false,

    alert_level: "UNKNOWN"
});
