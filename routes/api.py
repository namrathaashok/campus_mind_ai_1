"""
CampusPulse DSU — JSON REST API Blueprint
Provides all endpoints consumed by the React dashboard (frontend/src/App.jsx)
and any external API clients.  All write operations reuse the same business
rules and audit trail as the existing Flask/Jinja forms.
"""
import datetime
import uuid
import os
from flask import Blueprint, jsonify, request, g, current_app
from werkzeug.utils import secure_filename
from models.db import query_db, execute_db
from services.ai_service import AIService
from services.audit_service import AuditService

api_bp = Blueprint('api', __name__, url_prefix='/api')

# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _allowed_file(filename):
    """Return True if the file extension is in the configured allow-list."""
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    return ext in current_app.config.get('ALLOWED_EXTENSIONS', {'png', 'jpg', 'jpeg', 'webp'})


def _error(message, code=400):
    """Return a consistent JSON error response."""
    return jsonify({'status': 'error', 'message': message}), code


def _row_to_dict(row):
    """Convert a sqlite3.Row to a plain dict, serialising None safely."""
    return dict(row) if row else {}


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@api_bp.route('/cat')
def cat_status():
    """Simple endpoint confirming the backend API is available."""
    return jsonify({'status': 'success', 'message': 'Backend is running'})


# ---------------------------------------------------------------------------
# Dashboard statistics
# ---------------------------------------------------------------------------

@api_bp.route('/stats/summary')
def stats_summary():
    """Returns real-time dashboard KPIs calculated from the SQLite database."""
    total    = query_db("SELECT COUNT(*) as c FROM reports", one=True)['c']
    pending  = query_db(
        "SELECT COUNT(*) as c FROM reports "
        "WHERE status IN ('submitted','verified','assigned','in_progress')",
        one=True
    )['c']
    resolved = query_db(
        "SELECT COUNT(*) as c FROM reports WHERE status = 'resolved'",
        one=True
    )['c']
    water_active = query_db(
        "SELECT COUNT(*) as c FROM reports "
        "WHERE category = 'water' AND status != 'resolved'",
        one=True
    )['c']
    elec_active = query_db(
        "SELECT COUNT(*) as c FROM reports "
        "WHERE category = 'electricity' AND status != 'resolved'",
        one=True
    )['c']

    return jsonify({
        'status': 'success',
        'total_reports':      total,
        'pending_reports':    pending,
        'resolved_reports':   resolved,
        'resolution_rate':    round((resolved / total * 100), 1) if total > 0 else 0,
        'active_water_leaks': water_active,
        'active_elec_waste':  elec_active,
    })


# ---------------------------------------------------------------------------
# Map issues  (used by the React sustainability map widget)
# ---------------------------------------------------------------------------

@api_bp.route('/map-issues')
def map_issues():
    """
    Returns campus environmental issues formatted for the React dashboard map.
    Uses LEFT JOIN so reports whose location_id is NULL (or has no matching
    campus_locations row) are still included — they appear without coordinates.
    Supports ?category=, ?status=, ?priority= query parameters.
    """
    category = request.args.get('category', '').strip()
    status   = request.args.get('status',   '').strip()
    priority = request.args.get('priority', '').strip()

    # LEFT JOIN — don't exclude reports that have no campus_location row
    query = """
        SELECT r.id, r.report_number, r.title, r.description, r.category,
               r.priority, r.status, r.photo_path, r.specific_spot,
               r.created_at, r.updated_at,
               l.building_name, l.floor, l.zone_or_wing,
               l.latitude, l.longitude
        FROM reports r
        LEFT JOIN campus_locations l ON r.location_id = l.id
        WHERE 1=1
    """
    params = []

    if category:
        query += " AND r.category = ?"
        params.append(category)
    if status:
        query += " AND r.status = ?"
        params.append(status)
    if priority:
        query += " AND r.priority = ?"
        params.append(priority)

    query += " ORDER BY r.created_at DESC"

    rows   = query_db(query, params)
    issues = [_row_to_dict(r) for r in rows]

    return jsonify({
        'status': 'success',
        'count':  len(issues),
        'issues': issues,
    })


# ---------------------------------------------------------------------------
# Reports  (list + detail + submit + status update)
# ---------------------------------------------------------------------------

