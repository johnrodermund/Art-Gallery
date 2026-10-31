import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from flask import current_app, g


def get_db():
    if "db" not in g:
        conn = sqlite3.connect(current_app.config["DATABASE"])
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        g.db = conn
    return g.db


def close_db(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db():
    """Create tables if they do not exist yet. Safe to run on every start."""
    schema = (Path(__file__).parent / "schema.sql").read_text()
    conn = sqlite3.connect(current_app.config["DATABASE"])
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(schema)
    conn.commit()
    conn.close()


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_app(app):
    app.teardown_appcontext(close_db)
