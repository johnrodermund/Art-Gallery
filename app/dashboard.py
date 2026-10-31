from decimal import Decimal, InvalidOperation

from flask import (Blueprint, abort, current_app, flash, g, jsonify, redirect,
                   render_template, request, url_for)

from . import images
from .db import get_db, now_iso

bp = Blueprint("dash", __name__, url_prefix="/dashboard")

STATUSES = ("available", "reserved", "sold", "hidden")


@bp.before_request
def artists_only():
    if g.user is None:
        return redirect(url_for("auth.login", next=request.path))
    if g.user["role"] != "artist":
        abort(403)


def _own_painting(pid):
    row = get_db().execute("SELECT * FROM paintings WHERE id = ? AND artist_id = ?",
                           (pid, g.user["id"])).fetchone()
    if row is None:
        abort(404)
    return row


def _own_message(mid):
    row = get_db().execute("""
        SELECT m.*, p.status AS painting_status, p.image_key, p.width, p.height
        FROM messages m LEFT JOIN paintings p ON p.id = m.painting_id
        WHERE m.id = ? AND m.artist_id = ?""", (mid, g.user["id"])).fetchone()
    if row is None:
        abort(404)
    return row


def _parse_price(raw):
    raw = raw.strip().replace(",", "").lstrip("$£€").strip()
    if not raw:
        return None
    try:
        value = Decimal(raw)
    except InvalidOperation:
        raise ValueError("Enter the price as a number, like 450 or 1200.50.")
    if not value.is_finite() or value < 0 or value > Decimal("10000000"):
        raise ValueError("Enter a price between 0 and 10,000,000.")
    return int((value * 100).to_integral_value())


def _read_painting_form():
    form = {
        "title": request.form.get("title", "").strip(),
        "description": request.form.get("description", "").strip(),
        "price": request.form.get("price", "").strip(),
        "status": request.form.get("status", "available"),
    }
    errors, price = [], None
    if not 1 <= len(form["title"]) <= 120:
        errors.append("Enter a title (up to 120 characters).")
    if len(form["description"]) > 4000:
        errors.append("Keep the description under 4,000 characters.")
    if form["status"] not in STATUSES:
        errors.append("Choose a status from the list.")
    try:
        price = _parse_price(form["price"])
    except ValueError as exc:
        errors.append(str(exc))
    return form, price, errors


@bp.route("/")
def index():
    paintings = get_db().execute("""
        SELECT p.*, (SELECT COUNT(*) FROM messages m
                     WHERE m.painting_id = p.id AND m.status = 'unread') AS unread
        FROM paintings p WHERE p.artist_id = ?
        ORDER BY p.created_at DESC, p.id DESC""", (g.user["id"],)).fetchall()
    return render_template("dashboard/index.html", paintings=paintings)


@bp.route("/paintings/new", methods=["GET", "POST"])
def new_painting():
    form, errors = {"title": "", "description": "", "price": "", "status": "available"}, []
    if request.method == "POST":
        form, price, errors = _read_painting_form()
        upload = request.files.get("image")
        if not upload or not upload.filename:
            errors.append("Choose an image of the painting.")
        key = None
        if not errors:
            try:
                key, width, height = images.save_painting_image(
                    upload, current_app.config["MEDIA_ROOT"])
            except images.ImageError as exc:
                errors.append(str(exc))
        if not errors:
            db = get_db()
            now = now_iso()
            db.execute(
                "INSERT INTO paintings (artist_id, title, description, price_cents, status, "
                "image_key, width, height, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (g.user["id"], form["title"], form["description"], price, form["status"],
                 key, width, height, now, now))
            db.commit()
            flash("Painting added.", "ok")
            return redirect(url_for("dash.index"))
    return render_template("dashboard/edit.html", painting=None, form=form,
                           errors=errors, statuses=STATUSES)


@bp.route("/paintings/<int:pid>/edit", methods=["GET", "POST"])
def edit_painting(pid):
    painting = _own_painting(pid)
    errors = []
    form = {
        "title": painting["title"], "description": painting["description"],
        "price": "" if painting["price_cents"] is None else f"{painting['price_cents'] / 100:g}",
        "status": painting["status"],
    }
    if request.method == "POST":
        form, price, errors = _read_painting_form()
        upload = request.files.get("image")
        new_image = None
        if not errors and upload and upload.filename:
            try:
                new_image = images.save_painting_image(upload, current_app.config["MEDIA_ROOT"])
            except images.ImageError as exc:
                errors.append(str(exc))
        if not errors:
            db = get_db()
            key, width, height = new_image or (
                painting["image_key"], painting["width"], painting["height"])
            db.execute(
                "UPDATE paintings SET title = ?, description = ?, price_cents = ?, status = ?, "
                "image_key = ?, width = ?, height = ?, updated_at = ? WHERE id = ?",
                (form["title"], form["description"], price, form["status"],
                 key, width, height, now_iso(), pid))
            db.commit()
            if new_image:
                images.delete_painting_files(current_app.config["MEDIA_ROOT"],
                                             painting["image_key"])
            flash("Changes saved.", "ok")
            return redirect(url_for("dash.index"))
    return render_template("dashboard/edit.html", painting=painting, form=form,
                           errors=errors, statuses=STATUSES)


