# Studio Wall: a local gallery for selling paintings

A website where several artists each log in, list paintings (image, title,
description, price) and receive buy requests. It runs entirely on one computer.
Nothing calls out to the internet: images are stored on disk, fonts are system
fonts, and a buyer's "Request this painting" form creates a message in the
artist's inbox on the site instead of sending an email.

It follows the "fully local" design: one web app, a SQLite file and an image folder.

```
 Buyer / artist browser
          |
   Local web app (Python, Flask)
   +-- Auth            login, sessions, password hashing
   +-- Message inbox   buy requests and notes
   +-- Painting pages  gallery, uploads, thumbnails
          |                       |
   SQLite file (instance/)    Image folder (instance/media/)
```

Note: the design called for Django. This build uses Flask because Django could
not be installed where it was built (no network), and everything here was
tested. The structure is the same; the pieces Django would supply (login,
hashing, CSRF, upload handling) are implemented in `app/security.py`,
`app/auth.py` and `app/images.py`.

## Quick start

Requires Python 3.9 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python manage.py create-admin --username admin   # asks for a password
python run.py                                    # http://127.0.0.1:8000
```

Want to see it with sample content first?

```bash
python manage.py demo        # two sample artists, eight generated paintings
```

Demo artist logins: `mara` or `jonah`, password `demo-password-123`.
Remove or change these before real use.

## How people use it

- **Buyers** browse the gallery, open a painting and fill in the request form
  (name, email or phone, optional message). No account is needed.
- **Artists** log in at `/login`. "My paintings" lists their work; they add or
  edit paintings, upload a photo, set a price (or leave it empty for
  "Price on request") and change the status (available, reserved, sold, hidden).
  "Inbox" shows buyer requests with an unread count. Artists add private notes,
  archive requests, and mark a painting reserved or sold from a request.
- **The admin** (created with `manage.py`) adds artists, gets a one-time
  temporary password to hand to each artist, resets passwords, deactivates
  accounts, and can hide or delete any painting.

Artists must choose their own password at first login. There is no email, so
password resets go through the admin.

## Making it reachable on your network

```bash
python run.py --host 0.0.0.0 --port 8000
```

Other devices on the same network can then open `http://<this-computer's-address>:8000`.
For anything beyond a small trusted network, use a proper server:

```bash
pip install waitress
waitress-serve --listen=0.0.0.0:8000 wsgi:application
```

and put it behind HTTPS (for example Caddy with its internal certificate
authority, or mkcert), then set `ARTGALLERY_SECURE_COOKIES=1`. Without HTTPS,
artist passwords travel unencrypted across the network.

Making the site reachable from the internet needs port forwarding or a tunnel.
That goes beyond the "no external calls" design, so it is not set up here.

## Settings (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `ARTGALLERY_HOME` | `./instance` | Folder for the database, images, secret key and backups |
| `ARTGALLERY_SITE_NAME` | `Studio Wall` | Name shown in the header |
| `ARTGALLERY_CURRENCY` | `$` | Currency symbol for prices |
| `ARTGALLERY_SECURE_COOKIES` | off | Set to `1` when serving over HTTPS |

## Backups

Everything lives in `ARTGALLERY_HOME`. Make a consistent copy any time, even
while the site is running:

```bash
python manage.py backup --to /path/to/another/disk
```

To restore, unzip it into the `instance` folder (`gallery.db` and `media/`).
Test a restore once before you rely on it.

## Admin commands

```
python manage.py create-admin   --username NAME
python manage.py create-artist  --username NAME --temporary
python manage.py list-users
python manage.py reset-password NAME --temporary
python manage.py backup
python manage.py demo
```

## Security notes

- Passwords are hashed with scrypt (Werkzeug), minimum 10 characters.
- Session cookies are HTTP-only and SameSite=Lax; sessions are renewed at login.
- Every form carries a CSRF token. Pages send a strict Content-Security-Policy
  (no inline scripts or external resources).
- Login is rate limited (5 failures per username and address, then 15 minutes).
  Buy requests are limited to 5 per address per 10 minutes and use a hidden
  honeypot field. These limits are kept in memory and reset on restart.
- Uploads are fully decoded and re-encoded as new JPEGs, which removes metadata
  such as GPS location and rejects non-images. Files get random names.
- Artists can only see and edit their own paintings and requests.
- Buyer names and contact details are stored in the database until deleted.
  Tell buyers how you will use them.

## Known limits

- No email or push notifications: artists see requests when they open the site
  (the badge refreshes every 30 seconds while a page is open).
- No online payments; a request is a message, not an order.
- Run a single server process. The login limiter is per process, and SQLite
  suits a small site with modest traffic.
- Behind a reverse proxy, rate limits see the proxy's address unless you
  configure forwarded addresses.

## Tests

```bash
python -m unittest discover -s tests -v
```

## Layout

```
app/            application code (auth, public, dashboard, admin, images, security)
app/templates/  HTML pages
app/static/     stylesheet and a little JavaScript
manage.py       admin commands
run.py          start with the built-in server
wsgi.py         entry point for waitress or gunicorn
tests/          automated tests
instance/       created at first run: database, media, secret_key, backups
```
