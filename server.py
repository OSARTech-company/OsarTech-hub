import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from functools import partial
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "coachlab.db"
SESSION_COOKIE = "coachlab_session"
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
INVITE_CODE = os.environ.get("INVITE_CODE", "").strip()
SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 180
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "").strip().lower()
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "").strip()

try:
    import psycopg  # type: ignore
except ImportError:
    psycopg = None


class DB:
    def __init__(self):
        self.mode = "sqlite"
        self.sqlite_path = DB_PATH
        self.postgres_url = None

        if DATABASE_URL:
            parsed = urlparse(DATABASE_URL)
            if parsed.scheme.startswith("postgres"):
                self.mode = "postgres"
                self.postgres_url = DATABASE_URL
            elif parsed.scheme.startswith("sqlite"):
                sqlite_target = parsed.path.lstrip("/")
                self.sqlite_path = BASE_DIR / sqlite_target if sqlite_target else DB_PATH

    def connect(self):
        if self.mode == "postgres":
            if psycopg is None:
                raise RuntimeError(
                    "DATABASE_URL points to PostgreSQL, but psycopg is not installed. "
                    "Run `pip install psycopg[binary]`."
                )
            connection = psycopg.connect(self.postgres_url, autocommit=False)
            connection.row_factory = psycopg.rows.dict_row
            return connection

        connection = sqlite3.connect(self.sqlite_path)
        connection.row_factory = sqlite3.Row
        return connection

    def integrity_error(self):
        return Exception if self.mode == "postgres" and psycopg is None else (psycopg.IntegrityError if self.mode == "postgres" else sqlite3.IntegrityError)

    def placeholder(self):
        return "%s" if self.mode == "postgres" else "?"

    def upsert_progress_sql(self):
        placeholder = self.placeholder()
        values = ", ".join([placeholder] * 9)
        return f"""
            INSERT INTO progress (
                user_id,
                active_mode,
                active_python_lesson,
                active_web_lesson,
                python_code,
                web_html,
                web_css,
                web_js,
                updated_at
            )
            VALUES ({values})
            ON CONFLICT(user_id) DO UPDATE SET
                active_mode = excluded.active_mode,
                active_python_lesson = excluded.active_python_lesson,
                active_web_lesson = excluded.active_web_lesson,
                python_code = excluded.python_code,
                web_html = excluded.web_html,
                web_css = excluded.web_css,
                web_js = excluded.web_js,
                updated_at = excluded.updated_at
        """

    def column_exists(self, connection, table_name, column_name):
        if self.mode == "postgres":
            row = connection.execute(
                """
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = %s AND column_name = %s
                """,
                (table_name, column_name),
            ).fetchone()
            return bool(row)

        row = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        return any(item["name"] == column_name for item in row)


db = DB()


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def row_to_dict(row):
    if row is None:
        return None
    if isinstance(row, sqlite3.Row):
        return dict(row)
    return dict(row)


