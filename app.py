import cv2
import os
import json
import glob
import csv
import pandas as pd
import numpy as np
from flask import Flask, render_template, url_for, request, redirect, flash, Response, jsonify, session
from datetime import datetime, timedelta
import logging
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect, CSRFError
from flask_talisman import Talisman   # optional, for production
import subprocess
from flask import make_response
# Load environment variables
load_dotenv()

# Import modules
from modules.camera import VideoCamera
from modules.database import db_connection
from modules.trainer import train_faces
train_faces()

# Email imports
from flask_mail import Mail, Message

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'brightpath_hero_key_2026')

from datetime import timedelta
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

# --- CSRF PROTECTION ---
csrf = CSRFProtect()
csrf.init_app(app)

# --- RATE LIMITING ---
limiter = Limiter(key_func=get_remote_address, default_limits=["5000 per day", "500 per hour"])
limiter.init_app(app)

# --- EMAIL CONFIGURATION ---
app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.environ.get('MAIL_USE_TLS', 'True') == 'True'
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME', 'your_email@gmail.com')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD', 'your_app_password')
mail = Mail(app)

# --- CONFIGURATION ---
FACES_FOLDER = 'static/faces'
TRAINER_FILE = 'static/trainer.yml'
USER_MAP_FILE = 'static/user_map.json'
ADMIN_MASTER_KEY = os.environ.get('ADMIN_MASTER_KEY', 'BRIGHTPATH_SUPER_SECRET_2026')
SCHEDULED_TIME_IN = os.environ.get('SCHEDULED_TIME_IN', '08:00:00')
SCHEDULED_TIME_OUT = os.environ.get('SCHEDULED_TIME_OUT', '17:00:00')

UPLOAD_FOLDER = 'static/profile_pics'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

for folder in [FACES_FOLDER, UPLOAD_FOLDER]:
    if not os.path.exists(folder):
        os.makedirs(folder)

video_camera = None
face_attempts = {}  # key: ip_address, value: {'count': int, 'lock_until': datetime}

# ========== NOTIFICATION SYSTEM ==========
def init_notifications_table():
    conn = db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            message TEXT NOT NULL,
            link VARCHAR(255) DEFAULT NULL,
            is_read BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    conn.commit()
    conn.close()

def create_notification(user_id, message, link=None):
    try:
        conn = db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO notifications (user_id, message, link) VALUES (%s, %s, %s)",
            (user_id, message, link)
        )
        conn.commit()
        conn.close()
        logging.info(f"Notification created for user {user_id}: {message[:50]}")
    except Exception as e:
        logging.error(f"Failed to create notification: {e}")

init_notifications_table()

# ========== GENERATED REPORTS TABLE ==========
def init_reports_table():
    conn = db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS generated_reports (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            report_type VARCHAR(50) NOT NULL,
            title VARCHAR(255) NOT NULL,
            params TEXT,
            url VARCHAR(500),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    conn.commit()
    conn.close()

init_reports_table()

# ========== AUDIT LOGS TABLE ==========
def init_audit_table():
    conn = db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT,
            action VARCHAR(255) NOT NULL,
            details TEXT,
            ip_address VARCHAR(45),
            user_agent TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
        )
    """)
    conn.commit()
    conn.close()

init_audit_table()

# ========== FINANCE TABLES (LOANS, CASH ADVANCES) ==========
def init_finance_tables():
    conn = db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cash_advances (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            amount DECIMAL(10,2) NOT NULL,
            repayment_months INT DEFAULT 0,
            remaining_balance DECIMAL(10,2) DEFAULT 0,
            status ENUM('pending','approved','paid') DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS loan_requests (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            amount DECIMAL(10,2) NOT NULL,
            purpose TEXT,
            months_to_pay INT NOT NULL,
            status ENUM('pending','approved','rejected') DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS loans (
            id INT AUTO_INCREMENT PRIMARY KEY,
            employee_id INT NOT NULL,
            loan_date DATE,
            amount_taken DECIMAL(10,2),
            interest_amount DECIMAL(10,2),
            months_to_pay INT,
            balance_amount DECIMAL(10,2),
            remaining_months INT,
            FOREIGN KEY (employee_id) REFERENCES users(id)
        )
    """)
    conn.commit()
    conn.close()

init_finance_tables()

# ========== OVERTIME REQUESTS TABLE ==========
def init_overtime_table():
    conn = db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS overtime_requests (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            overtime_date DATE NOT NULL,
            hours DECIMAL(5,2) NOT NULL,
            reason TEXT,
            status ENUM('Pending','Approved','Rejected') DEFAULT 'Pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_overtime_table()

def log_audit(user_id, action, details=None, req=None):
    try:
        ip = req.remote_addr if req else None
        ua = req.headers.get('User-Agent') if req else None
        conn = db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO audit_logs (user_id, action, details, ip_address, user_agent) VALUES (%s, %s, %s, %s, %s)",
            (user_id, action, details, ip, ua)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Audit log failed: {e}")

def get_camera():
    global video_camera
    if video_camera is None:
        try:
            video_camera = VideoCamera()
            logging.info("Camera started successfully.")
        except Exception as e:
            logging.error(f"Camera Initialization Error: {e}")
            return None
    return video_camera

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def send_email_notification(recipient, subject, body):
    try:
        msg = Message(subject, sender=app.config['MAIL_USERNAME'], recipients=[recipient])
        msg.body = body
        mail.send(msg)
        logging.info(f"Email sent to {recipient}")
        return True
    except Exception as e:
        logging.error(f"Email failed: {e}")
        return False

# ----------------------------------------------------------------------
# Attendance helpers
# ----------------------------------------------------------------------
def log_attendance(user_id):
    today = datetime.now().strftime('%Y-%m-%d')
    now_time = datetime.now().strftime('%H:%M:%S')
    scheduled_in = SCHEDULED_TIME_IN
    conn = None
    try:
        conn = db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM attendance WHERE user_id = %s AND log_date = %s AND time_out IS NULL", (user_id, today))
        existing = cursor.fetchone()
        if not existing:
            sched_dt = datetime.strptime(scheduled_in, '%H:%M:%S')
            actual_dt = datetime.strptime(now_time, '%H:%M:%S')
            minutes_late = max(0, (actual_dt - sched_dt).seconds // 60)
            status = "On Time" if minutes_late == 0 else "Late"
            cursor.execute(
                "INSERT INTO attendance (user_id, log_date, time_in, status, minutes_late) VALUES (%s, %s, %s, %s, %s)",
                (user_id, today, now_time, status, minutes_late)
            )
            conn.commit()
            return True, f"Clocked in at {now_time} ({status})" + (f" +{minutes_late} min late" if minutes_late else "")
        else:
            return False, "Already clocked in today"
    except Exception as e:
        logging.error(f"Attendance DB Error: {e}")
        return False, f"Database error: {str(e)}"
    finally:
        if conn: conn.close()

def clock_out_user(user_id):
    today = datetime.now().strftime('%Y-%m-%d')
    now_time = datetime.now().strftime('%H:%M:%S')
    scheduled_out = SCHEDULED_TIME_OUT
    conn = None
    try:
        conn = db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id FROM attendance WHERE user_id = %s AND log_date = %s AND time_out IS NULL", (user_id, today))
        att = cursor.fetchone()
        if att:
            sched_dt = datetime.strptime(scheduled_out, '%H:%M:%S')
            actual_dt = datetime.strptime(now_time, '%H:%M:%S')
            minutes_undertime = max(0, (sched_dt - actual_dt).seconds // 60)
            cursor.execute("UPDATE attendance SET time_out = %s, undertime_minutes = %s WHERE id = %s", (now_time, minutes_undertime, att['id']))
            conn.commit()
            return True, f"Clocked out at {now_time}" + (f" (undertime {minutes_undertime} min)" if minutes_undertime else "")
        else:
            return False, "No active clock-in found"
    except Exception as e:
        return False, f"Error: {e}"
    finally:
        if conn: conn.close()

# ----------------------------------------------------------------------
# Payroll helpers
# ----------------------------------------------------------------------
def get_contribution_rate(rate_type):
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT rate_value, cap_amount FROM contribution_rates WHERE rate_type=%s", (rate_type,))
    row = cursor.fetchone()
    conn.close()
    if row:
        rate_val = float(row['rate_value'])
        cap_val = float(row['cap_amount']) if row['cap_amount'] is not None else None
        return rate_val, cap_val
    return 0.0, None

# ========== ACCURATE STATUTORY CONTRIBUTIONS (Philippine Tables 2024) ==========
def compute_sss_contribution(monthly_basic):
    """SSS Employee Share based on 2024 schedule."""
    sss_table = [
        (0, 3250, 135.0),
        (3250.01, 3750, 157.5),
        (3750.01, 4250, 180.0),
        # … (kumpletong listahan) …
        (19750.01, 20250, 900.0),
    ]
    for low, high, amount in sss_table:
        if low <= monthly_basic <= high:
            return amount
    return 900.0   # max for 20250+

def compute_philhealth_contribution(monthly_basic):
    """PhilHealth Employee Share: 2.5% of monthly basic, max ₱125."""
    return min(monthly_basic * 0.025, 125.0)

def compute_pagibig_contribution(monthly_basic):
    """Pag-IBIG Employee Share: 2% of monthly basic, max ₱100."""
    return min(monthly_basic * 0.02, 100.0)

def compute_withholding_tax(monthly_taxable):
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM tax_brackets WHERE min_income <= %s AND (max_income >= %s OR max_income IS NULL) ORDER BY min_income LIMIT 1", (monthly_taxable, monthly_taxable))
    bracket = cursor.fetchone()
    conn.close()
    if bracket:
        min_inc = float(bracket['min_income'])
        base_tax = float(bracket['base_tax'])
        rate_over = float(bracket['rate_over'])
        excess = float(monthly_taxable) - min_inc
        tax = base_tax + (excess * rate_over)
        return tax
    return 0.0

def is_holiday(date_str, conn):
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT is_regular FROM holidays WHERE holiday_date = %s", (date_str,))
    row = cursor.fetchone()
    if row:
        return 'regular' if row['is_regular'] else 'special'
    return None

def compute_holiday_pay(hourly_rate, hours_worked, holiday_type):
    if holiday_type == 'regular':
        return hours_worked * hourly_rate * 2.0
    else:
        return hours_worked * hourly_rate * 1.3

def get_approved_overtime_hours(user_id, cutoff_start, cutoff_end, conn):
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT SUM(hours) as total_hours
        FROM overtime_requests
        WHERE user_id = %s AND status = 'Approved'
        AND overtime_date BETWEEN %s AND %s
    """, (user_id, cutoff_start, cutoff_end))
    result = cursor.fetchone()
    return result['total_hours'] or 0

def compute_payroll_for_employee(user_id, cutoff_start, cutoff_end, payroll_date, status='draft'):
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # 1. Daily rate (default 500)
    cursor.execute("SELECT COALESCE(daily_rate, 500) as daily_rate FROM users WHERE id=%s", (user_id,))
    emp = cursor.fetchone()
    daily_rate = float(emp['daily_rate']) if emp else 500.0
    hourly_rate = daily_rate / 8
    
    # 2. Attendance summary
    cursor.execute("""
        SELECT COALESCE(COUNT(*), 0) as days_present,
               COALESCE(SUM(minutes_late), 0) as total_late,
               COALESCE(SUM(undertime_minutes), 0) as total_undertime
        FROM attendance
        WHERE user_id=%s AND log_date BETWEEN %s AND %s AND time_in IS NOT NULL
    """, (user_id, cutoff_start, cutoff_end))
    att = cursor.fetchone()
    days_present = int(att['days_present'] or 0)
    late_minutes = float(att['total_late'] or 0)
    undertime_minutes = float(att['total_undertime'] or 0)
    
    # 3. Holiday pay
    holiday_pay = 0.0
    current_date = datetime.strptime(cutoff_start, '%Y-%m-%d')
    end_date = datetime.strptime(cutoff_end, '%Y-%m-%d')
    while current_date <= end_date:
        date_str = current_date.strftime('%Y-%m-%d')
        holiday_type = is_holiday(date_str, conn)
        if holiday_type:
            cursor.execute("SELECT time_in FROM attendance WHERE user_id=%s AND log_date=%s", (user_id, date_str))
            if cursor.fetchone():
                holiday_pay += compute_holiday_pay(hourly_rate, 8, holiday_type)
        current_date += timedelta(days=1)
    
    # 4. Overtime
    overtime_hours = float(get_approved_overtime_hours(user_id, cutoff_start, cutoff_end, conn) or 0)
    overtime_pay = overtime_hours * hourly_rate * 1.25
    
    basic_pay = days_present * daily_rate
    tardiness_deduction = (late_minutes / 60) * hourly_rate
    undertime_deduction = (undertime_minutes / 60) * hourly_rate
    gross_pay = basic_pay + overtime_pay + holiday_pay

    # 5. 13th month pay
    thirteenth_month = 0
    cutoff_start_date = datetime.strptime(cutoff_start, '%Y-%m-%d')
    if cutoff_start_date.month == 12:
        year = cutoff_start_date.year
        cursor.execute("""
            SELECT COALESCE(SUM(basic_pay), 0) as total_basic
            FROM payroll
            WHERE user_id = %s AND YEAR(date_paid) = %s AND status = 'published'
        """, (user_id, year))
        ytd_basic = cursor.fetchone()['total_basic']
        ytd_basic += basic_pay
        thirteenth_month = ytd_basic / 12
    
    # 6. Cash advance deduction (convert to float)
    cash_advance_deduction = 0.0
    cursor.execute("""
        SELECT id, amount, repayment_months, remaining_balance
        FROM cash_advances
        WHERE user_id = %s AND status = 'approved' AND remaining_balance > 0
        ORDER BY id LIMIT 1
    """, (user_id,))
    ca = cursor.fetchone()
    if ca:
        if ca['repayment_months'] == 0:
            cash_advance_deduction = float(ca['remaining_balance'] or 0)
            if status == 'published':
                cursor.execute("UPDATE cash_advances SET remaining_balance = 0, status = 'paid' WHERE id = %s", (ca['id'],))
        else:
            monthly_deduction = float(ca['amount'] or 0) / float(ca['repayment_months'])
            cash_advance_deduction = monthly_deduction
            if status == 'published':
                new_balance = float(ca['remaining_balance'] or 0) - monthly_deduction
                new_status = 'paid' if new_balance <= 0 else 'approved'
                cursor.execute("UPDATE cash_advances SET remaining_balance = %s, status = %s WHERE id = %s", (new_balance, new_status, ca['id']))

    # 7. SSS, PhilHealth, Pag-IBIG at withholding tax (convert to float)
    if gross_pay <= 0:
        gross_pay = 0
        sss = philhealth = pagibig = withholding_tax = tardiness_deduction = undertime_deduction = 0
        total_deductions = 0
        net_pay = 0
    else:
        monthly_basis = days_present * daily_rate
        sss = float(compute_sss_contribution(monthly_basis) or 0)
        philhealth = float(compute_philhealth_contribution(monthly_basis) or 0)
        pagibig = float(compute_pagibig_contribution(monthly_basis) or 0)
        taxable_income = gross_pay - (sss + philhealth + pagibig)
        withholding_tax = float(compute_withholding_tax(taxable_income) or 0)
        total_deductions = (sss + philhealth + pagibig + withholding_tax +
                            tardiness_deduction + undertime_deduction)
        net_pay = gross_pay - total_deductions
        net_pay = max(0, net_pay)
    
    cash_advance_deduction = float(cash_advance_deduction or 0)
    net_pay = net_pay - cash_advance_deduction
    net_pay = max(0, net_pay)
    
    cutoff_period = f"{cutoff_start} to {cutoff_end}"
    
    cursor.execute("""
        INSERT INTO payroll 
        (user_id, cutoff_period, total_days_worked, basic_pay, overtime_pay, holiday_pay,
         gross_pay, net_pay, date_paid, sss, philhealth, pagibig, late_deduction,
         tardiness_deduction, undertime_deduction, withholding_tax, status,
         thirteenth_month, cash_advance_deduction)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (user_id, cutoff_period, days_present, basic_pay, overtime_pay, holiday_pay,
          gross_pay, net_pay, payroll_date, sss, philhealth, pagibig,
          tardiness_deduction + undertime_deduction, tardiness_deduction, undertime_deduction,
          withholding_tax, status, thirteenth_month, cash_advance_deduction))
    
    conn.commit()
    conn.close()
    
    if status == 'published':
        create_notification(user_id, f"Your payroll for {cutoff_start} to {cutoff_end} has been generated. Net pay: ₱{net_pay:,.2f}", url_for('employee_dashboard') + "#emp-payroll")
    return True
    
# ========== POSITION RATE MAPPING ==========
def get_daily_rate_by_position(position):
    position_rate_map = {
        'Sales and Marketing Staff': 550,
        'Operations and Delivery Staff': 520,
        'HR Officer': 600,
        'Finance Officer': 650,
        'Admin Staff': 500,
        'General Manager': 800,
        'Delivery Driver': 480,
        'Warehouse Staff': 470,
        'Staff': 500  # default
    }
    return position_rate_map.get(position, 500)

# =============================================================================
# AUTHENTICATION & ACCESS CONTROL
# =============================================================================
@limiter.exempt
@app.route('/')
def index():
    if session.get('logged_in'):
        if session.get('role') == 'admin':
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('employee_dashboard'))
    return render_template('auth/login.html')

@app.route('/login_manual_action', methods=['POST'])
@limiter.limit("5 per minute")
def login_manual_action():
    email = request.form.get('email')
    password = request.form.get('password')
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE email=%s AND role='employee' AND status='active'", (email,))
    user = cursor.fetchone()
    conn.close()
    if user and check_password_hash(user['password'], password):
        session.update({'logged_in': True, 'user_id': user['id'], 'name': user['name'], 'role': 'employee'})
        session.permanent = True
        log_audit(user['id'], "LOGIN_SUCCESS", f"Employee {email} logged in", request)
        return redirect(url_for('employee_dashboard'))
    log_audit(None, "LOGIN_FAILED", f"Failed login for {email}", request)
    flash("Invalid Employee Credentials.")
    return redirect(url_for('index'))

@app.route('/admin/login_action', methods=['POST'])
@limiter.limit("5 per minute")
def admin_login_action():
    email = request.form.get('email')
    password = request.form.get('password')
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE email=%s AND role='admin'", (email,))
    admin = cursor.fetchone()
    conn.close()
    if admin and check_password_hash(admin['password'], password):
        session.update({'logged_in': True, 'user_id': admin['id'], 'name': admin['name'], 'role': 'admin'})
        session.permanent = True
        log_audit(admin['id'], "ADMIN_LOGIN", f"Admin {email} logged in", request)
        return redirect(url_for('admin_dashboard'))
    log_audit(None, "ADMIN_LOGIN_FAILED", f"Failed admin login for {email}", request)
    flash("Unauthorized: Invalid Admin Credentials.")
    return redirect(url_for('admin_login_page'))

@app.route('/logout')
def logout():
    global video_camera
    role_param = request.args.get('role')
    if role_param == 'admin':
        redirect_url = url_for('admin_login_page')
    elif role_param == 'employee':
        redirect_url = url_for('index')
    else:
        role = session.get('role')
        if role == 'admin':
            redirect_url = url_for('admin_login_page')
        else:
            redirect_url = url_for('index')
    
    if video_camera:
        video_camera.stop()
        video_camera = None
    
    session.clear()
    flash("Successfully logged out.")
    return redirect(redirect_url)

# =============================================================================
# ADMIN & EMPLOYEE PAGES
# =============================================================================
@app.route('/brightpath-admin-portal-2026')
def admin_login_page():
    return render_template('auth/admin_login.html')

@app.route('/brightpath-admin-registration-2026', methods=['GET', 'POST'])
def secret_admin_signup():
    if request.method == 'POST':
        full_name = request.form.get('full_name')
        email = request.form.get('email')
        password = request.form.get('password')
        admin_key = request.form.get('admin_key')
        if admin_key != ADMIN_MASTER_KEY:
            flash("Invalid Master Key!")
            return redirect(url_for('secret_admin_signup'))
        hashed_password = generate_password_hash(password)
        conn = db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (name, email, password, role, daily_rate) VALUES (%s, %s, %s, 'admin', 0)",
                       (full_name, email, hashed_password))
        conn.commit()
        conn.close()
        flash("New Admin onboarded.")
        return redirect(url_for('admin_login_page'))
    return render_template('auth/admin_signup.html')

