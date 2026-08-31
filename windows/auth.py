from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import sqlite3
import time
from pathlib import Path
from urllib.parse import unquote, urlsplit

from flask import (
    abort,
    g,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
    has_request_context,
)

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = BASE_DIR / "data" / "kook_music.db"
BOOTSTRAP_ADMIN_USERNAME = os.environ.get("INITIAL_ADMIN_USERNAME", "gen").strip() or "gen"
CURRENT_SCHEMA_VERSION = 3
LOGGER = logging.getLogger(__name__)

SCHEMA_MIGRATIONS = {
    2: (
        "CREATE INDEX IF NOT EXISTS idx_channels_guild_channel ON channels(guild_id, kook_channel_id)",
        """
        UPDATE user_scopes
        SET guild_id=(SELECT guild_id FROM channels WHERE channels.id=user_scopes.channel_id)
        WHERE channel_id IS NOT NULL
          AND COALESCE(guild_id, -1) != COALESCE(
              (SELECT guild_id FROM channels WHERE channels.id=user_scopes.channel_id), -2
          )
        """,
        """
        CREATE TRIGGER IF NOT EXISTS trg_user_scopes_channel_guild_insert
        BEFORE INSERT ON user_scopes
        WHEN NEW.channel_id IS NOT NULL AND (
            NEW.guild_id IS NULL OR
            NEW.guild_id != (SELECT guild_id FROM channels WHERE id=NEW.channel_id)
        )
        BEGIN
            SELECT RAISE(ABORT, 'channel scope guild mismatch');
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS trg_user_scopes_channel_guild_update
        BEFORE UPDATE OF guild_id, channel_id ON user_scopes
        WHEN NEW.channel_id IS NOT NULL AND (
            NEW.guild_id IS NULL OR
            NEW.guild_id != (SELECT guild_id FROM channels WHERE id=NEW.channel_id)
        )
        BEGIN
            SELECT RAISE(ABORT, 'channel scope guild mismatch');
        END
        """,
    ),
    3: (
        "ALTER TABLE channels ADD COLUMN verified INTEGER NOT NULL DEFAULT 0 CHECK(verified IN (0,1))",
        "CREATE INDEX IF NOT EXISTS idx_channels_verified ON channels(verified, enabled)",
    ),
}

SESSION_COOKIE = "kook_session"
CSRF_COOKIE = "kook_csrf"
SESSION_IDLE_SECONDS = int(os.environ.get("AUTH_SESSION_IDLE_SECONDS", "86400"))
SESSION_ABSOLUTE_SECONDS = int(os.environ.get("AUTH_SESSION_ABSOLUTE_SECONDS", "604800"))
SESSION_TOUCH_SECONDS = 300
COOKIE_SECURE = os.environ.get("AUTH_COOKIE_SECURE", "false").strip().lower() in {
    "1", "true", "yes", "on"
}
TRUST_PROXY_HEADERS = os.environ.get("AUTH_TRUST_PROXY_HEADERS", "false").strip().lower() in {
    "1", "true", "yes", "on"
}
LOGIN_USER_LIMIT = int(os.environ.get("AUTH_LOGIN_USER_FAILURES", "5"))
LOGIN_IP_LIMIT = int(os.environ.get("AUTH_LOGIN_IP_FAILURES", "20"))
LOGIN_WINDOW_SECONDS = int(os.environ.get("AUTH_LOGIN_WINDOW_SECONDS", "600"))

ROLE_PERMISSIONS = {
    "admin": {"*"},
    "user": {"playback.read", "playback.control"},
}
USER_PAGE_ALLOW = {"/", "/dashboard", "/library", "/change-password"}
ADMIN_PAGE_PREFIXES = ("/account", "/status", "/settings", "/users", "/monitor")
ADMIN_API_PREFIXES = (
    "/api/account",
    "/api/qq/account",
    "/api/bili/account",
    "/api/system",
    "/api/logs",
    "/api/terminal",
    "/api/debug",
    "/api/cache",
    "/api/admin",
    "/api/stats",
)
USER_ACCOUNT_READ_API = {
    "/api/account/status",
    "/api/account/playlists",
    "/api/qq/account/status",
    "/api/qq/account/profile",
    "/api/qq/account/playlists",
    "/api/bili/account/status",
    "/api/bili/account/profile",
    "/api/bili/account/playlists",
}
USER_API_EXACT = {
    "/api/guilds",
    "/api/channels",
    "/api/channels/active",
    "/api/search",
    "/api/join",
    "/api/leave",
    "/api/play",
    "/api/playlist/add",
    "/api/playlist",
    "/api/skip",
    "/api/seek",
    "/api/playlist/current",
    "/api/playlist/repeat",
    "/api/pause",
    "/api/resume",
    "/api/stop",
    "/api/clear",
    "/api/remove",
    "/api/playlist/promote",
}
PUBLIC_PATHS = {"/login", "/healthz", "/favicon.ico"}
PASSWORD_RE = re.compile(r"^(?=.{12,128}$)(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9]).+$")
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")


def _db_path() -> Path:
    configured = os.environ.get("AUTH_DATABASE_PATH", "").strip()
    if not configured:
        return DEFAULT_DB_PATH
    path = Path(os.path.expandvars(os.path.expanduser(configured)))
    if not path.is_absolute():
        path = BASE_DIR / path
    return path.resolve()


def _chmod_private(path: Path, mode: int) -> None:
    if os.name == "nt":
        return
    try:
        path.chmod(mode)
    except OSError as exc:
        LOGGER.warning("无法收紧认证数据权限 path=%s error=%s", path, type(exc).__name__)


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _chmod_private(path.parent, 0o700)
    conn = sqlite3.connect(str(path), timeout=5.0)
    _chmod_private(path, 0o600)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _bootstrap_credential_path() -> Path:
    configured = os.environ.get("INITIAL_ADMIN_CREDENTIAL_PATH", "").strip()
    if not configured:
        return _db_path().with_name("bootstrap-admin.json")
    path = Path(os.path.expandvars(os.path.expanduser(configured)))
    if not path.is_absolute():
        path = BASE_DIR / path
    return path.resolve()


