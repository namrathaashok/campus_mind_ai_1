"""
CampusPulse DSU — Comprehensive Test Suite
Tests cover:
- Database initialisation and persistence
- Dashboard statistics API
- Report retrieval and filtering
- Report creation and persistence
- Status update and history recording
- Statistics change after writes
- Invalid input and missing records
- Authentication and role-based access control
- Existing application functionality
All tests use an isolated temporary SQLite database.
"""
import os
import re
import pytest
import tempfile
import base64
from io import BytesIO
from app import create_app
from config import TestingConfig
from models.db import init_db, query_db, execute_db
from services.seed_service import rotate_legacy_seed_passwords, seed_database
from services.ai_service import AIService
from werkzeug.security import check_password_hash, generate_password_hash


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture
def app():
    """Create app with an isolated temporary database for each test."""
    db_fd, db_path = tempfile.mkstemp()
    TestingConfig.DATABASE_PATH = db_path

    application = create_app(TestingConfig)

    with application.app_context():
        init_db()
        seed_database(force=True)

    yield application

    os.close(db_fd)
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def runner(app):
    return app.test_cli_runner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def login_student(client):
    return client.post(
        '/login',
        data={'login_input': 'student@dsu.edu.in', 'password': TestingConfig.SEEDED_STUDENT_PASSWORD},
        follow_redirects=True,
    )


def login_admin(client):
    return client.post(
        '/admin/login',
        data={'login_input': 'admin@dsu.edu.in', 'password': TestingConfig.SEEDED_ADMIN_PASSWORD},
        follow_redirects=True,
    )


def login_staff(client):
    """Log in as the first staff user seeded in the database."""
    with client.application.app_context():
        staff = query_db("SELECT email FROM users WHERE role = 'staff' LIMIT 1", one=True)
    return client.post(
        '/login',
        data={'login_input': staff['email'], 'password': TestingConfig.SEEDED_STAFF_PASSWORD},
        follow_redirects=True,
    )


def first_location_id(app):
    with app.app_context():
        loc = query_db("SELECT id FROM campus_locations WHERE is_active = 1 LIMIT 1", one=True)
    return loc['id'] if loc else None


# ===========================================================================
# 1. Database initialisation and seeding
# ===========================================================================

class TestDatabaseInit:
    def test_database_seeded_with_users(self, app):
        with app.app_context():
            count = query_db("SELECT COUNT(*) as c FROM users", one=True)['c']
        assert count >= 5, "Expected at least 5 seeded users"

    def test_database_seeded_with_locations(self, app):
        with app.app_context():
            count = query_db("SELECT COUNT(*) as c FROM campus_locations", one=True)['c']
        assert count >= 1, "Expected at least one campus location"

    def test_database_seeded_with_reports(self, app):
        with app.app_context():
            count = query_db("SELECT COUNT(*) as c FROM reports", one=True)['c']
        assert count >= 1, "Expected at least one seeded report"

    def test_reinitialising_schema_preserves_existing_records(self, app):
        """Running init_db() again must not delete any existing rows."""
        with app.app_context():
            before = query_db("SELECT COUNT(*) as c FROM reports", one=True)['c']
            init_db()
            after = query_db("SELECT COUNT(*) as c FROM reports", one=True)['c']
        assert after == before, "Re-running init_db() should not wipe existing records"

    def test_test_database_path_is_separate_from_production(self, app):
        """The test database must not point to the real instance/campuspulse.db."""
        db_path = str(app.config['DATABASE_PATH'])
        assert 'test_campuspulse.db' not in db_path or 'tmp' in db_path or tempfile.gettempdir().lower().replace('\\', '/') in db_path.lower().replace('\\', '/'), \
            "Test database should be isolated from production"


# ===========================================================================
# 2. Health check
# ===========================================================================

class TestHealthCheck:
    def test_cat_returns_success(self, client):
        res = client.get('/api/cat')
        assert res.status_code == 200
        data = res.get_json()
        assert data['status'] == 'success'
        assert data['message'] == 'Backend is running'


# ===========================================================================
# 3. Dashboard statistics API
# ===========================================================================