@app.route('/employee/signup')
def employee_signup():
    return render_template('auth/signup.html')

# ----------------------------------------------------------------------
# FACE CAPTURE & REGISTRATION
# ----------------------------------------------------------------------
def cleanup_temp_faces():
    temp_files = glob.glob(os.path.join(FACES_FOLDER, "User.temp.*.jpg"))
    for f in temp_files:
        try:
            os.remove(f)
        except:
            pass

@app.route('/capture_frame', methods=['POST'])
@limiter.limit("100 per minute")
def capture_frame():
    data = request.get_json()
    if not data or 'count' not in data:
        return jsonify({"status": "error", "message": "Missing count"}), 400
    count = data['count']
    cam = get_camera()
    if cam is None:
        return jsonify({"status": "error", "message": "Camera not ready"}), 500

    if count == 1:
        cleanup_temp_faces()

    # Use the dedicated face capture method
    success, face_img = cam.get_face_for_capture()
    if not success or face_img is None:
        return jsonify({"status": "error", "message": "No face detected"}), 400
    
    if not os.path.exists(FACES_FOLDER):
        os.makedirs(FACES_FOLDER)
    temp_path = os.path.join(FACES_FOLDER, f"User.temp.{count}.jpg")
    cv2.imwrite(temp_path, face_img)
    return jsonify({"status": "success", "message": f"Frame {count} captured"})

@app.route('/register_employee_action', methods=['POST'])
def register_employee_action():
    full_name = request.form.get('full_name')
    email = request.form.get('email')
    password = request.form.get('password')
    if not full_name or not email or not password:
        flash("All fields required!")
        return redirect(url_for('employee_signup'))
    conn = db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE email=%s", (email,))
    if cursor.fetchone():
        flash("Email already registered!")
        conn.close()
        return redirect(url_for('employee_signup'))
    hashed_password = generate_password_hash(password)
    cursor.execute("""INSERT INTO users (name, email, password, role, daily_rate, leave_credits, profile_pic) 
                      VALUES (%s, %s, %s, 'employee', 500, 15.0, 'default_profile.png')""",
                   (full_name, email, hashed_password))
    conn.commit()
    new_id = cursor.lastrowid
    create_notification(new_id, f"Welcome to BrightPath, {full_name}! Your account has been created. Please complete your profile.", url_for('employee_profile_update'))
    temp_files = glob.glob(os.path.join(FACES_FOLDER, "User.temp.*.jpg"))
    for temp_path in temp_files:
        filename = os.path.basename(temp_path)
        parts = filename.split('.')
        if len(parts) >= 3:
            count_num = parts[2]
            new_name = f"{new_id}.{full_name.replace(' ', '_')}.{count_num}.jpg"
            os.rename(temp_path, os.path.join(FACES_FOLDER, new_name))
    try:
        train_faces()
    except Exception as e:
        logging.error(f"Training error: {e}")
    conn.close()
    flash(f"Welcome, {full_name}! Registration complete.")
    return redirect(url_for('index'))

@app.route('/employee/manual_signup')
def employee_manual_signup_page():
    return render_template('auth/manual_signup.html')

@app.route('/employee/register_manual', methods=['POST'])
def employee_manual_register():
    full_name = request.form.get('full_name')
    email = request.form.get('email')
    password = request.form.get('password')
    position = request.form.get('position', 'Staff')
    daily_rate = request.form.get('daily_rate', 500)
    
    if not full_name or not email or not password:
        flash("All fields are required!")
        return redirect(url_for('employee_manual_signup_page'))
    
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
    if cursor.fetchone():
        flash("Email already registered. Please use a different email.")
        conn.close()
        return redirect(url_for('employee_manual_signup_page'))
    hashed_password = generate_password_hash(password)
    cursor.execute("""
        INSERT INTO users (name, email, password, role, position, daily_rate, leave_credits, profile_pic)
        VALUES (%s, %s, %s, 'employee', %s, %s, 15.0, 'default_profile.png')
    """, (full_name, email, hashed_password, position, daily_rate))
    conn.commit()
    new_id = cursor.lastrowid
    create_notification(new_id, f"Welcome to BrightPath, {full_name}! Your account has been created. Please complete your profile.", url_for('employee_profile_update'))
    conn.close()
    flash(f"Employee {full_name} registered successfully! You can now login manually.")
    return redirect(url_for('index'))

# =============================================================================
# DASHBOARDS
# =============================================================================
@app.route('/admin/dashboard')
def admin_dashboard():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('admin_login_page'))
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, name, email, position, daily_rate, status FROM users WHERE role='employee' ORDER BY name")
    all_employees = cursor.fetchall()
    today_str = datetime.now().strftime('%Y-%m-%d')
    
    cursor.execute("""
        SELECT COUNT(DISTINCT a.user_id) as cnt
        FROM attendance a
        JOIN users u ON a.user_id = u.id
        WHERE a.log_date = %s AND a.time_in IS NOT NULL AND a.time_out IS NULL AND u.role = 'employee'
    """, (today_str,))
    active_today = cursor.fetchone()['cnt']
    
    cursor.execute("""
        SELECT COUNT(DISTINCT a.user_id) as cnt
        FROM attendance a
        JOIN users u ON a.user_id = u.id
        WHERE a.log_date = %s AND a.status = 'Late' AND u.role = 'employee'
    """, (today_str,))
    late_today = cursor.fetchone()['cnt']
    
    cursor.execute("""
        SELECT u.name, a.time_in, a.time_out, a.status 
        FROM users u LEFT JOIN attendance a ON u.id = a.user_id AND a.log_date=%s
        WHERE u.role='employee' 
        ORDER BY a.time_in IS NULL, a.time_in DESC
    """, (today_str,))
    attendance = cursor.fetchall()
    
    cursor.execute("SELECT l.*, u.name FROM leave_requests l JOIN users u ON l.user_id=u.id WHERE l.status='Pending'")
    leaves = cursor.fetchall()
    
    cursor.execute("SELECT p.*, u.name as employee_name FROM payroll p JOIN users u ON p.user_id=u.id ORDER BY p.date_paid DESC LIMIT 50")
    payroll_records = cursor.fetchall()
    # Convert Decimal to float for template
    for p in payroll_records:
        p['net_pay'] = float(p['net_pay']) if p['net_pay'] else 0.0
    
    cursor.execute("SELECT COUNT(*) as cnt FROM leave_requests WHERE status = 'Pending'")
    pending_leaves = cursor.fetchone()['cnt']
    
    cursor.execute("SELECT COUNT(*) as cnt FROM overtime_requests WHERE status = 'Pending'")
    pending_overtime = cursor.fetchone()['cnt']
    
    cursor.execute("SELECT COUNT(*) as cnt FROM cash_advances WHERE status = 'pending'")
    pending_ca = cursor.fetchone()['cnt']
    
    conn.close()
    
    return render_template('admin/dashboard.html', 
                           all_employees=all_employees, 
                           attendance=attendance,
                           leaves=leaves, 
                           payroll_records=payroll_records, 
                           active_today=active_today,
                           late_today=late_today, 
                           current_date=today_str,
                           pending_leaves=pending_leaves,
                           pending_overtime=pending_overtime,
                           pending_ca=pending_ca)

@app.route('/admin/employee-directory')
def employee_directory():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('admin_login_page'))
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE role='employee'")
    employees = cursor.fetchall()
    conn.close()
    return render_template('admin/employee_directory.html', all_employees=employees)

@app.route('/employee/dashboard')
def employee_dashboard():
    if not session.get('logged_in') or session.get('role') != 'employee':
        return redirect(url_for('index'))
    user_id = session['user_id']
    today = datetime.now().strftime('%Y-%m-%d')
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # User info
    cursor.execute("SELECT * FROM users WHERE id=%s", (user_id,))
    user_info = cursor.fetchone()
    
    # Current duty status
    cursor.execute("SELECT * FROM attendance WHERE user_id=%s AND log_date=%s ORDER BY id DESC LIMIT 1", (user_id, today))
    last_log = cursor.fetchone()
    clock_status = "On Duty" if last_log and last_log['time_in'] and not last_log['time_out'] else "Clocked Out"
    status_color = "primary" if clock_status == "On Duty" else "dark"
    
    # Days worked this month
    current_month = datetime.now().month
    current_year = datetime.now().year
    cursor.execute("""
        SELECT COUNT(DISTINCT log_date) as days_worked 
        FROM attendance 
        WHERE user_id=%s AND MONTH(log_date)=%s AND YEAR(log_date)=%s AND time_in IS NOT NULL
    """, (user_id, current_month, current_year))
    days_worked = cursor.fetchone()['days_worked'] or 0
    
    # Payroll history
    cursor.execute("SELECT * FROM payroll WHERE user_id=%s ORDER BY date_paid DESC", (user_id,))
    payroll_history = cursor.fetchall()
    for pay in payroll_history:
        pay['deductions'] = float(pay.get('sss',0)+pay.get('philhealth',0)+pay.get('pagibig',0)+pay.get('late_deduction',0))
    last_net_pay = float(payroll_history[0]['net_pay']) if payroll_history else 0.0
    
    # Attendance history (with computed status)
    cursor.execute("""
        SELECT 
            log_date,
            time_in,
            time_out,
            minutes_late,
            undertime_minutes,
            CASE 
                WHEN time_in IS NULL THEN 'Absent'
                WHEN minutes_late > 0 THEN 'Late'
                WHEN undertime_minutes > 0 THEN 'Undertime'
                ELSE 'On Time'
            END as status
        FROM attendance
        WHERE user_id = %s
        ORDER BY log_date DESC, id DESC
        LIMIT 10
    """, (user_id,))
    attendance_history = cursor.fetchall()
    
    # Leave requests
    cursor.execute("""
        SELECT id, leave_type, start_date, end_date, status, reason, created_at
        FROM leave_requests
        WHERE user_id = %s
        ORDER BY created_at DESC
        LIMIT 5
    """, (user_id,))
    leave_requests = cursor.fetchall()
    
    # Overtime requests
    cursor.execute("""
        SELECT id, overtime_date, hours, reason, status
        FROM overtime_requests
        WHERE user_id = %s
        ORDER BY created_at DESC
        LIMIT 5
    """, (user_id,))
    overtime_requests = cursor.fetchall()
    
    # Weekly summary
    weekly_summary = []
    today_dt = datetime.now()
    for i in range(4):
        week_start = today_dt - timedelta(days=today_dt.weekday() + 7*i)
        week_end = week_start + timedelta(days=6)
        cursor.execute("""
            SELECT 
                COUNT(*) as days_present,
                COALESCE(SUM(TIMESTAMPDIFF(MINUTE, time_in, time_out)), 0) as total_minutes,
                COALESCE(SUM(minutes_late), 0) as total_late,
                COALESCE(SUM(undertime_minutes), 0) as total_undertime
            FROM attendance
            WHERE user_id = %s 
                AND log_date BETWEEN %s AND %s
                AND time_in IS NOT NULL
                AND time_out IS NOT NULL
        """, (user_id, week_start.strftime('%Y-%m-%d'), week_end.strftime('%Y-%m-%d')))
        row = cursor.fetchone()
        total_minutes = row['total_minutes'] if row['total_minutes'] else 0
        total_hours = total_minutes / 60
        weekly_summary.append({
            'week_range': f"{week_start.strftime('%b %d')} - {week_end.strftime('%b %d')}",
            'days_present': row['days_present'] or 0,
            'total_hours': f"{total_hours:.1f}",
            'total_late': row['total_late'] or 0,
            'total_undertime': row['total_undertime'] or 0
        })
    
    # Cash advances and loans
    cursor.execute("SELECT * FROM cash_advances WHERE user_id = %s ORDER BY created_at DESC", (user_id,))
    cash_advances = cursor.fetchall()
    cursor.execute("SELECT * FROM loan_requests WHERE user_id = %s ORDER BY created_at DESC", (user_id,))
    loan_requests = cursor.fetchall()
    
    conn.close()
    
    return render_template('employee/dashboard.html',
                           employee_name=session['name'],
                           clock_status=clock_status,
                           status_color=status_color,
                           leave_credits=user_info['leave_credits'],
                           profile_pic=user_info['profile_pic'],
                           user_email=user_info['email'],
                           user_position=user_info['position'],
                           user_contact=user_info['contact_number'],
                           user_address=user_info['address'],
                           last_net_pay=last_net_pay,
                           days_worked=days_worked,
                           attendance_history=attendance_history,
                           payroll_history=payroll_history,
                           leave_requests=leave_requests,
                           overtime_requests=overtime_requests,
                           weekly_summary=weekly_summary,
                           cash_advances=cash_advances,
                           loan_requests=loan_requests)

@app.route('/admin/employees')
def admin_employees_page():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('admin_login_page'))

    conn = db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT id, name, email, position, daily_rate, status FROM users WHERE role='employee' ORDER BY name")
    all_employees = cursor.fetchall()

    # Fetch distinct positions for filter AND edit modal
    cursor.execute("SELECT DISTINCT position FROM users WHERE role='employee' AND position IS NOT NULL AND position != '' ORDER BY position")
    positions = [row['position'] for row in cursor.fetchall()]
    if not positions:
        positions = [
            'Sales and Marketing Staff', 'Operations and Delivery Staff', 'HR',
            'Finance Officer','General Manager', 'Delivery Driver', 'Warehouse Staff'
        ]
    conn.close()

    return render_template('admin/employees.html', all_employees=all_employees, positions=positions)

@app.route('/admin/payroll')
def admin_payroll_page():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('admin_login_page'))
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, name, position, daily_rate FROM users WHERE role='employee' ORDER BY name")
    all_employees = cursor.fetchall()
    conn.close()
    return render_template('admin/payroll.html', all_employees=all_employees)

@app.route('/admin/leaves')
def admin_leaves_page():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('admin_login_page'))
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT l.*, u.name FROM leave_requests l JOIN users u ON l.user_id=u.id WHERE l.status='Pending'")
    leaves = cursor.fetchall()
    conn.close()
    return render_template('admin/leaves.html', leaves=leaves)

@app.route('/admin/reports')
def admin_reports_page():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('admin_login_page'))
    return render_template('admin/reports_dashboard.html')

