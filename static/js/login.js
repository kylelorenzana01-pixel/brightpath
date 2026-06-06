// ===================================================
// FACE LOGIN SCRIPT - Clean version with CSRF support
// ===================================================
let facePollingInterval = null;
let isFaceLoggingIn = false;

// Helper to get CSRF token
function getCsrfToken() {
    return document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
}

function closeScanner() {
    if (facePollingInterval) {
        clearInterval(facePollingInterval);
        facePollingInterval = null;
    }
    isFaceLoggingIn = false;
    
    const modal = document.getElementById('cameraModal');
    const feed = document.getElementById('faceFeed');
    if (modal) modal.style.display = 'none';
    if (feed) feed.src = "";
    
    fetch('/stop_camera').catch(err => console.log("Camera stop error:", err));
}

async function startFaceLogin(videoFeedUrl) {
    const modal = document.getElementById('cameraModal');
    const feed = document.getElementById('faceFeed');
    const status = document.getElementById('scanStatus');

    if (!modal || !feed || !status) {
        console.error("Modal elements not found!");
        return;
    }

    if (facePollingInterval) clearInterval(facePollingInterval);
    isFaceLoggingIn = true;

    modal.style.display = 'flex';
    feed.src = videoFeedUrl + "?t=" + new Date().getTime();
    status.style.color = "#2c3e50";
    status.innerHTML = "Starting camera...";

    await new Promise(resolve => setTimeout(resolve, 1500));
    
    let attempts = 0;
    const maxAttempts = 15;
    
    facePollingInterval = setInterval(async () => {
        if (!isFaceLoggingIn) return;
        
        attempts++;
        status.innerHTML = `Authenticating identity (${attempts}/${maxAttempts})...`;
        
        try {
            const response = await fetch('/login_with_face', { 
                method: 'POST',
                headers: {
                    'X-CSRFToken': getCsrfToken()
                }
            });
            const data = await response.json();
            console.log("Face login response:", data);
            
            if (data.success === true) {
                clearInterval(facePollingInterval);
                facePollingInterval = null;
                isFaceLoggingIn = false;
                status.style.color = "#27ae60";
                status.innerText = "Welcome back! Redirecting...";
                setTimeout(() => { window.location.href = data.redirect; }, 1000);
            } else if (attempts >= maxAttempts) {
                clearInterval(facePollingInterval);
                facePollingInterval = null;
                isFaceLoggingIn = false;
                status.style.color = "#e74c3c";
                status.innerText = data.message || "Face not recognized. Try manual login.";
                setTimeout(() => closeScanner(), 2500);
            }
        } catch (err) {
            console.error("Face login error:", err);
            if (attempts >= maxAttempts) {
                clearInterval(facePollingInterval);
                facePollingInterval = null;
                isFaceLoggingIn = false;
                status.style.color = "#e74c3c";
                status.innerText = "Connection error. Please try again.";
                setTimeout(() => closeScanner(), 2500);
            }
        }
    }, 3000);
}

document.addEventListener('DOMContentLoaded', function() {
    const faceBtn = document.querySelector('.btn-face');
    if (faceBtn) {
        const videoUrl = faceBtn.getAttribute('data-video-url');
        faceBtn.addEventListener('click', function(e) {
            e.preventDefault();
            startFaceLogin(videoUrl);
        });
    }
});