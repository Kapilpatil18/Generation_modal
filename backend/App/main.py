from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs
from threading import Thread
from wsgiref.simple_server import make_server


BASE_DIR = Path(__file__).resolve().parents[1]
ENV_FILE = BASE_DIR / ".env"
def resolve_db_path() -> Path:
    """Return the SQLite database path, allowing isolated local test databases."""
    configured = ENV.get("DATABASE_PATH") or ENV.get("DATABASE_URL", "")
    if configured.startswith("sqlite:///"):
        configured = configured.removeprefix("sqlite:///")
    if configured:
        path = Path(configured)
        return path if path.is_absolute() else BASE_DIR / path
    return BASE_DIR / "app.db"


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


ENV = {**load_env_file(ENV_FILE), **os.environ}
DB_PATH = resolve_db_path()
SECRET_KEY = ENV.get("SECRET_KEY", "change-me-in-production").encode("utf-8")
FRONTEND_URL = ENV.get("FRONTEND_URL", "http://localhost:5173")
MAX_REQUEST_BODY_BYTES = 20_000
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                username TEXT NOT NULL UNIQUE,
                hashed_password TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                prompt TEXT NOT NULL,
                status TEXT NOT NULL,
                s3_key TEXT,
                task_id TEXT,
                created_at TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        conn.commit()


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
    return f"{salt.hex()}:{digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split(":", 1)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except ValueError:
        return False

    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
    return hmac.compare_digest(digest, expected)


def base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def base64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def create_access_token(email: str) -> str:
    payload = {"sub": email, "exp": int(time.time()) + 3600}
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    payload_part = base64url_encode(payload_bytes)
    signature = hmac.new(SECRET_KEY, payload_part.encode("ascii"), hashlib.sha256).digest()
    return f"{payload_part}.{base64url_encode(signature)}"


def decode_token(token: str) -> dict[str, Any] | None:
    try:
        payload_part, signature_part = token.split(".", 1)
        expected_signature = hmac.new(SECRET_KEY, payload_part.encode("ascii"), hashlib.sha256).digest()
        provided_signature = base64url_decode(signature_part)
        if not hmac.compare_digest(expected_signature, provided_signature):
            return None
        payload = json.loads(base64url_decode(payload_part).decode("utf-8"))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


def read_body(environ: dict[str, Any]) -> bytes:
    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
    except ValueError as exc:
        raise ValueError("Invalid request body length") from exc
    if length <= 0:
        return b""
    if length > MAX_REQUEST_BODY_BYTES:
        raise ValueError("Request body is too large")
    return environ["wsgi.input"].read(length)