@app.route('/admin/generated_reports')
def admin_generated_reports_page():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('admin_login_page'))
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT gr.*, u.name as employee_name
        FROM generated_reports gr
        JOIN users u ON gr.user_id = u.id
        ORDER BY gr.created_at DESC
    """)
    reports = cursor.fetchall()
    conn.close()
    return render_template('admin/generated_reports_list.html', reports=reports)

# =============================================================================
# PROFILE & LEAVES
# =============================================================================
@app.route('/employee/profile/update', methods=['POST'])
def employee_profile_update():
    if 'user_id' not in session or session.get('role') != 'employee':
        flash("Unauthorized access.")
        return redirect(url_for('index'))
    
    user_id = session['user_id']
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    
    new_position = request.form.get('position')
    contact = request.form.get('contact_number')
    address = request.form.get('address')
    file = request.files.get('profile_pic')
    
    new_rate = get_daily_rate_by_position(new_position)
    
    if file and file.filename and allowed_file(file.filename):
        filename = secure_filename(f"user_{user_id}_{file.filename}")
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        cursor.execute("UPDATE users SET profile_pic=%s WHERE id=%s", (filename, user_id))
    
    try:
        cursor.execute("UPDATE users SET position=%s, daily_rate=%s, contact_number=%s, address=%s WHERE id=%s",
                       (new_position, new_rate, contact, address, user_id))
        conn.commit()
        flash("Profile updated successfully!", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error updating profile: {e}", "danger")
    finally:
        conn.close()
    
    return redirect(url_for('employee_dashboard') + '#emp-profile')

@app.route('/file_leave', methods=['POST'])
def file_leave():
    if 'user_id' not in session or session.get('role') != 'employee':
        flash("Unauthorized access.")
        return redirect(url_for('index'))
    leave_type = request.form.get('leave_type')
    start = request.form.get('start_date')
    end = request.form.get('end_date')
    reason = request.form.get('reason')
    conn = db_connection()
    cursor = conn.cursor()
    cursor.execute("""INSERT INTO leave_requests (user_id, leave_type, start_date, end_date, reason, status)
                      VALUES (%s, %s, %s, %s, %s, 'Pending')""",
                   (session['user_id'], leave_type, start, end, reason))
    conn.commit()
    conn.close()
    flash("Leave request submitted.")
    return redirect(url_for('employee_dashboard'))

# =============================================================================
# PAYROLL ROUTES
# =============================================================================
@app.route('/admin/payroll/preview_all')
def admin_payroll_preview_all():
    if not session.get('logged_in') or session.get('role') != 'admin':
        flash("Unauthorized")
        return redirect(url_for('admin_login_page'))
    
    cutoff_start = request.args.get('cutoff_start')
    cutoff_end = request.args.get('cutoff_end')
    payroll_date = request.args.get('payroll_date')
    position_filter = request.args.get('position', 'all')
    search_term = request.args.get('search', '').strip()
    employees_param = request.args.get('employees', 'all')
    
    if not cutoff_start or not cutoff_end or not payroll_date:
        flash("Missing dates")
        return redirect(url_for('admin_dashboard') + '#payroll-tab')
    
    if datetime.strptime(cutoff_start, '%Y-%m-%d') > datetime.strptime(cutoff_end, '%Y-%m-%d'):
        flash("Cutoff start must be earlier than cutoff end.")
        return redirect(url_for('admin_dashboard') + '#payroll-tab')
    
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    
    if employees_param != 'all':
        emp_ids = [int(x) for x in employees_param.split(',') if x.isdigit()]
        if emp_ids:
            placeholders = ','.join(['%s'] * len(emp_ids))
            query = f"SELECT id, name, position, daily_rate FROM users WHERE role='employee' AND id IN ({placeholders}) ORDER BY name"
            cursor.execute(query, emp_ids)
            employees = cursor.fetchall()
        else:
            employees = []
    else:
        query = "SELECT id, name, position, daily_rate FROM users WHERE role='employee'"
        params = []
        if position_filter != 'all':
            query += " AND position = %s"
            params.append(position_filter)
        if search_term:
            query += " AND (name LIKE %s OR id LIKE %s)"
            search_wild = f"%{search_term}%"
            params.append(search_wild)
            params.append(search_wild)
        query += " ORDER BY name"
        cursor.execute(query, params)
        employees = cursor.fetchall()
    
    results = []
    for emp in employees:
        daily_rate = float(emp['daily_rate'] or 500)
        hourly_rate = daily_rate / 8
        cursor.execute("""
            SELECT COUNT(*) as days_present,
                   SUM(minutes_late) as total_late,
                   SUM(undertime_minutes) as total_undertime
            FROM attendance
            WHERE user_id=%s AND log_date BETWEEN %s AND %s AND time_in IS NOT NULL
        """, (emp['id'], cutoff_start, cutoff_end))
        att = cursor.fetchone()
        days_present = att['days_present'] or 0
        late_minutes = att['total_late'] or 0
        undertime_minutes = att['total_undertime'] or 0
        cursor.execute("""
            SELECT SUM(hours) as total_hours
            FROM overtime_requests
            WHERE user_id=%s AND status='Approved' AND overtime_date BETWEEN %s AND %s
        """, (emp['id'], cutoff_start, cutoff_end))
        ot_row = cursor.fetchone()
        overtime_hours = ot_row['total_hours'] or 0
        basic_pay = days_present * daily_rate
        overtime_pay = overtime_hours * hourly_rate * 1.25
        tardiness_deduction = (late_minutes / 60) * hourly_rate
        undertime_deduction = (undertime_minutes / 60) * hourly_rate
        gross_pay = basic_pay + overtime_pay
        sss_percent, sss_cap = get_contribution_rate('sss_percent')
        sss = min(gross_pay * (sss_percent/100), sss_cap or 999999)
        phil_percent, phil_cap = get_contribution_rate('philhealth_percent')
        philhealth = min(gross_pay * (phil_percent/100), phil_cap or 999999)
        pagibig_percent, pagibig_cap = get_contribution_rate('pagibig_percent')
        pagibig = min(gross_pay * (pagibig_percent/100), pagibig_cap or 999999)
        taxable_income = gross_pay - (sss + philhealth + pagibig)
        withholding_tax = compute_withholding_tax(taxable_income)
        total_deductions = sss + philhealth + pagibig + withholding_tax + tardiness_deduction + undertime_deduction
        net_pay = gross_pay - total_deductions
        results.append({
            'id': emp['id'],
            'name': emp['name'],
            'position': emp['position'],
            'days_present': days_present,
            'gross_pay': gross_pay,
            'total_deductions': total_deductions,
            'net_pay': net_pay
        })
    conn.close()
    pos_list = list(set([emp['position'] for emp in employees if emp['position']]))
    return render_template('admin/payroll_preview_all.html',
                           results=results,
                           cutoff_start=cutoff_start,
                           cutoff_end=cutoff_end,
                           payroll_date=payroll_date,
                           position_filter=position_filter,
                           position_list=pos_list)

@app.route('/admin/payroll/generate_all', methods=['POST'])
@csrf.exempt
def admin_payroll_generate_all():
    if not session.get('logged_in') or session.get('role') != 'admin':
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({"success": False, "message": "Unauthorized"}), 403
        return redirect(url_for('admin_login_page'))
    
    cutoff_start = request.form.get('cutoff_start')
    cutoff_end = request.form.get('cutoff_end')
    payroll_date = request.form.get('payroll_date')
    position_filter = request.form.get('position', 'all')
    payroll_status = request.form.get('status', 'draft')
    employees_param = request.form.get('employees', '')
    
    # Check for AJAX request
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    
    # Validation
    if not cutoff_start or not cutoff_end or not payroll_date:
        msg = "Please provide cutoff dates and payroll date."
        if is_ajax:
            return jsonify({"success": False, "message": msg}), 400
        flash(msg)
        return redirect(url_for('admin_dashboard'))
    
    if datetime.strptime(cutoff_start, '%Y-%m-%d') > datetime.strptime(cutoff_end, '%Y-%m-%d'):
        msg = "Cutoff start date must be earlier than cutoff end date."
        if is_ajax:
            return jsonify({"success": False, "message": msg}), 400
        flash(msg)
        return redirect(url_for('admin_dashboard'))
    
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    
    if employees_param:
        emp_ids = [int(x) for x in employees_param.split(',') if x.isdigit()]
        if emp_ids:
            placeholders = ','.join(['%s'] * len(emp_ids))
            query = f"SELECT id, email, name FROM users WHERE role='employee' AND id IN ({placeholders})"
            cursor.execute(query, emp_ids)
            employees = cursor.fetchall()
        else:
            employees = []
    else:
        if position_filter and position_filter != 'all':
            cursor.execute("SELECT id, email, name FROM users WHERE role='employee' AND position=%s", (position_filter,))
        else:
            cursor.execute("SELECT id, email, name FROM users WHERE role='employee'")
        employees = cursor.fetchall()
    
    success = 0
    errors = []
    for emp in employees:
        try:
            compute_payroll_for_employee(emp['id'], cutoff_start, cutoff_end, payroll_date, payroll_status)
            success += 1
            log_audit(session['user_id'], "PAYROLL_BATCH_GENERATE", f"Generated payroll for cutoff {cutoff_start} to {cutoff_end} for employee {emp['id']}", request)
            if emp.get('email') and payroll_status == 'published':
                subject = "Payroll Generated - BrightPath"
                body = f"Dear {emp['name']},\n\nYour payroll for cutoff {cutoff_start} to {cutoff_end} has been generated.\nPlease login to view your payslip.\n\nThank you."
                send_email_notification(emp['email'], subject, body)
        except Exception as e:
            logging.error(f"Payroll failed for {emp['id']}: {e}")
            errors.append(f"{emp['name']} (ID: {emp['id']}): {str(e)}")
    
    conn.close()
    
    if is_ajax:
        return jsonify({"success": True, "count": success, "errors": errors})
    else:
        flash(f"Payroll generated for {success} employees" + 
              (f" in position '{position_filter}'" if position_filter and position_filter != 'all' else "") +
              (f" (selected employees)" if employees_param else ""))
        return redirect(url_for('admin_payroll_page'))
    
@app.route('/admin/payroll/generate_single', methods=['POST'])
@csrf.exempt
def admin_payroll_generate_single():
    if not session.get('logged_in') or session.get('role') != 'admin':
        flash("Unauthorized")
        return redirect(url_for('admin_login_page'))
    
    user_id = request.form.get('employee_id')
    cutoff_start = request.form.get('cutoff_start')
    cutoff_end = request.form.get('cutoff_end')
    payroll_date = request.form.get('payroll_date')
    status = request.form.get('status', 'published')
    if not user_id or not cutoff_start or not cutoff_end or not payroll_date:
        flash("Please provide employee and cutoff dates.")
        return redirect(url_for('admin_dashboard') + '#payroll-tab')
    if datetime.strptime(cutoff_start, '%Y-%m-%d') > datetime.strptime(cutoff_end, '%Y-%m-%d'):
        flash("Cutoff start must be earlier than cutoff end.")
        return redirect(url_for('admin_dashboard') + '#payroll-tab')
    try:
        compute_payroll_for_employee(int(user_id), cutoff_start, cutoff_end, payroll_date, status)
        log_audit(session['user_id'], "PAYROLL_SINGLE_GENERATE", f"Generated payroll for user {user_id} cutoff {cutoff_start} to {cutoff_end}", request)
        flash(f"Payroll generated for employee ID {user_id}.", "success")
        return redirect(url_for('generate_payslip', employee_id=int(user_id), start_date=cutoff_start, end_date=cutoff_end))
    except Exception as e:
        logging.error(f"Payroll generation error: {e}")
        flash(f"Error: {e}", "danger")
        return redirect(url_for('admin_dashboard') + '#payroll-tab')

@app.route('/admin/payroll/generate/<int:user_id>', methods=['POST'])
@csrf.exempt
def admin_payroll_generate_single_json(user_id):
    if not session.get('logged_in') or session.get('role') != 'admin':
        return jsonify({"error": "Unauthorized"}), 403
    data = request.get_json()
    cutoff_start = data.get('cutoff_start')
    cutoff_end = data.get('cutoff_end')
    payroll_date = data.get('payroll_date')
    if not cutoff_start or not cutoff_end or not payroll_date:
        return jsonify({"error": "Missing dates"}), 400
    if datetime.strptime(cutoff_start, '%Y-%m-%d') > datetime.strptime(cutoff_end, '%Y-%m-%d'):
        return jsonify({"error": "Invalid date range"}), 400
    try:
        compute_payroll_for_employee(user_id, cutoff_start, cutoff_end, payroll_date, 'published')
        log_audit(session['user_id'], "PAYROLL_SINGLE_GENERATE", f"Generated payroll for user {user_id}", request)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/admin/payroll/preview/<int:user_id>')
def admin_payroll_preview(user_id):
    if not session.get('logged_in') or session.get('role') != 'admin':
        flash("Unauthorized")
        return redirect(url_for('admin_login_page'))
    
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    payroll_date = request.args.get('payroll_date')
    if not start_date or not end_date or not payroll_date:
        flash("Missing dates")
        return redirect(url_for('admin_dashboard') + '#payroll-tab')
    
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, name, position, daily_rate FROM users WHERE id=%s AND role='employee'", (user_id,))
    employee = cursor.fetchone()
    if not employee:
        conn.close()
        flash("Employee not found")
        return redirect(url_for('admin_dashboard') + '#payroll-tab')
    
    daily_rate = float(employee['daily_rate'] or 500)
    hourly_rate = daily_rate / 8
    cursor.execute("""
        SELECT log_date, time_in, time_out, minutes_late, undertime_minutes
        FROM attendance
        WHERE user_id=%s AND log_date BETWEEN %s AND %s ORDER BY log_date
    """, (user_id, start_date, end_date))
    attendance_records = cursor.fetchall()
    days_present = len(attendance_records)
    total_late_minutes = sum(rec['minutes_late'] for rec in attendance_records)
    total_undertime_minutes = sum(rec['undertime_minutes'] for rec in attendance_records)
    cursor.execute("""
        SELECT SUM(hours) as total_hours
        FROM overtime_requests
        WHERE user_id=%s AND status='Approved' AND overtime_date BETWEEN %s AND %s
    """, (user_id, start_date, end_date))
    ot_row = cursor.fetchone()
    overtime_hours = ot_row['total_hours'] or 0
    
    basic_pay = days_present * daily_rate
    overtime_pay = overtime_hours * hourly_rate * 1.25
    tardiness_deduction = (total_late_minutes / 60) * hourly_rate
    undertime_deduction = (total_undertime_minutes / 60) * hourly_rate
    gross_pay = basic_pay + overtime_pay
    
    sss_percent, sss_cap = get_contribution_rate('sss_percent')
    sss = min(gross_pay * (sss_percent/100), sss_cap or 999999)
    phil_percent, phil_cap = get_contribution_rate('philhealth_percent')
    philhealth = min(gross_pay * (phil_percent/100), phil_cap or 999999)
    pagibig_percent, pagibig_cap = get_contribution_rate('pagibig_percent')
    pagibig = min(gross_pay * (pagibig_percent/100), pagibig_cap or 999999)
    sss = float(sss); philhealth = float(philhealth); pagibig = float(pagibig)
    gross_pay = float(gross_pay)
    tardiness_deduction = float(tardiness_deduction)
    undertime_deduction = float(undertime_deduction)
    taxable_income = gross_pay - (sss + philhealth + pagibig)
    withholding_tax = compute_withholding_tax(taxable_income)
    withholding_tax = float(withholding_tax)
    total_deductions = sss + philhealth + pagibig + withholding_tax + tardiness_deduction + undertime_deduction
    net_pay = gross_pay - total_deductions
    
    from datetime import timedelta
    def format_time(t):
        if t is None: return '--:--'
        if isinstance(t, timedelta):
            total_seconds = t.total_seconds()
            hours = int(total_seconds // 3600)
            minutes = int((total_seconds % 3600) // 60)
            am_pm = 'AM' if hours < 12 else 'PM'
            hour_12 = hours % 12
            if hour_12 == 0: hour_12 = 12
            return f"{hour_12:02d}:{minutes:02d} {am_pm}"
        elif hasattr(t, 'strftime'):
            return t.strftime('%I:%M %p')
        else:
            return str(t)
    
    for rec in attendance_records:
        rec['log_date_str'] = rec['log_date'].strftime('%b %d, %Y') if rec['log_date'] else ''
        rec['time_in_str'] = format_time(rec['time_in'])
        rec['time_out_str'] = format_time(rec['time_out'])
    
    conn.close()
    return render_template('admin/payroll_preview.html',
                           employee=employee,
                           start_date=start_date,
                           end_date=end_date,
                           payroll_date=payroll_date,
                           attendance_records=attendance_records,
                           days_present=days_present,
                           total_late_minutes=total_late_minutes,
                           total_undertime_minutes=total_undertime_minutes,
                           overtime_hours=overtime_hours,
                           basic_pay=basic_pay,
                           overtime_pay=overtime_pay,
                           gross_pay=gross_pay,
                           tardiness_deduction=tardiness_deduction,
                           undertime_deduction=undertime_deduction,
                           sss=sss,
                           philhealth=philhealth,
                           pagibig=pagibig,
                           withholding_tax=withholding_tax,
                           total_deductions=total_deductions,
                           net_pay=net_pay,
                           hourly_rate=hourly_rate,
                           sss_percent=sss_percent,
                           phil_percent=phil_percent,
                           pagibig_percent=pagibig_percent)

@app.route('/admin/payroll/view/<int:payroll_id>')
def admin_payroll_view(payroll_id):
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('admin_login_page'))
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT p.*, u.name, u.position, u.daily_rate
        FROM payroll p JOIN users u ON p.user_id = u.id
        WHERE p.id = %s
    """, (payroll_id,))
    payroll = cursor.fetchone()
    if payroll:
        payroll['net_pay'] = float(payroll['net_pay'])
    conn.close()
    if not payroll:
        flash("Payroll record not found")
        return redirect(url_for('admin_dashboard'))
    return render_template('admin/payroll_view.html', payroll=payroll)

@app.route('/admin/payroll_breakdown/<int:user_id>')
def payroll_breakdown(user_id):
    if not session.get('logged_in') or session.get('role') != 'admin':
        return jsonify({"error": "Unauthorized"}), 403
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT name, daily_rate FROM users WHERE id=%s", (user_id,))
    user = cursor.fetchone()
    if not user:
        return jsonify({"error": "Not found"}), 404
    daily_rate = float(user['daily_rate'] or 500)
    curr_month = datetime.now().month
    curr_year = datetime.now().year
    cursor.execute("SELECT COUNT(*) as days FROM attendance WHERE user_id=%s AND MONTH(log_date)=%s AND YEAR(log_date)=%s", (user_id, curr_month, curr_year))
    days_worked = cursor.fetchone()['days']
    cursor.execute("SELECT COUNT(*) as lates FROM attendance WHERE user_id=%s AND MONTH(log_date)=%s AND YEAR(log_date)=%s AND status='Late'", (user_id, curr_month, curr_year))
    late_count = cursor.fetchone()['lates']
    gross_pay = days_worked * daily_rate
    late_penalty = late_count * 50.00
    sss = min(gross_pay * 0.045, 1125)
    philhealth = min(gross_pay * 0.03, 675)
    pagibig = min(gross_pay * 0.02, 100)
    total_ded = sss + philhealth + pagibig + late_penalty
    net_pay = gross_pay - total_ded
    conn.close()
    return jsonify({
        "employee_name": user['name'],
        "daily_rate": daily_rate,
        "days_worked": days_worked,
        "gross_pay": gross_pay,
        "late_count": late_count,
        "late_penalty": late_penalty,
        "sss": sss,
        "philhealth": philhealth,
        "pagibig": pagibig,
        "total_deductions": total_ded,
        "net_pay": max(0, net_pay)
    })

@app.route('/admin/generate_payroll/<int:user_id>', methods=['POST'])
@csrf.exempt
def generate_payroll(user_id):
    if not session.get('logged_in') or session.get('role') != 'admin':
        return jsonify({"error": "Unauthorized"}), 403
    today = datetime.now()
    cutoff_start = today.replace(day=1).strftime('%Y-%m-%d')
    cutoff_end = today.strftime('%Y-%m-%d')
    payroll_date = today.strftime('%Y-%m-%d')
    try:
        compute_payroll_for_employee(user_id, cutoff_start, cutoff_end, payroll_date, 'published')
        log_audit(session['user_id'], "PAYROLL_SINGLE_GENERATE", f"Generated payroll for user {user_id}", request)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.route('/admin/payroll/approve/<int:payroll_id>', methods=['POST'])
@csrf.exempt
def admin_payroll_approve(payroll_id):
    if not session.get('logged_in') or session.get('role') != 'admin':
        return jsonify({"success": False, "message": "Unauthorized"}), 403
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT user_id, net_pay, cutoff_period FROM payroll WHERE id = %s", (payroll_id,))
    payroll = cursor.fetchone()
    if not payroll:
        conn.close()
        return jsonify({"success": False, "message": "Payroll not found"}), 404
    cursor.execute("UPDATE payroll SET status = 'published' WHERE id = %s", (payroll_id,))
    conn.commit()
    conn.close()
    create_notification(payroll['user_id'], f"Your payroll for {payroll['cutoff_period']} has been approved. Net pay: ₱{float(payroll['net_pay']):,.2f}", url_for('employee_dashboard') + "#emp-payroll")
    return jsonify({"success": True, "message": "Payroll approved"})

@app.route('/admin/generate_payslip/<int:employee_id>')
def generate_payslip(employee_id):
    if not session.get('logged_in'):
        return redirect(url_for('index'))
        
    print(f"🔎 DEBUG: role={session.get('role')}, user_id={session.get('user_id')}, employee_id={employee_id}")
    # Allow admin, OR the employee who owns this payslip
    if not (session.get('role') == 'admin' or
            (session.get('role') == 'employee' and int(session.get('user_id')) == employee_id)):
        flash("Unauthorized access.")
        return redirect(url_for('index'))

    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    if not start_date or not end_date:
        flash("Missing start_date/end_date.")
        return redirect(url_for('employee_dashboard'))

    from datetime import timedelta
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)

    # Employee info
    cursor.execute("SELECT id, name, position, daily_rate FROM users WHERE id=%s AND role='employee'", (employee_id,))
    emp = cursor.fetchone()
    if not emp:
        conn.close()
        flash("Employee not found.")
        return redirect(url_for('employee_dashboard'))

    daily_rate = float(emp['daily_rate'] or 500)
    hourly_rate = daily_rate / 8

    # Attendance
    cursor.execute("""
        SELECT log_date, time_in, time_out, minutes_late, undertime_minutes, status
        FROM attendance
        WHERE user_id = %s AND log_date BETWEEN %s AND %s
        ORDER BY log_date
    """, (employee_id, start_date, end_date))
    records = cursor.fetchall()

    days_present = len(records)
    total_late = sum(r['minutes_late'] or 0 for r in records)
    total_undertime = sum(r['undertime_minutes'] or 0 for r in records)

    # Overtime
    cursor.execute("""
        SELECT COALESCE(SUM(hours), 0) as total_hours
        FROM overtime_requests
        WHERE user_id = %s AND status='Approved' AND overtime_date BETWEEN %s AND %s
    """, (employee_id, start_date, end_date))
    overtime_hours = float(cursor.fetchone()['total_hours'] or 0)

    # Earnings
    basic_pay = days_present * daily_rate
    overtime_pay = overtime_hours * hourly_rate * 1.25
    gross_pay = basic_pay + overtime_pay

    # ========== ACCURATE STATUTORY DEDUCTIONS ==========
    monthly_basis = days_present * daily_rate
    sss = compute_sss_contribution(monthly_basis)
    philhealth = compute_philhealth_contribution(monthly_basis)
    pagibig = compute_pagibig_contribution(monthly_basis)

    taxable_income = gross_pay - (sss + philhealth + pagibig)
    withholding_tax = compute_withholding_tax(taxable_income)
    tardiness_deduction = (total_late / 60) * hourly_rate
    undertime_deduction = (total_undertime / 60) * hourly_rate
    total_deductions = sss + philhealth + pagibig + withholding_tax + tardiness_deduction + undertime_deduction
    net_pay = gross_pay - total_deductions

    # Loan & cash advance (display only)
    loan_deduction = 0.0
    cursor.execute("""
        SELECT balance_amount, remaining_months, monthly_amortization
        FROM loans WHERE employee_id = %s AND balance_amount > 0
        ORDER BY id LIMIT 1
    """, (employee_id,))
    loan = cursor.fetchone()
    if loan:
        loan_deduction = float(loan['monthly_amortization']) if loan['monthly_amortization'] else float(loan['balance_amount']) / max(1, loan['remaining_months'])

    cash_advance_deduction = 0.0
    cursor.execute("""
        SELECT amount, repayment_months, remaining_balance
        FROM cash_advances WHERE user_id = %s AND status = 'approved' AND remaining_balance > 0
        ORDER BY id LIMIT 1
    """, (employee_id,))
    ca = cursor.fetchone()
    if ca:
        cash_advance_deduction = float(ca['remaining_balance']) if ca['repayment_months'] == 0 else float(ca['amount']) / ca['repayment_months']

    net_pay_after = max(0, net_pay - loan_deduction - cash_advance_deduction)
    conn.close()

    # ---------- BUILD TEMPLATE DATA ----------
    income = {
        'basic': basic_pay,
        'rate': daily_rate,
        'days': days_present,
        'gross': gross_pay
    }

    deductions = {
        'late': tardiness_deduction,
        'undertime': undertime_deduction,
        'sss': sss,
        'cash_advance': cash_advance_deduction, 
        'total': total_deductions
    }

    additionals = {
        'overtime_hours': overtime_hours,
        'overtime_pay': overtime_pay,
        'total_add': overtime_pay
    }

    summary = {
        'net_pay': net_pay_after
    }

    # ========== BENEFITS (Employer contributions + 13th month) ==========
    emp_sss = sss * 2           # simplified employer SSS
    emp_philhealth = philhealth # employer share equals employee share
    emp_pagibig = pagibig       # employer share equals employee share
    thirteenth = 0.0            # 13th month – will compute only if December

    benefits = {
        'sss_employer': emp_sss,
        'philhealth_employer': emp_philhealth,
        'pagibig_employer': emp_pagibig,
        'thirteenth_month': thirteenth
    }

    # Timesheet rows (without break columns)
    def fmt_time(val):
        if val is None: return '--:--'
        if isinstance(val, timedelta):
            sec = int(val.total_seconds())
            h, m = sec // 3600, (sec % 3600) // 60
            return f"{h:02d}:{m:02d}"
        if hasattr(val, 'strftime'):
            return val.strftime('%H:%M')
        return str(val)

    timesheet_rows = []
    for r in records:
        timesheet_rows.append({
            'date': r['log_date'].strftime('%Y-%m-%d') if hasattr(r['log_date'], 'strftime') else str(r['log_date']),
            'emp_id': employee_id,
            'time_in': fmt_time(r['time_in']),
            'time_out': fmt_time(r['time_out']),
            'dept': emp['position'] or 'Staff'
        })

    # ---- INSERT generated report for this employee ----
    params_save = {'start_date': start_date, 'end_date': end_date}
    title = f"Payslip ({start_date} to {end_date})"
    conn_temp = db_connection()
    cursor_temp = conn_temp.cursor()
    cursor_temp.execute("""
        INSERT INTO generated_reports (user_id, report_type, title, params, url)
        VALUES (%s, %s, %s, %s, %s)
    """, (employee_id, 'payslip', title, json.dumps(params_save), ''))
    report_id = cursor_temp.lastrowid
    conn_temp.commit()
    conn_temp.close()
    actual_url = url_for('employee_view_report', report_id=report_id)
    conn_update = db_connection()
    cursor_update = conn_update.cursor()
    cursor_update.execute("UPDATE generated_reports SET url = %s WHERE id = %s", (actual_url, report_id))
    conn_update.commit()
    conn_update.close()
    create_notification(employee_id, f"Your payslip for {start_date} to {end_date} is ready.", actual_url)

    return render_template(
        'admin/reports/payslip_report.html',
        employee=emp,
        start_date=start_date,
        end_date=end_date,
        income=income,
        deductions=deductions,
        additionals=additionals,
        summary=summary,
        benefits=benefits,
        timesheet_rows=timesheet_rows,
        current_date=datetime.now().strftime('%B %d, %Y')
    )
