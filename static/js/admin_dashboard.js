// ===================================================
// ADMIN DASHBOARD JS - Full CRUD + Search + Charts + Unified Payroll
// ===================================================

// Helper to get CSRF token
function getCsrfToken() {
    return document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
}

// Helper to reload while preserving the current active tab
function reloadWithCurrentTab() {
    const activeTab = document.querySelector('.tab-content.active')?.id;
    if (activeTab) {
        window.location.href = window.location.pathname + '#' + activeTab;
    } else {
        location.reload();
    }
}

// ========== HELPER FUNCTIONS ==========
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
function formatNumber(num) {
    return num ? num.toLocaleString('en-PH') : '0';
}

// ========== CLOCK ==========
function updateClock() {
    const now = new Date();
    const clockEl = document.getElementById('liveClock');
    const dateEl = document.getElementById('liveDate');
    if (clockEl) clockEl.textContent = now.toLocaleTimeString('en-US', { hour:'2-digit', minute:'2-digit', second:'2-digit', hour12:true });
    if (dateEl) dateEl.textContent = now.toLocaleDateString('en-US', { weekday:'long', year:'numeric', month:'long', day:'numeric' });
}
setInterval(updateClock, 1000);
updateClock();

// ========== TAB SWITCHING + URL HASH ==========
const tabLinks = document.querySelectorAll('.nav-link[data-tab]');
if (tabLinks.length) {
    tabLinks.forEach(link => {
        link.addEventListener('click', function(e) {
            e.preventDefault();
            const target = this.getAttribute('data-tab');
            document.querySelectorAll('.tab-content').forEach(tab => tab.classList.remove('active'));
            document.querySelectorAll('.nav-link').forEach(nav => nav.classList.remove('active'));
            document.getElementById(target).classList.add('active');
            this.classList.add('active');
            window.location.hash = target;
        });
    });
}

function activateTabFromHash() {
    const hash = window.location.hash.substring(1);
    if (hash) {
        const targetTab = document.getElementById(hash);
        if (targetTab && targetTab.classList.contains('tab-content')) {
            document.querySelectorAll('.tab-content').forEach(tab => tab.classList.remove('active'));
            document.querySelectorAll('.nav-link').forEach(nav => nav.classList.remove('active'));
            targetTab.classList.add('active');
            const activeNav = document.querySelector(`.nav-link[data-tab="${hash}"]`);
            if (activeNav) activeNav.classList.add('active');
        }
    }
}
activateTabFromHash();
window.addEventListener('hashchange', activateTabFromHash);

// ========== LOAD POSITIONS FOR FILTERS ==========
function loadPositionFilters() {
    fetch('/admin/api/positions')
        .then(res => res.json())
        .then(data => {
            let positions = [];
            if (data.success && data.positions && data.positions.length > 0) {
                positions = data.positions;
            } else {
                positions = [
                    'Sales and Marketing Staff', 'Operations and Delivery Staff', 'HR Officer',
                    'Finance Officer', 'Admin Staff', 'General Manager', 'Delivery Driver', 'Warehouse Staff'
                ];
            }
            
            // Payroll position select (if exists)
            const payrollSelect = document.getElementById('position_filter');
            if (payrollSelect) {
                payrollSelect.innerHTML = '<option value="all">All Employees</option>';
                positions.forEach(pos => {
                    const option = document.createElement('option');
                    option.value = pos;
                    option.textContent = pos;
                    payrollSelect.appendChild(option);
                });
            }
            
            // Employee directory position filter
            const employeeFilter = document.getElementById('employeePositionFilter');
            if (employeeFilter) {
                employeeFilter.innerHTML = '<option value="all">All Positions</option>';
                positions.forEach(pos => {
                    const option = document.createElement('option');
                    option.value = pos;
                    option.textContent = pos;
                    employeeFilter.appendChild(option);
                });
            }
        })
        .catch(err => {
            console.error("Failed to load positions:", err);
            // Fallback on error
            const defaultPositions = [
                'Sales and Marketing Staff', 'Operations and Delivery Staff', 'HR Officer',
                'Finance Officer', 'Admin Staff', 'General Manager', 'Delivery Driver', 'Warehouse Staff'
            ];
            const employeeFilter = document.getElementById('employeePositionFilter');
            if (employeeFilter) {
                employeeFilter.innerHTML = '<option value="all">All Positions</option>';
                defaultPositions.forEach(pos => {
                    const option = document.createElement('option');
                    option.value = pos;
                    option.textContent = pos;
                    employeeFilter.appendChild(option);
                });
            }
        });
}

