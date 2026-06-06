/**
 * BrightPath 2.0 - Signup Logic
 * Features: Flash Effect, Dynamic Border, and Progress Tracking
 * Updated: April 2026 - FULLY FIXED VERSION + CSRF support
 */

// Helper to get CSRF token
function getCsrfToken() {
    return document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
}

// Store registration data
let regData = {
    name: '',
    email: '',
    password: ''
};

// Function para lumipat sa Face Scan step
function showFaceScan() {
    const name = document.getElementById('full_name').value;
    const email = document.getElementById('email').value;
    const password = document.getElementById('password').value;

    // Validation
    if (!name || !email || !password) {
        alert("Please fill up all fields first!");
        return;
    }

    // Store data
    regData.name = name;
    regData.email = email;
    regData.password = password;

    // UI Transitions: Lipat sa Step 2
    document.getElementById('step-1').classList.add('hidden');
    document.getElementById('step-2').classList.remove('hidden');

    const videoFeed = document.getElementById('video-feed');
    const loader = document.getElementById('loading-video');
    
    // Ipakita ang loader habang nag-a-init ang camera
    loader.style.display = 'block';
    loader.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i> Initializing Camera...';
    
    // I-set ang source ng video feed na may timestamp para iwas cache
    videoFeed.src = "/video_feed?t=" + new Date().getTime(); 
    
    videoFeed.onload = () => {
        loader.style.display = 'none';
        console.log("✅ Camera stream started successfully.");
    };

    videoFeed.onerror = () => {
        loader.innerHTML = '<i class="fas fa-exclamation-triangle"></i> Failed to load camera stream. Please check your camera.';
        loader.style.color = "red";
    };
}

// Function para bumalik sa Form at Patayin ang Camera
async function showForm() {
    document.getElementById('step-1').classList.remove('hidden');
    document.getElementById('step-2').classList.add('hidden');
    
    const videoFeed = document.getElementById('video-feed');
    videoFeed.src = ""; // Putulin ang visual feed sa UI
    
    const progCont = document.getElementById('prog-cont');
    if (progCont) progCont.style.display = 'none';

    // Reset progress bar
    const progBar = document.getElementById('prog-bar');
    if (progBar) progBar.style.width = "0%";

    // Reset status
    const status = document.getElementById('scan-status');
    if (status) {
        status.innerText = "Look directly at the camera";
        status.style.color = "#2c3e50";
    }

    // Reset register button
    const btn = document.getElementById('register-btn');
    if (btn) {
        btn.disabled = false;
        btn.style.opacity = "1";
    }

    // Sabihan ang Python na i-release na ang camera access
    try {
        await fetch('/stop_camera');
        console.log("Camera stopped.");
    } catch (err) {
        console.log("Camera already closed.");
    }
}

// Main Function para sa Registration (Face Capture + DB Save)
async function startCombinedRegistration() {
    const btn = document.getElementById('register-btn');
    const status = document.getElementById('scan-status');
    const progCont = document.getElementById('prog-cont');
    const progBar = document.getElementById('prog-bar');
    const videoDisplay = document.querySelector('.video-display');
    const videoCont = document.getElementById('video-container');

    // Check if we have registration data
    if (!regData.name || !regData.email || !regData.password) {
        status.innerText = "❌ Missing registration data. Please go back and re-enter your details.";
        status.style.color = "#e74c3c";
        return;
    }

    // UI Update: Simula ng Scan
    btn.disabled = true;
    btn.style.opacity = "0.5";
    progCont.style.display = 'block';
    status.innerText = "🔄 Starting camera and face detection...";
    status.style.color = "#3498db";
    
    // Wait a bit para mag-stabilize ang camera
    await new Promise(resolve => setTimeout(resolve, 1000));

    let successCount = 0;
    const TOTAL_FRAMES = 20;
    let failedFrames = 0;

    // 1. Face capture loop (20 frames)
    for (let i = 1; i <= TOTAL_FRAMES; i++) {
        try {
            // --- FLASH EFFECT: Mag-uultra bright ang preview bago ang bawat capture ---
            if (videoCont) {
                videoCont.style.transition = "filter 0.1s";
                videoCont.style.filter = "brightness(1.8)";
                setTimeout(() => { 
                    if (videoCont) videoCont.style.filter = "brightness(1)"; 
                }, 150);
            }

            // ✅ IMPORTANT: 'count' LANG ang ipinapasa (hindi 'name'), plus CSRF token
            const response = await fetch('/capture_frame', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrfToken()
                },
                body: JSON.stringify({ count: i })
            });
            
            const data = await response.json();
            
            if (data.status === 'success') {
                successCount++;
                // SUCCESS: Gawing Green ang border at update progress
                if (videoDisplay) {
                    videoDisplay.style.borderColor = "#2ecc71";
                    videoDisplay.style.boxShadow = "0 0 15px rgba(46, 204, 113, 0.5)";
                }
                
                let percentage = (successCount / TOTAL_FRAMES) * 100;
                if (progBar) progBar.style.width = percentage + "%";
                status.innerText = `✅ Face captured: ${successCount}/${TOTAL_FRAMES}`;
                status.style.color = "#2ecc71";
                console.log(`✅ Frame ${i} captured successfully`);
                failedFrames = 0; // Reset failed frames counter
            } else {
                // FAIL: Gawing Red ang border at ulitin ang frame
                if (videoDisplay) {
                    videoDisplay.style.borderColor = "#e74c3c";
                    videoDisplay.style.boxShadow = "0 0 15px rgba(231, 76, 60, 0.5)";
                }
                failedFrames++;
                status.innerText = `⚠️ No face detected (${failedFrames}x). Please look directly at the camera...`;
                status.style.color = "#e67e22";
                i--; // Ulitin itong frame count
                console.log(`❌ Frame ${i} failed: no face detected`);
            }
        } catch (error) {
            console.error("Capture Error:", error);
            status.innerText = "❌ Connection lost. Retrying camera...";
            status.style.color = "#e74c3c";
            
            // Try to restart video feed
            const videoFeed = document.getElementById('video-feed');
            if (videoFeed) {
                videoFeed.src = "/video_feed?t=" + new Date().getTime();
            }
            await new Promise(resolve => setTimeout(resolve, 1000));
            i--; 
        }
        
        // Delay para sa stability
        await new Promise(resolve => setTimeout(resolve, 300));
    }

    // Check if we have enough successful captures
    if (successCount < 10) {
        status.innerText = `❌ Only ${successCount}/20 faces captured. Please try again and look directly at the camera!`;
        status.style.color = "#e74c3c";
        btn.disabled = false;
        btn.style.opacity = "1";
        if (progCont) progCont.style.display = 'none';
        return;
    }

    // 2. Pag tapos na ang capture, i-sync sa hidden form
    status.innerText = "✅ Face captured successfully! Saving account details...";
    status.style.color = "#27ae60";
    if (progBar) progBar.style.backgroundColor = "#27ae60";
    
    // I-pass ang values sa hidden form inputs
    document.getElementById('hidden_name').value = regData.name;
    document.getElementById('hidden_email').value = regData.email;
    document.getElementById('hidden_password').value = regData.password;

    console.log("Submitting registration for:", regData.name);
    
    // Submit ang form
    setTimeout(() => {
        document.getElementById('finalSignupForm').submit();
    }, 1000);
}

// Add enter key support
document.addEventListener('DOMContentLoaded', function() {
    const inputs = document.querySelectorAll('#step-1 input');
    inputs.forEach(input => {
        input.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                showFaceScan();
            }
        });
    });
});