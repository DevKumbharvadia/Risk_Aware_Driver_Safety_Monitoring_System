
function startSensors() {

    if (navigator.geolocation) {

        gpsWatchId = navigator.geolocation.watchPosition(
            position => {
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

    window.addEventListener(
        "devicemotion",
        onMotion
    );

    updateSensors();
}

function stopSensors() {

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

    window.removeEventListener(
        "devicemotion",
        onMotion
    );

    updateSensors();
}

function onMotion(event) {

    const a =
        event.accelerationIncludingGravity ||
        event.acceleration;

    const r = event.rotationRate;

    const numberOrZero = value =>
        Number.isFinite(value) ? value : 0;

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

async function requestMotionPermission() {

    if (
        typeof DeviceMotionEvent !== "undefined" &&
        typeof DeviceMotionEvent.requestPermission === "function"
    ) {
        const result =
            await DeviceMotionEvent.requestPermission();

        if (result !== "granted") {
            console.warn("Motion permission denied.");
        }
    }
}

/* GPS telemetry */

function gpsPayload() {

    if (manualSpeedEnabled) {
        return {
            timestamp: Date.now() / 1000,
            speed_mps: manualSpeedKmh / 3.6,
            speed_kmh: manualSpeedKmh,
            accuracy_m: 0,
            simulated: true
        };
    }

    if (!gpsPosition) {
        return null;
    }

    const coords = gpsPosition.coords;

    return {
        timestamp: gpsPosition.timestamp / 1000,

        speed_mps:
            Number.isFinite(coords.speed)
                ? coords.speed
                : null,

        speed_kmh:
            Number.isFinite(coords.speed)
                ? coords.speed * 3.6
                : null,

        accuracy_m:
            Number.isFinite(coords.accuracy)
                ? coords.accuracy
                : null,

        simulated: false
    };
}