@api_bp.route('/reports')
def list_reports():
    """
    Paginated list of reports with optional filters.
    Query params: status, category, priority, location_id, search, page, per_page.
    Returns reports from the database (no hardcoded data).
    """
    status_f   = request.args.get('status',      '').strip()
    category_f = request.args.get('category',    '').strip()
    priority_f = request.args.get('priority',    '').strip()
    location_f = request.args.get('location_id', '').strip()
    search_q   = request.args.get('search',      '').strip()
    try:
        page = max(1, int(request.args.get('page', 1)))
        per_page = min(100, max(1, int(request.args.get('per_page', 50))))
    except (TypeError, ValueError):
        return _error('page and per_page must be integers.')

    query = """
        SELECT r.id, r.report_number, r.title, r.description, r.category,
               r.priority, r.status, r.specific_spot, r.photo_path,
               r.is_anonymous, r.ai_confidence, r.created_at, r.updated_at,
               l.building_name, l.floor, l.zone_or_wing,
               l.latitude, l.longitude
        FROM reports r
        LEFT JOIN campus_locations l ON r.location_id = l.id
        WHERE 1=1
    """
    params = []

    if status_f:
        query += " AND r.status = ?"
        params.append(status_f)
    if category_f:
        query += " AND r.category = ?"
        params.append(category_f)
    if priority_f:
        query += " AND r.priority = ?"
        params.append(priority_f)
    if location_f:
        query += " AND r.location_id = ?"
        params.append(location_f)
    if search_q:
        query += """ AND (
            r.title LIKE ? OR r.report_number LIKE ?
            OR r.description LIKE ? OR l.building_name LIKE ?
        )"""
        like = f"%{search_q}%"
        params.extend([like, like, like, like])

    query += " ORDER BY r.created_at DESC LIMIT ? OFFSET ?"
    params.extend([per_page, (page - 1) * per_page])

    rows    = query_db(query, params)
    reports = [_row_to_dict(r) for r in rows]

    return jsonify({
        'status':   'success',
        'page':     page,
        'per_page': per_page,
        'count':    len(reports),
        'reports':  reports,
    })


@api_bp.route('/reports/<int:report_id>')
def get_report(report_id):
    """
    Return full detail for a single report, including history and public comments.
    Internal (staff-only) comments are hidden from unauthenticated/student callers.
    """
    report = query_db("""
        SELECT r.*, l.campus_name, l.building_name, l.floor, l.zone_or_wing,
               l.latitude, l.longitude,
               u.full_name  AS reporter_name,
               staff.full_name AS assigned_staff_name,
               d.name AS assigned_dept_name
        FROM reports r
        LEFT JOIN campus_locations l  ON r.location_id         = l.id
        LEFT JOIN users u             ON r.user_id              = u.id
        LEFT JOIN users staff         ON r.assigned_to_user_id  = staff.id
        LEFT JOIN departments d       ON r.assigned_department_id = d.id
        WHERE r.id = ?
    """, (report_id,), one=True)

    if not report:
        return _error('Report not found.', 404)

    history = query_db("""
        SELECT h.id, h.old_status, h.new_status, h.comment, h.created_at,
               u.full_name AS changed_by_name
        FROM report_history h
        LEFT JOIN users u ON h.changed_by_user_id = u.id
        WHERE h.report_id = ?
        ORDER BY h.created_at ASC
    """, (report_id,))

    # Only expose internal comments to staff/admin
    is_privileged = g.user and g.user['role'] in ('staff', 'admin')
    comments_query = """
        SELECT c.id, c.comment, c.is_internal_staff_only, c.created_at,
               u.full_name, u.role, u.avatar_color
        FROM report_comments c
        JOIN users u ON c.user_id = u.id
        WHERE c.report_id = ?
    """
    if not is_privileged:
        comments_query += " AND c.is_internal_staff_only = 0"
    comments_query += " ORDER BY c.created_at ASC"
    comments = query_db(comments_query, (report_id,))

    return jsonify({
        'status':   'success',
        'report':   _row_to_dict(report),
        'history':  [_row_to_dict(h) for h in history],
        'comments': [_row_to_dict(c) for c in comments],
    })