// Call it when page loads
document.addEventListener('DOMContentLoaded', loadPositionFilters);

// ========== SEARCH & POSITION FILTER FOR EMPLOYEES (Employee Directory) ==========
const searchInput = document.getElementById('employeeSearchInput');
const positionFilter = document.getElementById('employeePositionFilter');
const employeeTableBody = document.getElementById('employeeTableBody');

function filterEmployees() {
    if (!employeeTableBody) return;
    const searchTerm = searchInput ? searchInput.value.toLowerCase() : '';
    const selectedPosition = positionFilter ? positionFilter.value : 'all';
    const rows = employeeTableBody.getElementsByTagName('tr');
    for (let row of rows) {
        const name = row.cells[1]?.innerText.toLowerCase() || '';
        const email = row.cells[2]?.innerText.toLowerCase() || '';
        const position = row.cells[3]?.innerText.toLowerCase() || '';
        const matchesSearch = name.includes(searchTerm) || email.includes(searchTerm);
        const matchesPosition = (selectedPosition === 'all') || (position === selectedPosition.toLowerCase());
        row.style.display = (matchesSearch && matchesPosition) ? '' : 'none';
    }
}
if (searchInput) searchInput.addEventListener('keyup', filterEmployees);
if (positionFilter) positionFilter.addEventListener('change', filterEmployees);

// ========== ADD EMPLOYEE ==========
// ========== ADD EMPLOYEE ==========
document.getElementById('saveEmployeeBtn')?.addEventListener('click', function() {
    const name = document.getElementById('empName').value;
    const email = document.getElementById('empEmail').value;
    const password = document.getElementById('empPassword').value;
    const position = document.getElementById('empPosition').value;
    const daily_rate = parseFloat(document.getElementById('empRate').value);
    if (!name || !email || !password) return Swal.fire('Error', 'All fields required', 'error');
    fetch('/admin/api/employees', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
        body: JSON.stringify({ name, email, password, position, daily_rate })
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) Swal.fire('Success', 'Employee added', 'success').then(() => reloadWithCurrentTab());
        else Swal.fire('Error', data.message, 'error');
    });
});

// ========== VIEW EMPLOYEE ==========
document.querySelectorAll('.view-employee').forEach(btn => {
    btn.addEventListener('click', function() {
        const id = this.dataset.id;
        fetch(`/admin/api/employees/${id}`)
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    const emp = data.employee;
                    let content = '<div class="row"><div class="col-4 fw-bold">ID:</div><div class="col-8">#'+emp.id+'</div></div>';
                    content += '<div class="row"><div class="col-4 fw-bold">Name:</div><div class="col-8">'+escapeHtml(emp.name)+'</div></div>';
                    content += '<div class="row"><div class="col-4 fw-bold">Email:</div><div class="col-8">'+escapeHtml(emp.email)+'</div></div>';
                    content += '<div class="row"><div class="col-4 fw-bold">Position:</div><div class="col-8">'+(emp.position || 'Staff')+'</div></div>';
                    content += '<div class="row"><div class="col-4 fw-bold">Daily Rate:</div><div class="col-8">₱'+formatNumber(emp.daily_rate)+'</div></div>';
                    content += '<div class="row"><div class="col-4 fw-bold">Contact:</div><div class="col-8">'+(emp.contact_number || 'N/A')+'</div></div>';
                    content += '<div class="row"><div class="col-4 fw-bold">Address:</div><div class="col-8">'+(emp.address || 'N/A')+'</div></div>';
                    content += '<div class="row"><div class="col-4 fw-bold">Leave Credits:</div><div class="col-8">'+(emp.leave_credits || 15)+' days</div></div>';
                    content += '<div class="row"><div class="col-4 fw-bold">Status:</div><div class="col-8">'+(emp.status == 'active' ? 'Active' : 'Inactive')+'</div></div>';
                    document.getElementById('viewEmployeeContent').innerHTML = content;
                    new bootstrap.Modal(document.getElementById('viewEmployeeModal')).show();
                } else {
                    Swal.fire('Error', 'Employee not found', 'error');
                }
            });
    });
});