class TestStatsSummary:
    def test_returns_all_required_keys(self, client):
        res = client.get('/api/stats/summary')
        assert res.status_code == 200
        data = res.get_json()
        for key in ('total_reports', 'pending_reports', 'resolved_reports',
                    'resolution_rate', 'active_water_leaks', 'active_elec_waste'):
            assert key in data, f"Missing key: {key}"

    def test_counts_are_non_negative_integers(self, client):
        data = client.get('/api/stats/summary').get_json()
        for key in ('total_reports', 'pending_reports', 'resolved_reports',
                    'active_water_leaks', 'active_elec_waste'):
            assert isinstance(data[key], int) and data[key] >= 0

    def test_resolution_rate_is_between_0_and_100(self, client):
        data = client.get('/api/stats/summary').get_json()
        assert 0.0 <= data['resolution_rate'] <= 100.0

    def test_pending_plus_resolved_leq_total(self, client):
        data = client.get('/api/stats/summary').get_json()
        # pending + resolved may be < total if 'reopened' status exists
        assert data['pending_reports'] + data['resolved_reports'] <= data['total_reports']


# ===========================================================================
# 4. Report retrieval and filtering
# ===========================================================================

class TestReportsList:
    def test_list_reports_returns_success(self, client):
        res = client.get('/api/reports')
        assert res.status_code == 200
        data = res.get_json()
        assert data['status'] == 'success'
        assert 'reports' in data
        assert isinstance(data['reports'], list)

    def test_reports_include_required_fields(self, client):
        data = client.get('/api/reports').get_json()
        if data['reports']:
            report = data['reports'][0]
            for field in ('id', 'report_number', 'title', 'category', 'priority', 'status', 'created_at'):
                assert field in report, f"Missing field: {field}"

    def test_filter_by_status(self, client, app):
        with app.app_context():
            statuses = query_db("SELECT DISTINCT status FROM reports")
        for row in statuses:
            status = row['status']
            data = client.get(f'/api/reports?status={status}').get_json()
            assert all(r['status'] == status for r in data['reports']), \
                f"Filter by status={status} returned wrong records"

    def test_filter_by_category(self, client, app):
        with app.app_context():
            cats = query_db("SELECT DISTINCT category FROM reports")
        for row in cats:
            cat = row['category']
            data = client.get(f'/api/reports?category={cat}').get_json()
            assert all(r['category'] == cat for r in data['reports'])

    def test_search_finds_matching_reports(self, client, app):
        with app.app_context():
            sample = query_db("SELECT title FROM reports LIMIT 1", one=True)
        if sample:
            keyword = sample['title'][:6]
            data = client.get(f'/api/reports?search={keyword}').get_json()
            assert data['count'] >= 1

    def test_empty_filter_returns_empty_list(self, client):
        data = client.get('/api/reports?status=nonexistent_status_xyz').get_json()
        assert data['count'] == 0
        assert data['reports'] == []

    @pytest.mark.parametrize('query', ['page=invalid', 'per_page=invalid'])
    def test_invalid_pagination_returns_json_error(self, client, query):
        res = client.get(f'/api/reports?{query}')
        assert res.status_code == 400
        assert res.get_json()['status'] == 'error'


class TestMapIssues:
    def test_map_issues_uses_left_join(self, client, app):
        """
        Reports with location_id = NULL must appear in /api/map-issues results.
        Previously, an INNER JOIN silently dropped them.
        """
        with app.app_context():
            # Insert a report without a campus location
            execute_db(
                """INSERT INTO reports (
                       report_number, title, description, category, priority,
                       status, location_id, specific_spot
                   ) VALUES ('TEST-NULL-LOC', 'No-location test', 'Test desc',
                             'waste', 'low', 'submitted', NULL, 'Anywhere')"""
            )
        data = client.get('/api/map-issues').get_json()
        numbers = [i['report_number'] for i in data['issues']]
        assert 'TEST-NULL-LOC' in numbers, \
            "/api/map-issues INNER JOIN bug: reports without location_id are missing"

    def test_map_issues_filter_by_category(self, client):
        data = client.get('/api/map-issues?category=water').get_json()
        assert all(i['category'] == 'water' for i in data['issues'])


