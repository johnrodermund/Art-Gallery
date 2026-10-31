from flask import (Blueprint, abort, current_app, flash, g, redirect,
                   render_template, request, send_from_directory, url_for)

from .db import get_db, now_iso

bp = Blueprint("public", __name__)

GALLERY_SQL = """
    SELECT p.*, u.display_name AS artist_name, u.username AS artist_username
    FROM paintings p JOIN users u ON u.id = p.artist_id
    WHERE p.status != 'hidden' AND u.active = 1 {extra}
    ORDER BY p.created_at DESC, p.id DESC
"""


@bp.route("/")
def index():
    only_available = request.args.get("available") == "1"
    extra = "AND p.status = 'available'" if only_available else ""
    paintings = get_db().execute(GALLERY_SQL.format(extra=extra)).fetchall()
    return render_template("index.html", paintings=paintings, only_available=only_available)


@bp.route("/artists")
def artists():
    rows = get_db().execute("""
        SELECT u.username, u.display_name, u.bio,
               COUNT(p.id) AS total,
               SUM(CASE WHEN p.status = 'available' THEN 1 ELSE 0 END) AS available
        FROM users u JOIN paintings p ON p.artist_id = u.id AND p.status != 'hidden'
        WHERE u.role = 'artist' AND u.active = 1
        GROUP BY u.id ORDER BY u.display_name COLLATE NOCASE
    """).fetchall()
    return render_template("artists.html", artists=rows)


@bp.route("/artists/<username>")
def artist(username):
    db = get_db()
    person = db.execute("SELECT * FROM users WHERE username = ? AND role = 'artist' "
                        "AND active = 1", (username,)).fetchone()
    if person is None:
        abort(404)
    paintings = db.execute(GALLERY_SQL.format(extra="AND u.id = ?"), (person["id"],)).fetchall()
    return render_template("artist.html", person=person, paintings=paintings)


def _visible_painting(pid):
    row = get_db().execute("""
        SELECT p.*, u.display_name AS artist_name, u.username AS artist_username
        FROM paintings p JOIN users u ON u.id = p.artist_id
        WHERE p.id = ? AND p.status != 'hidden' AND u.active = 1""", (pid,)).fetchone()
    if row is None:
        abort(404)
    return row


@bp.route("/painting/<int:pid>")
def painting(pid):
    return render_template("painting.html", p=_visible_painting(pid), form={}, errors=[])


@bp.route("/painting/<int:pid>/request", methods=["POST"])
def buy_request(pid):
    p = _visible_painting(pid)
    if p["status"] != "available":
        flash("This painting is no longer available.", "error")
        return redirect(url_for("public.painting", pid=pid))

    # Hidden field that people never fill in; simple bots do.
    if request.form.get("website", "").strip():
        flash(f"Your request has been sent to {p['artist_name']}.", "ok")
        return redirect(url_for("public.painting", pid=pid))

    limiter = current_app.extensions["limiter"]
    key = f"buy:{request.remote_addr}"
    if limiter.blocked(key, 5, 600):
        flash("You have sent several requests recently. Please wait a few minutes.", "error")
        return redirect(url_for("public.painting", pid=pid))

    form = {k: request.form.get(k, "").strip() for k in ("name", "contact", "message")}
    errors = []
    if not 1 <= len(form["name"]) <= 80:
        errors.append("Enter your name (up to 80 characters).")
    if not 3 <= len(form["contact"]) <= 120:
        errors.append("Enter an email address or phone number the artist can reach you on.")
    if len(form["message"]) > 2000:
        errors.append("Keep your message under 2,000 characters.")
    if errors:
        return render_template("painting.html", p=p, form=form, errors=errors), 400

    db = get_db()
    db.execute(
        "INSERT INTO messages (artist_id, painting_id, painting_title, buyer_name, "
        "buyer_contact, body, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (p["artist_id"], p["id"], p["title"], form["name"], form["contact"],
         form["message"], now_iso()))
    db.commit()
    limiter.record(key, 600)
    flash(f"Your request has been sent to {p['artist_name']}. They will contact you "
          "using the details you gave.", "ok")
    return redirect(url_for("public.painting", pid=pid))


@bp.route("/media/<path:filename>")
def media(filename):
    return send_from_directory(current_app.config["MEDIA_ROOT"] / "paintings",
                               filename, max_age=86400)