# =============================================================================
# LEAVE APPROVAL / REJECTION
# =============================================================================
@app.route('/admin/leave/approve/<int:leave_id>', methods=['POST'])
@csrf.exempt
def approve_leave(leave_id):
    if not session.get('logged_in') or session.get('role') != 'admin':
        return jsonify({"success": False, "message": "Unauthorized"}), 403
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT user_id, start_date, end_date, leave_type FROM leave_requests WHERE id = %s", (leave_id,))
    leave = cursor.fetchone()
    if not leave:
        conn.close()
        return jsonify({"success": False, "message": "Leave not found"}), 404
    days = (leave['end_date'] - leave['start_date']).days + 1
    cursor.execute("SELECT leave_credits FROM users WHERE id = %s", (leave['user_id'],))
    credits = cursor.fetchone()['leave_credits']
    if credits < days:
        conn.close()
        return jsonify({"success": False, "message": f"Insufficient leave credits. Available: {credits}, Requested: {days}"}), 400
    cursor.execute("UPDATE users SET leave_credits = leave_credits - %s WHERE id = %s", (days, leave['user_id']))
    cursor.execute("UPDATE leave_requests SET status='Approved' WHERE id=%s", (leave_id,))
    conn.commit()
    log_audit(session['user_id'], "LEAVE_APPROVE", f"Leave ID {leave_id} for user {leave['user_id']} approved, deducted {days} days", request)
    cursor.execute("SELECT email, name FROM users WHERE id = %s", (leave['user_id'],))
    emp = cursor.fetchone()
    if emp:
        send_email_notification(emp['email'], "Leave Request Approved", f"Dear {emp['name']},\n\nYour leave request has been approved.\n\nThank you.")
        create_notification(leave['user_id'], f"Your {leave['leave_type']} leave request has been approved. {days} day(s) deducted from your credits.", url_for('employee_dashboard') + "#emp-leave")
    conn.close()
    return jsonify({"success": True})

@app.route('/admin/leave/reject/<int:leave_id>', methods=['POST'])
@csrf.exempt
def reject_leave(leave_id):
    if not session.get('logged_in') or session.get('role') != 'admin':
        return jsonify({"success": False, "message": "Unauthorized"}), 403
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT user_id, leave_type FROM leave_requests WHERE id=%s", (leave_id,))
    leave = cursor.fetchone()
    if not leave:
        conn.close()
        return jsonify({"success": False, "message": "Leave not found"}), 404
    cursor.execute("UPDATE leave_requests SET status='Rejected' WHERE id=%s", (leave_id,))
    conn.commit()
    log_audit(session['user_id'], "LEAVE_REJECT", f"Leave ID {leave_id} for user {leave['user_id']} rejected", request)
    cursor.execute("SELECT email, name FROM users WHERE id = %s", (leave['user_id'],))
    emp = cursor.fetchone()
    if emp:
        send_email_notification(emp['email'], "Leave Request Rejected", f"Dear {emp['name']},\n\nYour leave request has been rejected.\n\nPlease contact HR for more details.")
        create_notification(leave['user_id'], f"Your {leave['leave_type']} leave request has been rejected.", url_for('employee_dashboard') + "#emp-leave")
    conn.close()
    return jsonify({"success": True})

# =============================================================================
# CLOCK IN/OUT
# =============================================================================
@app.route('/clock_in', methods=['POST'])
def clock_in():
    if 'user_id' not in session:
        flash("Please login first.")
        return redirect(url_for('index'))
    
    user_role = session.get('role')
    if user_role != 'employee':
        flash("Access denied. Only employees can clock in.")
        if user_role == 'admin':
            return redirect(url_for('admin_dashboard'))
        else:
            return redirect(url_for('index'))
    
    _, msg = log_attendance(session['user_id'])
    flash(msg)
    return redirect(url_for('employee_dashboard'))

@app.route('/clock_out', methods=['POST'])
def clock_out():
    if 'user_id' not in session:
        flash("Please login first.")
        return redirect(url_for('index'))
    
    user_role = session.get('role')
    if user_role != 'employee':
        flash("Access denied. Only employees can clock out.")
        if user_role == 'admin':
            return redirect(url_for('admin_dashboard'))
        else:
            return redirect(url_for('index'))
    
    _, msg = clock_out_user(session['user_id'])
    flash(msg)
    return redirect(url_for('employee_dashboard'))

# =============================================================================
# FACE RECOGNITION
# =============================================================================
@app.route('/login_with_face', methods=['POST'])
@limiter.limit("300 per minute")
def login_with_face():
    client_ip = request.remote_addr
    now = datetime.now()
    
    # Check IP lock
    if client_ip in face_attempts:
        attempt = face_attempts[client_ip]
        if attempt['lock_until'] and now < attempt['lock_until']:
            return jsonify({"success": False, "message": "Too many failed attempts. Try again later."}), 429
    
    cam = get_camera()
    if cam is None or cam.video is None or not cam.video.isOpened():
        logging.error("Camera not available")
        return jsonify({"success": False, "message": "Camera not ready"}), 400
    
    # Use dedicated face capture method
    success, face_img = cam.get_face_for_capture()
    if not success or face_img is None:
        if client_ip not in face_attempts:
            face_attempts[client_ip] = {'count': 0, 'lock_until': None}
        face_attempts[client_ip]['count'] += 1
        if face_attempts[client_ip]['count'] >= 5:
            face_attempts[client_ip]['lock_until'] = now + timedelta(minutes=5)
        return jsonify({"success": False, "message": "No face detected"}), 401
    
    # Recognize face
    try:
        id_num, confidence = cam.recognizer.predict(face_img)
        logging.info(f"Face recognition result: ID={id_num}, Confidence={confidence}")
    except Exception as e:
        logging.error(f"Recognition error: {e}")
        return jsonify({"success": False, "message": "Recognition error"}), 500
    
    # Check if ID exists in user map
    user_map = cam.user_map
    if str(id_num) not in user_map:
        if client_ip not in face_attempts:
            face_attempts[client_ip] = {'count': 0, 'lock_until': None}
        face_attempts[client_ip]['count'] += 1
        if face_attempts[client_ip]['count'] >= 5:
            face_attempts[client_ip]['lock_until'] = now + timedelta(minutes=5)
        return jsonify({"success": False, "message": "Face not registered"}), 401
    
    # 🔧 FIX: Increased confidence threshold to 120 (lower is better)
    # Accept if confidence <= 120, reject if > 120
    if confidence > 120:
        if client_ip not in face_attempts:
            face_attempts[client_ip] = {'count': 0, 'lock_until': None}
        face_attempts[client_ip]['count'] += 1
        if face_attempts[client_ip]['count'] >= 5:
            face_attempts[client_ip]['lock_until'] = now + timedelta(minutes=5)
        return jsonify({"success": False, "message": f"Face not recognized (confidence: {confidence:.1f})"}), 401
    
    # Reset failed attempts on success
    if client_ip in face_attempts:
        face_attempts[client_ip]['count'] = 0
        face_attempts[client_ip]['lock_until'] = None
    
    # Verify database record
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE id = %s AND role = 'employee' AND status = 'active'", (id_num,))
    user = cursor.fetchone()
    conn.close()
    
    if not user:
        return jsonify({"success": False, "message": "Account inactive or not found"}), 401
    
    # Login success
    session.update({'logged_in': True, 'user_id': user['id'], 'name': user['name'], 'role': user['role']})
    
    # Stop camera
    cam.stop()
    global video_camera
    video_camera = None
    
    return jsonify({"success": True, "redirect": url_for('employee_dashboard')})

@app.route('/video_feed')
def video_feed():
    cam = get_camera()
    if cam is None:
        return "Camera error", 404
    return Response(cam.generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/stop_camera')
def stop_camera():
    global video_camera
    if video_camera:
        video_camera.stop()
        video_camera = None
    return jsonify({"status": "camera off"})

# =============================================================================
# NOTIFICATIONS API (admin + employee access)
# =============================================================================
@app.route('/employee/notifications')
def employee_notifications():
    if not session.get('logged_in') or session.get('role') not in ['employee', 'admin']:
        return jsonify({"success": False, "message": "Unauthorized"}), 403
    user_id = session['user_id']
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT id, message, link, is_read, created_at 
        FROM notifications 
        WHERE user_id = %s 
        ORDER BY created_at DESC LIMIT 20
    """, (user_id,))
    notifs = cursor.fetchall()
    conn.close()
    return jsonify({"success": True, "notifications": notifs})

@limiter.exempt
@app.route('/employee/notifications/unread_count')
def employee_notifications_unread_count():
    if not session.get('logged_in') or session.get('role') not in ['employee', 'admin']:
        return jsonify({"success": False, "message": "Unauthorized"}), 403
    user_id = session['user_id']
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT COUNT(*) as cnt FROM notifications WHERE user_id = %s AND is_read = FALSE", (user_id,))
    count = cursor.fetchone()['cnt']
    conn.close()
    return jsonify({"success": True, "count": count})

@app.route('/employee/notifications/mark_read/<int:notif_id>', methods=['POST'])
def mark_notification_read(notif_id):
    if not session.get('logged_in') or session.get('role') not in ['employee', 'admin']:
        return jsonify({"success": False, "message": "Unauthorized"}), 403
    user_id = session['user_id']
    conn = db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE notifications SET is_read = TRUE WHERE id = %s AND user_id = %s", (notif_id, user_id))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route('/employee/notifications/mark_all_read', methods=['POST'])
def mark_all_notifications_read():
    if not session.get('logged_in') or session.get('role') not in ['employee', 'admin']:
        return jsonify({"success": False, "message": "Unauthorized"}), 403
    user_id = session['user_id']
    conn = db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE notifications SET is_read = TRUE WHERE user_id = %s", (user_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

# =============================================================================
# REPORTS MODULE (Updated)
# =============================================================================

# Helper functions for employee report rendering
def render_dtr_report_for_employee(user_id, start_date, end_date):
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, name, position FROM users WHERE id = %s", (user_id,))
    employee = cursor.fetchone()
    cursor.execute("""
        SELECT log_date, time_in, time_out, minutes_late, undertime_minutes, status
        FROM attendance
        WHERE user_id = %s AND log_date BETWEEN %s AND %s
        ORDER BY log_date
    """, (user_id, start_date, end_date))
    records = cursor.fetchall()
    conn.close()
    return render_template('employee/employee_dtr_report.html',
                           employee=employee,
                           start_date=start_date,
                           end_date=end_date,
                           records=records)

def render_overtime_summary_for_employee(user_id, start_date, end_date):
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, name, position, daily_rate FROM users WHERE id = %s", (user_id,))
    emp = cursor.fetchone()
    hourly_rate = (emp['daily_rate'] or 500) / 8
    cursor.execute("""
        SELECT SUM(hours) as total_hours,
               SUM(hours * %s * 1.25) as overtime_pay
        FROM overtime_requests
        WHERE user_id = %s AND status = 'Approved'
        AND overtime_date BETWEEN %s AND %s
    """, (hourly_rate, user_id, start_date, end_date))
    result = cursor.fetchone()
    conn.close()
    return render_template('employee/employee_overtime_summary.html',
                           employee=emp,
                           start_date=start_date,
                           end_date=end_date,
                           total_hours=result['total_hours'] or 0,
                           overtime_pay=result['overtime_pay'] or 0)

def render_leave_summary_for_employee(user_id, start_date, end_date, status_filter='Approved'):
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, name, position FROM users WHERE id = %s", (user_id,))
    employee = cursor.fetchone()
    cursor.execute("""
        SELECT leave_type, start_date, end_date, DATEDIFF(end_date, start_date) + 1 as days, status, reason
        FROM leave_requests
        WHERE user_id = %s AND status = %s
        AND start_date BETWEEN %s AND %s
        ORDER BY start_date DESC
    """, (user_id, status_filter, start_date, end_date))
    leaves = cursor.fetchall()
    conn.close()
    return render_template('employee/employee_leave_summary.html',
                           employee=employee,
                           start_date=start_date,
                           end_date=end_date,
                           leaves=leaves)


@app.route('/admin/reports/dtr')
def admin_report_dtr():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('admin_login_page'))
    employee_id = request.args.get('employee_id', type=int)
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, name FROM users WHERE role='employee' ORDER BY name")
    employees = cursor.fetchall()
    report_data = None
    if employee_id and start_date and end_date:
        cursor.execute("""
            SELECT u.name, u.position, a.log_date, a.time_in, a.time_out, 
                   a.minutes_late, a.undertime_minutes, a.status
            FROM attendance a JOIN users u ON a.user_id = u.id
            WHERE a.user_id = %s AND a.log_date BETWEEN %s AND %s
            ORDER BY a.log_date
        """, (employee_id, start_date, end_date))
        records = cursor.fetchall()
        total_late_mins = sum(r['minutes_late'] for r in records)
        total_undertime_mins = sum(r['undertime_minutes'] for r in records)
        cursor.execute("SELECT name, position FROM users WHERE id=%s", (employee_id,))
        employee_info = cursor.fetchone()
        report_data = {
            'employee': employee_info,
            'start_date': start_date,
            'end_date': end_date,
            'records': records,
            'total_late': total_late_mins,
            'total_undertime': total_undertime_mins
        }

        params = {'start_date': start_date, 'end_date': end_date}
        title = f"DTR Report ({start_date} to {end_date})"
        conn_temp = db_connection()
        cursor_temp = conn_temp.cursor()
        cursor_temp.execute("""
            INSERT INTO generated_reports (user_id, report_type, title, params, url)
            VALUES (%s, %s, %s, %s, %s)
        """, (employee_id, 'dtr', title, json.dumps(params), ''))
        report_id = cursor_temp.lastrowid
        conn_temp.commit()
        conn_temp.close()
        actual_url = url_for('employee_view_report', report_id=report_id)
        conn_update = db_connection()
        cursor_update = conn_update.cursor()
        cursor_update.execute("UPDATE generated_reports SET url = %s WHERE id = %s", (actual_url, report_id))
        conn_update.commit()
        conn_update.close()
        create_notification(employee_id, f"Your DTR report for {start_date} to {end_date} is ready.", actual_url)

    conn.close()
    return render_template('admin/reports/dtr_report.html', employees=employees, report=report_data,
                           selected_emp=employee_id, start_date=start_date, end_date=end_date)

@app.route('/admin/reports/overtime_summary')
def admin_reports_overtime_summary():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('admin_login_page'))
    
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    employee_id = request.args.get('employee_id')
    
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, name FROM users WHERE role='employee' ORDER BY name")
    employees = cursor.fetchall()
    
    query = """
        SELECT 
            u.id,
            u.name,
            u.position,
            COALESCE(SUM(ot.hours), 0) as total_hours,
            COALESCE(SUM(ot.hours * (u.daily_rate / 8) * 1.25), 0) as overtime_pay
        FROM users u
        LEFT JOIN overtime_requests ot ON u.id = ot.user_id 
            AND ot.status = 'Approved'
            AND (ot.overtime_date BETWEEN %s AND %s)
        WHERE u.role = 'employee'
    """
    params = [start_date, end_date]
    if employee_id:
        query += " AND u.id = %s"
        params.append(employee_id)
    query += " GROUP BY u.id, u.name, u.position ORDER BY u.name"
    cursor.execute(query, params)
    records = cursor.fetchall()
    conn.close()
    
    if employee_id and start_date and end_date:
        try:
            emp_id_int = int(employee_id)
            params_save = {'start_date': start_date, 'end_date': end_date, 'employee_id': emp_id_int}
            title = f"Overtime Summary ({start_date} to {end_date})"
            conn_temp = db_connection()
            cursor_temp = conn_temp.cursor()
            cursor_temp.execute("""
                INSERT INTO generated_reports (user_id, report_type, title, params, url)
                VALUES (%s, %s, %s, %s, %s)
            """, (emp_id_int, 'overtime_summary', title, json.dumps(params_save), ''))
            report_id = cursor_temp.lastrowid
            conn_temp.commit()
            conn_temp.close()
            actual_url = url_for('employee_view_report', report_id=report_id)
            conn_update = db_connection()
            cursor_update = conn_update.cursor()
            cursor_update.execute("UPDATE generated_reports SET url = %s WHERE id = %s", (actual_url, report_id))
            conn_update.commit()
            conn_update.close()
            create_notification(emp_id_int, f"Your Overtime Summary for {start_date} to {end_date} is ready.", actual_url)
        except Exception as e:
            logging.error(f"Failed to save overtime report: {e}")
    
    return render_template('admin/reports/overtime_summary.html',
                           start_date=start_date,
                           end_date=end_date,
                           records=records,
                           employees=employees,
                           selected_emp=employee_id)

@app.route('/admin/reports/leave_summary')
def admin_report_leave_summary():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('admin_login_page'))
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    status_filter = request.args.get('status', 'Approved')
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    query = """
        SELECT u.name, u.position, l.leave_type, l.start_date, l.end_date, 
               DATEDIFF(l.end_date, l.start_date) + 1 as days, l.status, l.reason, l.user_id
        FROM leave_requests l JOIN users u ON l.user_id = u.id WHERE 1=1
    """
    params = []
    if start_date:
        query += " AND l.start_date >= %s"; params.append(start_date)
    if end_date:
        query += " AND l.end_date <= %s"; params.append(end_date)
    if status_filter:
        query += " AND l.status = %s"; params.append(status_filter)
    query += " ORDER BY l.start_date DESC"
    cursor.execute(query, params)
    leaves = cursor.fetchall()
    conn.close()

    # ---- INSERT generated reports for each unique employee ----
    if leaves and start_date and end_date:
        unique_users = set()
        for leave in leaves:
            uid = leave.get('user_id')
            if uid:
                unique_users.add(uid)
        for uid in unique_users:
            params_save = {'start_date': start_date, 'end_date': end_date, 'status_filter': status_filter}
            title = f"Leave Summary ({start_date} to {end_date})"
            conn_temp = db_connection()
            cursor_temp = conn_temp.cursor()
            cursor_temp.execute("""
                INSERT INTO generated_reports (user_id, report_type, title, params, url)
                VALUES (%s, %s, %s, %s, %s)
            """, (uid, 'leave_summary', title, json.dumps(params_save), ''))
            report_id = cursor_temp.lastrowid
            conn_temp.commit()
            conn_temp.close()
            actual_url = url_for('employee_view_report', report_id=report_id)
            conn_update = db_connection()
            cursor_update = conn_update.cursor()
            cursor_update.execute("UPDATE generated_reports SET url = %s WHERE id = %s", (actual_url, report_id))
            conn_update.commit()
            conn_update.close()
            create_notification(uid, f"Your Leave Summary for {start_date} to {end_date} is ready.", actual_url)

    return render_template('admin/reports/leave_summary.html', leaves=leaves,
                           start_date=start_date, end_date=end_date, status_filter=status_filter)
# =============================================================================
# EMPLOYEE API REPORTS
# =============================================================================
@app.route('/employee/api/reports')
def employee_api_reports():
    if not session.get('logged_in') or session.get('role') != 'employee':
        return jsonify({"success": False, "message": "Unauthorized"}), 403
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT id, title, created_at, url
        FROM generated_reports
        WHERE user_id = %s
        ORDER BY created_at DESC
    """, (session['user_id'],))
    reports = cursor.fetchall()
    conn.close()
    for r in reports:
        if r['created_at']:
            r['created_at'] = r['created_at'].strftime('%Y-%m-%d %H:%M:%S')
    return jsonify({"success": True, "reports": reports})

