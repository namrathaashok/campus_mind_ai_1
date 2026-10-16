import os
import secrets
from pathlib import Path
from flask import Flask, render_template, session, g, request, redirect, url_for, flash, send_from_directory
from config import Config
from models.db import init_app, init_db, query_db, get_db
from services.seed_service import rotate_legacy_seed_passwords, seed_database
from routes import (
    auth_bp, main_bp, reports_bp, maintenance_bp,
    assistant_bp, green_hub_bp, monitoring_bp, admin_bp, api_bp
)

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Ensure upload directory exists
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['INSTANCE_PATH'], exist_ok=True)

    # Database teardown registration
    init_app(app)

    # Initialize and seed database if brand new
    with app.app_context():
        init_db()
        rotate_legacy_seed_passwords()
        # Seed realistic Dayananda Sagar University demo data if empty
        user_count = query_db("SELECT COUNT(*) as c FROM users", one=True)
        if not user_count or user_count['c'] == 0:
            seed_database()

    # Register Blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(maintenance_bp)
    app.register_blueprint(assistant_bp)
    app.register_blueprint(green_hub_bp)
    app.register_blueprint(monitoring_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(api_bp)

    # Before request: Load authenticated user into g.user
    @app.before_request
    def load_logged_in_user():
        user_id = session.get('user_id')
        if user_id is None:
            g.user = None
        else:
            g.user = query_db(
                """SELECT u.*, d.name as dept_name, d.code as dept_code 
                   FROM users u 
                   LEFT JOIN departments d ON u.department_id = d.id 
                   WHERE u.id = ? AND u.is_active = 1""",
                (user_id,),
                one=True
            )
            if not g.user:
                session.clear()

    # Context processor: Global variables accessible in all Jinja templates
    @app.context_processor
    def inject_globals():
        # CSRF Token
        if '_csrf_token' not in session:
            session['_csrf_token'] = secrets.token_hex(24)

        unread_notifs = 0
        if g.user:
            res = query_db(
                "SELECT COUNT(*) as c FROM notifications WHERE user_id = ? AND is_read = 0",
                (g.user['id'],),
                one=True
            )
            unread_notifs = res['c'] if res else 0

        return {
            'app_name': 'CampusPulse DSU',
            'app_subtitle': 'AI-Powered Sustainable Campus',
            'campus_name': app.config.get('CAMPUS_NAME', 'Dayananda Sagar University'),
            'campus_location': app.config.get('CAMPUS_LOCATION', 'Bengaluru, Karnataka, India'),
            'csrf_token': session.get('_csrf_token'),
            'unread_notifications_count': unread_notifs,
            'current_user': g.user
        }

    # Error Handlers
    @app.errorhandler(404)
    def page_not_found(e):
        return render_template('base.html', error_title="404 - Page Not Found",
                               error_msg="The requested campus sustainability resource could not be found."), 404

    @app.errorhandler(500)
    def internal_server_error(e):
        return render_template('base.html', error_title="500 - Server Error",
                               error_msg="An unexpected error occurred. Please contact the DSU Facilities IT Cell."), 500

    # ------------------------------------------------------------------
    # React dashboard  — serve the Vite production build from Flask
    # The Vite dev server (npm run dev) remains the preferred local route;
    # these routes let Flask serve the built SPA in production or for
    # end-to-end verification without running two separate servers.
    # ------------------------------------------------------------------
    FRONTEND_DIST = Path(__file__).resolve().parent / "frontend" / "dist"

    @app.route('/react-dashboard')
    @app.route('/react-dashboard/')
    def react_dashboard():
        """Serve the compiled React SPA entry point."""
        dist_index = FRONTEND_DIST / "index.html"
        if dist_index.exists():
            return send_from_directory(str(FRONTEND_DIST), "index.html")
        return (
            "<h2>React dashboard not built yet.</h2>"
            "<p>Run <code>cd frontend &amp;&amp; npm run build</code> first, "
            "then refresh this page.</p>",
            200,
        )

    @app.route('/react-dashboard/assets/<path:filename>')
    def react_assets(filename):
        """Serve Vite-generated JS/CSS asset chunks."""
        assets_dir = FRONTEND_DIST / "assets"
        return send_from_directory(str(assets_dir), filename)

    return app

app = create_app()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', '').lower() in ('1', 'true', 'yes')
    print(f"\n[OK] CampusPulse DSU starting on http://0.0.0.0:{port}")
    print("[INFO] Dayananda Sagar University - AI-Powered Sustainable Campus\n")
    app.run(host='0.0.0.0', port=port, debug=debug)
