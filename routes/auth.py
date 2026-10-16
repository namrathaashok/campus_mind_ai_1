import re
import secrets
import time
from flask import Blueprint, current_app, render_template, request, redirect, url_for, flash, session, g
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from models.db import query_db, execute_db
from services.audit_service import AuditService
from services.email_service import send_recovery_email

auth_bp = Blueprint('auth', __name__)

def login_required(view):
    """Decorator to require login for a route."""
    @wraps(view)
    def wrapped_view(**kwargs):
        if g.user is None:
            flash("Please sign in to access this feature.", "warning")
            return redirect(url_for('auth.login', next=request.path))
        return view(**kwargs)
    return wrapped_view

def role_required(*roles):
    """Decorator to require specific user roles."""
    def decorator(view):
        @wraps(view)
        def wrapped_view(**kwargs):
            if g.user is None:
                flash("Please sign in first.", "warning")
                return redirect(url_for('auth.login', next=request.path))
            if g.user['role'] not in roles:
                flash(f"Access denied. Requires {' or '.join(roles)} privileges.", "danger")
                return redirect(url_for('main.dashboard'))
            return view(**kwargs)
        return wrapped_view
    return decorator

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Standard campus sign-in for Students and Staff."""
    if g.user:
        return redirect(url_for('main.dashboard'))

    if request.method == 'POST':
        login_input = request.form.get('login_input', '').strip()
        password = request.form.get('password', '').strip()

        user = query_db(
            "SELECT * FROM users WHERE (email = ? OR username = ?) AND is_active = 1",
            (login_input, login_input),
            one=True
        )

        if user and check_password_hash(user['password_hash'], password):
            if user['role'] == 'admin':
                flash("Administrator accounts must sign in through the separate Admin portal.", "warning")
                return redirect(url_for('auth.admin_login'))
            session.clear()
            session['user_id'] = user['id']
            session['role'] = user['role']
            session['full_name'] = user['full_name']
            AuditService.log(user['id'], 'USER_LOGIN', 'USER', user['id'], f"Logged in as {user['role']}")
            flash(f"Welcome back, {user['full_name']}! 👋", "success")
            if request.args.get('next'):
                return redirect(request.args.get('next'))
            return redirect(url_for('main.dashboard'))
        else:
            flash("Invalid email/username or password. Please try again.", "danger")

    return render_template('auth/login.html')

@auth_bp.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    """Dedicated Administrator sign-in portal (strictly admin-only)."""
    if g.user:
        if g.user['role'] == 'admin':
            return redirect(url_for('admin.dashboard'))
        return redirect(url_for('main.dashboard'))

    if request.method == 'POST':
        login_input = request.form.get('login_input', '').strip()
        password = request.form.get('password', '').strip()

        user = query_db(
            "SELECT * FROM users WHERE (email = ? OR username = ?) AND is_active = 1",
            (login_input, login_input),
            one=True
        )

        if (user and user['role'] == 'admin' and
                password == current_app.config['SEEDED_ADMIN_PASSWORD'] and
                check_password_hash(user['password_hash'], password)):
            session.clear()
            session['user_id'] = user['id']
            session['role'] = user['role']
            session['full_name'] = user['full_name']
            AuditService.log(user['id'], 'ADMIN_LOGIN', 'USER', user['id'], "Administrator signed in via Admin portal")
            flash(f"Welcome, {user['full_name']}! Administrator console unlocked. 🛡️", "success")
            return redirect(url_for('admin.dashboard'))
        else:
            flash("Invalid administrator credentials. Please try again.", "danger")

    return render_template('auth/admin_login.html')

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if g.user:
        return redirect(url_for('main.dashboard'))

    departments = query_db("SELECT * FROM departments ORDER BY name")

    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        username = request.form.get('username', '').strip().lower()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '').strip()
        role = request.form.get('role', 'student').strip()
        department_id = request.form.get('department_id') or None
        campus = request.form.get('campus', 'Main Innovation Campus (Harohalli)')

        # Validations
        phone_number = request.form.get('phone_number', '').strip()
        if not full_name or not username or not email or not phone_number or not password:
            flash("All fields are required.", "danger")
            return render_template('auth/register.html', departments=departments)

        if not re.fullmatch(r"\+?[0-9]{8,15}", phone_number):
            flash("Enter a valid phone number with country code.", "danger")
            return render_template('auth/register.html', departments=departments)

        if len(password) < 6:
            flash("Password must be at least 6 characters.", "danger")
            return render_template('auth/register.html', departments=departments)

        existing = query_db("SELECT 1 FROM users WHERE username = ? OR email = ?", (username, email), one=True)
        if existing:
            flash("Username or email already registered.", "danger")
            return render_template('auth/register.html', departments=departments)

        # Enforce student role by default for public registration
        if role not in ('student', 'staff'):
            role = 'student'

        pwd_hash = generate_password_hash(password)
        # Assign avatar colors
        colors = ['#1E3F20', '#2E7D32', '#00796B', '#388E3C', '#1565C0', '#6A1B9A']
        avatar_color = colors[len(username) % len(colors)]

        cur = execute_db(
                """INSERT INTO users (username, email, phone_number, password_hash, full_name, role, department_id, campus, green_points, avatar_color)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 50, ?)""",
                (username, email, phone_number, pwd_hash, full_name, role, department_id, campus, avatar_color)
        )
        new_user_id = cur.lastrowid

        AuditService.log(new_user_id, 'USER_REGISTER', 'USER', new_user_id, f"Registered new account: {username}")
        AuditService.award_points(new_user_id, 50, "Welcome Bonus for joining CampusPulse DSU!")
        
        session.clear()
        session['user_id'] = new_user_id
        session['role'] = role
        session['full_name'] = full_name

        flash(f"Account successfully created! You earned +50 Green Points welcome bonus. 🎉", "success")
        return redirect(url_for('main.dashboard'))

    return render_template('auth/register.html', departments=departments)


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    code_requested = False
    identifier = ''

    if request.method == 'POST':
        action = request.form.get('action')
        identifier = request.form.get('identifier', '').strip()

        if action == 'send_code':
            user = query_db(
                "SELECT id, email FROM users WHERE (email = ? OR username = ?) AND is_active = 1",
                (identifier.lower(), identifier.lower()),
                one=True
            ) if identifier else None
            now = time.time()
            existing = query_db(
                "SELECT created_at, expires_at FROM password_recovery_codes WHERE user_id = ?",
                (user['id'],),
                one=True
            ) if user else None
            if (user and user['email'] and
                    (not existing or now - existing['created_at'] >= 60 or existing['expires_at'] <= now)):
                code = f"{secrets.randbelow(1000000):06d}"
                execute_db(
                    """INSERT INTO password_recovery_codes (user_id, code_hash, expires_at, created_at, attempts)
                       VALUES (?, ?, ?, ?, 0)
                       ON CONFLICT(user_id) DO UPDATE SET code_hash = excluded.code_hash,
                       expires_at = excluded.expires_at, created_at = excluded.created_at, attempts = 0""",
                    (user['id'], generate_password_hash(code), now + 600, now)
                )
                if not send_recovery_email(user['email'], code):
                    execute_db("DELETE FROM password_recovery_codes WHERE user_id = ?", (user['id'],))

            code_requested = True
            flash("If the account exists, a verification code has been sent to its email address.", "info")

        elif action == 'reset_password':
            code_requested = True
            code = request.form.get('code', '').strip()
            password = request.form.get('password', '')
            confirm_password = request.form.get('confirm_password', '')
            user = query_db(
                "SELECT id FROM users WHERE (email = ? OR username = ?) AND is_active = 1",
                (identifier.lower(), identifier.lower()),
                one=True
            ) if identifier else None
            recovery = query_db(
                "SELECT * FROM password_recovery_codes WHERE user_id = ?",
                (user['id'],),
                one=True
            ) if user else None

            if (not recovery or recovery['expires_at'] <= time.time() or recovery['attempts'] >= 5):
                if recovery:
                    execute_db("DELETE FROM password_recovery_codes WHERE user_id = ?", (user['id'],))
                flash("The code is invalid or expired. Request a new verification code.", "danger")
            elif not check_password_hash(recovery['code_hash'], code):
                attempts = recovery['attempts'] + 1
                if attempts >= 5:
                    execute_db("DELETE FROM password_recovery_codes WHERE user_id = ?", (user['id'],))
                else:
                    execute_db("UPDATE password_recovery_codes SET attempts = ? WHERE user_id = ?", (attempts, user['id']))
                flash("The code is invalid or expired. Request a new verification code.", "danger")
            elif len(password) < 8:
                flash("Choose a password with at least 8 characters.", "danger")
            elif password != confirm_password:
                flash("The passwords do not match.", "danger")
            else:
                execute_db(
                    "UPDATE users SET password_hash = ?, password_changed_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (generate_password_hash(password), user['id'])
                )
                execute_db("DELETE FROM password_recovery_codes WHERE user_id = ?", (user['id'],))
                AuditService.log(user['id'], 'PASSWORD_RESET', 'USER', user['id'], "Password reset using email verification")
                flash("Your password has been reset. Sign in with your new password.", "success")
                return redirect(url_for('auth.login'))

    return render_template('auth/forgot_password.html', code_requested=code_requested, identifier=identifier)

@auth_bp.route('/logout')
def logout():
    uid = session.get('user_id')
    if uid:
        AuditService.log(uid, 'USER_LOGOUT', 'USER', uid, "Logged out")
    session.clear()
    flash("You have been signed out safely.", "info")
    return redirect(url_for('auth.login'))
