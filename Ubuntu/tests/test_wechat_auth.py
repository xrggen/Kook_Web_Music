from contextlib import closing
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from flask import Flask, jsonify

PLATFORM_DIR = Path(__file__).resolve().parents[1]
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))
import auth


class WechatAuthCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.fixture = tempfile.TemporaryDirectory(prefix="kook-native-auth-")
        root = Path(self.fixture.name)
        self.environment = patch.dict(os.environ, {
            "AUTH_DATABASE_PATH": str(root / "auth.db"),
            "INITIAL_ADMIN_CREDENTIAL_PATH": str(root / "bootstrap-fixture.json"),
            "INITIAL_ADMIN_PASSWORD": "FixtureAdmin!12345",
        })
        self.environment.start()
        auth.init_database()
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True, SECRET_KEY="fixture-not-production")
        self.app.add_url_rule("/api/pause", "fixture_pause", lambda: jsonify(success=True), methods=["POST"])
        auth.register_auth(self.app)
        self.client = self.app.test_client()
        self.password = "FixtureUser!12345"
        with closing(auth._connect()) as db, db:
            cursor = db.execute(
                """INSERT INTO users(username,password_hash,role,enabled,must_change_password,
                   auth_version,created_at,updated_at) VALUES(?,?,'user',1,0,1,1,1)""",
                ("native_fixture", auth.hash_password(self.password)),
            )
            self.user_id = cursor.lastrowid
            auth._set_scopes(db, self.user_id, "channel:100/200")
        auth.sync_channel("100", "200", "allowed")
        auth.sync_channel("100", "201", "denied")

    def tearDown(self):
        self.environment.stop()
        self.fixture.cleanup()

    def login(self):
        return self.client.post("/login", json={"username": "native_fixture", "password": self.password})

    def test_json_login_returns_protocol_and_csrf_but_session_only_in_cookie(self):
        response = self.login()
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["clientProtocol"], "kook-wechat-v1")
        self.assertEqual(body["user"]["role"], "user")
        self.assertFalse(body["user"]["must_change_password"])
        self.assertTrue(body["csrfToken"])
        self.assertNotIn("password", body)
        self.assertNotIn("sessionToken", body)
        cookies = response.headers.getlist("Set-Cookie")
        self.assertTrue(any("kook_session=" in cookie and "HttpOnly" in cookie for cookie in cookies))
        self.assertTrue(any("kook_csrf=" in cookie for cookie in cookies))
        self.assertIn("no-store", response.headers["Cache-Control"].lower())
        self.assertNotIn("public", response.headers["Cache-Control"].lower())

    def test_existing_form_login_keeps_redirect_and_cookies(self):
        response = self.client.post("/login", data={"username": "native_fixture", "password": self.password})
        self.assertEqual(response.status_code, 302)
        location = urlsplit(response.headers["Location"])
        self.assertEqual(location.path, "/dashboard")
        self.assertIn(location.netloc, ("", "localhost"))
        self.assertTrue(response.headers.getlist("Set-Cookie"))

    def test_invalid_native_json_and_bad_password_do_not_create_a_session(self):
        for payload in ([], {}, {"username": 1, "password": "x"}, {"username": "native_fixture", "password": "x" * 513}):
            self.assertEqual(self.client.post("/login", json=payload).status_code, 400)
        self.assertEqual(self.client.post("/login", json={"username": "native_fixture", "password": "wrong"}).status_code, 401)
        self.assertEqual(self.client.get("/api/auth/session").status_code, 401)

    def test_native_login_does_not_bypass_csrf_or_channel_scope(self):
        csrf = self.login().get_json()["csrfToken"]
        payload = {"guild_id": "100", "channel_id": "200"}
        self.assertEqual(self.client.post("/api/pause", json=payload).status_code, 403)
        self.assertEqual(self.client.post("/api/pause", json=payload, headers={"X-CSRF-Token": "wrong"}).status_code, 403)
        self.assertEqual(self.client.post("/api/pause", json={"guild_id": "100", "channel_id": "201"},
                                         headers={"X-CSRF-Token": csrf}).status_code, 403)
        self.assertEqual(self.client.post("/api/pause", json=payload, headers={"X-CSRF-Token": csrf}).status_code, 200)

    def test_native_password_change_is_mandatory_and_rotates_authenticated_session(self):
        with closing(auth._connect()) as db, db:
            db.execute("UPDATE users SET must_change_password=1 WHERE id=?", (self.user_id,))
        body = self.login().get_json()
        self.assertTrue(body["user"]["must_change_password"])
        self.assertEqual(self.client.post("/api/pause", json={"guild_id": "100", "channel_id": "200"},
                                         headers={"X-CSRF-Token": body["csrfToken"]}).status_code, 428)
        response = self.client.post("/change-password", json={
            "current_password": self.password, "new_password": "NewFixture!12345", "confirm_password": "NewFixture!12345",
        }, headers={"X-CSRF-Token": body["csrfToken"]})
        self.assertEqual(response.status_code, 200)
        changed = response.get_json()
        self.assertFalse(changed["user"]["must_change_password"])
        self.assertNotEqual(changed["csrfToken"], body["csrfToken"])
        self.assertTrue(auth.verify_password("NewFixture!12345", auth.get_user_by_id(self.user_id)["password_hash"]))
        self.assertEqual(self.client.post("/api/pause", json={"guild_id": "100", "channel_id": "200"},
                                         headers={"X-CSRF-Token": body["csrfToken"]}).status_code, 403)

    def test_native_invalid_password_change_is_json_and_does_not_mutate_password(self):
        csrf = self.login().get_json()["csrfToken"]
        response = self.client.post("/change-password", json={"current_password": self.password,
            "new_password": ["invalid"], "confirm_password": ["invalid"]}, headers={"X-CSRF-Token": csrf})
        self.assertEqual(response.status_code, 400)
        self.assertIsNotNone(response.get_json())
        self.assertTrue(auth.verify_password(self.password, auth.get_user_by_id(self.user_id)["password_hash"]))

    def test_regular_user_can_revoke_own_session_without_a_csrf_exemption(self):
        body = self.login().get_json()
        self.assertEqual(self.client.post("/logout", json={}).status_code, 403)
        response = self.client.post("/logout", json={}, headers={"X-CSRF-Token": body["csrfToken"]})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["success"])
        self.assertEqual(self.client.get("/api/auth/session").status_code, 401)


if __name__ == "__main__":
    unittest.main()