@bp.route("/paintings/<int:pid>/status", methods=["POST"])
def set_status(pid):
    _own_painting(pid)
    status = request.form.get("status")
    if status not in STATUSES:
        abort(400, "Unknown status.")
    db = get_db()
    db.execute("UPDATE paintings SET status = ?, updated_at = ? WHERE id = ?",
               (status, now_iso(), pid))
    db.commit()
    flash(f"Marked as {status}.", "ok")
    return redirect(request.form.get("back") if (request.form.get("back") or "").startswith("/dashboard")
                    else url_for("dash.index"))


@bp.route("/paintings/<int:pid>/delete", methods=["POST"])
def delete_painting(pid):
    painting = _own_painting(pid)
    db = get_db()
    db.execute("DELETE FROM paintings WHERE id = ?", (pid,))
    db.commit()
    images.delete_painting_files(current_app.config["MEDIA_ROOT"], painting["image_key"])
    flash("Painting deleted.", "ok")
    return redirect(url_for("dash.index"))


@bp.route("/inbox")
def inbox():
    views = {
        "active": "m.status IN ('unread', 'read')",
        "unread": "m.status = 'unread'",
        "archived": "m.status = 'archived'",
        "all": "1 = 1",
    }
    show = request.args.get("show", "active")
    if show not in views:
        show = "active"
    rows = get_db().execute(f"""
        SELECT m.*, p.image_key, p.width, p.height
        FROM messages m LEFT JOIN paintings p ON p.id = m.painting_id
        WHERE m.artist_id = ? AND {views[show]}
        ORDER BY m.created_at DESC, m.id DESC""", (g.user["id"],)).fetchall()
    return render_template("dashboard/inbox.html", messages=rows, show=show)


@bp.route("/inbox/unread-count")
def unread_count():
    count = get_db().execute(
        "SELECT COUNT(*) FROM messages WHERE artist_id = ? AND status = 'unread'",
        (g.user["id"],)).fetchone()[0]
    response = jsonify(unread=count)
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.route("/inbox/<int:mid>", methods=["GET", "POST"])
def message(mid):
    msg = _own_message(mid)
    db = get_db()
    if request.method == "POST":
        actions = {"read": "read", "unread": "unread", "archive": "archived", "restore": "read"}
        action = request.form.get("action", "")
        note = request.form.get("note")
        if note is not None:
            db.execute("UPDATE messages SET artist_note = ? WHERE id = ?", (note.strip()[:1000], mid))
        if action in actions:
            db.execute("UPDATE messages SET status = ? WHERE id = ?", (actions[action], mid))
        db.commit()
        flash("Saved.", "ok")
        return redirect(url_for("dash.message", mid=mid) if action not in ("archive",)
                        else url_for("dash.inbox"))
    if msg["status"] == "unread":
        db.execute("UPDATE messages SET status = 'read' WHERE id = ?", (mid,))
        db.commit()
        msg = _own_message(mid)
    return render_template("dashboard/message.html", m=msg)


@bp.route("/profile", methods=["GET", "POST"])
def profile():
    errors = []
    form = {"display_name": g.user["display_name"], "bio": g.user["bio"]}
    if request.method == "POST":
        form = {"display_name": request.form.get("display_name", "").strip(),
                "bio": request.form.get("bio", "").strip()}
        if not 1 <= len(form["display_name"]) <= 60:
            errors.append("Enter the name to show on your paintings (up to 60 characters).")
        if len(form["bio"]) > 1500:
            errors.append("Keep your bio under 1,500 characters.")
        if not errors:
            db = get_db()
            db.execute("UPDATE users SET display_name = ?, bio = ? WHERE id = ?",
                       (form["display_name"], form["bio"], g.user["id"]))
            db.commit()
            flash("Profile saved.", "ok")
            return redirect(url_for("dash.profile"))
    return render_template("dashboard/profile.html", form=form, errors=errors)
