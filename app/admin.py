import re
import secrets
import sqlite3

from flask import (Blueprint, abort, current_app, flash, g, redirect,
                   render_template, request, url_for)
from werkzeug.security import generate_password_hash

from . import images
from .db import get_db, now_iso

bp = Blueprint("admin", __name__, url_prefix="/admin")

USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,29}$")
TEMP_ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def temporary_password(length=14):
    return "".join(secrets.choice(TEMP_ALPHABET) for _ in range(length))


@bp.before_request
def admins_only():
    if g.user is None:
        return redirect(url_for("auth.login", next=request.path))
    if g.user["role"] != "admin":
        abort(403)


def _artist(uid):
    row = get_db().execute("SELECT * FROM users WHERE id = ? AND role = 'artist'", (uid,)).fetchone()
    if row is None:
        abort(404)
    return row


@bp.route("/")
def index():
    rows = get_db().execute("""
        SELECT u.*,
          (SELECT COUNT(*) FROM paintings p WHERE p.artist_id = u.id) AS painting_count,
          (SELECT COUNT(*) FROM messages m WHERE m.artist_id = u.id AND m.status = 'unread') AS unread
        FROM users u WHERE u.role = 'artist' ORDER BY u.display_name COLLATE NOCASE""").fetchall()
    return render_template("admin/index.html", artists=rows)


@bp.route("/artists/new", methods=["GET", "POST"])
def new_artist():
    form, errors = {"username": "", "display_name": ""}, []
    if request.method == "POST":
        form = {"username": request.form.get("username", "").strip().lower(),
                "display_name": request.form.get("display_name", "").strip()}
        if not USERNAME_RE.match(form["username"]):
            errors.append("Username must be 3 to 30 characters: lowercase letters, "
                          "numbers, hyphens or underscores.")
        if not 1 <= len(form["display_name"]) <= 60:
            errors.append("Enter the artist's display name (up to 60 characters).")
        if not errors:
            password = temporary_password()
            db = get_db()
            try:
                db.execute(
                    "INSERT INTO users (username, display_name, role, password_hash, "
                    "must_change_password, created_at) VALUES (?, ?, 'artist', ?, 1, ?)",
                    (form["username"], form["display_name"],
                     generate_password_hash(password), now_iso()))
                db.commit()
            except sqlite3.IntegrityError:
                errors.append("That username is already taken.")
            else:
                return render_template("admin/credentials.html", username=form["username"],
                                       display_name=form["display_name"], password=password,
                                       created=True)
    return render_template("admin/new_artist.html", form=form, errors=errors)


@bp.route("/artists/<int:uid>/reset", methods=["POST"])
def reset_password(uid):
    person = _artist(uid)
    password = temporary_password()
    db = get_db()
    db.execute("UPDATE users SET password_hash = ?, must_change_password = 1 WHERE id = ?",
               (generate_password_hash(password), uid))
    db.commit()
    return render_template("admin/credentials.html", username=person["username"],
                           display_name=person["display_name"], password=password, created=False)


@bp.route("/artists/<int:uid>/active", methods=["POST"])
def toggle_active(uid):
    person = _artist(uid)
    db = get_db()
    db.execute("UPDATE users SET active = ? WHERE id = ?", (0 if person["active"] else 1, uid))
    db.commit()
    flash(f"{person['display_name']} is now {'inactive' if person['active'] else 'active'}.", "ok")
    return redirect(url_for("admin.index"))


@bp.route("/paintings")
def paintings():
    rows = get_db().execute("""
        SELECT p.*, u.display_name AS artist_name FROM paintings p
        JOIN users u ON u.id = p.artist_id
        ORDER BY p.created_at DESC, p.id DESC""").fetchall()
    return render_template("admin/paintings.html", paintings=rows)


@bp.route("/paintings/<int:pid>/hide", methods=["POST"])
def hide_painting(pid):
    db = get_db()
    db.execute("UPDATE paintings SET status = 'hidden', updated_at = ? WHERE id = ?",
               (now_iso(), pid))
    db.commit()
    flash("Painting hidden from the public gallery.", "ok")
    return redirect(url_for("admin.paintings"))


@bp.route("/paintings/<int:pid>/delete", methods=["POST"])
def delete_painting(pid):
    db = get_db()
    row = db.execute("SELECT * FROM paintings WHERE id = ?", (pid,)).fetchone()
    if row is None:
        abort(404)
    db.execute("DELETE FROM paintings WHERE id = ?", (pid,))
    db.commit()
    images.delete_painting_files(current_app.config["MEDIA_ROOT"], row["image_key"])
    flash("Painting deleted.", "ok")
    return redirect(url_for("admin.paintings"))
