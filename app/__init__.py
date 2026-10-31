import os
import secrets
from datetime import timedelta
from pathlib import Path

from flask import Flask, render_template
from werkzeug.exceptions import HTTPException


def _load_secret_key(home):
    path = home / "secret_key"
    if not path.exists():
        path.write_text(secrets.token_hex(32))
        try:
            path.chmod(0o600)
        except OSError:
            pass
    return path.read_text().strip()


def create_app(test_config=None):
    default_home = Path(__file__).resolve().parent.parent / "instance"
    home = Path(os.environ.get("ARTGALLERY_HOME", default_home)).resolve()
    home.mkdir(parents=True, exist_ok=True)

    app = Flask(__name__)
    app.config.update(
        HOME=home,
        DATABASE=home / "gallery.db",
        MEDIA_ROOT=home / "media",
        SITE_NAME=os.environ.get("ARTGALLERY_SITE_NAME", "Studio Wall"),
        CURRENCY=os.environ.get("ARTGALLERY_CURRENCY", "$"),
        MAX_CONTENT_LENGTH=16 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("ARTGALLERY_SECURE_COOKIES") == "1",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    )
    if test_config:
        app.config.update(test_config)
    app.secret_key = _load_secret_key(home)
    Path(app.config["MEDIA_ROOT"]).mkdir(parents=True, exist_ok=True)

    from . import auth, admin, dashboard, db, filters, public, security
    db.init_app(app)
    security.init_app(app)
    filters.init_app(app)
    app.register_blueprint(public.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(dashboard.bp)
    app.register_blueprint(admin.bp)

    with app.app_context():
        db.init_db()

    @app.errorhandler(HTTPException)
    def show_error(error):
        messages = {
            403: "You do not have access to this page.",
            404: "We could not find that page.",
            413: "That upload is too large. Keep images under 16 MB.",
        }
        message = messages.get(error.code) or error.description
        return render_template("error.html", code=error.code, message=message), error.code

    return app