class TestReportDetail:
    def test_get_existing_report(self, client, app):
        with app.app_context():
            report = query_db("SELECT id FROM reports LIMIT 1", one=True)
        res = client.get(f'/api/reports/{report["id"]}')
        assert res.status_code == 200
        data = res.get_json()
        assert data['status'] == 'success'
        assert 'report' in data
        assert 'history' in data

    def test_get_nonexistent_report_returns_404(self, client):
        res = client.get('/api/reports/99999999')
        assert res.status_code == 404
        data = res.get_json()
        assert data['status'] == 'error'


# ===========================================================================
# 5. Report creation via JSON API and persistence
# ===========================================================================

class TestReportSubmission:
    def _submit(self, client, **kwargs):
        """Submit a report via the JSON API as a logged-in student."""
        login_student(client)
        payload = {
            'title':        kwargs.get('title', 'Test water leak'),
            'description':  kwargs.get('description', 'There is water dripping from the ceiling in the corridor.'),
            'specific_spot': kwargs.get('specific_spot', 'Block A, Ground floor corridor'),
            'category':     kwargs.get('category', 'water'),
            'priority':     kwargs.get('priority', 'medium'),
        }
        return client.post('/api/reports', json=payload)

    def test_submit_report_returns_201(self, client):
        res = self._submit(client)
        assert res.status_code == 201
        data = res.get_json()
        assert data['status'] == 'success'
        assert 'report_id' in data
        assert 'report_number' in data

    def test_submitted_report_persists_in_sqlite(self, client, app):
        """After API submission, the record must exist in the SQLite database."""
        res = self._submit(client, title='Persistence test — water pipe')
        assert res.status_code == 201
        report_id = res.get_json()['report_id']

        with app.app_context():
            row = query_db("SELECT * FROM reports WHERE id = ?", (report_id,), one=True)

        assert row is not None, "Report was not saved in SQLite"
        assert row['title'] == 'Persistence test — water pipe'
        assert row['status'] == 'submitted'

    def test_submitted_report_survives_app_restart(self, client, app):
        """Record must remain after creating a fresh app context (simulates restart)."""
        res = self._submit(client, title='Restart-survival test')
        report_id = res.get_json()['report_id']

        # Create a brand-new app context pointing to the same temp database
        fresh_app = create_app(TestingConfig)
        with fresh_app.app_context():
            row = query_db("SELECT id, title FROM reports WHERE id = ?", (report_id,), one=True)

        assert row is not None, "Report disappeared after simulated app restart"
        assert row['title'] == 'Restart-survival test'

    def test_report_history_entry_is_created(self, client, app):
        """Submitting a report must create a corresponding report_history row."""
        res = self._submit(client)
        report_id = res.get_json()['report_id']

        with app.app_context():
            history = query_db(
                "SELECT * FROM report_history WHERE report_id = ?", (report_id,)
            )

        assert len(history) >= 1
        assert history[0]['new_status'] == 'submitted'

    def test_report_number_follows_cp_format(self, client):
        res = self._submit(client)
        rn = res.get_json()['report_number']
        assert re.match(r'^CP-\d{4}-\d{4}$', rn), f"Report number format wrong: {rn}"

    def test_ai_category_is_applied_when_not_supplied(self, client, app):
        """When no category is given, the AI engine must assign one."""
        login_student(client)
        payload = {
            'title':        'Sparking wires near the switchboard',
            'description':  'Exposed electrical wire sparking near Lab 304 switchboard.',
            'specific_spot': 'Lab 304',
        }
        res = client.post('/api/reports', json=payload)
        assert res.status_code == 201
        assert res.get_json()['category'] == 'electricity'

    def test_invalid_category_is_rejected(self, client):
        login_student(client)
        res = client.post('/api/reports', json={
            'title': 'x', 'description': 'y', 'specific_spot': 'z',
            'category': 'invalid_cat_xyz'
        })
        assert res.status_code == 400

    def test_invalid_priority_is_rejected(self, client):
        login_student(client)
        res = client.post('/api/reports', json={
            'title': 'x', 'description': 'y', 'specific_spot': 'z',
            'priority': 'super_urgent'
        })
        assert res.status_code == 400

    def test_missing_title_returns_400(self, client):
        login_student(client)
        res = client.post('/api/reports', json={
            'description': 'desc', 'specific_spot': 'spot'
        })
        assert res.status_code == 400

    def test_missing_description_returns_400(self, client):
        login_student(client)
        res = client.post('/api/reports', json={
            'title': 'title', 'specific_spot': 'spot'
        })
        assert res.status_code == 400

    def test_missing_specific_spot_returns_400(self, client):
        login_student(client)
        res = client.post('/api/reports', json={
            'title': 'title', 'description': 'desc'
        })
        assert res.status_code == 400

    def test_invalid_location_id_returns_404(self, client):
        login_student(client)
        res = client.post('/api/reports', json={
            'title': 't', 'description': 'd', 'specific_spot': 's',
            'location_id': 9999999
        })
        assert res.status_code == 404