def _apply_schema_migrations(db: sqlite3.Connection) -> None:
    applied = {
        int(row[0])
        for row in db.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
    }
    unsupported = [version for version in applied if version > CURRENT_SCHEMA_VERSION]
    if unsupported:
        raise RuntimeError(
            f"数据库版本 {max(unsupported)} 高于当前程序支持的版本 {CURRENT_SCHEMA_VERSION}"
        )
    for version in range(2, CURRENT_SCHEMA_VERSION + 1):
        if version in applied:
            continue
        statements = SCHEMA_MIGRATIONS.get(version)
        if not statements:
            raise RuntimeError(f"缺少数据库迁移脚本：版本 {version}")
        with db:
            for statement in statements:
                db.execute(statement)
            db.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES(?, ?)",
                (version, int(time.time())),
            )


def _load_or_create_bootstrap_password() -> str:
    if not USERNAME_RE.match(BOOTSTRAP_ADMIN_USERNAME):
        raise RuntimeError("INITIAL_ADMIN_USERNAME 必须为 3–32 位字母、数字、点、下划线或连字符")

    configured = os.environ.get("INITIAL_ADMIN_PASSWORD", "")
    if configured:
        error = validate_password(configured)
        if error:
            raise RuntimeError(f"INITIAL_ADMIN_PASSWORD 不符合密码策略：{error}")
        return configured

    path = _bootstrap_credential_path()
    if path.is_file():
        try:
            _chmod_private(path, 0o600)
            with path.open("r", encoding="utf-8") as credential_file:
                raw_payload = credential_file.read(4097)
            if len(raw_payload) > 4096:
                raise ValueError("初始化凭据文件过大")
            payload = json.loads(raw_payload)
            username = str(payload.get("username", ""))
            password = str(payload.get("password", ""))
        except (OSError, ValueError, TypeError) as exc:
            raise RuntimeError(f"无法读取初始化凭据文件：{path}") from exc
        if username != BOOTSTRAP_ADMIN_USERNAME or validate_password(password):
            raise RuntimeError(f"初始化凭据文件内容无效：{path}")
        return password

    password = secrets.token_urlsafe(24) + "!Aa1"
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(
                {"username": BOOTSTRAP_ADMIN_USERNAME, "password": password},
                handle,
                ensure_ascii=False,
            )
            handle.flush()
            os.fsync(handle.fileno())
        try:
            path.chmod(0o600)
        except OSError:
            LOGGER.warning("无法收紧初始化凭据文件权限：%s", path)
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise
    LOGGER.warning("已生成一次性初始化管理员凭据：%s；首次改密后将自动删除", path)
    return password


def _discard_bootstrap_credential_file(username: str) -> None:
    if username != BOOTSTRAP_ADMIN_USERNAME:
        return
    path = _bootstrap_credential_path()
    try:
        path.unlink(missing_ok=True)
    except OSError:
        LOGGER.warning("首次改密成功，但无法删除初始化凭据文件：%s", path)


def init_database() -> None:
    with _connect() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('admin','user')),
                enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
                must_change_password INTEGER NOT NULL DEFAULT 0 CHECK(must_change_password IN (0,1)),
                auth_version INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                last_login_at INTEGER
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                token_hash TEXT NOT NULL UNIQUE,
                csrf_hash TEXT NOT NULL,
                auth_version INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                last_seen_at INTEGER NOT NULL,
                idle_expires_at INTEGER NOT NULL,
                absolute_expires_at INTEGER NOT NULL,
                revoked_at INTEGER,
                ip_address TEXT,
                user_agent TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON sessions(absolute_expires_at);

            CREATE TABLE IF NOT EXISTS login_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT,
                ip_address TEXT,
                success INTEGER NOT NULL CHECK(success IN (0,1)),
                created_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_login_attempts_time ON login_attempts(created_at);

            CREATE TABLE IF NOT EXISTS guilds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kook_guild_id TEXT NOT NULL UNIQUE,
                name TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL REFERENCES guilds(id) ON DELETE CASCADE,
                kook_channel_id TEXT NOT NULL UNIQUE,
                name TEXT,
                channel_type TEXT NOT NULL DEFAULT 'voice',
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                UNIQUE(guild_id, kook_channel_id)
            );

            CREATE TABLE IF NOT EXISTS user_scopes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                domain TEXT NOT NULL DEFAULT 'playback',
                guild_id INTEGER REFERENCES guilds(id) ON DELETE CASCADE,
                channel_id INTEGER REFERENCES channels(id) ON DELETE CASCADE,
                created_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_user_scopes_user ON user_scopes(user_id, domain);
            CREATE UNIQUE INDEX IF NOT EXISTS uq_user_scope_global
                ON user_scopes(user_id, domain)
                WHERE guild_id IS NULL AND channel_id IS NULL;
            CREATE UNIQUE INDEX IF NOT EXISTS uq_user_scope_guild
                ON user_scopes(user_id, domain, guild_id)
                WHERE guild_id IS NOT NULL AND channel_id IS NULL;
            CREATE UNIQUE INDEX IF NOT EXISTS uq_user_scope_channel
                ON user_scopes(user_id, domain, channel_id)
                WHERE channel_id IS NOT NULL;

            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                action TEXT NOT NULL,
                domain TEXT NOT NULL,
                resource_type TEXT,
                resource_id TEXT,
                metadata_json TEXT,
                ip_address TEXT,
                created_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_audit_logs_time ON audit_logs(created_at);
            """
        )
        db.execute(
            "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(?, ?)",
            (1, int(time.time())),
        )
        _apply_schema_migrations(db)
        count = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if count == 0:
            now = int(time.time())
            bootstrap_password = _load_or_create_bootstrap_password()
            cur = db.execute(
                """
                INSERT INTO users(
                    username,password_hash,role,enabled,must_change_password,
                    auth_version,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    BOOTSTRAP_ADMIN_USERNAME,
                    hash_password(bootstrap_password),
                    "admin",
                    1,
                    1,
                    1,
                    now,
                    now,
                ),
            )
            audit(
                "iam.bootstrap_admin",
                domain="iam",
                user_id=int(cur.lastrowid),
                metadata={"username": BOOTSTRAP_ADMIN_USERNAME},
                db=db,
            )


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64d(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str, iterations: int = 600_000) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${_b64e(salt)}${_b64e(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations_text, salt_text, digest_text = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            _b64d(salt_text),
            int(iterations_text),
        )
        return hmac.compare_digest(digest, _b64d(digest_text))
    except (TypeError, ValueError):
        return False


def validate_password(password: str) -> str | None:
    if not PASSWORD_RE.match(password or ""):
        return "密码需为 12–128 位，并同时包含大写字母、小写字母、数字和特殊字符"
    return None


def client_ip() -> str:
    if TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",", 1)[0].strip()[:64]
    return (request.remote_addr or "")[:64]


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _row_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def get_user_by_id(user_id: int) -> dict | None:
    with _connect() as db:
        return _row_dict(db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())


