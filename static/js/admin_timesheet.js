// ===================================================
// ADMIN TIMESHEET JS - Fix anomalies & edit attendance
// ===================================================

// Helper to get CSRF token
function getCsrfToken() {
    return document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
}

// Fix missing time-out anomalies
document.querySelectorAll('.fix-anomaly').forEach(btn => {
    btn.addEventListener('click', function() {
        const row = this.closest('tr');
        const id = this.dataset.id;
        const timeOut = row.querySelector('.time-out-input').value;
        const timeIn = row.querySelector('td:nth-child(3)').innerText;
        
        fetch(`/admin/attendance/edit/${id}`, {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
            },
            body: JSON.stringify({ 
                time_out: timeOut, 
                time_in: timeIn, 
                minutes_late: 0, 
                undertime_minutes: 0 
            })
        })
        .then(res => res.json())
        .then(data => { 
            if (data.success) {
                Swal.fire('Updated', 'Time out has been set.', 'success')
                    .then(() => location.reload());
            } else {
                Swal.fire('Error', 'Failed to update.', 'error');
            }
        });
    });
});

// Save edited attendance record
document.querySelectorAll('.save-attendance').forEach(btn => {
    btn.addEventListener('click', function() {
        const row = this.closest('tr');
        const id = this.dataset.id;
        const timeIn = row.querySelector('.edit-time-in').value;
        const timeOut = row.querySelector('.edit-time-out').value;
        const minutesLate = row.querySelector('.edit-late').value;
        const minutesUndertime = row.querySelector('.edit-undertime').value;
        
        fetch(`/admin/attendance/edit/${id}`, {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
            },
            body: JSON.stringify({ 
                time_in: timeIn, 
                time_out: timeOut, 
                minutes_late: minutesLate, 
                undertime_minutes: minutesUndertime 
            })
        })
        .then(res => res.json())
        .then(data => { 
            if (data.success) {
                Swal.fire('Saved', 'Attendance record updated.', 'success');
            } else {
                Swal.fire('Error', 'Update failed.', 'error');
            }
        });
    });
});

// Live clock update
function updateClock() {
    const now = new Date();
    const clockEl = document.getElementById('liveClock');
    const dateEl = document.getElementById('liveDate');
    if (clockEl) {
        clockEl.textContent = now.toLocaleTimeString('en-US', {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: true
        });
    }
    if (dateEl) {
        dateEl.textContent = now.toLocaleDateString('en-US', {
            weekday: 'long',
            year: 'numeric',
            month: 'long',
            day: 'numeric'
        });
    }
}
setInterval(updateClock, 1000);
updateClock();