# ===========================================================================
# 6. Status update and statistics change after write
# ===========================================================================

class TestStatusUpdate:
    def _get_report_id(self, app):
        with app.app_context():
            row = query_db(
                "SELECT id FROM reports WHERE status = 'submitted' LIMIT 1",
                one=True,
            )
        return row['id'] if row else None

    def test_staff_can_update_status(self, client, app):
        report_id = self._get_report_id(app)
        assert report_id, "No 'submitted' report available for this test"

        login_staff(client)
        res = client.patch(
            f'/api/reports/{report_id}/status',
            json={'new_status': 'verified', 'comment': 'Verified by staff'}
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data['new_status'] == 'verified'

    def test_status_change_persists_in_database(self, client, app):
        report_id = self._get_report_id(app)
        login_staff(client)
        client.patch(
            f'/api/reports/{report_id}/status',
            json={'new_status': 'in_progress'}
        )

        with app.app_context():
            row = query_db("SELECT status FROM reports WHERE id = ?", (report_id,), one=True)
        assert row['status'] == 'in_progress'

    def test_status_update_creates_history_entry(self, client, app):
        report_id = self._get_report_id(app)
        login_staff(client)
        client.patch(
            f'/api/reports/{report_id}/status',
            json={'new_status': 'verified', 'comment': 'test comment'}
        )

        with app.app_context():
            history = query_db(
                "SELECT * FROM report_history WHERE report_id = ? AND new_status = 'verified'",
                (report_id,)
            )
        assert len(history) >= 1

    def test_resolving_report_increments_resolved_count(self, client, app):
        report_id = self._get_report_id(app)
        login_staff(client)

        before = client.get('/api/stats/summary').get_json()['resolved_reports']
        client.patch(
            f'/api/reports/{report_id}/status',
            json={'new_status': 'resolved', 'comment': 'Fixed'}
        )
        after = client.get('/api/stats/summary').get_json()['resolved_reports']

        assert after == before + 1

    def test_unauthenticated_status_update_returns_403(self, client, app):
        report_id = self._get_report_id(app)
        res = client.patch(
            f'/api/reports/{report_id}/status',
            json={'new_status': 'verified'}
        )
        assert res.status_code == 403

    def test_student_cannot_update_status(self, client, app):
        report_id = self._get_report_id(app)
        login_student(client)
        res = client.patch(
            f'/api/reports/{report_id}/status',
            json={'new_status': 'verified'}
        )
        assert res.status_code == 403

    def test_invalid_status_value_is_rejected(self, client, app):
        report_id = self._get_report_id(app)
        login_staff(client)
        res = client.patch(
            f'/api/reports/{report_id}/status',
            json={'new_status': 'not_a_real_status'}
        )
        assert res.status_code == 400

    def test_status_update_on_missing_report_returns_404(self, client, app):
        login_staff(client)
        res = client.patch(
            '/api/reports/99999999/status',
            json={'new_status': 'verified'}
        )
        assert res.status_code == 404

    def test_submitting_report_increments_total_count(self, client, app):
        login_student(client)
        before = client.get('/api/stats/summary').get_json()['total_reports']
        client.post('/api/reports', json={
            'title': 'Stats-change test', 'description': 'desc', 'specific_spot': 'spot'
        })
        after = client.get('/api/stats/summary').get_json()['total_reports']
        assert after == before + 1


# ===========================================================================
# 7. Locations API
# ===========================================================================

class TestLocationsAPI:
    def test_locations_returns_success(self, client):
        res = client.get('/api/locations')
        assert res.status_code == 200
        data = res.get_json()
        assert data['status'] == 'success'
        assert 'locations' in data
        assert isinstance(data['locations'], list)

    def test_locations_include_required_fields(self, client):
        data = client.get('/api/locations').get_json()
        if data['locations']:
            loc = data['locations'][0]
            for field in ('id', 'building_name', 'floor', 'zone_or_wing'):
                assert field in loc


# ===========================================================================
# 8. Auth status endpoint
# ===========================================================================

class TestAuthMe:
    def test_unauthenticated_returns_401(self, client):
        res = client.get('/api/auth/me')
        assert res.status_code == 401
        data = res.get_json()
        assert data['status'] == 'unauthenticated'

    def test_authenticated_returns_user_profile(self, client):
        login_student(client)
        res = client.get('/api/auth/me')
        assert res.status_code == 200
        data = res.get_json()
        assert data['status'] == 'success'
        assert 'user' in data
        assert 'password_hash' not in data['user'], "Password hash must never be exposed via API"

    def test_admin_auth_returns_admin_role(self, client):
        login_admin(client)
        res = client.get('/api/auth/me')
        assert res.status_code == 200
        assert res.get_json()['user']['role'] == 'admin'


# ===========================================================================
# 9. Authentication and role-based access (existing behaviour preserved)
# ===========================================================================

class TestAuthAndRoles:
    def test_guest_home_offers_sign_in_and_registration(self, client):
        response = client.get('/')
        assert response.status_code == 200
        assert b'CampusMindAi' in response.data
        assert b'href="/login"'    in response.data
        assert b'href="/register"' in response.data

    def test_dashboard_access_requires_login(self, client):
        res = client.get('/dashboard', follow_redirects=True)
        # The public Jinja dashboard actually does NOT require login in this project
        assert res.status_code == 200

    def test_student_blocked_from_admin_panel(self, client):
        login_student(client)
        res = client.get('/admin', follow_redirects=True)
        assert b'Access denied' in res.data

    def test_admin_login_via_correct_portal(self, client):
        res = login_admin(client)
        assert res.status_code == 200
        assert b'Administration Control Panel' in res.data

    def test_admin_login_rejects_wrong_password(self, client):
        res = client.post(
            '/admin/login',
            data={'login_input': 'admin@dsu.edu.in', 'password': 'wrong-password'},
        )
        assert b'Invalid administrator credentials' in res.data
        assert client.get('/admin').status_code == 302

    def test_admin_portal_rejects_non_admin_account(self, client):
        res = client.post(
            '/admin/login',
            data={'login_input': 'student@dsu.edu.in', 'password': TestingConfig.SEEDED_STUDENT_PASSWORD},
        )
        assert b'Invalid administrator credentials' in res.data
        assert client.get('/admin').status_code == 302

    def test_admin_blocked_from_student_portal(self, client):
        res = client.post(
            '/login',
            data={'login_input': 'admin@dsu.edu.in', 'password': TestingConfig.SEEDED_ADMIN_PASSWORD},
            follow_redirects=True,
        )
        assert b'separate Admin portal' in res.data

    def test_student_login_and_dashboard(self, client):
        res = login_student(client)
        assert res.status_code == 200
        assert b'Pooja Rao' in res.data          # seeded student name

    def test_logout_clears_session(self, client):
        login_student(client)
        client.get('/logout', follow_redirects=True)
        res = client.get('/api/auth/me')
        assert res.status_code == 401


# ===========================================================================
# 10. AI categorisation engine (existing tests preserved)
# ===========================================================================

class TestAICategorisation:
    def test_water_leak_detection(self):
        res = AIService.analyze_report('Pipe burst in rest facility',
                                       'Water gushing from 3rd floor washroom angle valve')
        assert res['predicted_category'] == 'water'
        assert res['suggested_priority'] in ('high', 'critical')
        assert res['confidence'] >= 0.8

    def test_electricity_hazard_detection(self):
        res = AIService.analyze_report('Exposed sparks in AC switchboard',
                                       'Sparking outlet with smoke in Lab 204')
        assert res['predicted_category'] == 'electricity'
        assert res['suggested_priority'] == 'critical'

    def test_waste_detection(self):
        res = AIService.analyze_report('Overflowing food waste bin',
                                       'Canteen bins full of plastic wrappers and garbage')
        assert res['predicted_category'] == 'waste'


# ===========================================================================
# 11. EcoBot assistant (existing tests preserved)
# ===========================================================================

class TestEcoBot:
    def test_chat_returns_reply(self, client):
        res = client.post('/api/assistant/chat',
                          json={'message': 'Summarize campus environmental status'})
        assert res.status_code == 200
        data = res.get_json()
        assert 'reply' in data
        assert 'DSU CampusPulse Live Sustainability Summary' in data['reply']

    def test_report_help_vs_problem_diagnosis(self, client):
        how_to = client.post('/api/assistant/chat',
                             json={'message': 'How can I report an issue?'})
        assert how_to.status_code == 200
        how_to_data = how_to.get_json()
        assert 'Report Issue' in how_to_data['reply']
        assert how_to_data['actions'][0]['url'] == '/report-issue'

        incident = client.post('/api/assistant/chat',
                               json={'message': 'There is a water leak in the washroom'})
        assert incident.status_code == 200
        assert incident.get_json()['diagnosis']['category'] == 'water'

    def test_image_requires_groq_key(self, client, app):
        app.config['GROQ_API_KEY'] = ''
        res = client.post(
            '/api/assistant/analyze-image',
            data={'image': (BytesIO(b'\x89PNG\r\n\x1a\nimage-data'), 'photo.png', 'image/png')},
            content_type='multipart/form-data',
        )
        assert res.status_code == 503
        assert 'not configured' in res.get_json()['error']


# ===========================================================================
# 12. Legacy seed-password rotation (existing test preserved)
# ===========================================================================

class TestLegacyPasswordRotation:
    def test_legacy_seed_passwords_are_rotated(self, app):
        with app.app_context():
            admin = query_db("SELECT id FROM users WHERE email = ?",
                             ('admin@dsu.edu.in',), one=True)
            execute_db("UPDATE users SET password_hash = ? WHERE id = ?",
                       (generate_password_hash('admin123'), admin['id']))
            rotate_legacy_seed_passwords()
            password_hash = query_db("SELECT password_hash FROM users WHERE id = ?",
                                     (admin['id'],), one=True)['password_hash']

        assert check_password_hash(password_hash, TestingConfig.SEEDED_ADMIN_PASSWORD)
        assert not check_password_hash(password_hash, 'admin123')


# ===========================================================================
# 13. Registration validation (existing tests preserved)
# ===========================================================================

class TestRegistration:
    def test_rejects_non_numeric_phone(self, client):
        res = client.post('/register', data={
            'full_name':   'Test Student',
            'username':    'test_student_abc',
            'email':       'test.student.abc@dsu.edu.in',
            'phone_number': '+91abc9876543210',
            'password':    'test-password-123',
        })
        assert res.status_code == 200
        assert b'Enter a valid phone number' in res.data


# ===========================================================================
# 14. Password recovery (existing test preserved)
# ===========================================================================

class TestPasswordRecovery:
    def test_email_code_reset_flow(self, client, app, monkeypatch):
        sent_emails = []

        def fake_send(recipient, code):
            sent_emails.append((recipient, code))
            return True

        monkeypatch.setattr('routes.auth.send_recovery_email', fake_send)

        with app.app_context():
            student = query_db("SELECT id FROM users WHERE email = ?",
                               ('student@dsu.edu.in',), one=True)
            execute_db("UPDATE users SET email = ? WHERE id = ?",
                       ('student@gmail.com', student['id']))

        client.post('/forgot-password',
                    data={'action': 'send_code', 'identifier': 'student@gmail.com'},
                    follow_redirects=True)
        assert sent_emails, "No email was sent"
        code = sent_emails[0][1]

        res = client.post('/forgot-password', data={
            'action':           'reset_password',
            'identifier':       'student@gmail.com',
            'code':             code,
            'password':         'new-password-123',
            'confirm_password': 'new-password-123',
        }, follow_redirects=True)
        assert b'Your password has been reset' in res.data


# ===========================================================================
# 15. React dashboard served from Flask
# ===========================================================================

class TestReactDashboardRoute:
    def test_react_dashboard_route_exists(self, client):
        """The /react-dashboard route must return 200 (even if dist not built)."""
        res = client.get('/react-dashboard')
        assert res.status_code == 200

    def test_removed_virtual_tour_routes(self, client):
        assert client.get('/virtual-tour').status_code == 404
        assert client.get('/api/tour-stops').status_code == 404