@api_bp.route('/reports', methods=['POST'])
def submit_report():
    """
    JSON endpoint for submitting a new campus environmental report.
    Accepts application/json OR multipart/form-data (with optional photo file).
    Requires the caller to be logged in; anonymous submission sets user_id = NULL.

    Required fields: title, description, specific_spot
    Optional fields: category, priority, location_id, is_anonymous (bool)
    """
    # Support both JSON body and multipart form data
    if request.content_type and 'application/json' in request.content_type:
        data = request.get_json(silent=True) or {}
    else:
        data = request.form.to_dict()

    # --- Validate required fields ---
    title        = (data.get('title', '') or '').strip()
    description  = (data.get('description', '') or '').strip()
    specific_spot = (data.get('specific_spot', '') or '').strip()

    if not title:
        return _error('title is required.')
    if not description:
        return _error('description is required.')
    if not specific_spot:
        return _error('specific_spot is required.')
    if len(title) > 200:
        return _error('title must not exceed 200 characters.')
    if len(description) > 3000:
        return _error('description must not exceed 3000 characters.')

    # --- Optional fields with validation ---
    valid_categories = {'water', 'electricity', 'waste', 'greenery', 'infrastructure'}
    valid_priorities  = {'low', 'medium', 'high', 'critical'}

    category  = (data.get('category', '') or '').strip().lower()
    priority  = (data.get('priority', '') or '').strip().lower()

    if category and category not in valid_categories:
        return _error(f'category must be one of: {", ".join(sorted(valid_categories))}.')
    if priority and priority not in valid_priorities:
        return _error(f'priority must be one of: {", ".join(sorted(valid_priorities))}.')

    location_id_raw = data.get('location_id') or None
    location_id = None
    if location_id_raw is not None:
        try:
            location_id = int(location_id_raw)
        except (ValueError, TypeError):
            return _error('location_id must be an integer.')
        # Verify location exists
        loc = query_db("SELECT id FROM campus_locations WHERE id = ? AND is_active = 1",
                       (location_id,), one=True)
        if not loc:
            return _error(f'Campus location {location_id} not found or inactive.', 404)

    is_anonymous = bool(data.get('is_anonymous', False))
    user_id = None if is_anonymous else (g.user['id'] if g.user else None)

    # --- Photo upload (multipart only) ---
    photo_path = None
    if 'photo' in request.files:
        file = request.files['photo']
        if file and file.filename and _allowed_file(file.filename):
            ext         = secure_filename(file.filename).rsplit('.', 1)[1].lower()
            unique_name = f"issue_{uuid.uuid4().hex[:12]}.{ext}"
            upload_dir  = current_app.config['UPLOAD_FOLDER']
            os.makedirs(upload_dir, exist_ok=True)
            file.save(os.path.join(upload_dir, unique_name))
            photo_path = f"/static/uploads/{unique_name}"

    # --- AI categorisation if not explicitly supplied ---
    ai_analysis   = AIService.analyze_report(title, description, specific_spot)
    final_category = category if category in valid_categories else ai_analysis.get('predicted_category', 'infrastructure')
    final_priority = priority if priority in valid_priorities  else ai_analysis.get('suggested_priority', 'medium')

    # --- Generate unique report number (CP-YYYY-NNNN) ---
    now           = datetime.datetime.now()
    count_all     = query_db("SELECT COUNT(*) as c FROM reports", one=True)['c'] + 1
    report_number = f"CP-{now.year}-{count_all:04d}"

    # --- Insert report ---
    cur = execute_db(
        """INSERT INTO reports (
               report_number, user_id, title, description, category, priority,
               status, location_id, specific_spot, is_anonymous, photo_path,
               ai_confidence, ai_reasoning
           ) VALUES (?, ?, ?, ?, ?, ?, 'submitted', ?, ?, ?, ?, ?, ?)""",
        (
            report_number, user_id, title, description,
            final_category, final_priority,
            location_id, specific_spot, int(is_anonymous), photo_path,
            ai_analysis.get('confidence', 0.0),
            ai_analysis.get('reasoning', ''),
        )
    )
    report_id = cur.lastrowid

    if not report_id:
        return _error('Database error: report could not be saved.', 500)

    # --- Record initial history entry ---
    execute_db(
        """INSERT INTO report_history
               (report_id, changed_by_user_id, old_status, new_status, comment)
           VALUES (?, ?, NULL, 'submitted', ?)""",
        (report_id, user_id, 'Issue reported via CampusPulse API. Awaiting facilities verification.')
    )

    # --- Audit & green points ---
    if user_id:
        AuditService.log(user_id, 'SUBMIT_REPORT_API', 'REPORT', report_id,
                         f"Created {report_number} via JSON API")
        AuditService.award_points(user_id, 50, f"Submitted environmental report {report_number}")

    return jsonify({
        'status':        'success',
        'report_id':     report_id,
        'report_number': report_number,
        'category':      final_category,
        'priority':      final_priority,
        'ai_confidence': ai_analysis.get('confidence', 0.0),
        'message':       f"Report {report_number} submitted. +50 Green Points awarded.",
    }), 201