@app.route('/employee/api/quick_payslips')
def employee_quick_payslips():
    if not session.get('logged_in') or session.get('role') != 'employee':
        return jsonify({"success": False}), 403
    user_id = session['user_id']
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT id, date_paid, net_pay
        FROM payroll
        WHERE user_id = %s AND status = 'published'
        ORDER BY date_paid DESC
        LIMIT 3
    """, (user_id,))
    payslips = cursor.fetchall()
    conn.close()
    return jsonify({"success": True, "payslips": payslips})

@app.route('/employee/payslip/<int:payroll_id>')
def employee_payslip_view(payroll_id):
    if not session.get('logged_in') or session.get('role') != 'employee':
        return redirect(url_for('index'))

    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT p.*, u.name, u.position, u.daily_rate
        FROM payroll p
        JOIN users u ON p.user_id = u.id
        WHERE p.id = %s AND p.user_id = %s
    """, (payroll_id, session['user_id']))
    pay = cursor.fetchone()
    conn.close()

    if not pay:
        flash("Payslip not found.")
        return redirect(url_for('employee_dashboard'))

    # Build the same data as the admin payslip page expects
    # Since we already have all computed values, we can directly pass them.
    # We'll use the existing admin/reports/payslip_report.html template.
    # However that template expects income/deductions/additionals etc.
    # We'll prepare them from the payroll record.

    income = {
        'basic': float(pay['basic_pay'] or 0),
        'rate': float(pay['daily_rate'] or 0),
        'days': pay['total_days_worked'] or 0,
        'gross': float(pay['gross_pay'] or 0)
    }
    deductions = {
        'late': float(pay['tardiness_deduction'] or 0),
        'undertime': float(pay['undertime_deduction'] or 0),
        'sss': float(pay['sss'] or 0),
        'total': float(pay['total_deductions'] or 0)
    }
    additionals = {
        'overtime_hours': float(pay['overtime_pay'] / (pay['daily_rate'] / 8 / 1.25) if pay['overtime_pay'] and pay['daily_rate'] else 0),
        'overtime_pay': float(pay['overtime_pay'] or 0),
        'total_add': float(pay['overtime_pay'] or 0)
    }
    summary = {
        'net_pay': float(pay['net_pay'] or 0)
    }
    # Timesheet rows can be left empty or fetched; but for simplicity we'll leave empty
    timesheet_rows = []

    return render_template(
        'admin/reports/payslip_report.html',
        employee={'id': pay['user_id'], 'name': pay['name'], 'position': pay['position'], 'daily_rate': pay['daily_rate']},
        start_date=pay['cutoff_period'].split(' to ')[0] if ' to ' in pay['cutoff_period'] else '',
        end_date=pay['cutoff_period'].split(' to ')[1] if ' to ' in pay['cutoff_period'] else '',
        income=income,
        deductions=deductions,
        additionals=additionals,
        summary=summary,
        timesheet_rows=timesheet_rows,
        current_date=datetime.now().strftime('%B %d, %Y')
    )

# =============================================================================
# EMPLOYEE API DASHBOARD STATS
# =============================================================================
@app.route('/employee/api/dashboard_stats')
def employee_dashboard_stats():
    if not session.get('logged_in') or session.get('role') != 'employee':
        return jsonify({"success": False, "message": "Unauthorized"}), 403
    user_id = session['user_id']
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    current_month = datetime.now().month
    current_year = datetime.now().year
    cursor.execute("""
        SELECT COUNT(DISTINCT log_date) as days_worked
        FROM attendance
        WHERE user_id = %s AND MONTH(log_date) = %s AND YEAR(log_date) = %s AND time_in IS NOT NULL
    """, (user_id, current_month, current_year))
    days_worked = cursor.fetchone()['days_worked'] or 0
    
    cursor.execute("SELECT leave_credits FROM users WHERE id = %s", (user_id,))
    leave_credits = cursor.fetchone()['leave_credits']
    
    cursor.execute("SELECT net_pay FROM payroll WHERE user_id = %s ORDER BY date_paid DESC LIMIT 1", (user_id,))
    last_payroll = cursor.fetchone()
    last_net_pay = float(last_payroll['net_pay']) if last_payroll else 0.0
    
    conn.close()
    return jsonify({
        "success": True,
        "days_worked": days_worked,
        "leave_credits": float(leave_credits),
        "last_net_pay": last_net_pay
    })

# =============================================================================
# HOLIDAY MANAGEMENT UI
# =============================================================================
@app.route('/admin/holidays')
def admin_holidays():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('admin_login_page'))
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    # Use the actual column names from your table
    cursor.execute("SELECT id, holiday_date, holiday_name as name, is_regular FROM holidays ORDER BY holiday_date DESC")
    holidays = cursor.fetchall()
    conn.close()
    return render_template('admin/holidays.html', holidays=holidays)

@app.route('/admin/holidays/add', methods=['POST'])
def admin_holidays_add():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('admin_login_page'))
    
    date = request.form.get('holiday_date')
    name = request.form.get('name')
    is_regular = 1 if request.form.get('is_regular') else 0
    
    conn = db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO holidays (holiday_date, name, is_regular) VALUES (%s, %s, %s)", (date, name, is_regular))
    conn.commit()
    
    # Magpadala ng notification sa LAHAT ng empleyado (broadcast)
    cursor.execute("SELECT id FROM users WHERE role='employee'")
    employees = cursor.fetchall()
    holiday_type = "Regular" if is_regular else "Special"
    message = f"📅 New holiday added: {name} on {date} ({holiday_type}). If you work on this day, you will receive { 'double pay' if is_regular else '130% pay' }."
    
    for emp in employees:
        create_notification(emp[0], message, url_for('employee_dashboard') + "#emp-att-summary")
    
    conn.close()
    
    log_audit(session['user_id'], "HOLIDAY_ADD", f"Added holiday: {name} on {date} ({holiday_type})", request)
    flash("Holiday added successfully.", "success")
    return redirect(url_for('admin_holidays'))

@app.route('/admin/holidays/delete/<int:id>', methods=['POST'])
def admin_holidays_delete(id):
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('admin_login_page'))
    
    conn = db_connection()
    cursor = conn.cursor()
    
    # Kunin muna ang detalye ng holiday bago burahin
    cursor.execute("SELECT name, holiday_date, is_regular FROM holidays WHERE id = %s", (id,))
    holiday = cursor.fetchone()
    if not holiday:
        conn.close()
        flash("Holiday not found.", "danger")
        return redirect(url_for('admin_holidays'))
    
    name, date, is_regular = holiday
    holiday_type = "Regular" if is_regular else "Special"
    
    # Burahin ang holiday
    cursor.execute("DELETE FROM holidays WHERE id = %s", (id,))
    conn.commit()
    
    # Magpadala ng notification sa lahat ng empleyado
    cursor.execute("SELECT id FROM users WHERE role='employee'")
    employees = cursor.fetchall()
    message = f"⚠️ Holiday removed: {name} on {date} ({holiday_type}). No special pay for this day."
    for emp in employees:
        create_notification(emp[0], message, url_for('employee_dashboard') + "#emp-att-summary")
    
    conn.close()
    
    log_audit(session['user_id'], "HOLIDAY_DELETE", f"Deleted holiday: {name} on {date}", request)
    flash("Holiday deleted successfully.", "success")
    return redirect(url_for('admin_holidays'))
# =============================================================================
# 13TH MONTH PAY REPORT
# =============================================================================
@app.route('/admin/reports/13th_month')
def admin_13th_month():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('admin_login_page'))
    year = request.args.get('year', datetime.now().year)
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT u.id, u.name, u.position, COALESCE(SUM(p.basic_pay), 0) as total_basic
        FROM users u
        LEFT JOIN payroll p ON u.id = p.user_id AND YEAR(p.date_paid) = %s
        WHERE u.role = 'employee'
        GROUP BY u.id
    """, (year,))
    employees = cursor.fetchall()
    for emp in employees:
        emp['thirteenth_month'] = emp['total_basic'] / 12
    conn.close()
    return render_template('admin/reports/13th_month.html', employees=employees, year=int(year))

# =============================================================================
# BATCH IMPORT EMPLOYEES (CSV)
# =============================================================================
@app.route('/admin/employees/import', methods=['GET', 'POST'])
def admin_import_employees():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('admin_login_page'))
    if request.method == 'POST':
        file = request.files.get('csv_file')
        if not file or not file.filename.endswith('.csv'):
            flash("Please upload a CSV file.", "danger")
            return redirect(url_for('admin_import_employees'))
        stream = file.stream.read().decode('utf-8').splitlines()
        reader = csv.DictReader(stream)
        conn = db_connection()
        cursor = conn.cursor()
        success_count = 0
        errors = []
        for row in reader:
            name = row.get('name')
            email = row.get('email')
            password = generate_password_hash(row.get('password', 'default123'))
            position = row.get('position', 'Staff')
            daily_rate = float(row.get('daily_rate', 500))
            try:
                cursor.execute("""
                    INSERT INTO users (name, email, password, role, position, daily_rate, leave_credits, profile_pic)
                    VALUES (%s, %s, %s, 'employee', %s, %s, 15.0, 'default_profile.png')
                """, (name, email, password, position, daily_rate))
                conn.commit()
                success_count += 1
            except Exception as e:
                errors.append(f"{email}: {e}")
        conn.close()
        if errors:
            flash(f"Imported {success_count} employees. Errors: {', '.join(errors[:5])}", "warning")
        else:
            flash(f"Successfully imported {success_count} employees.", "success")
        log_audit(session['user_id'], "IMPORT_EMPLOYEES", f"Imported {success_count} employees from CSV", request)
        return redirect(url_for('admin_dashboard'))
    return render_template('admin/import_employees.html')

@app.route('/admin/employee/update/<int:id>', methods=['POST'])
def admin_employee_update(id):
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('admin_login_page'))
    
    name = request.form.get('name')
    email = request.form.get('email')
    position = request.form.get('position')
    daily_rate = request.form.get('daily_rate')
    status = request.form.get('status')
    
    if not name or not email or not position:
        flash("Name, email, and position are required.")
        return redirect(url_for('admin_employees_page'))
    
    conn = db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE users 
        SET name=%s, email=%s, position=%s, daily_rate=%s, status=%s
        WHERE id=%s AND role='employee'
    """, (name, email, position, daily_rate, status, id))
    conn.commit()
    conn.close()
    
    flash("Employee updated successfully.")
    return redirect(url_for('admin_employees_page'))

# =============================================================================
# CSRF error handler
# =============================================================================
@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    flash("CSRF token missing or invalid. Please refresh and try again.", "danger")
    return redirect(request.referrer or url_for('index'))

# =============================================================================
# CONTRIBUTIONS SETTINGS AND DEDUCTIONS
# =============================================================================
@app.route('/admin/deductions_combined', methods=['GET', 'POST'])
def admin_deductions_combined():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('admin_login_page'))

    # Date range from form or default to current month
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    if not start_date or not end_date:
        today = datetime.now()
        start_date = today.replace(day=1).strftime('%Y-%m-%d')
        end_date = today.strftime('%Y-%m-%d')

    conn = db_connection()
    cursor = conn.cursor(dictionary=True)

    # Get all employees
    cursor.execute("SELECT id, name, position, daily_rate FROM users WHERE role='employee'")
    employees = cursor.fetchall()

    total_sss = 0.0
    total_philhealth = 0.0
    total_pagibig = 0.0
    total_tax = 0.0
    other_deductions = 0.0

    # Compute for each employee and sum up
    for emp in employees:
        daily_rate = float(emp['daily_rate'] or 500)
        hourly_rate = daily_rate / 8

        # Attendance for the period
        cursor.execute("""
            SELECT COUNT(*) as days_present,
                   SUM(minutes_late) as total_late,
                   SUM(undertime_minutes) as total_undertime
            FROM attendance
            WHERE user_id=%s AND log_date BETWEEN %s AND %s AND time_in IS NOT NULL
        """, (emp['id'], start_date, end_date))
        att = cursor.fetchone()
        days_present = int(att['days_present'] or 0)
        late_minutes = float(att['total_late'] or 0)
        undertime_minutes = float(att['total_undertime'] or 0)

        # Approved overtime
        cursor.execute("""
            SELECT COALESCE(SUM(hours), 0) as total_hours
            FROM overtime_requests
            WHERE user_id=%s AND status='Approved' AND overtime_date BETWEEN %s AND %s
        """, (emp['id'], start_date, end_date))
        overtime_hours = float(cursor.fetchone()['total_hours'] or 0)

        basic_pay = days_present * daily_rate
        overtime_pay = overtime_hours * hourly_rate * 1.25
        gross_pay = basic_pay + overtime_pay   # simplified (no holiday)

        # Accurate contributions
        monthly_basis = days_present * daily_rate
        sss = compute_sss_contribution(monthly_basis)
        philhealth = compute_philhealth_contribution(monthly_basis)
        pagibig = compute_pagibig_contribution(monthly_basis)

        taxable_income = gross_pay - (sss + philhealth + pagibig)
        withholding_tax = compute_withholding_tax(taxable_income)
        tardiness_deduction = (late_minutes / 60) * hourly_rate
        undertime_deduction = (undertime_minutes / 60) * hourly_rate

        total_sss += sss
        total_philhealth += philhealth
        total_pagibig += pagibig
        total_tax += withholding_tax
        other_deductions += tardiness_deduction + undertime_deduction

    conn.close()

    total_all = total_sss + total_philhealth + total_pagibig + total_tax + other_deductions

    # Build breakdown table (employee share only)
    breakdown = [
        {
            'desc': 'SSS Contribution',
            'employee_share': total_sss * 0.5,
            'employer_share': total_sss * 0.5,
            'total': total_sss,
            'percentage': (total_sss / total_all * 100) if total_all > 0 else 0
        },
        {
            'desc': 'PhilHealth Contribution',
            'employee_share': total_philhealth * 0.5,
            'employer_share': total_philhealth * 0.5,
            'total': total_philhealth,
            'percentage': (total_philhealth / total_all * 100) if total_all > 0 else 0
        },
        {
            'desc': 'Pag-IBIG Contribution',
            'employee_share': total_pagibig * 0.5,
            'employer_share': total_pagibig * 0.5,
            'total': total_pagibig,
            'percentage': (total_pagibig / total_all * 100) if total_all > 0 else 0
        },
        {
            'desc': 'Withholding Tax',
            'employee_share': total_tax,
            'employer_share': 0.0,
            'total': total_tax,
            'percentage': (total_tax / total_all * 100) if total_all > 0 else 0
        },
        {
            'desc': 'Other Deductions',
            'employee_share': other_deductions,
            'employer_share': 0.0,
            'total': other_deductions,
            'percentage': (other_deductions / total_all * 100) if total_all > 0 else 0
        }
    ]

    totals_row = {
        'total_employee': sum(item['employee_share'] for item in breakdown),
        'total_employer': sum(item['employer_share'] for item in breakdown),
        'total_all': total_all
    }

    return render_template('admin/deductions_combined.html',
                           totals={
                               'total_sss': total_sss,
                               'total_philhealth': total_philhealth,
                               'total_pagibig': total_pagibig,
                               'total_tax': total_tax,
                               'other_deductions': other_deductions
                           },
                           breakdown=breakdown,
                           totals_row=totals_row,
                           start_date=start_date,
                           end_date=end_date,
                           rates=None,   # we no longer use editable rates
                           dummy=False)

# ========== CASH ADVANCE API ==========
@app.route('/admin/api/cash_advances', methods=['GET'])
def admin_api_cash_advances():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return jsonify({"success": False, "message": "Unauthorized"}), 403
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT ca.*, u.name as employee_name
        FROM cash_advances ca
        JOIN users u ON ca.user_id = u.id
        ORDER BY ca.created_at DESC
    """)
    advances = cursor.fetchall()
    conn.close()
    return jsonify({"success": True, "advances": advances})

@app.route('/admin/api/cash_advances', methods=['POST'])
@csrf.exempt
def admin_api_add_cash_advance():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return jsonify({"success": False, "message": "Unauthorized"}), 403
    data = request.get_json()
    user_id = data.get('user_id')
    amount = float(data.get('amount', 0))
    repayment_months = int(data.get('repayment_months', 0))
    if not user_id or amount <= 0:
        return jsonify({"success": False, "message": "Invalid data"}), 400
    remaining_balance = amount
    status = 'approved' if repayment_months == 0 else 'pending'
    conn = db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO cash_advances (user_id, amount, repayment_months, remaining_balance, status)
        VALUES (%s, %s, %s, %s, %s)
    """, (user_id, amount, repayment_months, remaining_balance, status))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": "Cash advance added"})

@app.route('/admin/api/cash_advances/approve/<int:ca_id>', methods=['POST'])
@csrf.exempt
def admin_api_approve_cash_advance(ca_id):
    if not session.get('logged_in') or session.get('role') != 'admin':
        return jsonify({"success": False, "message": "Unauthorized"}), 403
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM cash_advances WHERE id = %s", (ca_id,))
    ca = cursor.fetchone()
    if not ca:
        conn.close()
        return jsonify({"success": False, "message": "Cash advance not found"}), 404
    cursor.execute("UPDATE cash_advances SET status = 'approved' WHERE id = %s", (ca_id,))
    conn.commit()
    # Ipadala ang notification sa empleyado
    create_notification(ca['user_id'], f"Your cash advance request of ₱{float(ca['amount']):,.2f} has been approved.", url_for('employee_dashboard') + "#emp-cash-advance")
    conn.close()
    return jsonify({"success": True, "message": "Cash advance approved"})

@app.route('/admin/api/cash_advances/delete/<int:ca_id>', methods=['DELETE'])
@csrf.exempt
def admin_api_delete_cash_advance(ca_id):
    if not session.get('logged_in') or session.get('role') != 'admin':
        return jsonify({"success": False, "message": "Unauthorized"}), 403
    conn = db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM cash_advances WHERE id = %s", (ca_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": "Deleted"})

# =============================================================================
# EMPLOYEE MANAGEMENT API
# =============================================================================
@app.route('/admin/api/employees')
def api_get_employees():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return jsonify({"success": False, "message": "Unauthorized"}), 403
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, name, email, position, daily_rate, status FROM users WHERE role='employee' ORDER BY name")
    employees = cursor.fetchall()
    conn.close()
    return jsonify({"success": True, "employees": employees})

@app.route('/admin/api/employees/<int:user_id>')
def api_get_employee(user_id):
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE id=%s AND role='employee'", (user_id,))
    emp = cursor.fetchone()
    conn.close()
    if emp:
        return jsonify({"success": True, "employee": emp})
    return jsonify({"success": False, "message": "Not found"}), 404

