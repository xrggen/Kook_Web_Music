"""Isolated WeChat auth tests: memory-only SQLite and a mocked HTTPS response."""
from http.client import HTTPException
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlsplit
import uuid

from flask import Flask, jsonify

PLATFORM_DIR = Path(__file__).resolve().parents[1]
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))
import auth

APP_ID = "wx-test-application"
APP_SECRET = "synthetic-secret-for-test"
OPEN_ID = "synthetic-open-id"
LOGIN_CODE = "synthetic-login-code"
PASSWORD = "FixturePassword!123"
LOGIN = "/api/auth/wechat/login"
STATUS = "/api/auth/wechat/status"
BIND = "/api/auth/wechat/bind"
UNBIND = "/api/auth/wechat/unbind"


class WechatBindingTests(unittest.TestCase):
    def setUp(self):
        self.db_uri = f"file:wechat-test-{uuid.uuid4().hex}?mode=memory&cache=shared"
        self.anchor = self.connect()
        self.addCleanup(self.anchor.close)
        env = mock.patch.dict(os.environ, {
            "INITIAL_ADMIN_PASSWORD": "FixtureAdmin!123",
            "WECHAT_MINIAPP_APP_ID": APP_ID,
            "WECHAT_MINIAPP_APP_SECRET": APP_SECRET,
            "SECRET_KEY": "synthetic-flask-key",
        })
        env.start()
        self.addCleanup(env.stop)
        patch_connect = mock.patch.object(auth, "_connect", side_effect=self.connect)
        patch_connect.start()
        self.addCleanup(patch_connect.stop)
        https = mock.patch.object(auth, "HTTPSConnection")
        self.https = https.start()
        self.addCleanup(https.stop)
        self.provider = self.https.return_value.getresponse.return_value
        self.provider.status = 200
        self.provider_payload(openid=OPEN_ID, session_key="synthetic-provider-session", unionid="synthetic-union")
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True, SECRET_KEY="synthetic-flask-key")
        self.app.add_url_rule("/api/pause", "test_pause", lambda: jsonify(success=True), methods=["POST"])
        auth.register_auth(self.app)
        self.client = self.app.test_client()
        self.identity_hash = hashlib.sha256(f"wechat-miniapp\0{APP_ID}\0{OPEN_ID}".encode()).hexdigest()
        with self.anchor as db:
            self.user_id = db.execute(
                """INSERT INTO users(username,password_hash,role,enabled,must_change_password,
                   auth_version,created_at,updated_at) VALUES(?,?,'user',1,0,1,1,1)""",
                ("wechat_fixture", auth.hash_password(PASSWORD, iterations=100_000)),
            ).lastrowid
            auth._set_scopes(db, self.user_id, "channel:100/200")
        auth.sync_channel("100", "200", "allowed")
        auth.sync_channel("100", "201", "denied")

    def connect(self):
        conn = sqlite3.connect(self.db_uri, uri=True)
        self.addCleanup(conn.close)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def provider_payload(self, **payload):
        self.provider.read.return_value = json.dumps(payload).encode()

    def seed_binding(self, user_id=None, identity_hash=None):
        with self.anchor as db:
            db.execute("INSERT INTO wechat_bindings VALUES(?,?,1)",
                       (user_id or self.user_id, identity_hash or self.identity_hash))

    def password_login(self):
        return self.client.post("/login", json={"username": "wechat_fixture", "password": PASSWORD})

    def wechat_login(self, client=None, **payload):
        return (client or self.client).post(LOGIN, json=payload or {"code": LOGIN_CODE})

    def session_headers(self):
        return {"X-CSRF-Token": self.password_login().json["csrfToken"]}

    def test_bind_and_unbind_require_session_csrf_and_completed_password_change(self):
        for path, body in ((BIND, {"code": LOGIN_CODE}), (UNBIND, {})):
            self.assertEqual(self.client.post(path, json=body).json["code"], "AUTH_REQUIRED")
        headers = self.session_headers()
        for path, body in ((BIND, {"code": LOGIN_CODE}), (UNBIND, {})):
            self.assertEqual(self.client.post(path, json=body).json["code"], "CSRF_FAILED")
        self.assertEqual(self.client.post(UNBIND, json=[], headers=headers).status_code, 400)
        with self.anchor as db:
            db.execute("UPDATE users SET must_change_password=1 WHERE id=?", (self.user_id,))
        for path, body in ((BIND, {"code": LOGIN_CODE}), (UNBIND, {})):
            response = self.client.post(path, json=body, headers=headers)
            self.assertEqual(response.status_code, 428)
            self.assertEqual(response.json["code"], "PASSWORD_CHANGE_REQUIRED")
        self.https.assert_not_called()

    def test_bind_is_self_only_idempotent_and_does_not_require_password_again(self):
        headers = self.session_headers()
        for _ in range(2):
            response = self.client.post(BIND, json={"code": LOGIN_CODE, "user_id": 1, "role": "admin"}, headers=headers)
            self.assertEqual(response.json, {"success": True, "bound": True})
            self.assertFalse(response.headers.getlist("Set-Cookie"))
        bound = self.anchor.execute("SELECT user_id,identity_hash FROM wechat_bindings").fetchall()
        self.assertEqual([tuple(row) for row in bound], [(self.user_id, self.identity_hash)])
        self.assertEqual(self.client.get(STATUS).json, {"success": True, "bound": True})
        self.assertEqual(self.anchor.execute("SELECT COUNT(*) FROM audit_logs WHERE action='auth.wechat_bound'").fetchone()[0], 1)

    def test_conflicts_never_transfer_or_replace_an_existing_binding(self):
        headers = self.session_headers()
        admin_id = self.anchor.execute("SELECT id FROM users WHERE role='admin'").fetchone()[0]
        self.seed_binding(user_id=admin_id)
        response = self.client.post(BIND, json={"code": LOGIN_CODE}, headers=headers)
        self.assertEqual((response.status_code, response.json["code"]), (409, "WECHAT_BINDING_CONFLICT"))
        self.seed_binding(identity_hash="3" * 64)
        self.provider_payload(openid="synthetic-different-open-id")
        response = self.client.post(BIND, json={"code": LOGIN_CODE}, headers=headers)
        self.assertEqual((response.status_code, response.json["code"]), (409, "WECHAT_BINDING_CONFLICT"))
        self.assertEqual(self.anchor.execute("SELECT identity_hash FROM wechat_bindings WHERE user_id=?",
                                             (self.user_id,)).fetchone()[0], "3" * 64)
        self.assertEqual(self.anchor.execute("SELECT user_id FROM wechat_bindings WHERE identity_hash=?",
                                             (self.identity_hash,)).fetchone()[0], admin_id)

    def test_disabled_account_cannot_bind_or_unbind(self):
        headers = self.session_headers()
        self.seed_binding()
        with self.anchor as db:
            db.execute("UPDATE users SET enabled=0 WHERE id=?", (self.user_id,))
        for path, body in ((BIND, {"code": LOGIN_CODE}), (UNBIND, {})):
            self.assertEqual(self.client.post(path, json=body, headers=headers).status_code, 401)
        self.https.assert_not_called()
        self.assertEqual(self.anchor.execute("SELECT COUNT(*) FROM wechat_bindings").fetchone()[0], 1)

    def test_bind_rechecks_revocation_after_provider_returns(self):
        headers = self.session_headers()

        def revoke_during_exchange(*_):
            with self.anchor as db:
                db.execute("UPDATE users SET auth_version=auth_version+1 WHERE id=?", (self.user_id,))
            return json.dumps({"openid": OPEN_ID}).encode()

        self.provider.read.side_effect = revoke_during_exchange
        response = self.client.post(BIND, json={"code": LOGIN_CODE}, headers=headers)
        self.assertEqual((response.status_code, response.json["code"]), (401, "AUTH_REQUIRED"))
        self.assertEqual(self.anchor.execute("SELECT COUNT(*) FROM wechat_bindings").fetchone()[0], 0)

    def test_unbind_stops_new_wechat_login_without_changing_current_session(self):
        self.seed_binding()
        response = self.wechat_login()
        headers = {"X-CSRF-Token": response.json["csrfToken"]}
        with mock.patch.dict(os.environ, {"WECHAT_MINIAPP_APP_SECRET": ""}):
            for _ in range(2):
                unbind = self.client.post(UNBIND, json={}, headers=headers)
                self.assertEqual(unbind.json, {"success": True, "bound": False})
                self.assertFalse(unbind.headers.getlist("Set-Cookie"))
        self.assertEqual(self.client.get(STATUS).json, {"success": True, "bound": False})
        self.assertEqual(self.client.get("/api/auth/session").status_code, 200)
        denied = self.wechat_login(client=self.app.test_client())
        self.assertEqual((denied.status_code, denied.json["code"]), (401, "WECHAT_NOT_LINKED"))
        self.assertEqual(self.password_login().status_code, 200)

    def test_password_change_unbinds_and_rotates_old_sessions(self):
        headers = self.session_headers()
        self.seed_binding()
        old_wechat_client = self.app.test_client()
        self.assertEqual(self.wechat_login(client=old_wechat_client).status_code, 200)
        payload = {"current_password": "wrong", "new_password": "NewFixture!456", "confirm_password": "NewFixture!456"}
        self.assertEqual(self.client.post("/change-password", json=payload, headers=headers).status_code, 400)
        self.assertTrue(self.client.get(STATUS).json["bound"])
        payload["current_password"] = PASSWORD
        changed = self.client.post("/change-password", json=payload, headers=headers)
        self.assertEqual(changed.status_code, 200)
        self.assertNotEqual(changed.json["csrfToken"], headers["X-CSRF-Token"])
        self.assertFalse(self.client.get(STATUS).json["bound"])
        self.assertEqual(old_wechat_client.get("/api/auth/session").status_code, 401)
        self.assertEqual(self.wechat_login(client=self.app.test_client()).json["code"], "WECHAT_NOT_LINKED")
        self.assertEqual(self.password_login().status_code, 401)
        self.assertEqual(self.client.post("/login", json={"username": "wechat_fixture", "password": "NewFixture!456"}).status_code, 200)

    def test_admin_reset_unbinds_revokes_sessions_and_still_requires_password_change(self):
        headers = self.session_headers()
        self.seed_binding()
        path = f"/api/admin/users/{self.user_id}/reset-password"
        self.assertEqual(self.client.post(path, json={}, headers=headers).status_code, 403)
        self.assertTrue(self.client.get(STATUS).json["bound"])
        admin = self.app.test_client()
        with self.anchor as db:
            db.execute("UPDATE users SET must_change_password=0 WHERE role='admin'")
        logged_in = admin.post("/login", json={"username": auth.BOOTSTRAP_ADMIN_USERNAME, "password": "FixtureAdmin!123"})
        reset = admin.post(path, json={}, headers={"X-CSRF-Token": logged_in.json["csrfToken"]})
        self.assertEqual(reset.status_code, 200)
        self.assertEqual(self.client.get(STATUS).status_code, 401)
        self.assertEqual(self.wechat_login(client=self.app.test_client()).json["code"], "WECHAT_NOT_LINKED")
        self.assertEqual(self.password_login().status_code, 401)
        temp = self.client.post("/login", json={"username": "wechat_fixture", "password": reset.json["temporary_password"]})
        self.assertTrue(temp.json["user"]["must_change_password"])
        response = self.client.post(BIND, json={"code": LOGIN_CODE}, headers={"X-CSRF-Token": temp.json["csrfToken"]})
        self.assertEqual(response.status_code, 428)
        change = self.client.post("/change-password", json={
            "current_password": reset.json["temporary_password"], "new_password": "NewFixture!456",
            "confirm_password": "NewFixture!456",
        }, headers={"X-CSRF-Token": temp.json["csrfToken"]})
        self.assertEqual(change.status_code, 200)
        self.assertFalse(self.client.get(STATUS).json["bound"])
        rebound = self.client.post(BIND, json={"code": LOGIN_CODE}, headers={"X-CSRF-Token": change.json["csrfToken"]})
        self.assertEqual(rebound.json, {"success": True, "bound": True})
        self.assertEqual(self.wechat_login(client=self.app.test_client()).json["user"]["id"], self.user_id)

    def test_password_update_and_unbind_roll_back_together_on_failure(self):
        headers = self.session_headers()
        self.seed_binding()
        with self.anchor as db:
            db.execute("CREATE TRIGGER test_deny_unbind BEFORE DELETE ON wechat_bindings "
                       "BEGIN SELECT RAISE(ABORT,'simulated delete failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.client.post("/change-password", json={"current_password": PASSWORD,
                             "new_password": "NewFixture!456", "confirm_password": "NewFixture!456"}, headers=headers)
        self.assertTrue(self.client.get(STATUS).json["bound"])
        self.assertEqual(self.password_login().status_code, 200)

    def test_missing_config_and_malformed_code_do_not_contact_wechat(self):
        for body in ([], {}, {"code": 0}, {"code": "x" * 129}, {"code": " x\n"}):
            self.assertEqual(self.client.post(LOGIN, json=body).status_code, 400)
        with mock.patch.dict(os.environ, {"WECHAT_MINIAPP_APP_SECRET": ""}):
            self.assertEqual(self.wechat_login().status_code, 503)
        self.https.assert_not_called()

    def test_password_login_and_binding_status_remain_session_scoped(self):
        self.assertEqual(self.client.get(STATUS).status_code, 401)
        self.assertEqual(self.password_login().status_code, 200)
        self.assertEqual(self.client.get(STATUS).get_json(), {"success": True, "bound": False})
        self.seed_binding()
        status = self.client.get(STATUS)
        self.assertEqual(status.get_json(), {"success": True, "bound": True})
        self.assertIn("no-store", status.headers["Cache-Control"])
        self.https.assert_not_called()

    def test_unbound_does_not_register_or_create_a_session(self):
        users_before = self.anchor.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        response = self.wechat_login(username="gen", openid="ignored", role="admin")  # malformed, no code
        self.assertEqual(response.status_code, 400)
        response = self.wechat_login(code=LOGIN_CODE, username="gen", openid="ignored", role="admin")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json["code"], "WECHAT_NOT_LINKED")
        self.assertEqual(self.anchor.execute("SELECT COUNT(*) FROM users").fetchone()[0], users_before)
        self.assertEqual(self.anchor.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 0)

    def test_bound_login_uses_existing_role_scope_csrf_and_cookie(self):
        self.seed_binding()
        response = self.wechat_login(code=LOGIN_CODE, role="admin")
        self.assertEqual(response.status_code, 200)
        body = response.json
        self.assertEqual(body["clientProtocol"], "kook-wechat-v1")
        self.assertEqual(body["user"]["role"], "user")
        self.assertIn("HttpOnly", next(c for c in response.headers.getlist("Set-Cookie") if c.startswith("kook_session=")))
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertEqual(set(body), {"success", "clientProtocol", "csrfToken", "user"})
        headers = {"X-CSRF-Token": body["csrfToken"]}
        self.assertEqual(self.client.post("/api/pause", json={"guild_id": "100", "channel_id": "200"}).status_code, 403)
        self.assertEqual(self.client.post("/api/pause", json={"guild_id": "100", "channel_id": "201"}, headers=headers).status_code, 403)
        self.assertEqual(self.client.post("/api/pause", json={"guild_id": "100", "channel_id": "200"}, headers=headers).status_code, 200)
        self.assertEqual(self.client.post("/logout", json={}, headers=headers).status_code, 200)
        self.assertEqual(self.client.get(STATUS).status_code, 401)
        self.assertEqual(self.anchor.execute("SELECT COUNT(*) FROM wechat_bindings").fetchone()[0], 1)
        audit = self.anchor.execute("SELECT metadata_json FROM audit_logs WHERE action='auth.wechat_login'").fetchone()[0]
        self.assertEqual(json.loads(audit), {})

    def test_disabled_or_password_change_required_cannot_sign_in(self):
        self.seed_binding()
        with self.anchor as db:
            db.execute("UPDATE users SET enabled=0 WHERE id=?", (self.user_id,))
        self.assertEqual(self.wechat_login().status_code, 401)
        with self.anchor as db:
            db.execute("UPDATE users SET enabled=1,must_change_password=1 WHERE id=?", (self.user_id,))
        self.assertEqual(self.wechat_login().status_code, 428)
        self.assertEqual(self.password_login().status_code, 200)
        self.assertEqual(self.client.get(STATUS).status_code, 428)

    def test_app_scope_does_not_match_identity_from_another_app(self):
        self.seed_binding()
        with mock.patch.dict(os.environ, {"WECHAT_MINIAPP_APP_ID": "wx-another-app"}):
            self.assertEqual(self.wechat_login().status_code, 401)

    def test_provider_query_is_fixed_https_and_error_never_echoes_provider_body(self):
        self.provider_payload(errcode=40029, errmsg=APP_SECRET + OPEN_ID + LOGIN_CODE)
        response = self.wechat_login()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json["code"], "WECHAT_CODE_INVALID")
        self.assertFalse(response.json["auth_required"])
        for value in (APP_SECRET, OPEN_ID, LOGIN_CODE):
            self.assertNotIn(value, response.get_data(as_text=True))
        self.https.assert_called_once_with("api.weixin.qq.com", timeout=5)
        conn = self.https.return_value
        conn.set_debuglevel.assert_called_once_with(0)
        method, target = conn.request.call_args.args
        self.assertEqual(method, "GET")
        self.assertEqual(urlsplit(target).path, "/sns/jscode2session")
        self.assertEqual(parse_qs(urlsplit(target).query), {"appid": [APP_ID], "secret": [APP_SECRET],
                         "js_code": [LOGIN_CODE], "grant_type": ["authorization_code"]})
        self.provider.read.assert_called_once_with(8193)

    def test_provider_errors_and_http_redirects_do_not_create_sessions(self):
        self.seed_binding()
        self.provider.status = 302
        self.assertEqual(self.wechat_login().status_code, 502)
        self.https.assert_called_once()
        self.provider.status = 200
        self.provider_payload(errcode=45011)
        self.assertEqual(self.wechat_login().status_code, 429)
        self.provider.read.return_value = b"not json"
        self.assertEqual(self.wechat_login().status_code, 502)
        self.https.return_value.request.side_effect = HTTPException(APP_SECRET)
        self.assertNotIn(APP_SECRET, self.wechat_login().get_data(as_text=True))
        self.assertEqual(self.anchor.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 0)

    def test_rate_limit_blocks_exchange_and_leaves_password_login_independent(self):
        with mock.patch.object(auth, "LOGIN_IP_LIMIT", 2):
            self.assertEqual(self.wechat_login().status_code, 401)
            self.assertEqual(self.wechat_login().status_code, 401)
            limited = self.wechat_login()
            self.assertEqual(limited.status_code, 429)
            self.assertEqual(limited.json["code"], "WECHAT_RATE_LIMITED")
            self.assertEqual(self.https.call_count, 2)
            self.assertEqual(self.password_login().status_code, 200)

    def test_migration_is_additive_idempotent_and_enforces_one_to_one(self):
        self.assertEqual(self.password_login().status_code, 200)
        with self.anchor as db:
            db.execute("DROP TABLE wechat_bindings")
            db.execute("DROP TABLE wechat_exchange_attempts")
            db.execute("DELETE FROM schema_migrations WHERE version=4")
        auth.init_database()
        auth.init_database()
        self.assertEqual(self.anchor.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], 4)
        self.assertEqual(self.client.get("/api/auth/session").json["user"]["id"], self.user_id)
        self.seed_binding()
        with self.assertRaises(sqlite3.IntegrityError):
            self.seed_binding(identity_hash="2" * 64)
        admin_id = self.anchor.execute("SELECT id FROM users WHERE role='admin'").fetchone()[0]
        with self.assertRaises(sqlite3.IntegrityError):
            self.seed_binding(user_id=admin_id)
        with self.anchor as db:
            db.execute("DELETE FROM users WHERE id=?", (self.user_id,))
        self.assertEqual(self.anchor.execute("SELECT COUNT(*) FROM wechat_bindings").fetchone()[0], 0)

    def test_form_login_still_sets_session_and_redirects(self):
        response = self.client.post("/login", data={"username": "wechat_fixture", "password": PASSWORD})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(urlsplit(response.headers["Location"]).path, "/dashboard")
        self.assertEqual(self.client.get("/api/auth/session").json["user"]["role"], "user")

    def test_unbound_during_provider_exchange_cannot_create_session(self):
        self.seed_binding()

        def unbind_during_exchange(*_):
            with self.anchor as db:
                db.execute("DELETE FROM wechat_bindings WHERE user_id=?", (self.user_id,))
            return json.dumps({"openid": OPEN_ID}).encode()

        self.provider.read.side_effect = unbind_during_exchange
        self.assertEqual(self.wechat_login().status_code, 401)
        self.assertEqual(self.anchor.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 0)

    @unittest.skipUnless(PLATFORM_DIR.name == "windows", "Cloud loads Windows auth")
    def test_cloud_entry_uses_same_auth_and_secure_cookie(self):
        with mock.patch.object(sys, "path", [str(PLATFORM_DIR.parent), *sys.path]):
            from cloud.app import create_app
        self.seed_binding()
        hub = mock.Mock()
        with mock.patch.object(auth, "COOKIE_SECURE", True):
            client = create_app(hub).test_client()
            response = client.post(LOGIN, json={"code": LOGIN_CODE}, base_url="https://test.invalid")
            self.assertEqual(response.status_code, 200)
            cookie = next(c for c in response.headers.getlist("Set-Cookie") if c.startswith("kook_session="))
            self.assertIn("Secure", cookie)
            self.assertIn("HttpOnly", cookie)
            self.assertEqual(client.get(STATUS, base_url="https://test.invalid").json, {"success": True, "bound": True})
            headers = {"X-CSRF-Token": response.json["csrfToken"]}
            self.assertEqual(client.post(UNBIND, json={}, headers=headers, base_url="https://test.invalid").json,
                             {"success": True, "bound": False})
            self.assertEqual(client.post(BIND, json={"code": LOGIN_CODE}, headers=headers, base_url="https://test.invalid").json,
                             {"success": True, "bound": True})
        self.assertEqual(hub.mock_calls, [])


if __name__ == "__main__":
    unittest.main()