// ========== EDIT EMPLOYEE – POPULATE MODAL ==========
document.querySelectorAll('.edit-employee').forEach(btn => {
    btn.addEventListener('click', function() {
        const id = this.getAttribute('data-id');
        fetch(`/admin/api/employees/${id}`)
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    const emp = data.employee;
                    document.getElementById('modal_emp_id').value = emp.id;
                    document.getElementById('modal_emp_name').value = emp.name;
                    document.getElementById('modal_emp_email').value = emp.email;
                    document.getElementById('modal_emp_rate').value = emp.daily_rate || 500;
                    document.getElementById('modal_emp_contact').value = emp.contact_number || '';
                    document.getElementById('modal_emp_address').value = emp.address || '';

                    // Always populate position dropdown using hardcoded list
                    const positionRateMap = {
                        'Sales and Marketing Staff': 550,
                        'Operations and Delivery Staff': 520,
                        'HR Officer': 600,
                        'Finance Officer': 650,
                        'Admin Staff': 500,
                        'General Manager': 800,
                        'Delivery Driver': 480,
                        'Warehouse Staff': 470,
                        'Staff': 500
                    };
                    const select = document.getElementById('modal_emp_position');
                    select.innerHTML = '';
                    Object.keys(positionRateMap).forEach(pos => {
                        const opt = document.createElement('option');
                        opt.value = pos;
                        opt.textContent = pos;
                        if (pos === emp.position) opt.selected = true;
                        select.appendChild(opt);
                    });
                    select.onchange = function() {
                        document.getElementById('modal_emp_rate').value = positionRateMap[this.value] || 500;
                    };

                    new bootstrap.Modal(document.getElementById('editModal')).show();
                } else {
                    Swal.fire('Error', 'Employee not found', 'error');
                }
            })
            .catch(() => Swal.fire('Error', 'Failed to load employee', 'error'));
    });
});

