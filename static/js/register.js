/**
 * Bubuksan ang camera feed mula sa Flask server.
 */
function startCam() {
    const video = document.getElementById('video-feed');
    const placeholder = document.getElementById('placeholder');
    const btnCapture = document.getElementById('btn-capture');
    const status = document.getElementById('status');

    // I-set ang source para magpakita ang live stream mula sa Flask route
    video.src = "/video_feed";
    video.style.display = "block";
    placeholder.style.display = "none";
    
    // I-enable ang capture button pagka-open ng camera
    btnCapture.disabled = false;
    btnCapture.style.opacity = "1";
    status.innerText = "Camera is LIVE. Look directly at the camera.";
    status.style.color = "#3b82f6"; // Default blue color
}

/**
 * Awtomatikong mag-ca-capture ng 20 frames para sa face registration.
 */
async function runAutoCapture() {
    const nameInput = document.getElementById('emp-name');
    const name = nameInput ? nameInput.value : "";
    const statusText = document.getElementById('status');
    const progressFill = document.getElementById('progress-fill');
    const progressContainer = document.getElementById('progress-container');
    const startBtn = document.getElementById('btn-capture');

    // Validation para sa pangalan
    if (!name || name.trim() === "" || name === "New_User") {
        alert("Pakilagay ang iyong pangalan o siguraduhing kusa itong lumabas.");
        return;
    }

    // I-setup ang UI para sa simula ng capture
    startBtn.disabled = true; 
    startBtn.style.opacity = "0.5";
    if (progressContainer) progressContainer.style.display = "block";
    
    let successCount = 0;

    // Loop para sa 20 successful captures
    for (let i = 1; i <= 20; i++) {
        statusText.innerText = `Capturing face data: ${i} / 20...`;
        statusText.style.color = "#3b82f6";
        
        try {
            const response = await fetch('/capture_frame', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: name, count: i })
            });

            const data = await response.json();

            if (data.status === 'success') {
                successCount++;
                // I-update ang progress bar width
                if (progressFill) {
                    let percent = (successCount / 20) * 100;
                    progressFill.style.width = percent + "%";
                }
            } else {
                // Pag walang mukha, bawasan ang counter para ulitin ang bilang na iyon
                i--; 
                statusText.innerText = "No face detected! Please adjust your position.";
                statusText.style.color = "#ef4444"; // Red for warning
            }
        } catch (err) {
            console.error("Capture Error:", err);
            statusText.innerText = "Connection error. Retrying...";
            i--; // Ulitin ang loop sa part na nag-error
        }

        // Delay na 500ms bawat shot para hindi mag-overload ang hardware
        await new Promise(resolve => setTimeout(resolve, 500));
    }

    // Final check kung nakumpleto ang 20 shots
    if (successCount >= 20) {
        statusText.innerText = "Face Registered Successfully! Redirecting...";
        statusText.style.color = "#10b981"; // Green for success
        
        // Baguhin ang itsura ng button para alam ng user na tapos na
        startBtn.innerText = "Registration Finished";
        startBtn.style.background = "#10b981";

        // Mag-wait ng 2 seconds bago lumipat sa dashboard para mabasa ang success message
        setTimeout(() => {
            window.location.href = "/employee/dashboard?name=" + encodeURIComponent(name);
        }, 2000);
    }
}