import math
from datetime import datetime, timedelta

class PayrollEngine:
    def __init__(self, db_connection):
        self.db = db_connection
        
    def get_employee_rate(self, user_id):
        """Get employee's rate based on employment type"""
        cursor = self.db.cursor(dictionary=True)
        cursor.execute("SELECT daily_rate, monthly_salary, hourly_rate, employment_type FROM users WHERE id = %s", (user_id,))
        return cursor.fetchone()
    
    def compute_tardiness_undertime(self, user_id, cutoff_start, cutoff_end):
        """Calculate total minutes late and undertime for the period"""
        cursor = self.db.cursor(dictionary=True)
        query = """
            SELECT 
                SUM(minutes_late) as total_late,
                SUM(minutes_undertime) as total_undertime,
                SUM(minutes_overtime) as total_overtime,
                COUNT(*) as days_present
            FROM attendance_details ad
            JOIN attendance a ON ad.attendance_id = a.id
            WHERE a.user_id = %s 
            AND a.log_date BETWEEN %s AND %s
            AND a.time_in IS NOT NULL
        """
        cursor.execute(query, (user_id, cutoff_start, cutoff_end))
        result = cursor.fetchone()
        return {
            'late_minutes': result['total_late'] or 0,
            'undertime_minutes': result['total_undertime'] or 0,
            'overtime_minutes': result['total_overtime'] or 0,
            'days_present': result['days_present'] or 0
        }
    
    def compute_basic_pay(self, user_id, days_present, hourly_rate, daily_rate, monthly_salary, employment_type):
        """Compute basic pay based on employment type"""
        if employment_type == 'monthly':
            # Pro-rated monthly salary (22 working days assumption)
            monthly_working_days = 22
            daily_rate_pro = monthly_salary / monthly_working_days
            return days_present * daily_rate_pro
        elif employment_type == 'daily':
            return days_present * daily_rate
        elif employment_type == 'hourly':
            # Assume 8 hours per day
            return days_present * 8 * hourly_rate
        return 0
    
    def compute_overtime_pay(self, overtime_minutes, hourly_rate, multiplier=1.25):
        """Overtime pay with 25% premium"""
        overtime_hours = overtime_minutes / 60
        return overtime_hours * hourly_rate * multiplier
    
    def compute_tardiness_deduction(self, late_minutes, hourly_rate):
        """Deduction per minute of tardiness"""
        late_hours = late_minutes / 60
        return late_hours * hourly_rate
    
    def compute_undertime_deduction(self, undertime_minutes, hourly_rate):
        """Deduction for leaving early"""
        undertime_hours = undertime_minutes / 60
        return undertime_hours * hourly_rate
    
    def get_contribution_rates(self, year):
        """Get current contribution rates"""
        cursor = self.db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM contribution_rates WHERE year = %s", (year,))
        return cursor.fetchone()
    
    def compute_sss(self, gross_salary):
        """SSS contribution table (example)"""
        if gross_salary <= 3250:
            return 135.00
        elif gross_salary <= 3750:
            return 157.50
        elif gross_salary <= 4250:
            return 180.00
        elif gross_salary <= 4750:
            return 202.50
        elif gross_salary <= 5250:
            return 225.00
        elif gross_salary <= 5750:
            return 247.50
        elif gross_salary <= 6250:
            return 270.00
        elif gross_salary <= 6750:
            return 292.50
        elif gross_salary <= 7250:
            return 315.00
        elif gross_salary <= 7750:
            return 337.50
        elif gross_salary <= 8250:
            return 360.00
        elif gross_salary <= 8750:
            return 382.50
        elif gross_salary <= 9250:
            return 405.00
        elif gross_salary <= 9750:
            return 427.50
        elif gross_salary <= 10250:
            return 450.00
        else:
            return 450.00 + (gross_salary - 10250) * 0.05
    
    def compute_philhealth(self, gross_salary):
        """PhilHealth contribution (3% of salary, split equally)"""
        return (gross_salary * 0.03) / 2
    
    def compute_pagibig(self, gross_salary):
        """Pag-IBIG contribution (2% of salary, max 100)"""
        return min(gross_salary * 0.02, 100)
    
    def compute_withholding_tax(self, taxable_income, status, dependents):
        """BIR withholding tax (simplified)"""
        # Personal exemption
        exemptions = {'single': 50000, 'head_of_family': 52000, 'married': 50000}
        personal_exemption = exemptions.get(status, 50000)
        dependent_exemption = dependents * 25000
        total_exemption = personal_exemption + dependent_exemption
        
        annual_taxable = max(0, (taxable_income * 12) - total_exemption)
        
        # Progressive tax rates
        if annual_taxable <= 250000:
            annual_tax = 0
        elif annual_taxable <= 400000:
            annual_tax = (annual_taxable - 250000) * 0.15
        elif annual_taxable <= 800000:
            annual_tax = 22500 + (annual_taxable - 400000) * 0.20
        elif annual_taxable <= 2000000:
            annual_tax = 102500 + (annual_taxable - 800000) * 0.25
        else:
            annual_tax = 402500 + (annual_taxable - 2000000) * 0.30
        
        return annual_tax / 12  # monthly tax
    
    def generate_payroll(self, user_id, cutoff_start, cutoff_end, payroll_date):
        """Complete payroll computation for one employee"""
        cursor = self.db.cursor(dictionary=True)
        
        # Get employee data
        cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        emp = cursor.fetchone()
        
        # Get attendance summary
        att = self.compute_tardiness_undertime(user_id, cutoff_start, cutoff_end)
        
        # Determine hourly/daily rate
        hourly_rate = emp['hourly_rate'] or (emp['daily_rate'] / 8)
        daily_rate = emp['daily_rate']
        monthly_salary = emp['monthly_salary']
        employment_type = emp['employment_type']
        
        # Compute components
        basic_pay = self.compute_basic_pay(user_id, att['days_present'], hourly_rate, daily_rate, monthly_salary, employment_type)
        overtime_pay = self.compute_overtime_pay(att['overtime_minutes'], hourly_rate)
        tardiness_deduction = self.compute_tardiness_deduction(att['late_minutes'], hourly_rate)
        undertime_deduction = self.compute_undertime_deduction(att['undertime_minutes'], hourly_rate)
        
        gross_earnings = basic_pay + overtime_pay
        
        # Contributions
        sss = self.compute_sss(gross_earnings)
        philhealth = self.compute_philhealth(gross_earnings)
        pagibig = self.compute_pagibig(gross_earnings)
        
        taxable_income = gross_earnings - sss - philhealth - pagibig
        withholding_tax = self.compute_withholding_tax(taxable_income, emp['tax_exemption_status'], emp['dependents'])
        
        total_deductions = sss + philhealth + pagibig + withholding_tax + tardiness_deduction + undertime_deduction
        net_pay = gross_earnings - total_deductions
        
        # Insert into payroll table
        query = """
            INSERT INTO payroll 
            (user_id, cutoff_period, total_days_worked, gross_pay, net_pay, date_paid, 
             sss, philhealth, pagibig, late_deduction, basic_pay, overtime_pay, 
             tardiness_deduction, undertime_deduction, gross_earnings, total_deductions, 
             withholding_tax, payroll_run_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        cutoff_period = f"{cutoff_start} to {cutoff_end}"
        values = (user_id, cutoff_period, att['days_present'], gross_earnings, net_pay, payroll_date,
                  sss, philhealth, pagibig, tardiness_deduction, basic_pay, overtime_pay,
                  tardiness_deduction, undertime_deduction, gross_earnings, total_deductions,
                  withholding_tax, 1)
        cursor.execute(query, values)
        self.db.commit()
        
        return {
            'employee': emp['name'],
            'basic_pay': basic_pay,
            'overtime_pay': overtime_pay,
            'gross_earnings': gross_earnings,
            'tardiness_deduction': tardiness_deduction,
            'undertime_deduction': undertime_deduction,
            'sss': sss,
            'philhealth': philhealth,
            'pagibig': pagibig,
            'withholding_tax': withholding_tax,
            'total_deductions': total_deductions,
            'net_pay': net_pay,
            'days_present': att['days_present'],
            'late_minutes': att['late_minutes'],
            'undertime_minutes': att['undertime_minutes']
        }