@app.route('/admin/api/employees', methods=['POST'])
@csrf.exempt
def api_add_employee():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return jsonify({"success": False, "message": "Unauthorized"}), 403
    data = request.get_json()
    conn = db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE email = %s", (data['email'],))
    if cursor.fetchone():
        conn.close()
        return jsonify({"success": False, "message": "Email already exists"}), 400
    
    hashed_password = generate_password_hash(data.get('password', 'default123'))
    position = data.get('position', 'Staff')
    daily_rate = get_daily_rate_by_position(position)
    cursor.execute("""
        INSERT INTO users (name, email, password, role, position, daily_rate, contact_number, address, leave_credits, profile_pic, status)
        VALUES (%s, %s, %s, 'employee', %s, %s, %s, %s, 15.0, 'default_profile.png', 'active')
    """, (data['name'], data['email'], hashed_password, position, daily_rate,
          data.get('contact_number', ''), data.get('address', '')))
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    create_notification(new_id, "Your employee account has been created by HR/Admin. You can now login.", url_for('index'))
    return jsonify({"success": True, "message": "Employee added", "id": new_id})

@app.route('/admin/api/employees/<int:user_id>', methods=['PUT'])
@csrf.exempt
def api_update_employee(user_id):
    if not session.get('logged_in') or session.get('role') != 'admin':
        return jsonify({"success": False, "message": "Unauthorized"}), 403

    data = request.get_json()
    print("🔥 RAW DATA:", data)

    conn = db_connection()
    cursor = conn.cursor(dictionary=True)

    # Check if user exists and is an employee
    cursor.execute("SELECT id, role, name FROM users WHERE id = %s", (user_id,))
    emp = cursor.fetchone()
    if not emp:
        conn.close()
        return jsonify({"success": False, "message": "Employee not found"}), 404
    if emp['role'] != 'employee':
        conn.close()
        return jsonify({"success": False, "message": "User is not an employee"}), 400

    # Email uniqueness (if changing email)
    new_email = data.get('email')
    if new_email:
        cursor.execute("SELECT id FROM users WHERE email=%s AND id!=%s", (new_email, user_id))
        if cursor.fetchone():
            conn.close()
            return jsonify({"success": False, "message": "Email already exists"}), 400

    # Extract fields with proper defaults
    name = data.get('name', '')
    email = new_email if new_email else emp['email']
    position = (data.get('position') or '').strip()
    if not position:
        position = 'Staff'
    daily_rate = data.get('daily_rate', 500)
    contact_number = data.get('contact_number', '')
    address = data.get('address', '')

    print(f"✏️ Updating user {user_id} (role={emp['role']}) with position={position}, daily_rate={daily_rate}")

    # Update the database
    cursor.execute("""
        UPDATE users 
        SET name=%s, email=%s, position=%s, daily_rate=%s,
            contact_number=%s, address=%s
        WHERE id=%s AND role='employee'
    """, (name, email, position, daily_rate, contact_number, address, user_id))
    conn.commit()
    affected = cursor.rowcount
    conn.close()

    print(f"✅ Rows affected: {affected}")

    if affected:
        # Log the action for audit trail
        log_audit(session['user_id'], "EMPLOYEE_UPDATE", 
                  f"Updated employee {emp['name']} (ID: {user_id}): position='{position}', daily_rate={daily_rate}", request)
        # Notify the employee
        create_notification(user_id, "Your profile was updated by HR.", url_for('employee_dashboard') + "#emp-profile")
        return jsonify({"success": True, "message": "Employee updated"})
    else:
        return jsonify({"success": False, "message": "No changes made or employee not found"}), 200
    
@app.route('/employee/leave_requests_json')
def employee_leave_requests_json():
    if not session.get('logged_in') or session.get('role') != 'employee':
        return jsonify({"success": False, "message": "Unauthorized"}), 403
    user_id = session['user_id']
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT id, leave_type, start_date, end_date, status, reason
        FROM leave_requests WHERE user_id = %s ORDER BY created_at DESC LIMIT 10
    """, (user_id,))
    requests = cursor.fetchall()
    conn.close()
    return jsonify({"success": True, "requests": requests})

@app.route('/admin/api/positions')
def api_get_positions():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return jsonify({"success": False, "message": "Unauthorized"}), 403

    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT DISTINCT position FROM users WHERE role='employee' AND position IS NOT NULL AND position != '' ORDER BY position")
    rows = cursor.fetchall()
    conn.close()
    positions = [row['position'] for row in rows]
    if not positions:
        positions = [
            'Sales and Marketing Staff', 'Operations and Delivery Staff', 'HR Officer',
            'Finance Officer', 'Admin Staff', 'General Manager', 'Delivery Driver', 'Warehouse Staff'
        ]
    return jsonify({"success": True, "positions": positions})

@app.route('/admin/api/payroll_calc', methods=['POST'])
def admin_api_payroll_calc():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return jsonify({"success": False, "message": "Unauthorized"}), 403
    
    data = request.get_json()
    employee_id = data.get('employee_id')
    days_worked = int(data.get('days_worked', 0))
    overtime_hours = float(data.get('overtime_hours', 0))
    late_minutes = int(data.get('late_minutes', 0))
    undertime_minutes = int(data.get('undertime_minutes', 0))
    
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, name, position, daily_rate FROM users WHERE id = %s AND role='employee'", (employee_id,))
    emp = cursor.fetchone()
    
    if not emp:
        conn.close()
        return jsonify({"success": False, "message": "Employee not found"}), 404
    
    daily_rate = float(emp['daily_rate'] or 500)
    hourly_rate = daily_rate / 8
    
    basic_pay = days_worked * daily_rate
    overtime_pay = overtime_hours * hourly_rate * 1.25
    tardiness_deduction = (late_minutes / 60) * hourly_rate
    undertime_deduction = (undertime_minutes / 60) * hourly_rate
    gross_pay = basic_pay + overtime_pay
    
    # Accurate contributions (convert to float to avoid Decimal + float error)
    monthly_basis = days_worked * daily_rate
    sss = float(compute_sss_contribution(monthly_basis) or 0)
    philhealth = float(compute_philhealth_contribution(monthly_basis) or 0)
    pagibig = float(compute_pagibig_contribution(monthly_basis) or 0)
    
    taxable_income = gross_pay - (sss + philhealth + pagibig)
    withholding_tax = float(compute_withholding_tax(taxable_income) or 0)
    
    # Cash Advance Deduction (if any)
    cash_advance_deduction = 0.0
    cursor.execute("""
        SELECT amount, repayment_months, remaining_balance
        FROM cash_advances
        WHERE user_id = %s AND status = 'approved' AND remaining_balance > 0
        ORDER BY id LIMIT 1
    """, (employee_id,))
    ca = cursor.fetchone()
    if ca:
        if ca['repayment_months'] == 0:
            cash_advance_deduction = float(ca['remaining_balance'] or 0)
        else:
            cash_advance_deduction = float(ca['amount'] or 0) / float(ca['repayment_months'])
    
    total_deductions = (sss + philhealth + pagibig + withholding_tax + 
                        tardiness_deduction + undertime_deduction + cash_advance_deduction)
    net_pay = gross_pay - total_deductions
    net_pay = max(0, net_pay)

    conn.close()
    
    return jsonify({
        "success": True,
        "basic_pay": round(basic_pay, 2),
        "overtime_pay": round(overtime_pay, 2),
        "gross_pay": round(gross_pay, 2),
        "tardiness_deduction": round(tardiness_deduction, 2),
        "undertime_deduction": round(undertime_deduction, 2),
        "sss": round(sss, 2),
        "philhealth": round(philhealth, 2),
        "pagibig": round(pagibig, 2),
        "withholding_tax": round(withholding_tax, 2),
        "cash_advance_deduction": round(cash_advance_deduction, 2),
        "total_deductions": round(total_deductions, 2),
        "net_pay": round(net_pay, 2),
        "employee_name": emp['name']
    })

@limiter.exempt
@app.route('/admin/api/generated_reports')
def admin_api_generated_reports():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return jsonify({"success": False, "message": "Unauthorized"}), 403
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT gr.*, u.name as employee_name
        FROM generated_reports gr
        JOIN users u ON gr.user_id = u.id
        ORDER BY gr.created_at DESC
    """)
    reports = cursor.fetchall()
    conn.close()
    for r in reports:
        if r['created_at']:
            r['created_at'] = r['created_at'].strftime('%Y-%m-%d %H:%M:%S')
    return jsonify({"success": True, "reports": reports})

@app.route('/admin/api/employees/deactivate/<int:user_id>', methods=['POST'])
def admin_deactivate_employee(user_id):
    if not session.get('logged_in') or session.get('role') != 'admin':
        return jsonify({"success": False, "message": "Unauthorized"}), 403
    conn = db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET status = 'inactive' WHERE id = %s AND role = 'employee'", (user_id,))
    conn.commit()
    affected = cursor.rowcount
    conn.close()
    if affected:
        create_notification(user_id, "Your account has been deactivated. Contact HR for reactivation.", None)
        return jsonify({"success": True, "message": "Employee deactivated"})
    return jsonify({"success": False, "message": "Employee not found"}), 404

@app.route('/admin/api/employees/reactivate/<int:user_id>', methods=['POST'])
def admin_reactivate_employee(user_id):
    if not session.get('logged_in') or session.get('role') != 'admin':
        return jsonify({"success": False, "message": "Unauthorized"}), 403
    conn = db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET status = 'active' WHERE id = %s AND role = 'employee'", (user_id,))
    conn.commit()
    affected = cursor.rowcount
    conn.close()
    if affected:
        create_notification(user_id, "Your account has been reactivated. You can now log in.", None)
        return jsonify({"success": True, "message": "Employee reactivated"})
    return jsonify({"success": False, "message": "Employee not found"}), 404

# The hard delete route already exists (api_delete_employee). It uses DELETE method.
# No change needed.


# =============================================================================
# CHARTS API (unchanged)
# =============================================================================
@app.route('/admin/api/attendance_summary')
def api_attendance_summary():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return jsonify({"error": "Unauthorized"}), 403
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT COUNT(*) as total FROM users WHERE role='employee'")
    total_employees = cursor.fetchone()['total']
    days = []
    present = []
    late = []
    absent = []
    for i in range(6, -1, -1):
        date = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
        days.append(date)
        cursor.execute("SELECT COUNT(*) as cnt FROM attendance WHERE log_date=%s AND status='On Time'", (date,))
        present_cnt = cursor.fetchone()['cnt']
        present.append(present_cnt)
        cursor.execute("SELECT COUNT(*) as cnt FROM attendance WHERE log_date=%s AND status='Late'", (date,))
        late_cnt = cursor.fetchone()['cnt']
        late.append(late_cnt)
        absent.append(total_employees - (present_cnt + late_cnt))
    conn.close()
    return jsonify({"days": days, "present": present, "late": late, "absent": absent})

@app.route('/admin/api/payroll_trend')
def api_payroll_trend():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return jsonify({"error": "Unauthorized"}), 403
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    months = []
    amounts = []
    for i in range(5, -1, -1):
        month_date = datetime.now().replace(day=1) - timedelta(days=30*i)
        month_name = month_date.strftime('%b %Y')
        months.append(month_name)
        cursor.execute("SELECT SUM(net_pay) as total FROM payroll WHERE MONTH(date_paid)=%s AND YEAR(date_paid)=%s", (month_date.month, month_date.year))
        total = cursor.fetchone()['total'] or 0
        amounts.append(total)
    conn.close()
    return jsonify({"months": months, "amounts": amounts})

@app.route('/admin/api/pending_requests')
def admin_api_pending_requests():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return jsonify({"success": False, "message": "Unauthorized"}), 403
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Pending leave requests (include employee name and leave id)
    cursor.execute("""
        SELECT l.id, l.leave_type, l.start_date, u.name as employee_name, 'leave' as type
        FROM leave_requests l
        JOIN users u ON l.user_id = u.id
        WHERE l.status = 'Pending'
        ORDER BY l.created_at DESC
    """)
    leaves = cursor.fetchall()
    
    # Pending overtime requests
    cursor.execute("""
        SELECT ot.id, ot.overtime_date, ot.hours, u.name as employee_name, 'overtime' as type
        FROM overtime_requests ot
        JOIN users u ON ot.user_id = u.id
        WHERE ot.status = 'Pending'
        ORDER BY ot.created_at DESC
    """)
    overtimes = cursor.fetchall()
    
    # Pending cash advances
    cursor.execute("""
        SELECT ca.id, ca.amount, u.name as employee_name, 'cash_advance' as type
        FROM cash_advances ca
        JOIN users u ON ca.user_id = u.id
        WHERE ca.status = 'pending'
        ORDER BY ca.created_at DESC
    """)
    cash_advances = cursor.fetchall()

    # Pending loan requests
    cursor.execute("""
    SELECT lr.id, lr.amount, lr.status, u.name as employee_name, 'loan' as type
    FROM loan_requests lr
    JOIN users u ON lr.user_id = u.id
    WHERE lr.status = 'pending'
    ORDER BY lr.created_at DESC
    """)
    loans = cursor.fetchall()
    
    conn.close()
    
    # Combine and add URLs
    all_requests = []
    for l in leaves:
        all_requests.append({
            'id': l['id'],
            'text': f"Leave request from {l['employee_name']} ({l['leave_type']}) starting {l['start_date']}",
            'url': f"/admin/dashboard#leaves-tab?highlight={l['id']}",  # or just #leaves-tab
            'type': 'leave'
        })
    for ot in overtimes:
        all_requests.append({
            'id': ot['id'],
            'text': f"Overtime request from {ot['employee_name']} on {ot['overtime_date']} ({ot['hours']} hrs)",
            'url': "/admin/overtime_requests",
            'type': 'overtime'
        })
    for ca in cash_advances:
        all_requests.append({
            'id': ca['id'],
            'text': f"Cash advance request from {ca['employee_name']} (₱{float(ca['amount']):,.2f})",
            'url': "/admin/loans",
            'type': 'cash_advance'
        })
    for loan in loans:
        all_requests.append({
        'id': loan['id'],
        'text': f"Loan request from {loan['employee_name']} (₱{float(loan['amount']):,.2f})",
        'url': "/admin/loans",   # or create a dedicated loan requests page
        'type': 'loan'
    })

    total = len(all_requests)
    return jsonify({"success": True, "total": total, "requests": all_requests})

@limiter.exempt
@app.route('/admin/api/pending_counts')
def admin_api_pending_counts():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return jsonify({"success": False, "message": "Unauthorized"}), 403
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT COUNT(*) as cnt FROM leave_requests WHERE status = 'Pending'")
    leaves = cursor.fetchone()['cnt']
    cursor.execute("SELECT COUNT(*) as cnt FROM overtime_requests WHERE status = 'Pending'")
    overtime = cursor.fetchone()['cnt']
    cursor.execute("SELECT COUNT(*) as cnt FROM cash_advances WHERE status = 'pending'")
    ca = cursor.fetchone()['cnt']
    conn.close()
    return jsonify({"success": True, "leaves": leaves, "overtime": overtime, "ca": ca})
# =============================================================================
# EMPLOYEE CHANGE PASSWORD (unchanged)
# =============================================================================
@app.route('/employee/change_password', methods=['POST'])
def employee_change_password():
    if not session.get('logged_in') or session.get('role') != 'employee':
        return redirect(url_for('index'))

    old = request.form.get('old_password')
    new = request.form.get('new_password')
    confirm = request.form.get('confirm_password')

    if new != confirm:
        flash("New passwords do not match")
        return redirect(url_for('employee_dashboard') + '#emp-profile')  # ✅

    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT password FROM users WHERE id=%s", (session['user_id'],))
    current = cursor.fetchone()

    if not check_password_hash(current['password'], old):
        flash("Old password is incorrect")
        conn.close()
        return redirect(url_for('employee_dashboard') + '#emp-profile')  # ✅

    new_hashed = generate_password_hash(new)
    cursor.execute("UPDATE users SET password=%s WHERE id=%s", (new_hashed, session['user_id']))
    conn.commit()
    conn.close()

    create_notification(session['user_id'], "Your password was changed successfully.", None)
    flash("Password changed successfully")
    return redirect(url_for('employee_dashboard') + '#emp-profile')  # ✅
# =============================================================================
# OVERTIME REQUEST (Employee)
# =============================================================================
@app.route('/employee/request_overtime', methods=['POST'])
def employee_request_overtime():
    if 'user_id' not in session or session.get('role') != 'employee':
        flash("Unauthorized access.")
        return redirect(url_for('index'))
    date = request.form.get('overtime_date')
    hours = request.form.get('overtime_hours')
    reason = request.form.get('overtime_reason')
    conn = db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS overtime_requests (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            overtime_date DATE NOT NULL,
            hours DECIMAL(5,2) NOT NULL,
            reason TEXT,
            status ENUM('Pending','Approved','Rejected') DEFAULT 'Pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        INSERT INTO overtime_requests (user_id, overtime_date, hours, reason, status)
        VALUES (%s, %s, %s, %s, 'Pending')
    """, (session['user_id'], date, hours, reason))
    conn.commit()
    conn.close()
    flash("Overtime request submitted.")
    return redirect(url_for('employee_dashboard'))

@app.route('/employee/request_cash_advance', methods=['POST'])
def employee_request_cash_advance():
    if not session.get('logged_in') or session.get('role') != 'employee':
        flash("Unauthorized access.")
        return redirect(url_for('index'))
    amount = request.form.get('amount')
    repayment_months = request.form.get('repayment_months', 0)
    if not amount or float(amount) <= 0:
        flash("Invalid amount.")
        return redirect(url_for('employee_dashboard') + '#emp-cash-advance')
    conn = db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO cash_advances (user_id, amount, repayment_months, remaining_balance, status)
        VALUES (%s, %s, %s, %s, 'pending')
    """, (session['user_id'], amount, repayment_months, amount))
    conn.commit()
    conn.close()
    create_notification(session['user_id'], f"Cash advance request of ₱{float(amount):,.2f} submitted for approval.")
    flash("Cash advance request submitted.", "success")
    return redirect(url_for('employee_dashboard') + '#emp-cash-advance')

