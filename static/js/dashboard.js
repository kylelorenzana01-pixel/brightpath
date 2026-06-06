/**
 * BRIGHTPATH EMPLOYEE DASHBOARD JS
 * – Fully functional with live stats, dynamic payslips & improved notifications
 */

// Helper to get CSRF token
function getCsrfToken() {
    return document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
}

// ========== 1. TAB SWITCHING (with auto‑refresh) ==========
let dashRefreshInterval = null;

window.switchTab = function(tabId, element) {
    const sections = document.querySelectorAll('.section-content');
    const navLinks = document.querySelectorAll('.nav-link');

    sections.forEach(sec => {
        sec.classList.remove('active');
        sec.classList.add('d-none');
    });
    
    navLinks.forEach(link => {
        link.classList.remove('active');
    });
    
    const target = document.getElementById(tabId);
    if (target) {
        target.classList.remove('d-none');
        setTimeout(() => target.classList.add('active'), 50);
    }

    if (element) {
        element.classList.add('active');
    } else {
        const fallbackLink = document.querySelector(`[onclick*="${tabId}"]`);
        if (fallbackLink) fallbackLink.classList.add('active');
    }

    // Clear any existing auto-refresh interval
    if (dashRefreshInterval) {
        clearInterval(dashRefreshInterval);
        dashRefreshInterval = null;
    }

    // Auto‑refresh data for each tab
    if (tabId === 'emp-dash') {
        refreshDashboardStats();
        loadQuickPayslips();               // dynamic Quick Payslips
        dashRefreshInterval = setInterval(refreshDashboardStats, 60000);   // every 60 seconds
    } else if (tabId === 'emp-reports') {
        setTimeout(loadEmployeeReports, 100);
    } else if (tabId === 'emp-leave') {
        loadLeaveRequests();
    } else if (tabId === 'emp-overtime') {
        loadOvertimeRequests();
    } else if (tabId === 'emp-cash-advance') {
        loadCashAdvances();
    } else if (tabId === 'emp-loan') {
        loadLoanRequests();
    }
}

// ========== 2. LIVE CLOCK ==========
function updateClock() {
    const clockElement = document.getElementById('liveClock');
    const dateElement = document.getElementById('liveDate');
    const now = new Date();
    
    if (clockElement) {
        clockElement.innerText = now.toLocaleTimeString('en-US', { 
            hour: '2-digit', 
            minute: '2-digit', 
            second: '2-digit',
            hour12: true 
        });
    }

    if (dateElement) {
        dateElement.innerText = now.toLocaleDateString('en-US', {
            weekday: 'long',
            year: 'numeric',
            month: 'long',
            day: 'numeric'
        });
    }
}

// ========== 3. PAYROLL ESTIMATOR ==========
window.openPayrollModal = function(name, rate, days) {
    const gross = rate * days;
    const sss = gross * 0.045; 
    const philhealth = gross * 0.04; 
    const pagibig = 100; 
    const tax = gross > 10000 ? (gross - 10000) * 0.15 : 0;
    const totalDeductions = sss + philhealth + pagibig + tax;
    const net = gross - totalDeductions;

    const formatter = new Intl.NumberFormat('en-PH', { 
        style: 'currency', 
        currency: 'PHP' 
    });

    document.getElementById('payName').innerText = name;
    document.getElementById('payGross').innerText = formatter.format(gross);
    document.getElementById('paySSS').innerText = "-" + formatter.format(sss);
    document.getElementById('payPH').innerText = "-" + formatter.format(philhealth);
    document.getElementById('payNet').innerText = formatter.format(net);

    const modalEl = document.getElementById('payrollModal');
    if (modalEl) {
        new bootstrap.Modal(modalEl).show();
    }
}

// ========== 4. NOTIFICATION SYSTEM (IMPROVED) ==========
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function loadUnreadCount() {
    fetch('/employee/notifications/unread_count')
        .then(res => res.json())
        .then(data => {
            const badge = document.getElementById('notifBadge');
            if (data.success && data.count > 0) {
                badge.style.display = 'flex';
                badge.innerText = data.count > 9 ? '9+' : data.count;
            } else {
                badge.style.display = 'none';
            }
        })
        .catch(err => console.error('Error loading unread count:', err));
}