def get_json_body(environ: dict[str, Any]) -> dict[str, Any]:
    raw_body = read_body(environ)
    if not raw_body:
        return {}
    payload = json.loads(raw_body.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("JSON body must be an object")
    return payload


def get_form_body(environ: dict[str, Any]) -> dict[str, str]:
    raw_body = read_body(environ).decode("utf-8")
    parsed = parse_qs(raw_body)
    return {key: values[0] for key, values in parsed.items()}


def get_bearer_token(environ: dict[str, Any]) -> str | None:
    auth_header = environ.get("HTTP_AUTHORIZATION", "")
    if not auth_header.startswith("Bearer "):
        return None
    return auth_header.removeprefix("Bearer ").strip()


def response_headers(content_length: int) -> list[tuple[str, str]]:
    return [
        ("Content-Type", "application/json; charset=utf-8"),
        ("Content-Length", str(content_length)),
        ("Access-Control-Allow-Origin", FRONTEND_URL),
        ("Access-Control-Allow-Credentials", "true"),
        ("Access-Control-Allow-Methods", "GET,POST,DELETE,OPTIONS"),
        ("Access-Control-Allow-Headers", "Content-Type, Authorization"),
    ]


def json_response(start_response, status: str, payload: Any, extra_headers: list[tuple[str, str]] | None = None):
    body = json.dumps(payload).encode("utf-8")
    headers = [
        *response_headers(len(body)),
    ]
    if extra_headers:
        headers.extend(extra_headers)
    start_response(status, headers)
    return [body]


def empty_response(start_response, status: str):
    headers = response_headers(0)
    headers = [header for header in headers if header[0] != "Content-Type"]
    start_response(status, headers)
    return []


def error_response(start_response, status: str, detail: str):
    return json_response(start_response, status, {"detail": detail})


def get_current_user(environ: dict[str, Any]) -> sqlite3.Row | None:
    token = get_bearer_token(environ)
    if not token:
        return None
    payload = decode_token(token)
    if not payload:
        return None
    email = payload.get("sub")
    if not email:
        return None
    with connect_db() as conn:
        return conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()


def row_to_user(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "email": row["email"],
        "username": row["username"],
        "is_active": bool(row["is_active"]),
        "created_at": row["created_at"],
    }


def row_to_video(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "prompt": row["prompt"],
        "status": row["status"],
        "s3_key": row["s3_key"],
        "task_id": row["task_id"],
        "created_at": row["created_at"],
    }


def simulate_video_generation(video_id: int) -> None:
    try:
        with connect_db() as conn:
            conn.execute(
                "UPDATE videos SET status = ?, task_id = ? WHERE id = ?",
                ("processing", f"local-{video_id}", video_id),
            )
            conn.commit()

        time.sleep(2)

        with connect_db() as conn:
            video = conn.execute("SELECT id FROM videos WHERE id = ?", (video_id,)).fetchone()
            if not video:
                return
            conn.execute(
                "UPDATE videos SET status = ?, s3_key = ? WHERE id = ?",
                ("completed", None, video_id),
            )
            conn.commit()
    except Exception:
        with connect_db() as conn:
            conn.execute("UPDATE videos SET status = ? WHERE id = ?", ("failed", video_id))
            conn.commit()


def app(environ, start_response):
    method = environ["REQUEST_METHOD"].upper()
    path = environ.get("PATH_INFO", "")

    if method == "OPTIONS":
        return empty_response(start_response, "204 No Content")

    if method == "GET" and path == "/health":
        return json_response(
            start_response,
            "200 OK",
            {"status": "healthy", "service": "AI Text-to-Video Preview Studio", "mode": "demo"},
        )

    if path == "/api/auth/register" and method == "POST":
        try:
            body = get_json_body(environ)
        except (json.JSONDecodeError, ValueError) as exc:
            return error_response(start_response, "400 Bad Request", str(exc) or "Invalid JSON body")

        email = (body.get("email") or "").strip().casefold()
        username = (body.get("username") or "").strip()
        password = body.get("password") or ""
        if not email or not username or not password:
            return error_response(start_response, "400 Bad Request", "Email, username, and password are required")
        if not EMAIL_PATTERN.fullmatch(email) or len(email) > 254:
            return error_response(start_response, "400 Bad Request", "Enter a valid email address")
        if not 3 <= len(username) <= 50:
            return error_response(start_response, "400 Bad Request", "Username must be 3 to 50 characters")
        if not USERNAME_PATTERN.fullmatch(username):
            return error_response(start_response, "400 Bad Request", "Username may use letters, numbers, hyphens, and underscores only")
        if len(password) < 8:
            return error_response(start_response, "400 Bad Request", "Password must be at least 8 characters")

        with connect_db() as conn:
            if conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
                return error_response(start_response, "400 Bad Request", "Email already registered")
            if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
                return error_response(start_response, "400 Bad Request", "Username already taken")

            cursor = conn.execute(
                "INSERT INTO users (email, username, hashed_password, is_active, created_at) VALUES (?, ?, ?, 1, ?)",
                (email, username, hash_password(password), utc_now()),
            )
            conn.commit()
            return json_response(
                start_response,
                "201 Created",
                {"message": "User registered successfully", "user_id": cursor.lastrowid},
            )

    if path == "/api/auth/login" and method == "POST":
        try:
            form = get_form_body(environ)
        except ValueError as exc:
            return error_response(start_response, "400 Bad Request", str(exc))
        email = (form.get("username") or "").strip().casefold()
        password = form.get("password") or ""

        with connect_db() as conn:
            user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            if not user or not verify_password(password, user["hashed_password"]):
                return error_response(start_response, "401 Unauthorized", "Invalid credentials")

        token = create_access_token(email)
        return json_response(start_response, "200 OK", {"access_token": token, "token_type": "bearer"})

    if path == "/api/auth/reset-password" and method == "POST":
        try:
            body = get_json_body(environ)
        except (json.JSONDecodeError, ValueError) as exc:
            return error_response(start_response, "400 Bad Request", str(exc) or "Invalid JSON body")

        email = (body.get("email") or "").strip().casefold()
        if not email or not EMAIL_PATTERN.fullmatch(email):
            return error_response(start_response, "400 Bad Request", "Enter a valid email address")

        # Resetting a password from only an email address would let anyone take
        # over an account. This portfolio build has no email provider, so it
        # deliberately returns a generic acknowledgement instead of changing
        # a password without a verified reset token.
        return json_response(
            start_response,
            "202 Accepted",
            {"message": "If an account exists, reset instructions will be sent when email delivery is configured."},
        )

    if path == "/api/auth/me" and method == "GET":
        user = get_current_user(environ)
        if not user:
            return error_response(start_response, "401 Unauthorized", "Invalid token")
        return json_response(start_response, "200 OK", row_to_user(user))

    if path == "/api/videos/" and method == "GET":
        user = get_current_user(environ)
        if not user:
            return error_response(start_response, "401 Unauthorized", "Invalid token")
        with connect_db() as conn:
            videos = conn.execute(
                "SELECT * FROM videos WHERE user_id = ? ORDER BY id DESC",
                (user["id"],),
            ).fetchall()
        return json_response(start_response, "200 OK", [row_to_video(video) for video in videos])

    if path == "/api/videos/generate" and method == "POST":
        user = get_current_user(environ)
        if not user:
            return error_response(start_response, "401 Unauthorized", "Invalid token")

        try:
            body = get_json_body(environ)
        except (json.JSONDecodeError, ValueError) as exc:
            return error_response(start_response, "400 Bad Request", str(exc) or "Invalid JSON body")

        title = (body.get("title") or "").strip()
        prompt = (body.get("prompt") or "").strip()
        if not title or not prompt:
            return error_response(start_response, "400 Bad Request", "Title and prompt are required")
        if len(title) > 120:
            return error_response(start_response, "400 Bad Request", "Title must be at most 120 characters")
        if not 10 <= len(prompt) <= 1_000:
            return error_response(start_response, "400 Bad Request", "Prompt must be between 10 and 1000 characters")

        with connect_db() as conn:
            cursor = conn.execute(
                """
                INSERT INTO videos (title, prompt, status, s3_key, task_id, created_at, user_id)
                VALUES (?, ?, ?, NULL, NULL, ?, ?)
                """,
                (title, prompt, "pending", utc_now(), user["id"]),
            )
            conn.commit()
            video = conn.execute("SELECT * FROM videos WHERE id = ?", (cursor.lastrowid,)).fetchone()

        Thread(target=simulate_video_generation, args=(video["id"],), daemon=True).start()
        return json_response(start_response, "201 Created", row_to_video(video))

    if path.startswith("/api/videos/"):
        parts = path.strip("/").split("/")
        if len(parts) < 3:
            return error_response(start_response, "404 Not Found", "Video not found")

        try:
            video_id = int(parts[2])
        except ValueError:
            return error_response(start_response, "404 Not Found", "Video not found")

        user = get_current_user(environ)
        if not user:
            return error_response(start_response, "401 Unauthorized", "Invalid token")

        with connect_db() as conn:
            video = conn.execute(
                "SELECT * FROM videos WHERE id = ? AND user_id = ?",
                (video_id, user["id"]),
            ).fetchone()
            if not video:
                return error_response(start_response, "404 Not Found", "Video not found")

            if len(parts) == 4 and parts[3] == "url" and method == "GET":
                if not video["s3_key"]:
                    return error_response(
                        start_response,
                        "409 Conflict",
                        "This demo uses a browser-generated preview; no remote video file is stored.",
                    )
                return json_response(start_response, "200 OK", {"url": video["s3_key"]})

            if len(parts) == 3 and method == "GET":
                return json_response(start_response, "200 OK", row_to_video(video))

            if len(parts) == 3 and method == "DELETE":
                conn.execute("DELETE FROM videos WHERE id = ? AND user_id = ?", (video_id, user["id"]))
                conn.commit()
                return json_response(start_response, "200 OK", {"message": "Video deleted"})

        return error_response(start_response, "404 Not Found", "Video not found")

    return error_response(start_response, "404 Not Found", "Not found")


init_db()


if __name__ == "__main__":
    port = int(ENV.get("PORT", "8000"))
    with make_server("0.0.0.0", port, app) as server:
        print(f"AI Text-to-Video API running on http://localhost:{port}")
        server.serve_forever()