@app.route('/employee/request_loan', methods=['POST'])
def employee_request_loan():
    if not session.get('logged_in') or session.get('role') != 'employee':
        flash("Unauthorized access.")
        return redirect(url_for('index'))
    amount = request.form.get('amount')
    purpose = request.form.get('purpose')
    months_to_pay = request.form.get('months_to_pay')
    if not amount or float(amount) <= 0 or not months_to_pay:
        flash("Invalid loan details.")
        return redirect(url_for('employee_dashboard') + '#emp-loan')
    conn = db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO loan_requests (user_id, amount, purpose, months_to_pay, status)
        VALUES (%s, %s, %s, %s, 'pending')
    """, (session['user_id'], amount, purpose, months_to_pay))
    conn.commit()
    conn.close()
    create_notification(session['user_id'], f"Loan request of ₱{float(amount):,.2f} submitted for approval.")
    flash("Loan request submitted.", "success")
    return redirect(url_for('employee_dashboard') + '#emp-loan')

# =============================================================================
# ACTIVE / LATE EMPLOYEES API (unchanged)
# =============================================================================
@app.route('/admin/api/active_employees')
def api_active_employees():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return jsonify({"success": False, "message": "Unauthorized"}), 403

    today_str = datetime.now().strftime('%Y-%m-%d')
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT u.id, u.name, u.position, a.time_in
        FROM attendance a JOIN users u ON a.user_id = u.id
        WHERE a.log_date = %s AND a.time_in IS NOT NULL AND a.time_out IS NULL AND u.role = 'employee'
        ORDER BY u.name
    """, (today_str,))
    active = cursor.fetchall()
    conn.close()

    # Convert time_in to a readable string format
    for emp in active:
        if emp['time_in']:
            if isinstance(emp['time_in'], timedelta):
                total_seconds = emp['time_in'].total_seconds()
                hours = int(total_seconds // 3600)
                minutes = int((total_seconds % 3600) // 60)
                emp['time_in'] = f"{hours:02d}:{minutes:02d}"
            elif hasattr(emp['time_in'], 'strftime'):
                emp['time_in'] = emp['time_in'].strftime('%I:%M %p')
            else:
                emp['time_in'] = str(emp['time_in'])

    return jsonify({"success": True, "employees": active})

@app.route('/admin/api/late_employees')
def api_late_employees():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return jsonify({"success": False, "message": "Unauthorized"}), 403

    today_str = datetime.now().strftime('%Y-%m-%d')
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT u.id, u.name, u.position, a.time_in, a.minutes_late
        FROM attendance a JOIN users u ON a.user_id = u.id
        WHERE a.log_date = %s AND a.status = 'Late' AND u.role = 'employee'
        ORDER BY a.minutes_late DESC
    """, (today_str,))
    late = cursor.fetchall()
    conn.close()

    for emp in late:
        if emp['time_in']:
            if isinstance(emp['time_in'], timedelta):
                total_seconds = emp['time_in'].total_seconds()
                hours = int(total_seconds // 3600)
                minutes = int((total_seconds % 3600) // 60)
                emp['time_in'] = f"{hours:02d}:{minutes:02d}"
            elif hasattr(emp['time_in'], 'strftime'):
                emp['time_in'] = emp['time_in'].strftime('%I:%M %p')
            else:
                emp['time_in'] = str(emp['time_in'])

    return jsonify({"success": True, "employees": late})

@app.route('/admin/api/employees/filter')
def api_filter_employees():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return jsonify({"success": False, "message": "Unauthorized"}), 403
    position = request.args.get('position', 'all')
    search = request.args.get('search', '').strip()
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    query = "SELECT id, name, position, daily_rate, status FROM users WHERE role='employee'"
    params = []
    if position != 'all':
        query += " AND position = %s"; params.append(position)
    if search:
        query += " AND (name LIKE %s OR id LIKE %s)"; search_wild = f"%{search}%"; params.append(search_wild); params.append(search_wild)
    query += " ORDER BY name"
    cursor.execute(query, params)
    employees = cursor.fetchall()
    conn.close()
    return jsonify({"success": True, "employees": employees})

@limiter.exempt
@app.route('/admin/api/stats')
def admin_api_stats():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return jsonify({"success": False, "message": "Unauthorized"}), 403
    try:
        conn = db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Total employees
        cursor.execute("SELECT COUNT(*) as total FROM users WHERE role='employee'")
        total_employees = cursor.fetchone()['total']
        
        today_str = datetime.now().strftime('%Y-%m-%d')
        
        # Active today (clocked in, not clocked out)
        cursor.execute("""
            SELECT COUNT(DISTINCT a.user_id) as cnt
            FROM attendance a
            WHERE a.log_date = %s AND a.time_in IS NOT NULL AND a.time_out IS NULL
        """, (today_str,))
        active_today = cursor.fetchone()['cnt'] or 0
        
        # Late today
        cursor.execute("""
            SELECT COUNT(DISTINCT a.user_id) as cnt
            FROM attendance a
            WHERE a.log_date = %s AND a.status = 'Late'
        """, (today_str,))
        late_today = cursor.fetchone()['cnt'] or 0
        
        # Payroll records count
        cursor.execute("SELECT COUNT(*) as cnt FROM payroll")
        payroll_records = cursor.fetchone()['cnt'] or 0
        
        # Today's attendance list
        cursor.execute("""
            SELECT u.name, a.time_in, a.time_out, a.status
            FROM users u LEFT JOIN attendance a ON u.id = a.user_id AND a.log_date = %s
            WHERE u.role = 'employee'
            ORDER BY a.time_in IS NULL, a.time_in DESC
        """, (today_str,))
        attendance = cursor.fetchall()
        for att in attendance:
            # Convert times to strings
            if att['time_in']:
                if hasattr(att['time_in'], 'strftime'):
                    att['time_in'] = att['time_in'].strftime('%I:%M %p')
                else:
                    att['time_in'] = str(att['time_in'])
            else:
                att['time_in'] = '--:--'
            if att['time_out']:
                if hasattr(att['time_out'], 'strftime'):
                    att['time_out'] = att['time_out'].strftime('%I:%M %p')
                else:
                    att['time_out'] = str(att['time_out'])
            else:
                att['time_out'] = '--:--'
            att['status'] = att['status'] if att['status'] else '--'
        
        conn.close()
        return jsonify({
            "success": True,
            "total_employees": total_employees,
            "active_today": active_today,
            "late_today": late_today,
            "payroll_records": payroll_records,
            "attendance": attendance
        })
    except Exception as e:
        logging.error(f"Stats API error: {e}")
        return jsonify({"success": False, "message": str(e)}), 500
    
# ========== PAYROLL PREVIEW APIs ==========
@app.route('/admin/api/payroll_preview_single/<int:user_id>')
def api_payroll_preview_single(user_id):
    if not session.get('logged_in') or session.get('role') != 'admin':
        return jsonify({"success": False, "message": "Unauthorized"}), 403

    start = request.args.get('start')
    end = request.args.get('end')
    payroll_date = request.args.get('payroll_date')
    if not start or not end or not payroll_date:
        return jsonify({"success": False, "message": "Missing parameters"}), 400

    from datetime import timedelta
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, name, position, daily_rate FROM users WHERE id=%s AND role='employee'", (user_id,))
    employee = cursor.fetchone()
    if not employee:
        conn.close()
        return jsonify({"success": False, "message": "Employee not found"}), 404

    daily_rate = float(employee['daily_rate'] or 500)
    hourly_rate = daily_rate / 8

    # Attendance summary
    cursor.execute("""
        SELECT COUNT(*) as days_present,
               SUM(minutes_late) as total_late,
               SUM(undertime_minutes) as total_undertime
        FROM attendance
        WHERE user_id=%s AND log_date BETWEEN %s AND %s AND time_in IS NOT NULL
    """, (user_id, start, end))
    att = cursor.fetchone()
    days_present = int(att['days_present'] or 0)
    late_minutes = float(att['total_late'] or 0)
    undertime_minutes = float(att['total_undertime'] or 0)

    # Overtime
    cursor.execute("""
        SELECT COALESCE(SUM(hours), 0) as total_hours
        FROM overtime_requests
        WHERE user_id=%s AND status='Approved' AND overtime_date BETWEEN %s AND %s
    """, (user_id, start, end))
    overtime_hours = float(cursor.fetchone()['total_hours'] or 0)

    holiday_pay = 0.0

    basic_pay = days_present * daily_rate
    overtime_pay = overtime_hours * hourly_rate * 1.25
    tardiness_deduction = (late_minutes / 60) * hourly_rate
    undertime_deduction = (undertime_minutes / 60) * hourly_rate
    gross_pay = basic_pay + overtime_pay + holiday_pay

    # ========== ACCURATE STATUTORY DEDUCTIONS ==========
    monthly_basis = days_present * daily_rate   # basic pay for the period
    sss = compute_sss_contribution(monthly_basis)
    philhealth = compute_philhealth_contribution(monthly_basis)
    pagibig = compute_pagibig_contribution(monthly_basis)

    taxable_income = gross_pay - (sss + philhealth + pagibig)
    withholding_tax = compute_withholding_tax(taxable_income)
    total_deductions = (sss + philhealth + pagibig + withholding_tax +
                        tardiness_deduction + undertime_deduction)
    net_pay = max(0, gross_pay - total_deductions)

    # Loan deduction (preview only)
    loan_deduction = 0.0
    cursor.execute("""
        SELECT balance_amount, remaining_months, monthly_amortization
        FROM loans
        WHERE employee_id = %s AND balance_amount > 0
        ORDER BY id LIMIT 1
    """, (user_id,))
    loan = cursor.fetchone()
    if loan:
        if loan['monthly_amortization'] and loan['monthly_amortization'] > 0:
            loan_deduction = float(loan['monthly_amortization'])
        else:
            loan_deduction = float(loan['balance_amount']) / max(1, loan['remaining_months'])

    # Cash advance deduction (preview only)
    cash_advance_deduction = 0.0
    cursor.execute("""
        SELECT amount, repayment_months, remaining_balance
        FROM cash_advances
        WHERE user_id = %s AND status = 'approved' AND remaining_balance > 0
        ORDER BY id LIMIT 1
    """, (user_id,))
    ca = cursor.fetchone()
    if ca:
        if ca['repayment_months'] == 0:
            cash_advance_deduction = float(ca['remaining_balance'])
        else:
            cash_advance_deduction = float(ca['amount']) / ca['repayment_months']

    net_pay_after_loans = max(0, net_pay - loan_deduction - cash_advance_deduction)

    conn.close()

    return jsonify({"success": True, "payroll": {
        "name": employee['name'],
        "position": employee['position'],
        "days_present": days_present,
        "basic_pay": basic_pay,
        "overtime_pay": overtime_pay,
        "holiday_pay": holiday_pay,
        "gross_pay": gross_pay,
        "tardiness_deduction": tardiness_deduction,
        "undertime_deduction": undertime_deduction,
        "sss": sss,
        "philhealth": philhealth,
        "pagibig": pagibig,
        "withholding_tax": withholding_tax,
        "total_deductions": total_deductions,
        "net_pay": net_pay,
        "loan_deduction": loan_deduction,
        "cash_advance_deduction": cash_advance_deduction,
        "net_pay_after_loans": net_pay_after_loans
    }})

@app.route('/admin/api/payroll_preview_all')
def api_payroll_preview_all():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return jsonify({"success": False, "message": "Unauthorized"}), 403

    start = request.args.get('start')
    end = request.args.get('end')
    payroll_date = request.args.get('payroll_date')
    position_filter = request.args.get('position', 'all')
    employee_ids = request.args.get('employee_ids', '')

    if not start or not end or not payroll_date:
        return jsonify({"success": False, "message": "Missing parameters"}), 400

    conn = db_connection()
    cursor = conn.cursor(dictionary=True)

    if employee_ids:
        ids = [int(x) for x in employee_ids.split(',') if x.isdigit()]
        if ids:
            placeholders = ','.join(['%s'] * len(ids))
            query = f"SELECT id, name, position, daily_rate FROM users WHERE role='employee' AND id IN ({placeholders}) ORDER BY name"
            cursor.execute(query, ids)
            employees = cursor.fetchall()
        else:
            employees = []
    else:
        if position_filter and position_filter != 'all':
            cursor.execute("SELECT id, name, position, daily_rate FROM users WHERE role='employee' AND position=%s ORDER BY name", (position_filter,))
        else:
            cursor.execute("SELECT id, name, position, daily_rate FROM users WHERE role='employee' ORDER BY name")
        employees = cursor.fetchall()

    results = []
    for emp in employees:
        daily_rate = float(emp['daily_rate'] or 500)
        hourly_rate = daily_rate / 8

        cursor.execute("""
            SELECT COUNT(*) as days_present,
                   SUM(minutes_late) as total_late,
                   SUM(undertime_minutes) as total_undertime
            FROM attendance
            WHERE user_id=%s AND log_date BETWEEN %s AND %s AND time_in IS NOT NULL
        """, (emp['id'], start, end))
        att = cursor.fetchone()
        days_present = int(att['days_present'] or 0)
        late_minutes = float(att['total_late'] or 0)
        undertime_minutes = float(att['total_undertime'] or 0)

        cursor.execute("""
            SELECT COALESCE(SUM(hours), 0) as total_hours
            FROM overtime_requests
            WHERE user_id=%s AND status='Approved' AND overtime_date BETWEEN %s AND %s
        """, (emp['id'], start, end))
        overtime_hours = float(cursor.fetchone()['total_hours'] or 0)

        basic_pay = days_present * daily_rate
        overtime_pay = overtime_hours * hourly_rate * 1.25
        tardiness_deduction = (late_minutes / 60) * hourly_rate
        undertime_deduction = (undertime_minutes / 60) * hourly_rate
        gross_pay = basic_pay + overtime_pay

        # ========== ACCURATE STATUTORY DEDUCTIONS ==========
        monthly_basis = days_present * daily_rate   # basic pay for the period
        sss = compute_sss_contribution(monthly_basis)
        philhealth = compute_philhealth_contribution(monthly_basis)
        pagibig = compute_pagibig_contribution(monthly_basis)

        taxable_income = gross_pay - (sss + philhealth + pagibig)
        withholding_tax = compute_withholding_tax(taxable_income)
        total_deductions = (sss + philhealth + pagibig + withholding_tax +
                            tardiness_deduction + undertime_deduction)
        net_pay = max(0, gross_pay - total_deductions)

        results.append({
            "name": emp['name'],
            "position": emp['position'],
            "days_present": days_present,
            "gross_pay": gross_pay,
            "total_deductions": total_deductions,
            "net_pay": net_pay
        })

    conn.close()
    return jsonify({"success": True, "employees": results})
# =============================================================================
# TIMESHEET (unchanged)
# =============================================================================


@app.route('/admin/attendance/edit/<int:att_id>', methods=['POST'])
def admin_edit_attendance(att_id):
    if not session.get('logged_in') or session.get('role') != 'admin':
        return jsonify({"success": False, "message": "Unauthorized"}), 403
    data = request.get_json()
    conn = db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM attendance WHERE id=%s", (att_id,))
    result = cursor.fetchone()
    if not result:
        conn.close()
        return jsonify({"success": False, "message": "Attendance not found"}), 404
    user_id = result[0]
    cursor.execute("""
        UPDATE attendance SET time_in=%s, time_out=%s, minutes_late=%s, undertime_minutes=%s WHERE id=%s
    """, (data.get('time_in'), data.get('time_out'), data.get('minutes_late'), data.get('undertime_minutes'), att_id))
    conn.commit()
    conn.close()
    create_notification(user_id, f"Your attendance record (ID: {att_id}) has been corrected by admin. Please check your timesheet.", url_for('employee_dashboard') + "#emp-att-summary")
    return jsonify({"success": True})

# =============================================================================
# SEND MANUAL NOTIFICATION (unchanged)
# =============================================================================
@app.route('/admin/send_notification', methods=['POST'])
def admin_send_notification():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return jsonify({"success": False, "message": "Unauthorized"}), 403
    employee_id = request.form.get('employee_id')
    message = request.form.get('message')
    link = request.form.get('link', '')
    if not employee_id or not message:
        flash("Employee and message are required.")
        return redirect(url_for('admin_dashboard'))
    create_notification(employee_id, message, link if link else None)
    log_audit(session['user_id'], "MANUAL_NOTIFICATION", f"Sent notification to employee {employee_id}", request)
    flash(f"Notification sent to employee ID {employee_id}")
    return redirect(url_for('admin_dashboard'))

@app.route('/test_frame')
def test_frame():
    cam = get_camera()
    if cam is None:
        return "Camera not available", 500
    ret, frame = cam.get_frame_raw()
    if not ret or frame is None:
        return "No frame captured", 500
    ret, jpeg = cv2.imencode('.jpg', frame)
    if not ret:
        return "Encoding failed", 500
    return Response(jpeg.tobytes(), mimetype='image/jpeg')

# =============================================================================
# GENERATE PAYSLIP (EMPLOYEE & ADMIN) - with save for admin
# =============================================================================
@app.route('/employee/report/<int:report_id>')
def employee_view_report(report_id):
    if not session.get('logged_in'):
        flash("Please login first.")
        return redirect(url_for('index'))

    role = session.get('role')
    if role not in ['employee', 'admin']:
        flash("Unauthorized access.")
        return redirect(url_for('index'))

    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    if role == 'admin':
        cursor.execute("SELECT * FROM generated_reports WHERE id = %s", (report_id,))
    else:
        cursor.execute("SELECT * FROM generated_reports WHERE id = %s AND user_id = %s",
                       (report_id, session['user_id']))
    report = cursor.fetchone()
    conn.close()

    if not report:
        flash("Report not found or access denied.")
        return redirect(url_for('employee_dashboard'))

    params = json.loads(report['params'])

    if report['report_type'] == 'dtr':
        return render_dtr_report_for_employee(report['user_id'], params.get('start_date'), params.get('end_date'))
    elif report['report_type'] == 'overtime_summary':
        return render_overtime_summary_for_employee(report['user_id'], params.get('start_date'), params.get('end_date'))
    elif report['report_type'] == 'leave_summary':
        return render_leave_summary_for_employee(report['user_id'], params.get('start_date'), params.get('end_date'),
                                                 params.get('status_filter', 'Approved'))
    elif report['report_type'] == 'payslip':
        return redirect(url_for('generate_payslip', employee_id=report['user_id'],
                                start_date=params.get('start_date'), end_date=params.get('end_date')))
    else:
        flash("Unsupported report type.")
        return redirect(url_for('employee_dashboard'))
    # SAVE REPORT IF ADMIN IS GENERATING
    if role == 'admin':
        try:
            params = {'start_date': start_date, 'end_date': end_date}
            title = f"Payslip ({start_display} to {end_display})"
            conn_temp = db_connection()
            cursor_temp = conn_temp.cursor()
            cursor_temp.execute("""
                INSERT INTO generated_reports (user_id, report_type, title, params, url)
                VALUES (%s, %s, %s, %s, %s)
            """, (employee_id, 'payslip', title, json.dumps(params), ''))
            report_id = cursor_temp.lastrowid
            conn_temp.commit()
            conn_temp.close()
            actual_url = url_for('employee_view_report', report_id=report_id)
            conn_update = db_connection()
            cursor_update = conn_update.cursor()
            cursor_update.execute("UPDATE generated_reports SET url = %s WHERE id = %s", (actual_url, report_id))
            conn_update.commit()
            conn_update.close()
            create_notification(employee_id, f"Your payslip for {start_display} to {end_display} is ready.", actual_url)
        except Exception as e:
            logging.error(f"Failed to save payslip report: {e}")

    conn.close()
    return render_template('payslip_report.html',
                           start_date=start_display,
                           end_date=end_display,
                           employee=emp,
                           income=income,
                           timesheet_rows=timesheet_rows,
                           deductions=deductions,
                           additionals=additionals,
                           summary=summary,
                           current_date=datetime.now().strftime('%B %d, %Y'))

# =============================================================================
# ADMIN REPORT PAYSLIP SELECTOR (unchanged)
# =============================================================================
@app.route('/admin/reports/payslip')
def admin_report_payslip():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('admin_login_page'))
    employee_id = request.args.get('employee_id')
    start_date  = request.args.get('start_date')
    end_date    = request.args.get('end_date')
    if not employee_id or not start_date or not end_date:
        conn = db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, name, position FROM users WHERE role='employee' ORDER BY name")
        employees = cursor.fetchall()
        conn.close()
        return render_template('admin/reports/payslip_selector.html', employees=employees)
    return redirect(url_for('generate_payslip', employee_id=int(employee_id), start_date=start_date, end_date=end_date))
# =============================================================================
# ATTENDANCE LIST (FULL PAGE)
# =============================================================================
@app.route('/admin/attendance_list')
def admin_attendance_list():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('admin_login_page'))
    
    # Get filter parameters
    employee_id = request.args.get('employee_id', type=int)
    month = request.args.get('month', type=int)
    year = request.args.get('year', type=int)
    if not month:
        month = datetime.now().month
    if not year:
        year = datetime.now().year
    
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Fetch employees for dropdown
    cursor.execute("SELECT id, name FROM users WHERE role='employee' ORDER BY name")
    employees = cursor.fetchall()
    
    # Base query
    query = """
        SELECT a.*, u.name, u.position 
        FROM attendance a JOIN users u ON a.user_id = u.id 
        WHERE u.role='employee'
    """
    params = []
    if employee_id:
        query += " AND a.user_id = %s"
        params.append(employee_id)
    if month and year:
        query += " AND MONTH(a.log_date) = %s AND YEAR(a.log_date) = %s"
        params.extend([month, year])
    query += " ORDER BY a.log_date DESC, a.id DESC"
    
    cursor.execute(query, params)
    attendances = cursor.fetchall()
    
    # --- Monthly Summary (for the selected month/year) ---
    cursor.execute("""
        SELECT 
            COUNT(DISTINCT a.user_id) as total_employees,
            COUNT(a.id) as total_records,
            SUM(CASE WHEN a.status = 'Late' THEN 1 ELSE 0 END) as late_count,
            SUM(a.minutes_late) as total_late_minutes,
            SUM(a.undertime_minutes) as total_undertime_minutes
        FROM attendance a JOIN users u ON a.user_id = u.id
        WHERE u.role='employee' AND MONTH(a.log_date)=%s AND YEAR(a.log_date)=%s
    """, (month, year))
    monthly_summary = cursor.fetchone()
    
    # --- Weekly Summary (last 4 weeks from today) ---
    weekly_summary = []
    today_dt = datetime.now()
    for i in range(4):
        week_start = today_dt - timedelta(days=today_dt.weekday() + 7*i)
        week_end = week_start + timedelta(days=6)
        cursor.execute("""
            SELECT 
                COUNT(DISTINCT a.user_id) as employees_worked,
                COUNT(a.id) as total_records,
                SUM(CASE WHEN a.status = 'Late' THEN 1 ELSE 0 END) as late_count,
                SUM(a.minutes_late) as total_late_minutes,
                SUM(a.undertime_minutes) as total_undertime_minutes
            FROM attendance a JOIN users u ON a.user_id = u.id
            WHERE u.role='employee' AND a.log_date BETWEEN %s AND %s
        """, (week_start.strftime('%Y-%m-%d'), week_end.strftime('%Y-%m-%d')))
        row = cursor.fetchone()
        weekly_summary.append({
            'week_range': f"{week_start.strftime('%b %d')} - {week_end.strftime('%b %d')}",
            'employees_worked': row['employees_worked'] or 0,
            'total_records': row['total_records'] or 0,
            'late_count': row['late_count'] or 0,
            'total_late_minutes': row['total_late_minutes'] or 0,
            'total_undertime_minutes': row['total_undertime_minutes'] or 0
        })
    
    conn.close()
    
    return render_template('admin/attendance_management.html',
                           attendances=attendances,
                           employees=employees,
                           selected_emp=employee_id,
                           month=month,
                           year=year,
                           monthly_summary=monthly_summary,
                           weekly_summary=weekly_summary)

@app.route('/admin/timesheet')
def admin_timesheet():
    # Redirect old timesheet URL to the new unified attendance page
    return redirect(url_for('admin_attendance_list'))


# =============================================================================
# OVERTIME REQUESTS ADMIN (unchanged)
# =============================================================================
@app.route('/admin/overtime_requests')
def admin_overtime_requests():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('admin_login_page'))
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT ot.*, u.name, u.position 
        FROM overtime_requests ot JOIN users u ON ot.user_id = u.id
        WHERE ot.status = 'Pending' ORDER BY ot.created_at DESC
    """)
    pending_requests = cursor.fetchall()
    conn.close()
    return render_template('admin/overtime_requests.html', requests=pending_requests)

@app.route('/admin/overtime/approve/<int:ot_id>', methods=['POST'])
@csrf.exempt
def approve_overtime(ot_id):
    if not session.get('logged_in') or session.get('role') != 'admin':
        return jsonify({"success": False, "message": "Unauthorized"}), 403
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT user_id, overtime_date, hours FROM overtime_requests WHERE id=%s", (ot_id,))
    ot = cursor.fetchone()
    if not ot:
        conn.close()
        return jsonify({"success": False, "message": "Overtime request not found"}), 404
    cursor.execute("UPDATE overtime_requests SET status='Approved' WHERE id=%s", (ot_id,))
    conn.commit()
    create_notification(ot['user_id'], f"✅ Your overtime request for {ot['overtime_date']} ({ot['hours']} hours) has been approved.", url_for('employee_dashboard') + "#emp-overtime")
    log_audit(session['user_id'], "OVERTIME_APPROVE", f"Approved overtime request {ot_id} for user {ot['user_id']}", request)
    conn.close()
    return jsonify({"success": True, "message": "Overtime request approved"})

@app.route('/admin/overtime/reject/<int:ot_id>', methods=['POST'])
def reject_overtime(ot_id):
    if not session.get('logged_in') or session.get('role') != 'admin':
        return jsonify({"success": False, "message": "Unauthorized"}), 403
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT user_id, overtime_date FROM overtime_requests WHERE id=%s", (ot_id,))
    ot = cursor.fetchone()
    if not ot:
        conn.close()
        return jsonify({"success": False, "message": "Overtime request not found"}), 404
    cursor.execute("UPDATE overtime_requests SET status='Rejected' WHERE id=%s", (ot_id,))
    conn.commit()
    create_notification(ot['user_id'], f"❌ Your overtime request for {ot['overtime_date']} has been rejected. Please contact HR for details.", url_for('employee_dashboard') + "#emp-overtime")
    log_audit(session['user_id'], "OVERTIME_REJECT", f"Rejected overtime request {ot_id} for user {ot['user_id']}", request)
    conn.close()
    return jsonify({"success": True, "message": "Overtime request rejected"})

# =============================================================================
# REPORTS DASHBOARD (unchanged)
# =============================================================================
@app.route('/admin/reports_dashboard')
def admin_reports_dashboard():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('admin_login_page'))
    report_stats = {
        'total_payroll_reports': 24,
        'total_deductions_reports': 18,
        'total_tax_reports': 12,
        'reports_downloaded': 156,
        'scheduled_reports': 3
    }
    available_reports = [
        {'title': 'Annual Employee Earnings Summary', 'description': 'Yearly earnings per employee with YTD totals'},
        {'title': 'Monthly Statutory Contributions', 'description': 'SSS, PhilHealth, Pag-IBIG breakdown by month'},
        {'title': 'Employee Leave Credits Report', 'description': 'Leave balances and usage'},
        {'title': 'Overtime Summary Report', 'description': 'Overtime hours and pay by department'},
        {'title': 'Department Payroll Cost', 'description': 'Payroll expenses per department'},
        {'title': 'Loan Amortization Schedule', 'description': 'Remaining loan balances and payments'},
    ]
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT r.*, u.name as generated_by 
        FROM generated_reports r JOIN users u ON r.user_id = u.id 
        ORDER BY r.created_at DESC LIMIT 10
    """)
    recent_reports = cursor.fetchall()
    conn.close()
    return render_template('admin/reports_dashboard.html', stats=report_stats,
                           available_reports=available_reports, recent_reports=recent_reports)

# =============================================================================
# PAYROLL LIST (with search & pagination)
# =============================================================================
@app.route('/admin/payroll_list')
def admin_payroll_list():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('admin_login_page'))

    conn = db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT p.*, u.name, u.position
        FROM payroll p
        JOIN users u ON p.user_id = u.id
        WHERE u.role = 'employee'
        ORDER BY p.date_paid DESC, u.name
    """)
    payrolls = cursor.fetchall()
    conn.close()

    return render_template('admin/payroll_list.html', payrolls=payrolls)