def init_db():
    with db.connect() as connection:
        if db.mode == "postgres":
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE,
                    role TEXT NOT NULL DEFAULT 'learner',
                    password_hash TEXT NOT NULL,
                    password_salt TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
                    token TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS progress (
                    user_id INTEGER PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
                    active_mode TEXT NOT NULL,
                    active_python_lesson TEXT NOT NULL,
                    active_web_lesson TEXT NOT NULL,
                    python_code TEXT NOT NULL,
                    web_html TEXT NOT NULL,
                    web_css TEXT NOT NULL,
                    web_js TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
        else:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE,
                    role TEXT NOT NULL DEFAULT 'learner',
                    password_hash TEXT NOT NULL,
                    password_salt TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    token TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS progress (
                    user_id INTEGER PRIMARY KEY,
                    active_mode TEXT NOT NULL,
                    active_python_lesson TEXT NOT NULL,
                    active_web_lesson TEXT NOT NULL,
                    python_code TEXT NOT NULL,
                    web_html TEXT NOT NULL,
                    web_css TEXT NOT NULL,
                    web_js TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

        # Backward-compatible migration for older databases.
        if not db.column_exists(connection, "users", "role"):
            if db.mode == "postgres":
                connection.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'learner'")
            else:
                connection.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'learner'")

        seed_invite_code(connection, INVITE_CODE)
        bootstrap_super_admin(connection)
        connection.commit()


def get_setting(connection, key):
    placeholder = db.placeholder()
    row = connection.execute(
        f"SELECT value FROM settings WHERE key = {placeholder}",
        (key,),
    ).fetchone()
    data = row_to_dict(row)
    return data["value"] if data else None


def set_setting(connection, key, value):
    placeholder = db.placeholder()
    now = utc_now()
    if db.mode == "postgres":
        connection.execute(
            f"""
            INSERT INTO settings (key, value, updated_at)
            VALUES ({placeholder}, {placeholder}, {placeholder})
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (key, value, now),
        )
    else:
        connection.execute(
            f"""
            INSERT INTO settings (key, value, updated_at)
            VALUES ({placeholder}, {placeholder}, {placeholder})
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (key, value, now),
        )


def seed_invite_code(connection, invite_code):
    if invite_code:
        existing = get_setting(connection, "invite_code")
        if not existing:
            set_setting(connection, "invite_code", invite_code)


def bootstrap_super_admin(connection):
    if not ADMIN_EMAIL or not ADMIN_PASSWORD:
        return

    salt, password_hash = create_password_record(ADMIN_PASSWORD)
    placeholder = db.placeholder()
    now = utc_now()
    row = connection.execute(
        f"SELECT id FROM users WHERE email = {placeholder}",
        (ADMIN_EMAIL,),
    ).fetchone()
    existing = row_to_dict(row)

    if existing:
        connection.execute(
            f"""
            UPDATE users
            SET role = 'super_admin',
                password_hash = {placeholder},
                password_salt = {placeholder}
            WHERE id = {placeholder}
            """,
            (password_hash, salt, existing["id"]),
        )
    else:
        insert_sql = (
            f"INSERT INTO users (name, email, role, password_hash, password_salt, created_at) "
            f"VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})"
        )
        connection.execute(
            insert_sql,
            ("Super Admin", ADMIN_EMAIL, "super_admin", password_hash, salt, now),
        )


def current_invite_code():
    with db.connect() as connection:
        code = get_setting(connection, "invite_code")
        connection.commit()
    return code or INVITE_CODE


def hash_password(password, salt):
    hashed = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000)
    return hashed.hex()


def create_password_record(password):
    salt = secrets.token_hex(16)
    return salt, hash_password(password, salt)


def verify_password(password, salt, password_hash):
    calculated_hash = hash_password(password, salt)
    return hmac.compare_digest(calculated_hash, password_hash)


class CoachLabHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store" if self.path.startswith("/api/") else "no-cache")
        super().end_headers()

    def do_GET(self):
        request_path = urlparse(self.path).path

        if request_path.startswith("/exercise/"):
            self.path = "/index.html"
            super().do_GET()
            return

        if request_path == "/api/me":
            self.handle_get_me()
            return

        if request_path == "/api/progress":
            self.handle_get_progress()
            return

        if request_path == "/api/admin/me":
            self.handle_admin_me()
            return

        if request_path == "/api/admin/users":
            self.handle_admin_users()
            return

        if request_path == "/api/admin/stats":
            self.handle_admin_stats()
            return

        if request_path == "/api/admin/invite-code":
            self.handle_admin_invite_code_get()
            return

        super().do_GET()

    def do_POST(self):
        request_path = urlparse(self.path).path

        if request_path == "/api/register":
            self.handle_register()
            return

        if request_path == "/api/login":
            self.handle_login()
            return

        if request_path == "/api/logout":
            self.handle_logout()
            return

        if request_path == "/api/admin/users/role":
            self.handle_admin_user_role_update()
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_PUT(self):
        request_path = urlparse(self.path).path
        if request_path == "/api/progress":
            self.handle_save_progress()
            return

        if request_path == "/api/admin/invite-code":
            self.handle_admin_invite_code_update()
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def log_message(self, format, *args):
        return

    def parse_json_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid JSON body."})
            return None

    def send_json(self, status, payload, cookie_value=None, clear_cookie=False):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))

        if cookie_value:
            cookie = SimpleCookie()
            cookie[SESSION_COOKIE] = cookie_value
            cookie[SESSION_COOKIE]["path"] = "/"
            cookie[SESSION_COOKIE]["httponly"] = True
            cookie[SESSION_COOKIE]["samesite"] = "Lax"
            cookie[SESSION_COOKIE]["max-age"] = SESSION_MAX_AGE_SECONDS
            self.send_header("Set-Cookie", cookie.output(header="").strip())

        if clear_cookie:
            cookie = SimpleCookie()
            cookie[SESSION_COOKIE] = ""
            cookie[SESSION_COOKIE]["path"] = "/"
            cookie[SESSION_COOKIE]["max-age"] = 0
            cookie[SESSION_COOKIE]["httponly"] = True
            cookie[SESSION_COOKIE]["samesite"] = "Lax"
            self.send_header("Set-Cookie", cookie.output(header="").strip())

        self.end_headers()
        self.wfile.write(body)

    def current_session_token(self):
        cookie_header = self.headers.get("Cookie")
        if not cookie_header:
            return None

        cookie = SimpleCookie()
        cookie.load(cookie_header)
        morsel = cookie.get(SESSION_COOKIE)
        return morsel.value if morsel else None

    def current_user(self):
        token = self.current_session_token()
        if not token:
            return None

        placeholder = db.placeholder()
        with db.connect() as connection:
            row = connection.execute(
                f"""
                SELECT users.id, users.name, users.email
                     , users.role
                FROM sessions
                JOIN users ON users.id = sessions.user_id
                WHERE sessions.token = {placeholder}
                """,
                (token,),
            ).fetchone()

        return row_to_dict(row)

    def require_user(self):
        user = self.current_user()
        if not user:
            self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "Please log in first."}, clear_cookie=True)
            return None
        return user

    def require_admin(self):
        user = self.require_user()
        if not user:
            return None
        if user.get("role") != "super_admin":
            self.send_json(HTTPStatus.FORBIDDEN, {"error": "Super admin access required."})
            return None
        return user

    def create_session(self, user_id):
        token = secrets.token_urlsafe(32)
        placeholder = db.placeholder()
        with db.connect() as connection:
            connection.execute(
                f"INSERT INTO sessions (user_id, token, created_at) VALUES ({placeholder}, {placeholder}, {placeholder})",
                (user_id, token, utc_now()),
            )
            connection.commit()
        return token

    def delete_session(self):
        token = self.current_session_token()
        if not token:
            return

        placeholder = db.placeholder()
        with db.connect() as connection:
            connection.execute(f"DELETE FROM sessions WHERE token = {placeholder}", (token,))
            connection.commit()

    def handle_register(self):
        payload = self.parse_json_body()
        if payload is None:
            return

        name = str(payload.get("name", "")).strip()
        email = str(payload.get("email", "")).strip().lower()
        password = str(payload.get("password", ""))
        invite_code = str(payload.get("inviteCode", "")).strip()

        if not name:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Name is required."})
            return

        if "@" not in email:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "A valid email is required."})
            return

        if len(password) < 6:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Password must be at least 6 characters."})
            return

        active_invite_code = current_invite_code()
        if active_invite_code and invite_code != active_invite_code:
            self.send_json(HTTPStatus.FORBIDDEN, {"error": "Invalid invite code."})
            return

        salt, password_hash = create_password_record(password)
        placeholder = db.placeholder()
        insert_sql = (
            f"INSERT INTO users (name, email, role, password_hash, password_salt, created_at) "
            f"VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})"
        )

        try:
            with db.connect() as connection:
                if db.mode == "postgres":
                    row = connection.execute(
                        insert_sql + " RETURNING id",
                        (name, email, "learner", password_hash, salt, utc_now()),
                    ).fetchone()
                    user_id = row["id"]
                else:
                    cursor = connection.execute(
                        insert_sql,
                        (name, email, "learner", password_hash, salt, utc_now()),
                    )
                    user_id = cursor.lastrowid
                connection.commit()
        except db.integrity_error():
            self.send_json(HTTPStatus.CONFLICT, {"error": "That email already has an account."})
            return

        token = self.create_session(user_id)
        self.send_json(
            HTTPStatus.CREATED,
            {"user": {"id": user_id, "name": name, "email": email, "role": "learner"}},
            cookie_value=token,
        )

    def handle_login(self):
        payload = self.parse_json_body()
        if payload is None:
            return

        email = str(payload.get("email", "")).strip().lower()
        password = str(payload.get("password", ""))
        placeholder = db.placeholder()

        with db.connect() as connection:
            row = connection.execute(
                f"SELECT id, name, email, role, password_hash, password_salt FROM users WHERE email = {placeholder}",
                (email,),
            ).fetchone()

        row = row_to_dict(row)
        if not row or not verify_password(password, row["password_salt"], row["password_hash"]):
            self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "Incorrect email or password."})
            return

        token = self.create_session(row["id"])
        self.send_json(
            HTTPStatus.OK,
            {"user": {"id": row["id"], "name": row["name"], "email": row["email"], "role": row.get("role", "learner")}},
            cookie_value=token,
        )

    def handle_logout(self):
        self.delete_session()
        self.send_json(HTTPStatus.OK, {"ok": True}, clear_cookie=True)

    def handle_get_me(self):
        self.send_json(HTTPStatus.OK, {"user": self.current_user()})

    def handle_get_progress(self):
        user = self.require_user()
        if not user:
            return

        placeholder = db.placeholder()
        with db.connect() as connection:
            row = connection.execute(
                f"""
                SELECT active_mode, active_python_lesson, active_web_lesson, python_code, web_html, web_css, web_js
                FROM progress
                WHERE user_id = {placeholder}
                """,
                (user["id"],),
            ).fetchone()

        row = row_to_dict(row)
        if not row:
            self.send_json(HTTPStatus.OK, {"progress": None})
            return

        self.send_json(
            HTTPStatus.OK,
            {
                "progress": {
                    "activeMode": row["active_mode"],
                    "activePythonLessonId": row["active_python_lesson"],
                    "activeWebLessonId": row["active_web_lesson"],
                    "pythonCode": row["python_code"],
                    "webHtml": row["web_html"],
                    "webCss": row["web_css"],
                    "webJs": row["web_js"],
                }
            },
        )

    def handle_save_progress(self):
        user = self.require_user()
        if not user:
            return

        payload = self.parse_json_body()
        if payload is None:
            return

        progress = (
            user["id"],
            "web" if payload.get("activeMode") == "web" else "python",
            str(payload.get("activePythonLessonId", "python-warmup")),
            str(payload.get("activeWebLessonId", "web-card")),
            str(payload.get("pythonCode", "")),
            str(payload.get("webHtml", "")),
            str(payload.get("webCss", "")),
            str(payload.get("webJs", "")),
            utc_now(),
        )

        with db.connect() as connection:
            connection.execute(db.upsert_progress_sql(), progress)
            connection.commit()

        self.send_json(HTTPStatus.OK, {"ok": True})

    def handle_admin_me(self):
        user = self.require_admin()
        if not user:
            return
        self.send_json(HTTPStatus.OK, {"user": user})

    def handle_admin_users(self):
        admin = self.require_admin()
        if not admin:
            return

        with db.connect() as connection:
            rows = connection.execute(
                "SELECT id, name, email, role, created_at FROM users ORDER BY id DESC"
            ).fetchall()
        users = [row_to_dict(row) for row in rows]
        self.send_json(HTTPStatus.OK, {"users": users})

    def handle_admin_stats(self):
        admin = self.require_admin()
        if not admin:
            return

        with db.connect() as connection:
            users_count = row_to_dict(connection.execute("SELECT COUNT(*) AS count FROM users").fetchone())["count"]
            active_sessions = row_to_dict(connection.execute("SELECT COUNT(*) AS count FROM sessions").fetchone())["count"]
            progress_count = row_to_dict(connection.execute("SELECT COUNT(*) AS count FROM progress").fetchone())["count"]

        self.send_json(
            HTTPStatus.OK,
            {
                "stats": {
                    "users": users_count,
                    "activeSessions": active_sessions,
                    "progressRows": progress_count,
                }
            },
        )

    def handle_admin_invite_code_get(self):
        admin = self.require_admin()
        if not admin:
            return

        self.send_json(HTTPStatus.OK, {"inviteCode": current_invite_code()})

    def handle_admin_invite_code_update(self):
        admin = self.require_admin()
        if not admin:
            return

        payload = self.parse_json_body()
        if payload is None:
            return

        invite_code = str(payload.get("inviteCode", "")).strip()
        if len(invite_code) < 4:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Invite code must be at least 4 characters."})
            return

        with db.connect() as connection:
            set_setting(connection, "invite_code", invite_code)
            connection.commit()

        self.send_json(HTTPStatus.OK, {"ok": True, "inviteCode": invite_code})

    def handle_admin_user_role_update(self):
        admin = self.require_admin()
        if not admin:
            return

        payload = self.parse_json_body()
        if payload is None:
            return

        try:
            target_id = int(payload.get("userId"))
        except Exception:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Valid userId is required."})
            return

        role = str(payload.get("role", "")).strip()
        if role not in {"learner", "super_admin"}:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Role must be learner or super_admin."})
            return

        if admin["id"] == target_id and role != "super_admin":
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "You cannot remove your own super admin role."})
            return

        placeholder = db.placeholder()
        with db.connect() as connection:
            row = connection.execute(
                f"SELECT id FROM users WHERE id = {placeholder}",
                (target_id,),
            ).fetchone()
            if not row:
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "User not found."})
                return
            connection.execute(
                f"UPDATE users SET role = {placeholder} WHERE id = {placeholder}",
                (role, target_id),
            )
            connection.commit()

        self.send_json(HTTPStatus.OK, {"ok": True})


def run():
    init_db()
    port = int(os.environ.get("PORT", "8000"))
    handler = partial(CoachLabHandler, directory=str(BASE_DIR))
    server = ThreadingHTTPServer(("0.0.0.0", port), handler)
    db_label = db.postgres_url if db.mode == "postgres" else str(db.sqlite_path)
    print(f"CodeWithCoach Lab running on http://127.0.0.1:{port}")
    print(f"Database: {db.mode} -> {db_label}")
    server.serve_forever()


if __name__ == "__main__":
    run()
