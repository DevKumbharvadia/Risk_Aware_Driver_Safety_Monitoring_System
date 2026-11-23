
/* Camera preview encoding */

function makePreviewBlob() {

    return new Promise((resolve, reject) => {

        if (!video.videoWidth || !video.videoHeight) {
            resolve(null);
            return;
        }

        if (!previewCanvas) {
            previewCanvas = document.createElement("canvas");
        }

        const scale = Math.min(
            1,
            PREVIEW_WIDTH / video.videoWidth
        );

        previewCanvas.width = Math.round(
            video.videoWidth * scale
        );

        previewCanvas.height = Math.round(
            video.videoHeight * scale
        );

        const context = previewCanvas.getContext(
            "2d",
            { alpha: false }
        );

        if (!context) {
            reject(Error("Could not create preview context."));
            return;
        }

        context.drawImage(
            video,
            0,
            0,
            previewCanvas.width,
            previewCanvas.height
        );

        previewCanvas.toBlob(
            blob => {
                if (blob) {
                    resolve(blob);
                } else {
                    reject(Error("Could not encode preview."));
                }
            },
            "image/jpeg",
            PREVIEW_QUALITY
        );
    });
}


/* Check whether manager is viewing this phone */

async function checkPreviewSelection() {

    try {

        const response = await fetch(
            "/preview-control",
            {
                headers: authHeaders(false),
                cache: "no-store"
            }
        );

        if (!response.ok) {
            previewEnabled = false;
            return;
        }

        const result = await response.json();

        previewEnabled = result.enabled === true;

    } catch (error) {

        console.warn(
            "Preview control check failed:",
            error
        );

        previewEnabled = false;
    }

    $("cameraState").textContent =
        previewEnabled
            ? "Manager viewing"
            : "Private";
}


/* Upload one camera frame */

async function uploadPreview() {

    if (
        !previewEnabled ||
        !activeTripId ||
        previewBusy ||
        !running ||
        video.readyState < 2
    ) {
        return;
    }

    previewBusy = true;

    const tripId = activeTripId;

    try {

        const blob = await makePreviewBlob();

        if (
            !blob ||
            !running ||
            !previewEnabled ||
            activeTripId !== tripId
        ) {
            return;
        }

        if (blob.size > PREVIEW_MAX_BYTES) {
            console.warn(
                "Preview exceeds maximum upload size:",
                blob.size
            );

            return;
        }

        const response = await fetch(
            "/preview",
            {
                method: "POST",

                headers: {
                    ...authHeaders(false),

                    "X-Trip": String(tripId),

                    "Content-Type": "image/jpeg"
                },

                body: blob,

                cache: "no-store"
            }
        );

        if (!response.ok) {
            console.warn(
                "Preview rejected:",
                response.status,
                await response.text()
            );
        }

    } catch (error) {

        console.warn(
            "Preview upload failed:",
            error
        );

    } finally {

        previewBusy = false;
    }
}


/* 12 FPS preview scheduler */

async function previewLoop() {

    if (!running) {
        return;
    }

    const started = performance.now();

    // Check manager permission once per second.

    if (
        !lastPreviewControlCheck ||
        started - lastPreviewControlCheck >=
            PREVIEW_CONTROL_INTERVAL
    ) {

        lastPreviewControlCheck = started;

        await checkPreviewSelection();
    }

    if (!running) {
        return;
    }

    if (previewEnabled) {
        await uploadPreview();
    }

    if (running) {

        const elapsed =
            performance.now() - started;

        const remaining = Math.max(
            0,
            PREVIEW_INTERVAL - elapsed
        );

        previewTimer = setTimeout(
            previewLoop,
            remaining
        );
    }
}


/* Stop camera preview transmission */

function stopPreview() {

    clearTimeout(previewTimer);

    previewTimer = null;

    previewEnabled = false;

    lastPreviewControlCheck = 0;

    activeTripId = null;

    $("cameraState").textContent = "Off";
}