@app.route('/admin/payroll/regenerate_bulk', methods=['GET', 'POST'])
def admin_payroll_regenerate_bulk():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('admin_login_page'))
    
    result = None
    if request.method == 'POST':
        start_date = request.form.get('start_date')
        end_date = request.form.get('end_date')
        if not start_date or not end_date:
            flash("Please provide both start and end dates.", "danger")
            return redirect(url_for('admin_payroll_regenerate_bulk'))
        
        conn = db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT id, user_id, cutoff_period, date_paid, status
            FROM payroll
            WHERE date_paid BETWEEN %s AND %s
            ORDER BY date_paid
        """, (start_date, end_date))
        payrolls = cursor.fetchall()
        conn.close()
        
        regenerated = 0
        errors = []
        for pay in payrolls:
            parts = pay['cutoff_period'].split(' to ')
            if len(parts) != 2:
                errors.append(f"Invalid cutoff period format for ID {pay['id']}")
                continue
            cutoff_start = parts[0].strip()
            cutoff_end = parts[1].strip()
            try:
                conn2 = db_connection()
                cursor2 = conn2.cursor()
                cursor2.execute("DELETE FROM payroll WHERE id = %s", (pay['id'],))
                conn2.commit()
                conn2.close()
                compute_payroll_for_employee(pay['user_id'], cutoff_start, cutoff_end, pay['date_paid'].strftime('%Y-%m-%d'), pay['status'])
                regenerated += 1
            except Exception as e:
                errors.append(f"Payroll ID {pay['id']}: {str(e)}")
        
        result = {"regenerated": regenerated, "errors": errors}
        flash(f"Regenerated {regenerated} payroll records.", "success")
    
    return render_template('admin/payroll_regenerate.html', result=result)

@app.route('/admin/api/timesheet/<int:user_id>')
def api_timesheet(user_id):
    if not session.get('logged_in') or session.get('role') != 'admin':
        return jsonify({"success": False, "message": "Unauthorized"}), 403

    start = request.args.get('start')
    end = request.args.get('end')
    if not start or not end:
        return jsonify({"success": False, "message": "Missing start/end dates"}), 400

    from datetime import timedelta
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)

    # Fetch attendance records
    cursor.execute("""
        SELECT log_date, time_in, time_out, minutes_late, undertime_minutes, status
        FROM attendance
        WHERE user_id = %s AND log_date BETWEEN %s AND %s
        ORDER BY log_date
    """, (user_id, start, end))
    records = cursor.fetchall()

    # Fetch approved overtime hours
    cursor.execute("""
        SELECT COALESCE(SUM(hours), 0) as total_overtime
        FROM overtime_requests
        WHERE user_id = %s AND status = 'Approved'
          AND overtime_date BETWEEN %s AND %s
    """, (user_id, start, end))
    overtime = float(cursor.fetchone()['total_overtime'] or 0)

    conn.close()

    # ---- SAFE CONVERSION FUNCTION ----
    def safe_str(val):
        if val is None:
            return '--:--'
        if isinstance(val, timedelta):
            total_sec = int(val.total_seconds())
            h = total_sec // 3600
            m = (total_sec % 3600) // 60
            return f"{h:02d}:{m:02d}"
        if hasattr(val, 'strftime'):
            return val.strftime('%H:%M')
        return str(val)

    # Apply to every record
    for rec in records:
        rec['time_in'] = safe_str(rec.get('time_in'))
        rec['time_out'] = safe_str(rec.get('time_out'))
        # Also convert log_date to string
        if 'log_date' in rec and hasattr(rec['log_date'], 'strftime'):
            rec['log_date'] = rec['log_date'].strftime('%Y-%m-%d')

    print("Timesheet records converted, ready to send:", len(records))  # debug

    return jsonify({
        "success": True,
        "timesheet": records,
        "approved_overtime_hours": overtime
    })


@app.route('/admin/check_payroll')
def check_payroll():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return "Unauthorized"
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT COUNT(*) as total FROM payroll")
    total = cursor.fetchone()['total']
    cursor.execute("SELECT * FROM payroll LIMIT 5")
    rows = cursor.fetchall()
    conn.close()
    return jsonify({"total_records": total, "sample": rows})

@app.route('/admin/api/check_position/<int:user_id>')
def check_position(user_id):
    if not session.get('logged_in') or session.get('role') != 'admin':
        return jsonify({"error": "Unauthorized"}), 403
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, name, position FROM users WHERE id=%s AND role='employee'", (user_id,))
    emp = cursor.fetchone()
    conn.close()
    if emp:
        return jsonify({"success": True, "employee": emp})
    return jsonify({"success": False, "message": "Not found"}), 404

@app.route('/admin/api/employees/<int:user_id>', methods=['DELETE'])
@csrf.exempt
def api_delete_employee(user_id):
    if not session.get('logged_in') or session.get('role') != 'admin':
        return jsonify({"success": False}), 403
    conn = db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE id=%s AND role='employee'", (user_id,))
    conn.commit()
    affected = cursor.rowcount
    conn.close()
    if affected:
        return jsonify({"success": True, "message": "Deleted"})
    else:
        return jsonify({"success": False, "message": "Employee not found or not an employee"}), 404

@app.route('/admin/audit_logs')
def admin_audit_logs():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('admin_login_page'))
    
    # Get filter parameters
    page = request.args.get('page', 1, type=int)
    per_page = 20
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    action_filter = request.args.get('action')
    search = request.args.get('search', '').strip()
    
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Base query
    query = """
        SELECT a.*, u.name as admin_name
        FROM audit_logs a
        LEFT JOIN users u ON a.user_id = u.id
        WHERE 1=1
    """
    params = []
    
    if start_date:
        query += " AND DATE(a.created_at) >= %s"
        params.append(start_date)
    if end_date:
        query += " AND DATE(a.created_at) <= %s"
        params.append(end_date)
    if action_filter:
        query += " AND a.action = %s"
        params.append(action_filter)
    if search:
        query += " AND (a.action LIKE %s OR a.details LIKE %s OR u.name LIKE %s)"
        search_pattern = f"%{search}%"
        params.extend([search_pattern, search_pattern, search_pattern])
    
    # Count total records
    count_query = query.replace("SELECT a.*, u.name as admin_name", "SELECT COUNT(*) as total")
    cursor.execute(count_query, params)
    total = cursor.fetchone()['total']
    total_pages = (total + per_page - 1) // per_page
    
    # Fetch paginated logs
    query += " ORDER BY a.created_at DESC LIMIT %s OFFSET %s"
    params.extend([per_page, (page-1)*per_page])
    cursor.execute(query, params)
    logs = cursor.fetchall()
    
    # Get distinct actions for filter dropdown
    cursor.execute("SELECT DISTINCT action FROM audit_logs ORDER BY action")
    action_list = [row['action'] for row in cursor.fetchall()]
    
    conn.close()
    
    return render_template('admin/audit_logs.html',
                           logs=logs,
                           page=page,
                           total_pages=total_pages,
                           action_list=action_list,
                           start_date=start_date,
                           end_date=end_date,
                           action_filter=action_filter,
                           search=search)

@app.route('/admin/backup/download')
def admin_backup_download():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('admin_login_page'))
    
    # Load MySQL path from .env
    mysqldump_path = os.getenv('MYSQLDUMP_PATH')
    if not mysqldump_path:
        flash("Backup configuration missing: MYSQLDUMP_PATH not set in .env", "danger")
        return redirect(url_for('admin_backup_restore_page'))
    
    if not os.path.exists(mysqldump_path):
        flash(f"mysqldump not found at: {mysqldump_path}", "danger")
        return redirect(url_for('admin_backup_restore_page'))
    
    # Database credentials
    DB_HOST = 'localhost'
    DB_USER = 'root'
    DB_PASSWORD = ''
    DB_NAME = 'bp_system_db'
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"brightpath_backup_{timestamp}.sql"
    
    try:
        # Use full path to mysqldump
        dump_cmd = [
            mysqldump_path,
            f'--host={DB_HOST}',
            f'--user={DB_USER}',
            f'--password={DB_PASSWORD}',
            DB_NAME
        ]
        result = subprocess.run(dump_cmd, capture_output=True, text=True, shell=True)
        if result.returncode != 0:
            flash("Backup failed: " + result.stderr, "danger")
            return redirect(url_for('admin_backup_restore_page'))
        
        response = make_response(result.stdout)
        response.headers['Content-Type'] = 'application/sql'
        response.headers['Content-Disposition'] = f'attachment; filename={filename}'
        return response
    except Exception as e:
        flash(f"Backup error: {e}", "danger")
        return redirect(url_for('admin_backup_restore_page'))

@app.route('/admin/backup/restore', methods=['POST'])
def admin_backup_restore():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('admin_login_page'))
    
    if 'backup_file' not in request.files:
        flash("No file uploaded", "danger")
        return redirect(url_for('admin_backup_restore_page'))
    
    file = request.files['backup_file']
    if file.filename == '':
        flash("No file selected", "danger")
        return redirect(url_for('admin_backup_restore_page'))
    
    if not file.filename.endswith('.sql'):
        flash("Only .sql files are allowed", "danger")
        return redirect(url_for('admin_backup_restore_page'))
    
    # Load MySQL path from .env
    mysql_path = os.getenv('MYSQL_PATH')
    if not mysql_path:
        flash("Restore configuration missing: MYSQL_PATH not set in .env", "danger")
        return redirect(url_for('admin_backup_restore_page'))
    
    if not os.path.exists(mysql_path):
        flash(f"mysql not found at: {mysql_path}", "danger")
        return redirect(url_for('admin_backup_restore_page'))
    
    # Create temp directory (Windows compatible)
    temp_dir = os.path.join(os.path.dirname(__file__), 'temp_backup')
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)
    
    temp_path = os.path.join(temp_dir, secure_filename(file.filename))
    file.save(temp_path)
    
    # Database credentials
    DB_HOST = 'localhost'
    DB_USER = 'root'
    DB_PASSWORD = ''
    DB_NAME = 'bp_system_db'
    
    try:
        restore_cmd = [
            mysql_path,
            f'--host={DB_HOST}',
            f'--user={DB_USER}',
            f'--password={DB_PASSWORD}',
            DB_NAME
        ]
        with open(temp_path, 'r', encoding='utf-8') as f:
            subprocess.run(restore_cmd, stdin=f, check=True, shell=True)
        
        log_audit(session['user_id'], "DATABASE_RESTORE", f"Restored database from {file.filename}", request)
        flash("Database restored successfully. Please log in again.", "success")
        session.clear()
        return redirect(url_for('admin_login_page'))
    except subprocess.CalledProcessError as e:
        flash(f"Restore failed: {e.stderr if e.stderr else 'Unknown error'}", "danger")
        return redirect(url_for('admin_backup_restore_page'))
    except Exception as e:
        flash(f"Restore error: {e}", "danger")
        return redirect(url_for('admin_backup_restore_page'))
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

@app.route('/admin/backup')
def admin_backup_restore_page():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('admin_login_page'))
    return render_template('admin/backup_restore.html')

@app.route('/admin/cash_advances')
def admin_cash_advances():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('admin_login_page'))
    
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT ca.*, u.name as employee_name
        FROM cash_advances ca
        JOIN users u ON ca.user_id = u.id
        ORDER BY 
            CASE ca.status 
                WHEN 'pending' THEN 1 
                WHEN 'approved' THEN 2 
                ELSE 3 
            END,
            ca.created_at DESC
    """)
    advances = cursor.fetchall()
    conn.close()
    return render_template('admin/cash_advances.html', advances=advances)

@app.route('/admin/api/cash_advances/reject/<int:ca_id>', methods=['POST'])
@csrf.exempt
def admin_api_reject_cash_advance(ca_id):
    if not session.get('logged_in') or session.get('role') != 'admin':
        return jsonify({"success": False, "message": "Unauthorized"}), 403
    
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT user_id, amount FROM cash_advances WHERE id = %s", (ca_id,))
    ca = cursor.fetchone()
    
    if not ca:
        conn.close()
        return jsonify({"success": False, "message": "Cash advance not found"}), 404
    
    # Update status to 'rejected' (you may need to add 'rejected' to ENUM if not present)
    # If 'rejected' is not in ENUM, you can just delete the record or set status to 'rejected'
    # For simplicity, we'll delete or mark as rejected. Let's update status.
    try:
        cursor.execute("UPDATE cash_advances SET status = 'rejected' WHERE id = %s", (ca_id,))
        conn.commit()
        # Notify employee
        create_notification(ca['user_id'], f"Your cash advance request of ₱{float(ca['amount']):,.2f} has been rejected.", None)
        log_audit(session['user_id'], "CASH_ADVANCE_REJECT", f"Rejected cash advance ID {ca_id} for user {ca['user_id']}", request)
        conn.close()
        return jsonify({"success": True, "message": "Cash advance rejected"})
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({"success": False, "message": str(e)}), 500
@app.route('/admin/api/employee/add_leave_credits', methods=['POST'])
@csrf.exempt
def api_add_employee_leave_credits():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return jsonify({"success": False, "message": "Unauthorized"}), 403
    
    data = request.get_json()
    employee_id = data.get('employee_id')
    credits = float(data.get('credits', 0))
    
    if not employee_id or credits <= 0:
        return jsonify({"success": False, "message": "Invalid request"}), 400
    
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("SELECT id, name, leave_credits FROM users WHERE id = %s AND role = 'employee'", (employee_id,))
    emp = cursor.fetchone()
    if not emp:
        conn.close()
        return jsonify({"success": False, "message": "Employee not found"}), 404
    
    # SAFE CONVERSION: Convert Decimal to float
    current_credits = float(emp['leave_credits']) if emp['leave_credits'] is not None else 0.0
    new_credits = current_credits + credits
    
    cursor.execute("UPDATE users SET leave_credits = %s WHERE id = %s", (new_credits, employee_id))
    conn.commit()
    
    log_audit(session['user_id'], "ADD_LEAVE_CREDITS", f"Added {credits} leave credits to employee {emp['name']} (ID: {employee_id})", request)
    create_notification(employee_id, f"Your leave credits have been increased by {credits}. Total credits: {new_credits:.1f}", url_for('employee_dashboard') + "#emp-profile")
    
    conn.close()
    return jsonify({"success": True, "new_leave_credits": new_credits})
    
# =============================================================================
# MAIN
# =============================================================================
 
if __name__ == '__main__':
    get_camera()
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)