function loadNotifications() {
    fetch('/employee/notifications')
        .then(res => res.json())
        .then(data => {
            const container = document.getElementById('notificationList');
            if (!container) return;
            if (data.success && data.notifications.length > 0) {
                let html = '';
                data.notifications.forEach(notif => {
                    const timeStr = new Date(notif.created_at).toLocaleString();
                    html += `
                        <div class="notification-item" data-id="${notif.id}" data-link="${notif.link || ''}" style="cursor:pointer;">
                            <div class="notification-message fw-bold">${escapeHtml(notif.message)}</div>
                            <div class="notification-time text-muted small">${timeStr}</div>
                        </div>
                    `;
                });
                container.innerHTML = html;
                document.querySelectorAll('.notification-item').forEach(item => {
                    item.addEventListener('click', function(e) {
                        const id = this.dataset.id;
                        const link = this.dataset.link;
                        if (id) {
                            fetch(`/employee/notifications/mark_read/${id}`, { 
                                method: 'POST',
                                headers: { 'X-CSRFToken': getCsrfToken() }
                            }).then(() => {
                                loadUnreadCount();
                                if (link) window.location.href = link;
                            });
                        }
                    });
                });
            } else {
                container.innerHTML = '<div class="text-center p-4 text-muted">No notifications</div>';
            }
        })
        .catch(err => console.error('Error loading notifications:', err));
}

// ========== 5. LOAD REPORTS FOR "MY REPORTS" TAB ==========
function loadEmployeeReports() {
    const tbody = document.getElementById('reportsTableBody');
    if (!tbody) return;
    
    fetch('/employee/api/reports')
        .then(res => res.json())
        .then(data => {
            if (data.success && data.reports && data.reports.length > 0) {
                let html = '';
                data.reports.forEach(report => {
                    const date = new Date(report.created_at).toLocaleString();
                    html += `
                        <tr>
                            <td>${escapeHtml(report.title)}</td>
                            <td>${date}</td>
                            <td><a href="${report.url}" target="_blank" class="btn btn-sm btn-info">View Report</a></td>
                        </tr>
                    `;
                });
                tbody.innerHTML = html;
            } else {
                tbody.innerHTML = '<tr><td colspan="3" class="text-center text-muted">No reports available.</td></tr>';
            }
        })
        .catch(err => {
            console.error('Error loading reports:', err);
            tbody.innerHTML = '<tr><td colspan="3" class="text-center text-danger">Failed to load reports.</td></tr>';
        });
}

// ========== 6. DYNAMIC DASHBOARD STATS ==========
function refreshDashboardStats() {
    fetch('/employee/api/dashboard_stats')
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                // Update Leave Credits card (second card)
                const leaveCard = document.querySelector('#emp-dash .col-md-3:nth-child(2) h2');
                if (leaveCard) leaveCard.innerText = data.leave_credits.toFixed(1);

                // Update Monthly Attendance card (third card)
                const daysCard = document.querySelector('#emp-dash .col-md-3:nth-child(3) h2');
                if (daysCard) daysCard.innerText = data.days_worked;

                // Update Last Payroll card (fourth card)
                const payrollCard = document.querySelector('#emp-dash .col-md-3:nth-child(4) h2');
                if (payrollCard) payrollCard.innerText = '₱' + data.last_net_pay.toLocaleString();
            }
        })
        .catch(err => console.error('Failed to refresh stats:', err));
}