// ========== UPDATE EMPLOYEE ==========
document.getElementById('updateEmployeeBtn')?.addEventListener('click', function() {
    const id = document.getElementById('modal_emp_id').value;
    console.log("Updating employee ID:", id);  // ✅ Add this line
    const name = document.getElementById('modal_emp_name').value;
    const email = document.getElementById('modal_emp_email').value;
    const position = document.getElementById('modal_emp_position').value;
    const daily_rate = parseFloat(document.getElementById('modal_emp_rate').value);
    const contact_number = document.getElementById('modal_emp_contact').value;
    const address = document.getElementById('modal_emp_address').value;
    if (!name || !email) return Swal.fire('Error', 'Name and email are required', 'error');
    fetch(`/admin/api/employees/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
        body: JSON.stringify({ name, email, position, daily_rate, contact_number, address })
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) Swal.fire('Updated', 'Employee updated', 'success').then(() => reloadWithCurrentTab());
        else Swal.fire('Error', data.message, 'error');
    });
});

// ========== DELETE EMPLOYEE ==========
document.querySelectorAll('.delete-employee').forEach(btn => {
    btn.addEventListener('click', function() {
        const id = this.dataset.id;
        const name = this.dataset.name;
        Swal.fire({
            title: 'Delete Employee?',
            text: `Permanently delete ${name}? All associated records will be lost.`,
            icon: 'warning',
            showCancelButton: true,
            confirmButtonColor: '#d33',
            confirmButtonText: 'Yes, delete'
        }).then(result => {
            if (result.isConfirmed) {
                fetch(`/admin/api/employees/${id}`, { method: 'DELETE', headers: { 'X-CSRFToken': getCsrfToken() } })
                    .then(res => res.json())
                    .then(data => {
                        if (data.success) Swal.fire('Deleted', '', 'success').then(() => reloadWithCurrentTab());
                        else Swal.fire('Error', data.message, 'error');
                    });
            }
        });
    });
});

// ========== DEACTIVATE ==========
document.querySelectorAll('.deactivate-employee').forEach(btn => {
    btn.addEventListener('click', function() {
        const id = this.dataset.id;
        const name = this.dataset.name;
        Swal.fire({
            title: 'Deactivate Employee?',
            text: `${name} will be unable to log in.`,
            icon: 'warning',
            showCancelButton: true,
            confirmButtonColor: '#d33',
            confirmButtonText: 'Yes, deactivate'
        }).then(result => {
            if (result.isConfirmed) {
                fetch(`/admin/api/employees/deactivate/${id}`, { method: 'POST', headers: { 'X-CSRFToken': getCsrfToken() } })
                    .then(res => res.json())
                    .then(data => {
                        if (data.success) Swal.fire('Deactivated', '', 'success').then(() => reloadWithCurrentTab());
                        else Swal.fire('Error', data.message, 'error');
                    });
            }
        });
    });
});

// ========== REACTIVATE ==========
document.querySelectorAll('.reactivate-employee').forEach(btn => {
    btn.addEventListener('click', function() {
        const id = this.dataset.id;
        const name = this.dataset.name;
        Swal.fire({
            title: 'Reactivate Employee?',
            text: `${name} will be able to log in again.`,
            icon: 'info',
            showCancelButton: true,
            confirmButtonColor: '#10b981',
            confirmButtonText: 'Yes, reactivate'
        }).then(result => {
            if (result.isConfirmed) {
                fetch(`/admin/api/employees/reactivate/${id}`, { method: 'POST', headers: { 'X-CSRFToken': getCsrfToken() } })
                    .then(res => res.json())
                    .then(data => {
                        if (data.success) Swal.fire('Reactivated', '', 'success').then(() => reloadWithCurrentTab());
                        else Swal.fire('Error', data.message, 'error');
                    });
            }
        });
    });
});

// ========== PAYROLL VIEW ==========
document.querySelectorAll('.view-payroll').forEach(btn => {
    btn.addEventListener('click', function() {
        const id = this.getAttribute('data-id');
        window.open(`/admin/payroll/view/${id}`, '_blank');
    });
});

// ========== LEAVE APPROVAL / REJECTION ==========
document.querySelectorAll('.approve-leave').forEach(btn => {
    btn.addEventListener('click', function() {
        const id = this.getAttribute('data-id');
        Swal.fire({ title: 'Approve Leave?', text: 'Confirm approval', icon: 'question', showCancelButton: true, confirmButtonColor: '#10b981', confirmButtonText: 'Yes' })
            .then(result => {
                if (result.isConfirmed) {
                    fetch(`/admin/leave/approve/${id}`, { 
                        method: 'POST',
                        headers: { 'X-CSRFToken': getCsrfToken() }
                    })
                        .then(res => res.json())
                        .then(data => { if (data.success) Swal.fire('Approved', '', 'success').then(() => reloadWithCurrentTab()); else Swal.fire('Error', data.message, 'error'); });
                }
            });
    });
});
document.querySelectorAll('.reject-leave').forEach(btn => {
    btn.addEventListener('click', function() {
        const id = this.getAttribute('data-id');
        Swal.fire({ title: 'Reject Leave?', text: 'Confirm rejection', icon: 'warning', showCancelButton: true, confirmButtonColor: '#ef4444', confirmButtonText: 'Yes' })
            .then(result => {
                if (result.isConfirmed) {
                    fetch(`/admin/leave/reject/${id}`, { 
                        method: 'POST',
                        headers: { 'X-CSRFToken': getCsrfToken() }
                    })
                        .then(res => res.json())
                        .then(data => { if (data.success) Swal.fire('Rejected', '', 'error').then(() => reloadWithCurrentTab()); else Swal.fire('Error', data.message, 'error'); });
                }
            });
    });
});

// ========== STATS CARD ACTIONS ==========
function switchToEmployeesTab() {
    const employeesNav = document.querySelector('.nav-link[data-tab="employees-tab"]');
    if (employeesNav) {
        employeesNav.click();
    } else {
        document.querySelectorAll('.tab-content').forEach(tab => tab.classList.remove('active'));
        document.getElementById('employees-tab')?.classList.add('active');
        document.querySelectorAll('.nav-link').forEach(link => link.classList.remove('active'));
        const activeLink = document.querySelector('.nav-link[data-tab="employees-tab"]');
        if (activeLink) activeLink.classList.add('active');
        window.location.hash = 'employees-tab';
    }
}

function switchToPayrollTab() {
    const payrollNav = document.querySelector('.nav-link[data-tab="payroll-tab"]');
    if (payrollNav) {
        payrollNav.click();
    } else {
        document.querySelectorAll('.tab-content').forEach(tab => tab.classList.remove('active'));
        document.getElementById('payroll-tab')?.classList.add('active');
        document.querySelectorAll('.nav-link').forEach(link => link.classList.remove('active'));
        const activeLink = document.querySelector('.nav-link[data-tab="payroll-tab"]');
        if (activeLink) activeLink.classList.add('active');
        window.location.hash = 'payroll-tab';
    }
}

function showActiveEmployees() {
    Swal.fire({
        title: '<i class="fas fa-user-check"></i> Active Employees (Currently Clocked In)',
        html: '<div id="activeEmployeesList" style="text-align: left;">Loading...</div>',
        showConfirmButton: true,
        confirmButtonText: 'Close',
        didOpen: () => {
            fetch('/admin/api/active_employees')
                .then(res => res.json())
                .then(data => {
                    const container = document.getElementById('activeEmployeesList');
                    if (data.success && data.employees && data.employees.length > 0) {
                        let html = '<ul style="margin:0; padding-left:1.5rem;">';
                        data.employees.forEach(emp => {
                            html += `<li><strong>${escapeHtml(emp.name)}</strong> - ${emp.position || 'Staff'} <br><small>Time in: ${emp.time_in}</small></li>`;
                        });
                        html += '</ul>';
                        container.innerHTML = html;
                    } else {
                        container.innerHTML = '<p class="text-muted">No active employees right now.</p>';
                    }
                })
                .catch(err => {
                    console.error(err);
                    document.getElementById('activeEmployeesList').innerHTML = '<p class="text-danger">Failed to load data.</p>';
                });
        }
    });
}

function showLateEmployees() {
    Swal.fire({
        title: '<i class="fas fa-clock"></i> Late Employees Today',
        html: '<div id="lateEmployeesList" style="text-align: left;">Loading...</div>',
        showConfirmButton: true,
        confirmButtonText: 'Close',
        didOpen: () => {
            fetch('/admin/api/late_employees')
                .then(res => res.json())
                .then(data => {
                    const container = document.getElementById('lateEmployeesList');
                    if (data.success && data.employees && data.employees.length > 0) {
                        let html = '<ul style="margin:0; padding-left:1.5rem;">';
                        data.employees.forEach(emp => {
                            html += `<li><strong>${escapeHtml(emp.name)}</strong> - ${emp.position || 'Staff'} <br><small>Late: ${emp.minutes_late} mins, Time in: ${emp.time_in}</small></li>`;
                        });
                        html += '</ul>';
                        container.innerHTML = html;
                    } else {
                        container.innerHTML = '<p class="text-muted">No late employees today.</p>';
                    }
                })
                .catch(err => {
                    console.error(err);
                    document.getElementById('lateEmployeesList').innerHTML = '<p class="text-danger">Failed to load data.</p>';
                });
        }
    });
}

// ========== CHARTS ==========
function loadCharts() {
    fetch('/admin/api/attendance_summary')
        .then(res => res.json())
        .then(data => {
            const ctx = document.getElementById('attendanceChart')?.getContext('2d');
            if (ctx) {
                if (window.attendanceChartInstance) window.attendanceChartInstance.destroy();
                window.attendanceChartInstance = new Chart(ctx, {
                    type: 'bar',
                    data: {
                        labels: data.days,
                        datasets: [
                            { label: 'Present', data: data.present, backgroundColor: '#10b981', borderRadius: 5 },
                            { label: 'Late', data: data.late, backgroundColor: '#f59e0b', borderRadius: 5 },
                            { label: 'Absent', data: data.absent, backgroundColor: '#ef4444', borderRadius: 5 }
                        ]
                    },
                    options: { responsive: true, maintainAspectRatio: true, plugins: { legend: { position: 'top' } } }
                });
            }
        })
        .catch(err => console.error('Attendance chart error:', err));

    fetch('/admin/api/payroll_trend')
        .then(res => res.json())
        .then(data => {
            const ctx = document.getElementById('payrollChart')?.getContext('2d');
            if (ctx) {
                if (window.payrollChartInstance) window.payrollChartInstance.destroy();
                window.payrollChartInstance = new Chart(ctx, {
                    type: 'line',
                    data: {
                        labels: data.months,
                        datasets: [{ label: 'Total Payroll (₱)', data: data.amounts, borderColor: '#3b82f6', backgroundColor: 'rgba(59,130,246,0.1)', tension: 0.3, fill: true }]
                    },
                    options: { responsive: true, plugins: { tooltip: { callbacks: { label: (ctx) => `₱${ctx.raw.toLocaleString()}` } } } }
                });
            }
        })
        .catch(err => console.error('Payroll chart error:', err));
}

// Load charts initially and when dashboard tab is clicked
const dashboardTab = document.getElementById('dashboard-tab');
if (dashboardTab) {
    if (dashboardTab.classList.contains('active')) loadCharts();
    const dashboardNav = document.querySelector('.nav-link[data-tab="dashboard-tab"]');
    if (dashboardNav) {
        dashboardNav.addEventListener('click', () => setTimeout(loadCharts, 200));
    }
}
document.addEventListener('DOMContentLoaded', () => setTimeout(loadCharts, 500));

// ========== UNIFIED PAYROLL CARD FUNCTIONS ==========
function togglePayrollMode() {
    const modeSingle = document.getElementById('modeSingle');
    // GUARD: exit if element does not exist (e.g., not on the payroll tab yet)
    if (!modeSingle) return;

    const singleFields = document.getElementById('singleModeFields');
    const allFields = document.getElementById('allModeFields');
    if (modeSingle.checked) {
        singleFields.style.display = 'flex';
        allFields.style.display = 'none';
        refreshSingleEmployeeList();
    } else {
        singleFields.style.display = 'none';
        allFields.style.display = 'flex';
        refreshAllEmployeeSelect();
    }
}

function refreshSingleEmployeeList() {
    const positionEl = document.getElementById('position_filter');
    if (!positionEl) return;   // huminto kung wala ang element (e.g., wala sa dashboard page)

    const searchEl = document.getElementById('single_search');
    if (!searchEl) return;

    const position = positionEl.value;
    const search = searchEl.value;

    fetch(`/admin/api/employees/filter?position=${encodeURIComponent(position)}&search=${encodeURIComponent(search)}`)
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                const select = document.getElementById('single_employee_select');
                if (!select) return;
                let options = '<option value="">-- Choose Employee --</option>';
                data.employees.forEach(emp => {
                    options += `<option value="${emp.id}">${escapeHtml(emp.name)} (ID: ${emp.id}) – ${emp.position || 'Staff'}</option>`;
                });
                select.innerHTML = options;
            }
        })
        .catch(err => console.error('Refresh error:', err));
}

function refreshAllEmployeeSelect() {
    const positionEl = document.getElementById('position_filter');
    if (!positionEl) return;

    const searchEl = document.getElementById('all_search');
    if (!searchEl) return;

    const position = positionEl.value;
    const search = searchEl.value;

    fetch(`/admin/api/employees/filter?position=${encodeURIComponent(position)}&search=${encodeURIComponent(search)}`)
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                const select = document.getElementById('all_employee_select');
                if (!select) return;
                let options = '';
                data.employees.forEach(emp => {
                    options += `<option value="${emp.id}">${escapeHtml(emp.name)} (ID: ${emp.id}) – ${emp.position || 'Staff'}</option>`;
                });
                select.innerHTML = options;
            }
        })
        .catch(err => console.error('Refresh error:', err));
}

function previewPayroll() {
    const modeSingle = document.getElementById('modeSingle').checked;
    const start = document.getElementById('cutoff_start').value;
    const end = document.getElementById('cutoff_end').value;
    const payrollDate = document.getElementById('payroll_date').value;
    if (!start || !end || !payrollDate) {
        alert("Please fill cutoff start, end, and payroll date.");
        return;
    }
    if (modeSingle) {
        const empId = document.getElementById('single_employee_select').value;
        if (!empId) {
            alert("Please select an employee.");
            return;
        }
        window.open(`/admin/payroll/preview/${empId}?start_date=${start}&end_date=${end}&payroll_date=${payrollDate}`, '_blank');
    } else {
        const select = document.getElementById('all_employee_select');
        let selectedValues = Array.from(select.selectedOptions).map(opt => opt.value);
        let employeeIds = selectedValues.length ? selectedValues.join(',') : '';
        let url = `/admin/payroll/preview_all?cutoff_start=${start}&cutoff_end=${end}&payroll_date=${payrollDate}&position=${document.getElementById('position_filter').value}`;
        if (employeeIds) url += `&employees=${employeeIds}`;
        window.open(url, '_blank');
    }
}

function generatePayroll() {
    const modeSingle = document.getElementById('modeSingle').checked;
    const start = document.getElementById('cutoff_start').value;
    const end = document.getElementById('cutoff_end').value;
    const payrollDate = document.getElementById('payroll_date').value;
    if (!start || !end || !payrollDate) {
        alert("Please fill cutoff start, end, and payroll date.");
        return;
    }
    if (modeSingle) {
        const empId = document.getElementById('single_employee_select').value;
        if (!empId) {
            alert("Please select an employee.");
            return;
        }
        const form = document.createElement('form');
        form.method = 'POST';
        form.action = '/admin/payroll/generate_single';
        form.target = '_blank';
        form.innerHTML = `
            <input type="hidden" name="csrf_token" value="${getCsrfToken()}">
            <input type="hidden" name="employee_id" value="${empId}">
            <input type="hidden" name="cutoff_start" value="${start}">
            <input type="hidden" name="cutoff_end" value="${end}">
            <input type="hidden" name="payroll_date" value="${payrollDate}">
            <input type="hidden" name="status" value="published">
        `;
        document.body.appendChild(form);
        form.submit();
        document.body.removeChild(form);
    } else {
        const select = document.getElementById('all_employee_select');
        let selectedValues = Array.from(select.selectedOptions).map(opt => opt.value);
        let employeeIds = selectedValues.length ? selectedValues.join(',') : '';
        const form = document.createElement('form');
        form.method = 'POST';
        form.action = '/admin/payroll/generate_all';
        form.target = '_blank';
        form.innerHTML = `
            <input type="hidden" name="csrf_token" value="${getCsrfToken()}">
            <input type="hidden" name="cutoff_start" value="${start}">
            <input type="hidden" name="cutoff_end" value="${end}">
            <input type="hidden" name="payroll_date" value="${payrollDate}">
            <input type="hidden" name="position" value="${document.getElementById('position_filter').value}">
            <input type="hidden" name="status" value="published">
            <input type="hidden" name="employees" value="${employeeIds}">
        `;
        document.body.appendChild(form);
        form.submit();
        document.body.removeChild(form);
    }
}

// ========== ATTACH EVENT LISTENERS FOR UNIFIED PAYROLL ==========
document.getElementById('modeSingle')?.addEventListener('change', togglePayrollMode);
document.getElementById('modeAll')?.addEventListener('change', togglePayrollMode);
document.getElementById('position_filter')?.addEventListener('change', () => {
    if (document.getElementById('modeSingle').checked) refreshSingleEmployeeList();
    else refreshAllEmployeeSelect();
});
document.getElementById('single_search')?.addEventListener('keyup', function(e) {
    if (e.key === 'Enter') refreshSingleEmployeeList();
});
document.getElementById('all_search')?.addEventListener('keyup', function() {
    const searchTerm = this.value.toLowerCase();
    const select = document.getElementById('all_employee_select');
    for (let i = 0; i < select.options.length; i++) {
        const text = select.options[i].text.toLowerCase();
        select.options[i].style.display = text.includes(searchTerm) ? '' : 'none';
    }
});
// Initial load
togglePayrollMode();
refreshSingleEmployeeList();
refreshAllEmployeeSelect();

// ========== EMPLOYEE REPORTS (for admin preview only) ==========
function loadEmployeeReports() {
    fetch('/employee/api/reports')
        .then(res => res.json())
        .then(data => {
            const tbody = document.getElementById('reportsTableBody');
            if (!tbody) return;
            if (data.success && data.reports.length > 0) {
                let html = '';
                data.reports.forEach(report => {
                    const date = new Date(report.created_at).toLocaleString();
                    html += `
                        <tr>
                            <td>${escapeHtml(report.title)}</td
                            <td>${date}</td
                            <td><a href="${report.url}" target="_blank" class="btn btn-sm btn-info">View Report</a></td
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
            const tbody = document.getElementById('reportsTableBody');
            if (tbody) tbody.innerHTML = '<tr><td colspan="3" class="text-center text-danger">Failed to load reports.</td></tr>';
        });
}

// Preserve switchTab for employee reports
const originalSwitchTab = window.switchTab;
window.switchTab = function(tabId, element) {
    if (originalSwitchTab) originalSwitchTab(tabId, element);
    if (tabId === 'emp-reports') {
        loadEmployeeReports();
    }
};


