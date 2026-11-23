
"use strict";

(function () {

    const VERSION = "0.10.14";

    const MODULE_URL =
        `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${VERSION}/+esm`;

    const WASM_URL =
        `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${VERSION}/wasm`;

    const MODEL_URL =
        "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task";

    /* Drowsiness thresholds */

    const EAR_THRESHOLD = 0.21;

    const WARNING_SECONDS = 1.5;
    const CRITICAL_SECONDS = 2.5;

    /* PERCLOS configuration */

    const PERCLOS_WINDOW_MS = 30000;
    const MIN_PERCLOS_OBSERVATION_MS = 5000;

    /* Ignore eye-closure continuity after tracking gaps */

    const MAX_CONTINUOUS_GAP_MS = 1000;

    /* MediaPipe eye landmark indices */

    const LEFT_EYE = [362, 385, 387, 263, 373, 380];
    const RIGHT_EYE = [33, 160, 158, 133, 153, 144];

    let landmarker = null;
    let initializationPromise = null;

    let closedSince = null;

    /*
     * Time-weighted observation segments.
     *
     * Each segment:
     * {
     *     start: timestamp,
     *     end: timestamp,
     *     observed: boolean,
     *     closed: boolean
     * }
     */

    let segments = [];

    let lastTimestamp = -1;
    let lastObservationTime = null;

    let previousState = null;

    let initializationGeneration = 0;

    /* Standard unavailable result */

    function unavailable(perclos = null) {

        return {
            available: false,
            face_detected: false,

            eyes_closed: false,

            ear: null,
            left_ear: null,
            right_ear: null,

            perclos,

            drowsy: false,
            alert_level: "UNKNOWN",

            closed_duration: 0
        };
    }

    /* Calculate Euclidean distance between landmarks */

    function distance(a, b) {

        if (
            !a ||
            !b ||
            !Number.isFinite(a.x) ||
            !Number.isFinite(a.y) ||
            !Number.isFinite(b.x) ||
            !Number.isFinite(b.y)
        ) {
            return null;
        }

        return Math.hypot(
            a.x - b.x,
            a.y - b.y
        );
    }

    /* Calculate Eye Aspect Ratio */

    function calculateEAR(landmarks, indices) {

        if (
            !Array.isArray(landmarks) ||
            landmarks.length <= Math.max(...indices)
        ) {
            return null;
        }

        const p = indices.map(
            index => landmarks[index]
        );

        const vertical1 = distance(p[1], p[5]);
        const vertical2 = distance(p[2], p[4]);

        const horizontal = distance(p[0], p[3]);

        if (
            vertical1 === null ||
            vertical2 === null ||
            horizontal === null ||
            horizontal < 0.000001
        ) {
            return null;
        }

        const ear =
            (vertical1 + vertical2) /
            (2 * horizontal);

        return Number.isFinite(ear)
            ? ear
            : null;
    }

    /* Keep only the relevant PERCLOS history */

    function trimSegments(now) {

        const cutoff = now - PERCLOS_WINDOW_MS;

        segments = segments.filter(
            segment => segment.end > cutoff
        );

        /*
         * Clip the oldest segment to the beginning
         * of the rolling observation window.
         */

        if (
            segments.length &&
            segments[0].start < cutoff
        ) {
            segments[0].start = cutoff;
        }
    }

    /* Add an observation interval */

    function addSegment(
        start,
        end,
        observed,
        closed
    ) {

        if (
            !Number.isFinite(start) ||
            !Number.isFinite(end) ||
            end <= start
        ) {
            return;
        }

        segments.push({
            start,
            end,
            observed,
            closed: observed && closed
        });
    }

    /*
     * Advance the observation timeline.
     *
     * The previous eye state is assigned to the elapsed
     * interval between consecutive detector observations.
     */

    function advanceTimeline(now) {

        if (lastObservationTime !== null) {

            const gap =
                now - lastObservationTime;

            if (
                gap > 0 &&
                gap <= MAX_CONTINUOUS_GAP_MS &&
                previousState
            ) {

                addSegment(
                    lastObservationTime,
                    now,
                    previousState.observed,
                    previousState.closed
                );

            } else if (
                gap > MAX_CONTINUOUS_GAP_MS
            ) {

                // A tracking interruption breaks continuous closure.

                closedSince = null;
            }
        }

        lastObservationTime = now;

        trimSegments(now);
    }

    /* Calculate time-weighted PERCLOS */

    function calculatePerclos(now) {

        trimSegments(now);

        const windowStart =
            now - PERCLOS_WINDOW_MS;

        let observedDuration = 0;
        let closedDuration = 0;

        for (const segment of segments) {

            const start = Math.max(
                segment.start,
                windowStart
            );

            const end = Math.min(
                segment.end,
                now
            );

            const duration = end - start;

            if (duration <= 0) {
                continue;
            }

            if (!segment.observed) {
                continue;
            }

            observedDuration += duration;

            if (segment.closed) {
                closedDuration += duration;
            }
        }

        if (
            observedDuration <
            MIN_PERCLOS_OBSERVATION_MS
        ) {
            return null;
        }

        return Math.min(
            1,
            Math.max(
                0,
                closedDuration / observedDuration
            )
        );
    }

    /* Initialize MediaPipe */

    async function initialize() {

        if (landmarker) {
            return true;
        }

        if (initializationPromise) {
            return initializationPromise;
        }

        const generation =
            initializationGeneration;

        const task = (async () => {

            const vision = await import(MODULE_URL);

            const fileset =
                await vision.FilesetResolver.forVisionTasks(
                    WASM_URL
                );

            const detector =
                await vision.FaceLandmarker.createFromOptions(
                    fileset,
                    {
                        baseOptions: {
                            modelAssetPath: MODEL_URL,
                            delegate: "CPU"
                        },

                        runningMode: "VIDEO",

                        numFaces: 1,

                        minFaceDetectionConfidence: 0.5,
                        minFacePresenceConfidence: 0.5,
                        minTrackingConfidence: 0.5,

                        outputFaceBlendshapes: false,

                        outputFacialTransformationMatrixes: false
                    }
                );

            /*
             * Prevent an initialization that completed after close()
             * from restoring an unwanted detector.
             */

            if (
                generation !== initializationGeneration
            ) {

                detector.close();

                return false;
            }

            landmarker = detector;

            reset();

            console.info(
                "Browser drowsiness detector initialized."
            );

            return true;

        })();

        initializationPromise = task;

        try {

            return await task;

        } catch (error) {

            if (
                generation === initializationGeneration
            ) {

                initializationPromise = null;
                landmarker = null;
            }

            console.error(
                "Drowsiness detector initialization failed:",
                error
            );

            throw error;
        }
    }

    /* Reset temporal detection state */

    function reset() {

        closedSince = null;

        segments = [];

        lastTimestamp = -1;

        lastObservationTime = null;

        previousState = null;
    }

    /* Detect drowsiness from a video frame */

    function detect(video) {

        if (!landmarker) {

            throw new Error(
                "Drowsiness detector is not initialized."
            );
        }

        if (
            !video ||
            video.readyState <
                HTMLMediaElement.HAVE_CURRENT_DATA ||
            !video.videoWidth ||
            !video.videoHeight
        ) {

            return unavailable(
                lastObservationTime === null
                    ? null
                    : calculatePerclos(performance.now())
            );
        }

        const now = performance.now();

        /*
         * Advance history before processing the current frame.
         */

        advanceTimeline(now);

        const timestamp = Math.max(
            now,
            lastTimestamp + 1
        );

        lastTimestamp = timestamp;

        let result;

        try {

            result = landmarker.detectForVideo(
                video,
                timestamp
            );

        } catch (error) {

            console.warn(
                "Face detection failed:",
                error
            );

            closedSince = null;

            previousState = {
                observed: false,
                closed: false
            };

            return unavailable(
                calculatePerclos(now)
            );
        }

        /*
         * No face detected.
         *
         * Preserve earlier valid PERCLOS observations,
         * but do not assume that the driver's eyes remain closed.
         */

        if (!result.faceLandmarks?.length) {

            closedSince = null;

            previousState = {
                observed: false,
                closed: false
            };

            return {
                ...unavailable(
                    calculatePerclos(now)
                ),

                available: true
            };
        }

        const landmarks =
            result.faceLandmarks[0];

        /* Calculate both eye aspect ratios */

        const leftEAR = calculateEAR(
            landmarks,
            LEFT_EYE
        );

        const rightEAR = calculateEAR(
            landmarks,
            RIGHT_EYE
        );

        if (
            leftEAR === null ||
            rightEAR === null
        ) {

            closedSince = null;

            previousState = {
                observed: false,
                closed: false
            };

            return unavailable(
                calculatePerclos(now)
            );
        }

        const ear =
            (leftEAR + rightEAR) / 2;

        /*
         * Require both eyes to be below the threshold.
         */

        const eyesClosed =
            leftEAR < EAR_THRESHOLD &&
            rightEAR < EAR_THRESHOLD;

        /*
         * Track continuous eye closure.
         *
         * Missing face observations and long frame gaps
         * reset this duration.
         */

        if (eyesClosed) {

            if (closedSince === null) {
                closedSince = now;
            }

        } else {

            closedSince = null;
        }

        const closedDuration =
            closedSince === null
                ? 0
                : (now - closedSince) / 1000;

        previousState = {
            observed: true,
            closed: eyesClosed
        };

        /* Calculate rolling PERCLOS */

        const perclosValue =
            calculatePerclos(now);

        const perclos =
            perclosValue === null
                ? null
                : Number(perclosValue.toFixed(4));

        /* Determine alert level */

        let alertLevel = "NORMAL";

        if (
            closedDuration >= CRITICAL_SECONDS
        ) {

            alertLevel = "CRITICAL";

        } else if (
            closedDuration >= WARNING_SECONDS
        ) {

            alertLevel = "WARNING";
        }

        return {

            available: true,

            face_detected: true,

            eyes_closed: eyesClosed,

            ear: Number(ear.toFixed(4)),

            left_ear: Number(leftEAR.toFixed(4)),

            right_ear: Number(rightEAR.toFixed(4)),

            perclos,

            drowsy: alertLevel !== "NORMAL",

            alert_level: alertLevel,

            closed_duration: Number(
                closedDuration.toFixed(2)
            )
        };
    }

    /* Release MediaPipe resources */

    function close() {

        initializationGeneration++;

        if (landmarker) {

            landmarker.close();

            landmarker = null;
        }

        initializationPromise = null;

        reset();
    }

    /* Public API */

    window.drowsinessDetector = {

        initialize,

        detect,

        reset,

        close
    };

})();