@api_bp.route('/reports/<int:report_id>/status', methods=['PATCH'])
def update_report_status(report_id):
    """
    Update the workflow status of an existing report.
    Restricted to authenticated staff and admin users.
    Body (JSON): { "new_status": "...", "comment": "..." }
    """
    if not g.user or g.user['role'] not in ('staff', 'admin'):
        return _error('Authentication required. Staff or admin role needed.', 403)

    data       = request.get_json(silent=True) or {}
    new_status = (data.get('new_status') or '').strip()
    comment    = (data.get('comment', '') or '').strip()

    valid_statuses = {'submitted', 'verified', 'assigned', 'in_progress', 'resolved', 'reopened'}
    if new_status not in valid_statuses:
        return _error(f'new_status must be one of: {", ".join(sorted(valid_statuses))}.')

    report = query_db("SELECT * FROM reports WHERE id = ?", (report_id,), one=True)
    if not report:
        return _error('Report not found.', 404)

    old_status  = report['status']
    execute_db(
        """UPDATE reports
           SET status = ?,
               resolution_notes = COALESCE(CASE WHEN ? = 'resolved' THEN ? ELSE NULL END, resolution_notes),
               resolved_at      = CASE WHEN ? = 'resolved' THEN CURRENT_TIMESTAMP ELSE resolved_at END,
               updated_at       = CURRENT_TIMESTAMP
           WHERE id = ?""",
        (new_status, new_status, comment or None, new_status, report_id)
    )

    execute_db(
        """INSERT INTO report_history
               (report_id, changed_by_user_id, old_status, new_status, comment)
           VALUES (?, ?, ?, ?, ?)""",
        (report_id, g.user['id'], old_status, new_status,
         comment or f"Status changed from {old_status} to {new_status}")
    )

    # Notify the original reporter
    if report['user_id']:
        AuditService.notify(
            report['user_id'],
            f"Update on {report['report_number']}: {new_status.replace('_', ' ').title()}",
            f"Your report '{report['title']}' is now {new_status.replace('_', ' ')}."
            + (f" Note: {comment}" if comment else ""),
        )
        if new_status == 'resolved':
            AuditService.award_points(report['user_id'], 25,
                                      f"Resolution of report {report['report_number']}")

    AuditService.log(g.user['id'], 'API_UPDATE_STATUS', 'REPORT', report_id,
                     f"Changed status to {new_status} via API")

    return jsonify({
        'status':        'success',
        'report_id':     report_id,
        'report_number': report['report_number'],
        'old_status':    old_status,
        'new_status':    new_status,
        'message':       f"Status updated from {old_status} to {new_status}.",
    })


# ---------------------------------------------------------------------------
# Campus locations  (React form needs this to populate the dropdown)
# ---------------------------------------------------------------------------

@api_bp.route('/locations')
def list_locations():
    """Return all active campus locations for use in report-submission dropdowns."""
    rows      = query_db(
        "SELECT id, campus_name, building_name, floor, zone_or_wing, latitude, longitude "
        "FROM campus_locations WHERE is_active = 1 "
        "ORDER BY campus_name, building_name, floor"
    )
    locations = [_row_to_dict(r) for r in rows]
    return jsonify({'status': 'success', 'count': len(locations), 'locations': locations})


# ---------------------------------------------------------------------------
# Auth status  (React uses this to know whether the user is logged in)
# ---------------------------------------------------------------------------

@api_bp.route('/auth/me')
def auth_me():
    """
    Returns the currently authenticated user's public profile.
    Returns 401 if not logged in (never exposes password hash or recovery codes).
    """
    if not g.user:
        return jsonify({'status': 'unauthenticated', 'user': None}), 401

    # sqlite3.Row doesn't support .get() — convert to plain dict first
    user_dict = dict(g.user)

    return jsonify({
        'status': 'success',
        'user': {
            'id':           user_dict['id'],
            'username':     user_dict['username'],
            'full_name':    user_dict['full_name'],
            'role':         user_dict['role'],
            'campus':       user_dict.get('campus'),
            'green_points': user_dict.get('green_points', 0),
            'avatar_color': user_dict.get('avatar_color'),
            'dept_name':    user_dict.get('dept_name'),
        }
    })

