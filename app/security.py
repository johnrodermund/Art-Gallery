"""Sessions, CSRF protection, rate limiting and response headers."""
import hmac
import secrets
import threading
import time
from collections import defaultdict, deque
from functools import wraps

from flask import abort, current_app, g, redirect, request, session, url_for
from markupsafe import Markup

from .db import get_db

MUST_CHANGE_ALLOWED = {"auth.change_password", "auth.logout", "static", "public.media"}


class RateLimiter:
    """Small in-memory limiter. It resets when the app restarts, which is fine
    for a single-process local site."""

    def __init__(self):
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()

    def _recent(self, key, window):
        queue = self._hits[key]
        cutoff = time.monotonic() - window
        while queue and queue[0] < cutoff:
            queue.popleft()
        return queue

    def blocked(self, key, limit, window):
        with self._lock:
            return len(self._recent(key, window)) >= limit

    def record(self, key, window):
        with self._lock:
            self._recent(key, window).append(time.monotonic())

    def clear(self, key):
        with self._lock:
            self._hits.pop(key, None)


def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)
    return session["_csrf"]


def csrf_field():
    return Markup('<input type="hidden" name="_csrf" value="%s">') % csrf_token()


def safe_next(url):
    """Only allow redirects to paths on this site."""
    if url and url.startswith("/") and not url.startswith("//") and "\\" not in url:
        return url
    return None


def login_required(role=None):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if g.user is None:
                return redirect(url_for("auth.login", next=request.path))
            if role and g.user["role"] != role:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


def init_app(app):
    app.extensions["limiter"] = RateLimiter()

    @app.before_request
    def load_user():
        g.user = None
        uid = session.get("uid")
        if uid:
            row = get_db().execute(
                "SELECT * FROM users WHERE id = ? AND active = 1", (uid,)).fetchone()
            if row:
                g.user = row
            else:
                session.pop("uid", None)

    @app.before_request
    def protect_forms():
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            sent = request.form.get("_csrf") or request.headers.get("X-CSRF-Token", "")
            expected = session.get("_csrf", "")
            if not sent or not expected or not hmac.compare_digest(sent, expected):
                abort(400, "This page expired. Go back, reload it and try again.")

    @app.before_request
    def force_password_change():
        if (g.user is not None and g.user["must_change_password"]
                and request.endpoint not in MUST_CHANGE_ALLOWED):
            return redirect(url_for("auth.change_password"))

    @app.after_request
    def secure_headers(response):
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; "
            "script-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'self'")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if request.endpoint not in ("static", "public.media"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.context_processor
    def inject_globals():
        unread = 0
        user = getattr(g, "user", None)
        if user is not None and user["role"] == "artist":
            unread = get_db().execute(
                "SELECT COUNT(*) FROM messages WHERE artist_id = ? AND status = 'unread'",
                (user["id"],)).fetchone()[0]
        return {"csrf_field": csrf_field, "site_name": current_app.config["SITE_NAME"],
                "unread_count": unread}
