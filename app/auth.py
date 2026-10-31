from flask import (Blueprint, current_app, flash, g, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db
from .security import login_required, safe_next

bp = Blueprint("auth", __name__)

MIN_PASSWORD = 10
# Checked when the username does not exist, so response time does not reveal valid names.
DUMMY_HASH = generate_password_hash("not-a-real-password")


def home_for(user):
    return url_for("admin.index" if user["role"] == "admin" else "dash.index")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(home_for(g.user))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        limiter = current_app.extensions["limiter"]
        user_key = f"login:{request.remote_addr}:{username.lower()}"
        ip_key = f"login-ip:{request.remote_addr}"
        if limiter.blocked(user_key, 5, 900) or limiter.blocked(ip_key, 30, 900):
            flash("Too many failed attempts. Wait 15 minutes, or ask the site admin "
                  "to reset your password.", "error")
            return render_template("login.html", username=username), 429
        row = get_db().execute(
            "SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        valid = check_password_hash(row["password_hash"] if row else DUMMY_HASH, password)
        if not (row and row["active"] and valid):
            limiter.record(user_key, 900)
            limiter.record(ip_key, 900)
            flash("Username or password is incorrect.", "error")
            return render_template("login.html", username=username), 401
        limiter.clear(user_key)
        session.clear()  # new session on login prevents session fixation
        session.permanent = True
        session["uid"] = row["id"]
        return redirect(safe_next(request.args.get("next")) or home_for(row))
    return render_template("login.html", username="")


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You are logged out.", "ok")
    return redirect(url_for("public.index"))


@bp.route("/account/password", methods=["GET", "POST"])
@login_required()
def change_password():
    errors = []
    if request.method == "POST":
        current = request.form.get("current_password", "")
        new = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")
        if not check_password_hash(g.user["password_hash"], current):
            errors.append("Your current password is not correct.")
        if len(new) < MIN_PASSWORD:
            errors.append(f"Use at least {MIN_PASSWORD} characters for the new password.")
        if new != confirm:
            errors.append("The new password and its confirmation do not match.")
        if new and new == current:
            errors.append("Choose a password different from the current one.")
        if not errors:
            db = get_db()
            db.execute("UPDATE users SET password_hash = ?, must_change_password = 0 "
                       "WHERE id = ?", (generate_password_hash(new), g.user["id"]))
            db.commit()
            uid = g.user["id"]
            session.clear()
            session.permanent = True
            session["uid"] = uid
            flash("Password changed.", "ok")
            return redirect(home_for(g.user))
    return render_template("change_password.html", errors=errors,
                           forced=bool(g.user["must_change_password"]))