def get_user_by_username(username: str) -> dict | None:
    with _connect() as db:
        return _row_dict(
            db.execute("SELECT * FROM users WHERE username=? COLLATE NOCASE", (username,)).fetchone()
        )


def audit(
    action: str,
    domain: str,
    user_id: int | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    metadata: dict | None = None,
    db: sqlite3.Connection | None = None,
) -> None:
    owns = db is None
    conn = db or _connect()
    try:
        conn.execute(
            """
            INSERT INTO audit_logs(
                user_id,action,domain,resource_type,resource_id,metadata_json,ip_address,created_at
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                user_id,
                action[:128],
                domain[:64],
                resource_type[:64] if resource_type else None,
                str(resource_id)[:128] if resource_id is not None else None,
                json.dumps(metadata or {}, ensure_ascii=False, separators=(",", ":")),
                client_ip() if has_request_context() else None,
                int(time.time()),
            ),
        )
        if owns:
            conn.commit()
    finally:
        if owns:
            conn.close()


def _record_login_attempt(username: str, success: bool) -> None:
    now = int(time.time())
    with _connect() as db:
        db.execute(
            "INSERT INTO login_attempts(username,ip_address,success,created_at) VALUES(?,?,?,?)",
            (username[:64], client_ip(), 1 if success else 0, now),
        )
        db.execute("DELETE FROM login_attempts WHERE created_at < ?", (now - 86400,))
        if success:
            db.execute(
                "DELETE FROM login_attempts WHERE success=0 AND (username=? COLLATE NOCASE OR ip_address=?)",
                (username, client_ip()),
            )


def _login_rate_limited(username: str) -> bool:
    cutoff = int(time.time()) - LOGIN_WINDOW_SECONDS
    with _connect() as db:
        by_user = db.execute(
            """
            SELECT COUNT(*) FROM login_attempts
            WHERE success=0 AND username=? COLLATE NOCASE AND created_at>=?
            """,
            (username, cutoff),
        ).fetchone()[0]
        by_ip = db.execute(
            """
            SELECT COUNT(*) FROM login_attempts
            WHERE success=0 AND ip_address=? AND created_at>=?
            """,
            (client_ip(), cutoff),
        ).fetchone()[0]
    return by_user >= LOGIN_USER_LIMIT or by_ip >= LOGIN_IP_LIMIT


def create_session(user: dict) -> tuple[str, str]:
    now = int(time.time())
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    with _connect() as db:
        db.execute(
            """
            INSERT INTO sessions(
                user_id,token_hash,csrf_hash,auth_version,created_at,last_seen_at,
                idle_expires_at,absolute_expires_at,ip_address,user_agent
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                user["id"],
                _token_hash(token),
                _token_hash(csrf),
                user["auth_version"],
                now,
                now,
                now + SESSION_IDLE_SECONDS,
                now + SESSION_ABSOLUTE_SECONDS,
                client_ip(),
                request.headers.get("User-Agent", "")[:512],
            ),
        )
    return token, csrf


def _load_session(token: str | None) -> tuple[dict | None, dict | None]:
    if not token:
        return None, None
    now = int(time.time())
    token_hash = _token_hash(token)
    with _connect() as db:
        row = db.execute(
            """
            SELECT
                s.*, u.username, u.role, u.enabled, u.must_change_password,
                u.auth_version AS user_auth_version
            FROM sessions s JOIN users u ON u.id=s.user_id
            WHERE s.token_hash=?
            """,
            (token_hash,),
        ).fetchone()
        if not row:
            return None, None
        session = dict(row)
        invalid = (
            session["revoked_at"] is not None
            or not session["enabled"]
            or session["idle_expires_at"] <= now
            or session["absolute_expires_at"] <= now
            or session["auth_version"] != session["user_auth_version"]
        )
        if invalid:
            if session["revoked_at"] is None:
                db.execute("UPDATE sessions SET revoked_at=? WHERE id=?", (now, session["id"]))
            return None, None
        if now - session["last_seen_at"] >= SESSION_TOUCH_SECONDS:
            new_idle = min(now + SESSION_IDLE_SECONDS, session["absolute_expires_at"])
            db.execute(
                "UPDATE sessions SET last_seen_at=?, idle_expires_at=? WHERE id=?",
                (now, new_idle, session["id"]),
            )
            session["last_seen_at"] = now
            session["idle_expires_at"] = new_idle
        user = {
            "id": session["user_id"],
            "username": session["username"],
            "role": session["role"],
            "enabled": bool(session["enabled"]),
            "must_change_password": bool(session["must_change_password"]),
            "auth_version": session["user_auth_version"],
        }
        return user, session


