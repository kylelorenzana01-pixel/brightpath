// --- BRIGHTPATH FACE REGISTRATION SYSTEM WITH CSRF SUPPORT ---

let captureCount = 0;
const totalShots = 20;
let captureInterval;

// Helper to get CSRF token
function getCsrfToken() {
    return document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
}

function initFaceLogin() {
    console.log("BrightPath Registration: Ready.");
}

/**
 * 1. Open Camera
 */
function startCamera() {
    console.log("Attempting to open camera...");
    const feed = document.getElementById('video-feed');
    const placeholder = document.getElementById('placeholder');
    const captureBtn = document.getElementById('btn-capture');

    if (feed) {
        // I-set ang source sa Flask route
        feed.src = "/video_feed"; 
        feed.style.display = "block";
        if (placeholder) placeholder.style.display = "none";
        
        // I-enable ang Start Capture button
        if (captureBtn) {
            captureBtn.disabled = false;
            captureBtn.style.opacity = "1";
        }
        console.log("Camera source set to /video_feed");
    } else {
        console.error("Element 'video-feed' not found!");
    }
}

/**
 * 2. Auto-Capture Logic
 */
async function runAutoCapture() {
    const status = document.getElementById('status');
    const progressContainer = document.getElementById('progress-container');
    const progressFill = document.getElementById('progress-fill');
    const captureBtn = document.getElementById('btn-capture');
    const openBtn = document.getElementById('btn-open');

    // UI Updates
    captureBtn.disabled = true;
    captureBtn.style.opacity = "0.5";
    if (openBtn) openBtn.style.display = "none";
    progressContainer.style.display = "block";
    status.innerHTML = "Capturing face data... Please move your head slightly.";
    status.style.color = "#3b82f6";

    // Siniguradong walang lumang interval na tumatakbo
    if (captureInterval) clearInterval(captureInterval);

    captureInterval = setInterval(async () => {
        try {
            // increment count bago ang fetch
            captureCount++;

            const response = await fetch('/capture_frame', {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrfToken()
                },
                body: JSON.stringify({ 
                    name: typeof employeeName !== 'undefined' ? employeeName : "Unknown", 
                    count: captureCount 
                })
            });
            
            if (!response.ok) throw new Error('Network response was not ok');
            
            const result = await response.json();

            if (result.status === "success") {
                // Update Progress Bar
                let percentage = (captureCount / totalShots) * 100;
                progressFill.style.width = percentage + "%";
                status.innerHTML = `Processing: ${captureCount} / ${totalShots} shots`;
                status.style.color = "#3b82f6";

                if (captureCount >= totalShots) {
                    clearInterval(captureInterval);
                    finishRegistration();
                }
            } else {
                // Bawasan ang count dahil hindi valid ang shot
                captureCount--; 
                status.innerHTML = "⚠️ Face not detected! Please face the camera.";
                status.style.color = "#ef4444";
            }
        } catch (err) {
            console.error("Capture Error:", err);
            status.innerHTML = "❌ Server Error. Please restart the app.";
            clearInterval(captureInterval);
        }
    }, 700);
}

/**
 * 3. Finalize Registration
 */
function finishRegistration() {
    const status = document.getElementById('status');
    const finishBtn = document.getElementById('btn-finish');
    const captureBtn = document.getElementById('btn-capture');
    
    status.innerHTML = "✅ Face Data Saved & Trained Successfully!";
    status.style.color = "#22c55e";
    
    if (captureBtn) captureBtn.style.display = "none";
    if (finishBtn) finishBtn.style.display = "inline-block";
    
    console.log("Registration complete.");
}

/**
 * Hardware Release
 */
async function stopCameraForce() {
    const feed = document.getElementById('video-feed');
    if (feed) feed.src = ""; 
    try {
        await fetch('/stop_camera'); 
    } catch (e) {
        console.log("Camera already stopped.");
    }
}

window.addEventListener('beforeunload', stopCameraForce);
document.addEventListener('DOMContentLoaded', initFaceLogin);