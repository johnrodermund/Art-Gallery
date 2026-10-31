"""Admin commands for the gallery.

    python manage.py create-admin            create the site administrator
    python manage.py list-users              show accounts
    python manage.py reset-password NAME     set a new password for an account
    python manage.py backup                  zip the database and images
    python manage.py demo                    load sample artists and paintings
"""
import argparse
import getpass
import random
import re
import sqlite3
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from werkzeug.security import generate_password_hash

from app import create_app
from app.db import get_db, now_iso

MIN_PASSWORD = 10
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,29}$")


def ask_password(given):
    if given:
        password = given
    else:
        password = getpass.getpass("Password (at least 10 characters): ")
        if password != getpass.getpass("Repeat password: "):
            sys.exit("The passwords do not match.")
    if len(password) < MIN_PASSWORD:
        sys.exit(f"Use at least {MIN_PASSWORD} characters.")
    return password


def add_user(username, display_name, role, password, must_change=False):
    username = username.strip().lower()
    if not USERNAME_RE.match(username):
        sys.exit("Username must be 3 to 30 characters: lowercase letters, numbers, - or _.")
    db = get_db()
    try:
        db.execute(
            "INSERT INTO users (username, display_name, role, password_hash, "
            "must_change_password, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (username, display_name, role, generate_password_hash(password),
             1 if must_change else 0, now_iso()))
        db.commit()
    except sqlite3.IntegrityError:
        sys.exit(f"The username '{username}' already exists.")
    return db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()["id"]


def cmd_create_admin(args, app):
    add_user(args.username, args.display_name or args.username, "admin", ask_password(args.password))
    print(f"Administrator '{args.username}' created. Log in at /login.")


def cmd_create_artist(args, app):
    add_user(args.username, args.display_name or args.username, "artist",
             ask_password(args.password), must_change=args.temporary)
    print(f"Artist '{args.username}' created.")


def cmd_list_users(args, app):
    rows = get_db().execute(
        "SELECT username, display_name, role, active FROM users ORDER BY role, username").fetchall()
    for r in rows:
        print(f"{r['username']:<20} {r['role']:<7} {'active' if r['active'] else 'inactive':<9} {r['display_name']}")
    if not rows:
        print("No accounts yet. Run: python manage.py create-admin")


def cmd_reset_password(args, app):
    db = get_db()
    if not db.execute("SELECT 1 FROM users WHERE username = ?", (args.username,)).fetchone():
        sys.exit("No such user.")
    db.execute("UPDATE users SET password_hash = ?, must_change_password = ? WHERE username = ?",
               (generate_password_hash(ask_password(args.password)),
                1 if args.temporary else 0, args.username))
    db.commit()
    print("Password updated.")


def cmd_backup(args, app):
    home = Path(app.config["HOME"])
    target_dir = Path(args.to) if args.to else home / "backups"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"gallery-{datetime.now():%Y%m%d-%H%M%S}.zip"
    with tempfile.TemporaryDirectory() as tmp:
        snapshot = Path(tmp) / "gallery.db"
        source = sqlite3.connect(app.config["DATABASE"])
        copy = sqlite3.connect(snapshot)
        source.backup(copy)  # consistent copy even while the site is running
        copy.close()
        source.close()
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(snapshot, "gallery.db")
            media = Path(app.config["MEDIA_ROOT"])
            for path in sorted(media.rglob("*")):
                if path.is_file():
                    archive.write(path, Path("media") / path.relative_to(media))
    print(f"Backup written to {target}")