def current_user() -> dict | None:
    user = getattr(g, "current_user", None)
    return user if isinstance(user, dict) else None


def csrf_token() -> str:
    return request.cookies.get(CSRF_COOKIE, "")


def _set_session_cookies(response, token: str, csrf: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_ABSOLUTE_SECONDS,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="Lax",
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf,
        max_age=SESSION_ABSOLUTE_SECONDS,
        httponly=False,
        secure=COOKIE_SECURE,
        samesite="Lax",
        path="/",
    )


def _clear_session_cookies(response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


def _safe_next(value: str | None) -> str:
    if not isinstance(value, str) or not value or len(value) > 2048:
        return "/dashboard"
    try:
        decoded = value
        # Browsers normalize backslashes in Location URLs. Decode a bounded
        # number of layers before validation so encoded scheme-relative URLs
        # cannot turn into an external redirect after the response is sent.
        for _ in range(2):
            decoded = unquote(decoded)
    except (TypeError, ValueError):
        return "/dashboard"
    try:
        parsed = urlsplit(decoded)
    except ValueError:
        return "/dashboard"
    if parsed.scheme or parsed.netloc or not decoded.startswith("/"):
        return "/dashboard"
    if decoded.startswith("//") or "\\" in decoded or any(ord(char) < 32 or ord(char) == 127 for char in decoded):
        return "/dashboard"
    return value


def has_permission(user: dict, permission: str) -> bool:
    permissions = ROLE_PERMISSIONS.get(user.get("role"), set())
    return "*" in permissions or permission in permissions


def ensure_guild(
    kook_guild_id: str,
    name: str = "",
    db: sqlite3.Connection | None = None,
) -> int:
    owns = db is None
    conn = db or _connect()
    now = int(time.time())
    try:
        conn.execute(
            """
            INSERT INTO guilds(kook_guild_id,name,enabled,created_at,updated_at)
            VALUES(?,?,1,?,?)
            ON CONFLICT(kook_guild_id) DO UPDATE SET
                name=CASE WHEN excluded.name<>'' THEN excluded.name ELSE guilds.name END,
                updated_at=excluded.updated_at
            """,
            (str(kook_guild_id), name[:255], now, now),
        )
        row = conn.execute(
            "SELECT id FROM guilds WHERE kook_guild_id=?", (str(kook_guild_id),)
        ).fetchone()
        if owns:
            conn.commit()
        return int(row[0])
    finally:
        if owns:
            conn.close()


def ensure_channel(
    kook_guild_id: str,
    kook_channel_id: str,
    name: str = "",
    channel_type: str = "voice",
    db: sqlite3.Connection | None = None,
) -> int:
    owns = db is None
    conn = db or _connect()
    try:
        guild_id = ensure_guild(kook_guild_id, db=conn)
        now = int(time.time())
        conn.execute(
            """
            INSERT INTO channels(
                guild_id,kook_channel_id,name,channel_type,enabled,created_at,updated_at
            ) VALUES(?,?,?,?,1,?,?)
            ON CONFLICT(kook_channel_id) DO UPDATE SET
                name=CASE WHEN excluded.name<>'' THEN excluded.name ELSE channels.name END,
                channel_type=excluded.channel_type,
                updated_at=excluded.updated_at
            """,
            (guild_id, str(kook_channel_id), name[:255], channel_type[:32], now, now),
        )
        row = conn.execute(
            "SELECT id FROM channels WHERE kook_channel_id=?", (str(kook_channel_id),)
        ).fetchone()
        if owns:
            conn.commit()
        return int(row[0])
    finally:
        if owns:
            conn.close()


def sync_guild(kook_guild_id: str, name: str = "") -> int:
    """保存从 KOOK API 获取的服务器信息。"""
    return ensure_guild(kook_guild_id, name=name)


def sync_channel(
    kook_guild_id: str,
    kook_channel_id: str,
    name: str = "",
    channel_type: str = "voice",
) -> int:
    """保存 KOOK API 已确认的频道归属，并原子修正已有频道范围。"""
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        guild_db_id = ensure_guild(kook_guild_id, db=db)
        now = int(time.time())
        row = db.execute(
            "SELECT id FROM channels WHERE kook_channel_id=?",
            (str(kook_channel_id),),
        ).fetchone()
        if row:
            channel_db_id = int(row[0])
            db.execute(
                """
                UPDATE channels
                SET guild_id=?,name=?,channel_type=?,verified=1,updated_at=?
                WHERE id=?
                """,
                (guild_db_id, name[:255], channel_type[:32], now, channel_db_id),
            )
            db.execute(
                "UPDATE user_scopes SET guild_id=? WHERE channel_id=?",
                (guild_db_id, channel_db_id),
            )
        else:
            cursor = db.execute(
                """
                INSERT INTO channels(
                    guild_id,kook_channel_id,name,channel_type,enabled,verified,created_at,updated_at
                ) VALUES(?,?,?,?,1,1,?,?)
                """,
                (
                    guild_db_id,
                    str(kook_channel_id),
                    name[:255],
                    channel_type[:32],
                    now,
                    now,
                ),
            )
            channel_db_id = int(cursor.lastrowid)
        return channel_db_id


def scope_allows(user: dict, guild_id: str | None = None, channel_id: str | None = None) -> bool:
    if user.get("role") == "admin":
        return True
    if not has_permission(user, "playback.control") and not has_permission(user, "playback.read"):
        return False
    with _connect() as db:
        guild_db_id = None
        if guild_id:
            guild_row = db.execute(
                "SELECT id FROM guilds WHERE kook_guild_id=? AND enabled=1",
                (str(guild_id),),
            ).fetchone()
            if not guild_row:
                return False
            guild_db_id = int(guild_row[0])

        channel_db_id = None
        if channel_id:
            channel_row = db.execute(
                """
                SELECT c.id,c.guild_id
                FROM channels c
                JOIN guilds gd ON gd.id=c.guild_id
                WHERE c.kook_channel_id=? AND c.enabled=1 AND c.verified=1 AND gd.enabled=1
                """,
                (str(channel_id),),
            ).fetchone()
            if not channel_row:
                return False
            channel_db_id = int(channel_row[0])
            actual_guild_db_id = int(channel_row[1])
            if guild_db_id is not None and guild_db_id != actual_guild_db_id:
                return False
            guild_db_id = actual_guild_db_id

        global_scope = db.execute(
            """
            SELECT 1 FROM user_scopes
            WHERE user_id=? AND domain='playback' AND guild_id IS NULL AND channel_id IS NULL
            LIMIT 1
            """,
            (user["id"],),
        ).fetchone()
        if global_scope:
            return True
        if channel_db_id is not None:
            row = db.execute(
                """
                SELECT 1 FROM user_scopes s
                WHERE s.user_id=? AND s.domain='playback' AND s.channel_id=?
                LIMIT 1
                """,
                (user["id"], channel_db_id),
            ).fetchone()
            if row:
                return True
        if guild_db_id is not None:
            row = db.execute(
                """
                SELECT 1 FROM user_scopes s
                WHERE s.user_id=? AND s.domain='playback'
                  AND s.channel_id IS NULL AND s.guild_id=?
                LIMIT 1
                """,
                (user["id"], guild_db_id),
            ).fetchone()
            if row:
                return True
    return False


def visible_guild_ids(user: dict) -> set[str] | None:
    if user.get("role") == "admin":
        return None
    with _connect() as db:
        if db.execute(
            """
            SELECT 1 FROM user_scopes
            WHERE user_id=? AND domain='playback' AND guild_id IS NULL AND channel_id IS NULL
            LIMIT 1
            """,
            (user["id"],),
        ).fetchone():
            return None
        rows = db.execute(
            """
            SELECT DISTINCT gd.kook_guild_id
            FROM user_scopes s
            JOIN guilds gd ON gd.id=s.guild_id
            WHERE s.user_id=? AND s.domain='playback' AND gd.enabled=1
            UNION
            SELECT DISTINCT gd.kook_guild_id
            FROM user_scopes s
            JOIN channels c ON c.id=s.channel_id
            JOIN guilds gd ON gd.id=c.guild_id
            WHERE s.user_id=? AND s.domain='playback' AND gd.enabled=1 AND c.enabled=1
            """,
            (user["id"], user["id"]),
        ).fetchall()
    return {str(row[0]) for row in rows}


def visible_channel_ids(user: dict, guild_id: str) -> set[str] | None:
    if user.get("role") == "admin":
        return None
    with _connect() as db:
        if db.execute(
            """
            SELECT 1 FROM user_scopes
            WHERE user_id=? AND domain='playback' AND guild_id IS NULL AND channel_id IS NULL
            LIMIT 1
            """,
            (user["id"],),
        ).fetchone():
            return None
        if db.execute(
            """
            SELECT 1
            FROM user_scopes s JOIN guilds gd ON gd.id=s.guild_id
            WHERE s.user_id=? AND s.domain='playback'
              AND s.channel_id IS NULL AND gd.kook_guild_id=? AND gd.enabled=1
            LIMIT 1
            """,
            (user["id"], str(guild_id)),
        ).fetchone():
            return None
        rows = db.execute(
            """
            SELECT c.kook_channel_id
            FROM user_scopes s
            JOIN channels c ON c.id=s.channel_id
            JOIN guilds gd ON gd.id=c.guild_id
            WHERE s.user_id=? AND s.domain='playback' AND gd.kook_guild_id=?
              AND gd.enabled=1 AND c.enabled=1
            """,
            (user["id"], str(guild_id)),
        ).fetchall()
    return {str(row[0]) for row in rows}


def _request_resource_ids() -> tuple[str | None, str | None]:
    cached = getattr(g, "request_resource_ids", None)
    if cached is not None:
        return cached
    data = request.get_json(silent=True) if request.method not in {"GET", "HEAD"} else None
    data = data if isinstance(data, dict) else {}

    def canonical(name: str) -> str | None:
        query_values = request.args.getlist(name)
        if len(query_values) > 1:
            raise ValueError(f"{name} 不允许重复")
        query_value = query_values[0] if query_values else None
        body_value = data.get(name)
        for value in (query_value, body_value):
            if value is not None and not isinstance(value, str):
                raise ValueError(f"{name} 必须是字符串")
            if isinstance(value, str) and value != value.strip():
                raise ValueError(f"{name} 格式无效")
            if isinstance(value, str) and any(
                char.isspace() or ord(char) < 32 or ord(char) == 127
                for char in value
            ):
                raise ValueError(f"{name} 格式无效")
        query_text = str(query_value).strip() if query_value not in (None, "") else None
        body_text = str(body_value).strip() if body_value not in (None, "") else None
        if request.method not in {"GET", "HEAD"} and query_text and not body_text:
            raise ValueError(f"写请求中的 {name} 必须放在请求体")
        if query_text and body_text and query_text != body_text:
            raise ValueError(f"查询参数与请求体中的 {name} 不一致")
        value = body_text or query_text
        if value and len(value) > 128:
            raise ValueError(f"{name} 过长")
        return value

    result = (canonical("guild_id"), canonical("channel_id"))
    g.request_resource_ids = result
    return result


def _api_error(message: str, status: int):
    return jsonify({"success": False, "error": message, "auth_required": status == 401}), status


def _authorize_request(user: dict):
    path = request.path
    if path.startswith("/api/"):
        try:
            _request_resource_ids()
        except ValueError as exc:
            return _api_error(str(exc), 400)
    if user["role"] == "admin":
        return None
    if path in USER_PAGE_ALLOW:
        return None
    if path.startswith(ADMIN_PAGE_PREFIXES):
        abort(403)
    if path.startswith("/api/"):
        if path == "/api/auth/session":
            return None
        if request.method == "GET" and path in USER_ACCOUNT_READ_API:
            return None
        if path.startswith(ADMIN_API_PREFIXES):
            return _api_error("需要管理员权限", 403)
        if path not in USER_API_EXACT:
            return _api_error("当前角色无权访问该接口", 403)
        if path == "/api/search":
            return None
        guild_id, channel_id = _request_resource_ids()
        if path == "/api/guilds":
            return None
        if path in {"/api/channels", "/api/channels/active"} and guild_id:
            allowed_channels = visible_channel_ids(user, guild_id)
            if allowed_channels is None or allowed_channels:
                return None
            return _api_error("当前用户不在该播放资源的授权范围内", 403)
        if not scope_allows(user, guild_id, channel_id):
            return _api_error("当前用户不在该播放资源的授权范围内", 403)
        return None
    abort(403)


def _csrf_valid(session: dict) -> bool:
    supplied = request.headers.get("X-CSRF-Token") or request.form.get("_csrf") or ""
    return bool(supplied) and hmac.compare_digest(_token_hash(supplied), session["csrf_hash"])


def _session_endpoint():
    user = current_user()
    if not user:
        return _api_error("未登录", 401)
    return jsonify(
        {
            "success": True,
            "user": {
                "id": user["id"],
                "username": user["username"],
                "role": user["role"],
                "must_change_password": user["must_change_password"],
            },
        }
    )


def _login():
    if request.method == "GET":
        if current_user():
            return redirect("/change-password" if current_user()["must_change_password"] else "/dashboard")
        return render_template("login.html", error=None)

    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    if _login_rate_limited(username):
        audit("auth.login_rate_limited", "auth", metadata={"username": username})
        return render_template("login.html", error="登录失败次数过多，请稍后再试"), 429

    user = get_user_by_username(username)
    if not user or not user["enabled"] or not verify_password(password, user["password_hash"]):
        _record_login_attempt(username, False)
        audit("auth.login_failed", "auth", user_id=user["id"] if user else None, metadata={"username": username})
        time.sleep(0.15)
        return render_template("login.html", error="用户名或密码错误"), 401

    _record_login_attempt(username, True)
    with _connect() as db:
        db.execute("UPDATE users SET last_login_at=?, updated_at=? WHERE id=?", (int(time.time()), int(time.time()), user["id"]))
    fresh = get_user_by_id(user["id"])
    token, csrf = create_session(fresh)
    audit("auth.login", "auth", user_id=user["id"])
    target = "/change-password" if fresh["must_change_password"] else _safe_next(request.args.get("next"))
    response = make_response(redirect(target))
    _set_session_cookies(response, token, csrf)
    return response


def _logout():
    user = current_user()
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        with _connect() as db:
            db.execute(
                "UPDATE sessions SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL",
                (int(time.time()), _token_hash(token)),
            )
    if user:
        audit("auth.logout", "auth", user_id=user["id"])
    response = make_response(redirect("/login"))
    _clear_session_cookies(response)
    return response


def _change_password():
    user = current_user()
    if not user:
        return redirect("/login")
    error = None
    if request.method == "POST":
        current = request.form.get("current_password") or ""
        new_password = request.form.get("new_password") or ""
        confirm = request.form.get("confirm_password") or ""
        row = get_user_by_id(user["id"])
        if not verify_password(current, row["password_hash"]):
            error = "当前密码不正确"
        elif new_password != confirm:
            error = "两次输入的新密码不一致"
        else:
            error = validate_password(new_password)
        if not error:
            now = int(time.time())
            with _connect() as db:
                db.execute(
                    """
                    UPDATE users
                    SET password_hash=?, must_change_password=0,
                        auth_version=auth_version+1, updated_at=?
                    WHERE id=?
                    """,
                    (hash_password(new_password), now, user["id"]),
                )
                db.execute("UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL", (now, user["id"]))
            if row["must_change_password"]:
                _discard_bootstrap_credential_file(row["username"])
            fresh = get_user_by_id(user["id"])
            token, csrf = create_session(fresh)
            audit("auth.password_changed", "auth", user_id=user["id"])
            response = make_response(redirect("/dashboard"))
            _set_session_cookies(response, token, csrf)
            return response
    return render_template("change_password.html", error=error)


def _parse_scope_lines(raw: str) -> list[dict]:
    entries: list[dict] = []
    for token in re.split(r"[\n,]+", raw or ""):
        item = token.strip()
        if not item:
            continue
        if item == "*":
            return [{"global": True}]
        if item.lower().startswith("guild:"):
            guild = item.split(":", 1)[1].strip()
            if guild:
                entries.append({"guild_id": guild})
            continue
        if item.lower().startswith("channel:"):
            value = item.split(":", 1)[1].strip()
            if "/" not in value:
                raise ValueError("频道范围格式应为 channel:服务器ID/频道ID")
            guild, channel = (part.strip() for part in value.split("/", 1))
            if guild and channel:
                entries.append({"guild_id": guild, "channel_id": channel})
            continue
        raise ValueError(f"无法识别的范围: {item}")
    if not entries:
        raise ValueError("普通用户至少需要一个播放范围，使用 * 表示全部服务器")
    return entries


def _set_scopes(db: sqlite3.Connection, user_id: int, raw: str) -> None:
    entries = _parse_scope_lines(raw)
    db.execute("DELETE FROM user_scopes WHERE user_id=? AND domain='playback'", (user_id,))
    now = int(time.time())
    for entry in entries:
        if entry.get("global"):
            db.execute(
                "INSERT INTO user_scopes(user_id,domain,guild_id,channel_id,created_at) VALUES(?,'playback',NULL,NULL,?)",
                (user_id, now),
            )
            continue
        guild_db_id = ensure_guild(entry["guild_id"], db=db)
        channel_db_id = None
        if entry.get("channel_id"):
            channel_db_id = ensure_channel(entry["guild_id"], entry["channel_id"], db=db)
        db.execute(
            "INSERT INTO user_scopes(user_id,domain,guild_id,channel_id,created_at) VALUES(?,'playback',?,?,?)",
            (user_id, guild_db_id, channel_db_id, now),
        )


def _scope_text(db: sqlite3.Connection, user_id: int) -> str:
    rows = db.execute(
        """
        SELECT gd.kook_guild_id, c.kook_channel_id
        FROM user_scopes s
        LEFT JOIN guilds gd ON gd.id=s.guild_id
        LEFT JOIN channels c ON c.id=s.channel_id
        WHERE s.user_id=? AND s.domain='playback'
        ORDER BY s.id
        """,
        (user_id,),
    ).fetchall()
    values = []
    for row in rows:
        if row["kook_guild_id"] is None and row["kook_channel_id"] is None:
            return "*"
        if row["kook_channel_id"]:
            values.append(f"channel:{row['kook_guild_id']}/{row['kook_channel_id']}")
        else:
            values.append(f"guild:{row['kook_guild_id']}")
    return ",".join(values)


def _admin_users_page():
    return render_template("users.html")


def _admin_users_api(user_id: int | None = None):
    actor = current_user()
    if request.method == "GET":
        with _connect() as db:
            rows = db.execute(
                """
                SELECT id,username,role,enabled,must_change_password,created_at,last_login_at
                FROM users ORDER BY id
                """
            ).fetchall()
            users = []
            for row in rows:
                item = dict(row)
                item["enabled"] = bool(item["enabled"])
                item["must_change_password"] = bool(item["must_change_password"])
                item["scopes"] = "" if item["role"] == "admin" else _scope_text(db, item["id"])
                users.append(item)
        return jsonify({"success": True, "users": users})

    data = request.get_json(silent=True) or {}
    if request.method == "POST" and user_id is None:
        username = str(data.get("username", "")).strip()
        role = str(data.get("role", "user")).strip()
        scopes = str(data.get("scopes", "")).strip()
        if not USERNAME_RE.match(username):
            return _api_error("用户名需为 3–32 位字母、数字、点、下划线或连字符", 400)
        if role not in ROLE_PERMISSIONS:
            return _api_error("无效角色", 400)
        temp_password = secrets.token_urlsafe(18) + "!Aa1"
        now = int(time.time())
        try:
            with _connect() as db:
                cur = db.execute(
                    """
                    INSERT INTO users(
                        username,password_hash,role,enabled,must_change_password,
                        auth_version,created_at,updated_at
                    ) VALUES(?,?,?,1,1,1,?,?)
                    """,
                    (username, hash_password(temp_password), role, now, now),
                )
                new_id = int(cur.lastrowid)
                if role == "user":
                    _set_scopes(db, new_id, scopes)
            audit("iam.user_created", "iam", user_id=actor["id"], resource_type="user", resource_id=str(new_id), metadata={"username": username, "role": role})
            return jsonify({"success": True, "user_id": new_id, "temporary_password": temp_password})
        except sqlite3.IntegrityError:
            return _api_error("用户名已存在", 409)
        except ValueError as exc:
            return _api_error(str(exc), 400)

    if user_id is None:
        return _api_error("缺少用户 ID", 400)
    target = get_user_by_id(user_id)
    if not target:
        return _api_error("用户不存在", 404)

    if request.method == "PATCH":
        scopes_value = data.get("scopes")
        with _connect() as db:
            db.execute("BEGIN IMMEDIATE")
            locked_row = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            if not locked_row:
                return _api_error("用户不存在", 404)
            target = dict(locked_row)
            role = str(data.get("role", target["role"]))
            raw_enabled = data.get("enabled", target["enabled"])
            if isinstance(raw_enabled, bool):
                enabled = raw_enabled
            elif isinstance(raw_enabled, int) and raw_enabled in {0, 1}:
                enabled = bool(raw_enabled)
            else:
                return _api_error("enabled 必须是布尔值", 400)
            if role not in ROLE_PERMISSIONS:
                return _api_error("无效角色", 400)
            if actor["id"] == user_id and (role != "admin" or not enabled):
                return _api_error("不能降级或禁用当前登录管理员", 400)
            if target["role"] == "admin" and (role != "admin" or not enabled):
                admins = db.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND enabled=1").fetchone()[0]
                if admins <= 1:
                    return _api_error("系统至少必须保留一个启用的管理员", 400)
            try:
                if role == "user":
                    scopes = (
                        str(scopes_value).strip()
                        if scopes_value is not None
                        else (_scope_text(db, user_id) if target["role"] == "user" else "")
                    )
                    _set_scopes(db, user_id, scopes)
                else:
                    db.execute("DELETE FROM user_scopes WHERE user_id=?", (user_id,))
            except ValueError as exc:
                return _api_error(str(exc), 400)
            now = int(time.time())
            db.execute(
                """
                UPDATE users SET role=?,enabled=?,auth_version=auth_version+1,updated_at=?
                WHERE id=?
                """,
                (role, 1 if enabled else 0, now, user_id),
            )
            db.execute("UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL", (now, user_id))
        audit("iam.user_updated", "iam", user_id=actor["id"], resource_type="user", resource_id=str(user_id), metadata={"role": role, "enabled": enabled})
        return jsonify({"success": True})

    if request.method == "DELETE":
        if actor["id"] == user_id:
            return _api_error("不能删除当前登录管理员", 400)
        with _connect() as db:
            db.execute("BEGIN IMMEDIATE")
            locked_row = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            if not locked_row:
                return _api_error("用户不存在", 404)
            target = dict(locked_row)
            if target["role"] == "admin":
                admins = db.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND enabled=1").fetchone()[0]
                if admins <= 1:
                    return _api_error("系统至少必须保留一个启用的管理员", 400)
            db.execute("DELETE FROM users WHERE id=?", (user_id,))
        audit("iam.user_deleted", "iam", user_id=actor["id"], resource_type="user", resource_id=str(user_id), metadata={"username": target["username"]})
        return jsonify({"success": True})
    return _api_error("不支持的方法", 405)


def _reset_user_password(user_id: int):
    actor = current_user()
    target = get_user_by_id(user_id)
    if not target:
        return _api_error("用户不存在", 404)
    temp_password = secrets.token_urlsafe(18) + "!Aa1"
    now = int(time.time())
    with _connect() as db:
        db.execute(
            """
            UPDATE users
            SET password_hash=?,must_change_password=1,
                auth_version=auth_version+1,updated_at=?
            WHERE id=?
            """,
            (hash_password(temp_password), now, user_id),
        )
        db.execute("UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL", (now, user_id))
    audit("iam.password_reset", "iam", user_id=actor["id"], resource_type="user", resource_id=str(user_id))
    return jsonify({"success": True, "temporary_password": temp_password})


def _request_guard():
    path = request.path
    if path.startswith("/static/") or path in PUBLIC_PATHS:
        if path == "/login":
            token = request.cookies.get(SESSION_COOKIE)
            user, session = _load_session(token)
            g.current_user, g.auth_session = user, session
        return None

    user, session = _load_session(request.cookies.get(SESSION_COOKIE))
    g.current_user, g.auth_session = user, session
    if not user:
        if path.startswith("/api/"):
            return _api_error("请先登录", 401)
        return redirect(url_for("auth_login", next=_safe_next(request.full_path.rstrip("?"))))

    if user["must_change_password"] and path not in {"/change-password", "/logout", "/api/auth/session"}:
        if path.startswith("/api/"):
            return jsonify({"success": False, "error": "首次登录必须先修改密码", "must_change_password": True}), 428
        return redirect("/change-password")

    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and path != "/login":
        if not session or not _csrf_valid(session):
            return _api_error("CSRF 校验失败", 403)

    return _authorize_request(user)


def _after_request(response):
    user = current_user()
    if user and request.path == "/api/guilds" and response.is_json and response.status_code == 200:
        allowed = visible_guild_ids(user)
        if allowed is not None:
            payload = response.get_json(silent=True)
            if isinstance(payload, dict) and isinstance(payload.get("guilds"), list):
                payload["guilds"] = [g for g in payload["guilds"] if str(g.get("id")) in allowed]
                response.set_data(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
                response.mimetype = "application/json"

    if user and request.path in {"/api/channels", "/api/channels/active"} and response.is_json and response.status_code == 200:
        guild_id = request.args.get("guild_id")
        if guild_id:
            allowed_channels = visible_channel_ids(user, guild_id)
            if allowed_channels is not None:
                payload = response.get_json(silent=True)
                if isinstance(payload, dict):
                    if isinstance(payload.get("channels"), list):
                        payload["channels"] = [
                            item for item in payload["channels"]
                            if str(item.get("id")) in allowed_channels
                        ]
                    if isinstance(payload.get("active"), dict):
                        payload["active"] = {
                            key: value for key, value in payload["active"].items()
                            if str(key) in allowed_channels
                        }
                    response.set_data(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
                    response.mimetype = "application/json"

    if user and request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.path.startswith("/api/") and response.status_code < 400:
        guild_id, channel_id = _request_resource_ids()
        audit(
            f"http.{request.method.lower()}",
            "iam" if request.path.startswith("/api/admin/") else ("account" if "/account" in request.path else "playback"),
            user_id=user["id"],
            resource_type="channel" if channel_id else ("guild" if guild_id else None),
            resource_id=channel_id or guild_id,
            metadata={"path": request.path},
        )

    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        "base-uri 'self'; object-src 'none'; frame-ancestors 'none'; "
        "script-src 'self' https://cdn.jsdelivr.net https://code.jquery.com; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "font-src 'self' https://cdn.jsdelivr.net data:; "
        "img-src 'self' data: https:; connect-src 'self'; form-action 'self'",
    )
    if not request.path.startswith("/static/"):
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Pragma"] = "no-cache"
        response.headers["Vary"] = "Cookie"
    return response


def _context():
    return {"current_user": current_user(), "csrf_token": csrf_token()}


def register_auth(app) -> None:
    if app.config.get("_AUTH_REGISTERED"):
        return
    init_database()
    app.add_url_rule("/login", "auth_login", _login, methods=["GET", "POST"])
    app.add_url_rule("/logout", "auth_logout", _logout, methods=["POST"])
    app.add_url_rule("/change-password", "auth_change_password", _change_password, methods=["GET", "POST"])
    app.add_url_rule("/users", "auth_users", _admin_users_page, methods=["GET"])
    app.add_url_rule("/api/auth/session", "auth_session", _session_endpoint, methods=["GET"])
    app.add_url_rule("/api/admin/users", "auth_admin_users", _admin_users_api, methods=["GET", "POST"], defaults={"user_id": None})
    app.add_url_rule("/api/admin/users/<int:user_id>", "auth_admin_user", _admin_users_api, methods=["PATCH", "DELETE"])
    app.add_url_rule("/api/admin/users/<int:user_id>/reset-password", "auth_admin_user_reset", _reset_user_password, methods=["POST"])
    app.before_request(_request_guard)
    app.after_request(_after_request)
    app.context_processor(_context)
    app.config["_AUTH_REGISTERED"] = True
