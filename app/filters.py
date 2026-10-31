import re
from datetime import datetime

from flask import url_for
from markupsafe import Markup, escape

STATUS_LABELS = {
    "available": "Available",
    "reserved": "Reserved",
    "sold": "Sold",
    "hidden": "Hidden",
}


def init_app(app):
    @app.template_filter("money")
    def money(cents):
        if cents is None:
            return "Price on request"
        whole, frac = divmod(int(cents), 100)
        symbol = app.config["CURRENCY"]
        return f"{symbol}{whole:,}" if frac == 0 else f"{symbol}{whole:,}.{frac:02d}"

    @app.template_filter("when")
    def when(iso):
        try:
            return datetime.fromisoformat(iso).astimezone().strftime("%d %b %Y, %H:%M")
        except (TypeError, ValueError):
            return iso or ""

    @app.template_filter("paragraphs")
    def paragraphs(text):
        parts = [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]
        out = []
        for part in parts:
            safe = str(escape(part)).replace("\r\n", "\n").replace("\n", "<br>")
            out.append(f"<p>{safe}</p>")
        return Markup("".join(out))

    def image_url(key, size="medium"):
        return url_for("public.media", filename=f"{key}_{size}.jpg")

    app.jinja_env.globals["image_url"] = image_url
    app.jinja_env.globals["status_labels"] = STATUS_LABELS
