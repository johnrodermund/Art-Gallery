CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name TEXT NOT NULL,
    bio TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL CHECK (role IN ('artist', 'admin')),
    password_hash TEXT NOT NULL,
    must_change_password INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paintings (
    id INTEGER PRIMARY KEY,
    artist_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    price_cents INTEGER CHECK (price_cents IS NULL OR price_cents >= 0),
    status TEXT NOT NULL DEFAULT 'available'
        CHECK (status IN ('available', 'reserved', 'sold', 'hidden')),
    image_key TEXT NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_paintings_artist ON paintings(artist_id);
CREATE INDEX IF NOT EXISTS idx_paintings_status ON paintings(status);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    artist_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    painting_id INTEGER REFERENCES paintings(id) ON DELETE SET NULL,
    painting_title TEXT NOT NULL,
    buyer_name TEXT NOT NULL,
    buyer_contact TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'unread'
        CHECK (status IN ('unread', 'read', 'archived')),
    artist_note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_artist ON messages(artist_id, status);