// ========== 7. DYNAMIC QUICK PAYSLIPS ==========
function loadQuickPayslips() {
    const container = document.getElementById('quickPayslipsList');
    if (!container) return;

    fetch('/employee/api/quick_payslips')
        .then(res => res.json())
        .then(data => {
            if (data.success && data.payslips && data.payslips.length > 0) {
                let html = '';
                data.payslips.forEach(pay => {
                    html += `<div class="list-group-item bg-transparent px-0 border-light d-flex justify-content-between align-items-center">
                        <div>
                            <p class="mb-0 fw-bold small">${pay.date_paid}</p>
                            <small class="text-success fw-bold">₱${pay.net_pay.toLocaleString()}</small>
                        </div>
                        <a href="/employee/payslip/${pay.id}" target="_blank" class="btn btn-sm btn-light rounded-circle">
                            <i class="fas fa-download"></i>
                        </a>
                    </div>`;
                });
                html += '<button class="btn btn-link btn-sm w-100 mt-2 text-decoration-none" onclick="switchTab(\'emp-payroll\', document.getElementById(\'link-payroll\'))">See All Records</button>';
                container.innerHTML = html;
            } else {
                container.innerHTML = '<p class="text-center text-muted py-4 small">No payroll records yet.</p>';
            }
        })
        .catch(err => console.error('Error loading quick payslips:', err));
}

// ========== 8. AJAX LOADERS FOR REQUEST TABS ==========
function loadLeaveRequests() {
    fetch('/employee/leave_requests_json')
        .then(res => res.json())
        .then(data => {
            const tbody = document.querySelector('#emp-leave tbody');
            if (data.success && data.requests) {
                let html = '';
                data.requests.forEach(req => {
                    const statusBadge = req.status === 'Pending' ? 'bg-warning text-dark' :
                                       req.status === 'Approved' ? 'bg-success' :
                                       req.status === 'Rejected' ? 'bg-danger' : 'bg-secondary';
                    html += `<tr>
                        <td>${req.leave_type}</td>
                        <td>${req.start_date}</td>
                        <td>${req.end_date}</td>
                        <td><span class="badge ${statusBadge}">${req.status}</span></td>
                        <td>${(req.reason||'').substring(0,50)}</td>
                    </tr>`;
                });
                tbody.innerHTML = html || '<tr><td colspan="5" class="text-center py-4 text-muted">No leave requests found.</td></tr>';
            }
        });
}

function loadOvertimeRequests() {
    // Placeholder – you need a JSON endpoint /employee/overtime_requests_json
    const tbody = document.querySelector('#emp-overtime tbody');
    if (tbody) tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted">Overtime requests loading…</td></tr>';
}

function loadCashAdvances() {
    // Placeholder – you need a JSON endpoint /employee/cash_advances_json
}

function loadLoanRequests() {
    // Placeholder – you need a JSON endpoint /employee/loan_requests_json
}

// ========== 9. INITIALIZATION ==========
document.addEventListener('DOMContentLoaded', function() {
    setInterval(updateClock, 1000); 
    updateClock();

    // Set default tab to Dashboard
    const dashLink = document.getElementById('link-dash');
    if (dashLink) {
        window.switchTab('emp-dash', dashLink);
    }
    
    // Auto-close flash alerts
    setTimeout(() => {
        document.querySelectorAll('.alert').forEach(alert => {
            new bootstrap.Alert(alert).close();
        });
    }, 4000);

    // Notification bell
    const bell = document.getElementById('notificationBell');
    const menu = document.getElementById('notificationMenu');
    if (bell && menu) {
        bell.addEventListener('click', function(e) {
            e.stopPropagation();
            if (menu.style.display === 'none' || !menu.style.display) {
                loadNotifications();
                menu.style.display = 'block';
            } else {
                menu.style.display = 'none';
            }
        });
        
        const markAllBtn = document.getElementById('markAllRead');
        if (markAllBtn) {
            markAllBtn.addEventListener('click', function(e) {
                e.stopPropagation();
                fetch('/employee/notifications/mark_all_read', { 
                    method: 'POST',
                    headers: { 'X-CSRFToken': getCsrfToken() }
                }).then(() => {
                    loadUnreadCount();
                    loadNotifications();
                });
            });
        }
        
        document.addEventListener('click', function(event) {
            if (!bell.contains(event.target) && !menu.contains(event.target)) {
                menu.style.display = 'none';
            }
        });
    }
    
    loadUnreadCount();
    setInterval(loadUnreadCount, 30000);
});

// Refresh stats when Dashboard link is clicked (redundant with switchTab but kept for safety)
document.getElementById('link-dash')?.addEventListener('click', () => {
    setTimeout(refreshDashboardStats, 200);
});