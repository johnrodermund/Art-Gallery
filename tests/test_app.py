import io
import os
import re
import shutil
import tempfile
import unittest

from PIL import Image
from werkzeug.security import generate_password_hash

from app import create_app
from app.db import get_db, now_iso


def png_bytes(size=(800, 600), color=(180, 80, 60)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    buf.seek(0)
    return buf


class GalleryTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        os.environ["ARTGALLERY_HOME"] = self.home
        self.app = create_app({"TESTING": True})
        self.ctx = self.app.app_context()
        self.ctx.push()
        for username, role in (("ana", "artist"), ("ben", "artist"), ("root", "admin")):
            self._user(username, role)
        self.client = self.app.test_client()

    def tearDown(self):
        self.ctx.pop()
        shutil.rmtree(self.home, ignore_errors=True)

    def _user(self, username, role, password="correct-horse-1", must_change=0):
        db = get_db()
        db.execute("INSERT INTO users (username, display_name, role, password_hash, "
                   "must_change_password, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                   (username, username.title(), role, generate_password_hash(password),
                    must_change, now_iso()))
        db.commit()

    def token(self, client, path="/login"):
        html = client.get(path).get_data(as_text=True)
        return re.search(r'name="_csrf" value="([^"]+)"', html).group(1)

    def login(self, client, username, password="correct-horse-1"):
        return client.post("/login", data={"username": username, "password": password,
                                           "_csrf": self.token(client)})

    def upload(self, client, title="Harbour", price="450", status="available", **extra):
        data = {"title": title, "description": "Oil", "price": price, "status": status,
                "_csrf": self.token(client, "/dashboard/paintings/new"),
                "image": (png_bytes(), "p.png")}
        data.update(extra)
        return client.post("/dashboard/paintings/new", data=data,
                          content_type="multipart/form-data")

    def artist_with_painting(self, username="ana", **kw):
        client = self.app.test_client()
        self.assertEqual(self.login(client, username).status_code, 302)
        self.assertEqual(self.upload(client, **kw).status_code, 302)
        return client

    # ---- public pages ----------------------------------------------------
    def test_empty_gallery_renders(self):
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("No paintings are listed yet", res.get_data(as_text=True))

    def test_security_headers_and_no_external_urls(self):
        self.artist_with_painting()
        res = self.client.get("/")
        self.assertIn("default-src 'self'", res.headers["Content-Security-Policy"])
        html = res.get_data(as_text=True)
        self.assertNotRegex(html, r'(src|href)="https?://')

    # ---- login and sessions ---------------------------------------------
    def test_dashboard_requires_login(self):
        res = self.client.get("/dashboard/")
        self.assertEqual(res.status_code, 302)
        self.assertIn("/login", res.headers["Location"])

    def test_login_wrong_password_and_rate_limit(self):
        for _ in range(5):
            self.assertEqual(self.login(self.client, "ana", "wrong-password").status_code, 401)
        self.assertEqual(self.login(self.client, "ana", "wrong-password").status_code, 429)
        # even the right password is refused while locked out
        self.assertEqual(self.login(self.client, "ana").status_code, 429)

    def test_open_redirect_blocked(self):
        token = self.token(self.client)
        res = self.client.post("/login?next=//evil.example", data={
            "username": "ana", "password": "correct-horse-1", "_csrf": token})
        self.assertEqual(res.status_code, 302)
        self.assertNotIn("evil.example", res.headers["Location"])

    def test_csrf_required(self):
        res = self.client.post("/login", data={"username": "ana", "password": "correct-horse-1"})
        self.assertEqual(res.status_code, 400)

    def test_forced_password_change(self):
        self._user("newbie", "artist", password="temporary-pass-1", must_change=1)
        client = self.app.test_client()
        self.assertEqual(self.login(client, "newbie", "temporary-pass-1").status_code, 302)
        res = client.get("/dashboard/")
        self.assertEqual(res.status_code, 302)
        self.assertIn("/account/password", res.headers["Location"])
        res = client.post("/account/password", data={
            "current_password": "temporary-pass-1", "new_password": "a-better-pass-9",
            "confirm_password": "a-better-pass-9", "_csrf": self.token(client, "/account/password")})
        self.assertEqual(res.status_code, 302)
        self.assertEqual(client.get("/dashboard/").status_code, 200)

    # ---- painting management --------------------------------------------
    def test_upload_creates_resized_files(self):
        self.artist_with_painting()
        row = get_db().execute("SELECT * FROM paintings").fetchone()
        folder = os.path.join(self.home, "media", "paintings")
        for name in ("thumb", "medium", "large"):
            self.assertTrue(os.path.exists(os.path.join(folder, f"{row['image_key']}_{name}.jpg")))
        self.assertEqual((row["width"], row["height"]), (800, 600))
        self.assertEqual(row["price_cents"], 45000)
        res = self.client.get(f"/media/{row['image_key']}_thumb.jpg")
        self.assertEqual(res.status_code, 200)
        res.close()

    def test_bad_upload_rejected(self):
        client = self.app.test_client()
        self.login(client, "ana")
        res = client.post("/dashboard/paintings/new", data={
            "title": "Fake", "status": "available",
            "_csrf": self.token(client, "/dashboard/paintings/new"),
            "image": (io.BytesIO(b"<script>alert(1)</script>"), "x.png")},
            content_type="multipart/form-data")
        self.assertEqual(res.status_code, 200)
        self.assertIn("could not be read as an image", res.get_data(as_text=True))
        self.assertEqual(get_db().execute("SELECT COUNT(*) FROM paintings").fetchone()[0], 0)

    def test_bad_price_rejected(self):
        client = self.app.test_client()
        self.login(client, "ana")
        res = self.upload(client, price="abc")
        self.assertEqual(res.status_code, 200)
        self.assertIn("price as a number", res.get_data(as_text=True))

    def test_hidden_painting_not_public(self):
        self.artist_with_painting(status="hidden")
        pid = get_db().execute("SELECT id FROM paintings").fetchone()["id"]
        self.assertEqual(self.client.get(f"/painting/{pid}").status_code, 404)
        self.assertNotIn("Harbour", self.client.get("/").get_data(as_text=True))

    def test_artist_cannot_touch_other_artists_painting(self):
        self.artist_with_painting("ana")
        pid = get_db().execute("SELECT id FROM paintings").fetchone()["id"]
        ben = self.app.test_client()
        self.login(ben, "ben")
        self.assertEqual(ben.get(f"/dashboard/paintings/{pid}/edit").status_code, 404)
        token = self.token(ben, "/dashboard/")
        self.assertEqual(ben.post(f"/dashboard/paintings/{pid}/delete", data={"_csrf": token}).status_code, 404)
        self.assertEqual(ben.post(f"/dashboard/paintings/{pid}/status",
                                  data={"_csrf": token, "status": "sold"}).status_code, 404)

    def test_delete_removes_files(self):
        client = self.artist_with_painting()
        row = get_db().execute("SELECT * FROM paintings").fetchone()
        res = client.post(f"/dashboard/paintings/{row['id']}/delete",
                          data={"_csrf": self.token(client, "/dashboard/")})
        self.assertEqual(res.status_code, 302)
        folder = os.path.join(self.home, "media", "paintings")
        self.assertEqual(os.listdir(folder), [])

    # ---- buy requests and inbox ------------------------------------------
    def buy(self, pid, **overrides):
        data = {"name": "Sam", "contact": "sam@example.test", "message": "Is it still here?",
                "_csrf": self.token(self.client, "/login")}
        data.update(overrides)
        return self.client.post(f"/painting/{pid}/request", data=data)

    def test_buy_request_reaches_only_the_right_artist(self):
        ana = self.artist_with_painting("ana")
        pid = get_db().execute("SELECT id FROM paintings").fetchone()["id"]
        self.assertEqual(self.buy(pid).status_code, 302)
        self.assertEqual(get_db().execute("SELECT COUNT(*) FROM messages").fetchone()[0], 1)

        page = ana.get("/dashboard/inbox").get_data(as_text=True)
        self.assertIn("Sam asked about", page)
        self.assertEqual(ana.get("/dashboard/inbox/unread-count").get_json(), {"unread": 1})

        ben = self.app.test_client()
        self.login(ben, "ben")
        self.assertNotIn("Sam asked about", ben.get("/dashboard/inbox").get_data(as_text=True))
        mid = get_db().execute("SELECT id FROM messages").fetchone()["id"]
        self.assertEqual(ben.get(f"/dashboard/inbox/{mid}").status_code, 404)

        detail = ana.get(f"/dashboard/inbox/{mid}").get_data(as_text=True)
        self.assertIn("sam@example.test", detail)
        self.assertEqual(ana.get("/dashboard/inbox/unread-count").get_json(), {"unread": 0})

    def test_buy_request_validation_and_honeypot(self):
        self.artist_with_painting()
        pid = get_db().execute("SELECT id FROM paintings").fetchone()["id"]
        self.assertEqual(self.buy(pid, name="").status_code, 400)
        self.assertEqual(self.buy(pid, website="http://spam.example").status_code, 302)
        self.assertEqual(get_db().execute("SELECT COUNT(*) FROM messages").fetchone()[0], 0)

    def test_buy_request_rate_limited_and_sold_blocked(self):
        self.artist_with_painting()
        pid = get_db().execute("SELECT id FROM paintings").fetchone()["id"]
        for _ in range(5):
            self.buy(pid)
        self.buy(pid)
        self.assertEqual(get_db().execute("SELECT COUNT(*) FROM messages").fetchone()[0], 5)
        get_db().execute("UPDATE paintings SET status = 'sold'")
        get_db().commit()
        self.buy(pid)
        self.assertEqual(get_db().execute("SELECT COUNT(*) FROM messages").fetchone()[0], 5)

    def test_messages_are_escaped(self):
        ana = self.artist_with_painting()
        pid = get_db().execute("SELECT id FROM paintings").fetchone()["id"]
        self.buy(pid, name="<b>Eve</b>", message="<script>alert(1)</script>")
        mid = get_db().execute("SELECT id FROM messages").fetchone()["id"]
        html = ana.get(f"/dashboard/inbox/{mid}").get_data(as_text=True)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)

    # ---- admin -----------------------------------------------------------
    def test_admin_creates_artist_with_temporary_password(self):
        admin = self.app.test_client()
        self.login(admin, "root")
        res = admin.post("/admin/artists/new", data={
            "username": "cleo", "display_name": "Cleo Park",
            "_csrf": self.token(admin, "/admin/artists/new")})
        self.assertEqual(res.status_code, 200)
        password = re.search(r"<code>([^<]+)</code>", res.get_data(as_text=True)).group(1)
        cleo = self.app.test_client()
        self.assertEqual(self.login(cleo, "cleo", password).status_code, 302)
        self.assertIn("/account/password", cleo.get("/dashboard/").headers["Location"])

    def test_artists_cannot_open_admin_and_inactive_cannot_login(self):
        ana = self.app.test_client()
        self.login(ana, "ana")
        self.assertEqual(ana.get("/admin/").status_code, 403)
        admin = self.app.test_client()
        self.login(admin, "root")
        uid = get_db().execute("SELECT id FROM users WHERE username='ana'").fetchone()["id"]
        admin.post(f"/admin/artists/{uid}/active", data={"_csrf": self.token(admin, "/admin/")})
        self.assertEqual(ana.get("/dashboard/").status_code, 302)  # existing session ended
        self.assertEqual(self.login(self.app.test_client(), "ana").status_code, 401)

    def test_admin_can_hide_painting(self):
        self.artist_with_painting()
        pid = get_db().execute("SELECT id FROM paintings").fetchone()["id"]
        admin = self.app.test_client()
        self.login(admin, "root")
        admin.post(f"/admin/paintings/{pid}/hide", data={"_csrf": self.token(admin, "/admin/paintings")})
        self.assertEqual(self.client.get(f"/painting/{pid}").status_code, 404)


if __name__ == "__main__":
    unittest.main()