def cmd_demo(args, app):
    from PIL import Image, ImageDraw, ImageFilter
    from app import images

    db = get_db()
    if db.execute("SELECT COUNT(*) FROM paintings").fetchone()[0] and not args.force:
        sys.exit("The gallery already has paintings. Use --force to add demo data anyway.")
    rng = random.Random(7)
    palettes = [
        [(222, 120, 70), (36, 54, 98), (240, 214, 160), (88, 140, 130)],
        [(30, 92, 110), (232, 196, 90), (170, 60, 70), (240, 238, 228)],
        [(70, 100, 60), (200, 170, 120), (30, 40, 36), (210, 120, 90)],
        [(60, 60, 120), (200, 90, 140), (250, 220, 120), (30, 30, 50)],
    ]

    def make(width, height, palette):
        img = Image.new("RGB", (width, height), palette[0])
        for _ in range(14):
            layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            draw = ImageDraw.Draw(layer)
            color = rng.choice(palette) + (rng.randint(90, 200),)
            x, y = rng.randint(-100, width), rng.randint(-100, height)
            w, h = rng.randint(200, width), rng.randint(120, height // 2 + 100)
            if rng.random() < 0.5:
                draw.ellipse([x, y, x + w, y + h], fill=color)
            else:
                draw.rectangle([x, y, x + w, y + h], fill=color)
            img = Image.alpha_composite(img.convert("RGBA"), layer.filter(
                ImageFilter.GaussianBlur(rng.randint(4, 30)))).convert("RGB")
        return img

    people = {
        "mara": ("Mara Lindqvist", "Mara paints large, layered landscapes from memory, "
                 "working in oil and cold wax."),
        "jonah": ("Jonah Okafor", "Jonah works on small and medium canvases, mixing "
                  "bold colour fields with soft edges."),
    }
    ids = {}
    for username, (name, bio) in people.items():
        row = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if row:
            ids[username] = row["id"]
        else:
            ids[username] = add_user(username, name, "artist", "demo-password-123")
        db.execute("UPDATE users SET bio = ? WHERE id = ?", (bio, ids[username]))
    db.commit()

    works = [
        ("mara", "Low tide, Sunday", 1600, 1100, 1450, "available"),
        ("mara", "Orchard in October", 1100, 1500, 2200, "available"),
        ("mara", "Salt and slate", 1400, 1400, None, "reserved"),
        ("mara", "The long field", 1800, 900, 1800, "sold"),
        ("jonah", "Blue room", 1200, 1500, 600, "available"),
        ("jonah", "Two windows", 1500, 1500, 750, "available"),
        ("jonah", "Late bus", 1700, 1100, 480, "available"),
        ("jonah", "Almost green", 1100, 1400, 520, "hidden"),
    ]
    media_root = app.config["MEDIA_ROOT"]
    first_painting = None
    for i, (who, title, w, h, price, status) in enumerate(works):
        img = make(w, h, palettes[i % len(palettes)])
        # A NamedTemporaryFile can't be reopened by name on Windows while it is open.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "demo.png"
            img.save(path)
            with open(path, "rb") as handle:
                class Upload:
                    stream = handle
                key, width, height = images.save_painting_image(Upload, media_root)
        now = now_iso()
        cur = db.execute(
            "INSERT INTO paintings (artist_id, title, description, price_cents, status, "
            "image_key, width, height, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ids[who], title, "Oil on canvas. Sample painting generated for the demo.",
             None if price is None else price * 100, status, key, width, height, now, now))
        first_painting = first_painting or cur.lastrowid
    db.execute(
        "INSERT INTO messages (artist_id, painting_id, painting_title, buyer_name, buyer_contact, "
        "body, created_at) VALUES (?, ?, 'Low tide, Sunday', 'Sam Rivera', 'sam@example.test', "
        "'Is this still available? I could collect it this weekend.', ?)",
        (ids["mara"], first_painting, now_iso()))
    db.commit()
    print("Demo data loaded.")
    print("Artist logins: mara or jonah, password: demo-password-123")
    print("These accounts are for trying the site only. Remove or change them before real use.")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create-admin")
    p.add_argument("--username", required=True)
    p.add_argument("--display-name")
    p.add_argument("--password", help="Omit to be prompted (recommended)")
    p.set_defaults(func=cmd_create_admin)

    p = sub.add_parser("create-artist")
    p.add_argument("--username", required=True)
    p.add_argument("--display-name")
    p.add_argument("--password", help="Omit to be prompted (recommended)")
    p.add_argument("--temporary", action="store_true", help="Make them choose a new password at first login")
    p.set_defaults(func=cmd_create_artist)

    sub.add_parser("list-users").set_defaults(func=cmd_list_users)

    p = sub.add_parser("reset-password")
    p.add_argument("username")
    p.add_argument("--password", help="Omit to be prompted (recommended)")
    p.add_argument("--temporary", action="store_true")
    p.set_defaults(func=cmd_reset_password)

    p = sub.add_parser("backup")
    p.add_argument("--to", help="Folder to save the backup in (default: instance/backups)")
    p.set_defaults(func=cmd_backup)

    p = sub.add_parser("demo")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_demo)

    args = parser.parse_args()
    app = create_app()
    with app.app_context():
        args.func(args, app)


if __name__ == "__main__":
    main()
