
"use strict";

/* Sensor state */

let sensorsStarted = false;

/* Safe numeric conversion */

function numberOrZero(value) {
    return (
        typeof value === "number" &&
        Number.isFinite(value)
    ) ? value : 0;
}

/* Start GPS and motion sensors */

function startSensors() {

    if (sensorsStarted) {
        return;
    }

    sensorsStarted = true;

    /* GPS */

    if (navigator.geolocation) {

        gpsWatchId = navigator.geolocation.watchPosition(

            position => {

                if (!position || !position.coords) {
                    return;
                }

                gpsPosition = position;
                gpsStatus = "available";

                updateSensors();
            },

            error => {

                gpsStatus =
                    error.code === 1
                        ? "denied"
                        : error.code === 3
                            ? "timeout"
                            : "unavailable";

                updateSensors();
            },

            {
                enableHighAccuracy: true,
                maximumAge: 1000,
                timeout: 10000
            }
        );

    } else {

        gpsStatus = "unavailable";
    }

    /* Motion */

    window.addEventListener(
        "devicemotion",
        onMotion,
        { passive: true }
    );

    updateSensors();
}

/* Stop GPS and motion sensors */

function stopSensors() {

    sensorsStarted = false;

    if (
        gpsWatchId !== null &&
        navigator.geolocation
    ) {
        navigator.geolocation.clearWatch(
            gpsWatchId
        );
    }

    gpsWatchId = null;

    gpsPosition = null;
    gpsStatus = "estimating";

    acceleration = [0, 0, 0];
    gyroscope = [0, 0, 0];

    window.removeEventListener(
        "devicemotion",
        onMotion
    );

    updateSensors();
}

/* Read motion sensor */

function onMotion(event) {

    if (!sensorsStarted) {
        return;
    }

    const a =
        event.accelerationIncludingGravity ||
        event.acceleration;

    const r = event.rotationRate;

    if (a) {

        acceleration = [
            numberOrZero(a.x),
            numberOrZero(a.y),
            numberOrZero(a.z)
        ];
    }

    if (r) {

        gyroscope = [
            numberOrZero(r.alpha),
            numberOrZero(r.beta),
            numberOrZero(r.gamma)
        ];
    }

    updateSensors();
}

/* Request motion permission */

async function requestMotionPermission() {

    if (
        typeof DeviceMotionEvent !== "undefined" &&
        typeof DeviceMotionEvent.requestPermission === "function"
    ) {

        try {

            const result =
                await DeviceMotionEvent.requestPermission();

            if (result !== "granted") {
                console.warn(
                    "Motion permission denied."
                );
            }

            return result === "granted";

        } catch (error) {

            console.warn(
                "Motion permission request failed:",
                error
            );

            return false;
        }
    }

    return true;
}

/* GPS telemetry */

function gpsPayload() {

    /* Manual speed */

    if (manualSpeedEnabled) {

        return {
            timestamp: Date.now() / 1000,

            speed_mps:
                manualSpeedKmh / 3.6,

            speed_kmh:
                manualSpeedKmh,

            accuracy_m: 0,

            simulated: true
        };
    }

    if (!gpsPosition) {
        return null;
    }

    const coords = gpsPosition.coords;

    const age =
        Date.now() - gpsPosition.timestamp;

    /* Reject stale GPS readings */

    if (
        !Number.isFinite(age) ||
        age < -2000 ||
        age > 10000
    ) {
        return null;
    }

    const speed =
        Number.isFinite(coords.speed) &&
        coords.speed >= 0
            ? coords.speed
            : null;

    const accuracy =
        Number.isFinite(coords.accuracy) &&
        coords.accuracy >= 0
            ? coords.accuracy
            : null;

    return {

        timestamp:
            gpsPosition.timestamp / 1000,

        speed_mps: speed,

        speed_kmh:
            speed === null
                ? null
                : speed * 3.6,

        accuracy_m: accuracy,

        simulated: false
    };
}
