import os
import sys
import tempfile
import unittest
from http.cookies import SimpleCookie
from pathlib import Path

from flask import Flask

PLATFORM_DIR = Path(__file__).resolve().parents[1]
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

import auth


class ControlPlaneAuthTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = os.environ.get("AUTH_DATABASE_PATH")
        os.environ["AUTH_DATABASE_PATH"] = str(Path(self.tempdir.name) / "auth.db")
        auth.init_database()

    def tearDown(self):
        if self.original_db is None:
            os.environ.pop("AUTH_DATABASE_PATH", None)
        else:
            os.environ["AUTH_DATABASE_PATH"] = self.original_db
        self.tempdir.cleanup()

    def _insert_user(self, username="tester", role="user", must_change=1, scopes="*"):
        now = 1_700_000_000
        with auth._connect() as db:
            cur = db.execute(
                """
                INSERT INTO users(
                    username,password_hash,role,enabled,must_change_password,
                    auth_version,created_at,updated_at
                ) VALUES(?,?,?,1,?,1,?,?)
                """,
                (username, auth.hash_password("TestPassword!123"), role, must_change, now, now),
            )
            user_id = int(cur.lastrowid)
            if role == "user":
                auth._set_scopes(db, user_id, scopes)
            return user_id

    def test_bootstrap_admin_is_created_and_forced_to_change_password(self):
        user = auth.get_user_by_username("gen")
        self.assertIsNotNone(user)
        self.assertEqual(user["role"], "admin")
        self.assertTrue(user["enabled"])
        self.assertTrue(user["must_change_password"])
        self.assertTrue(user["password_hash"].startswith("pbkdf2_sha256$"))

    def test_password_hash_round_trip(self):
        encoded = auth.hash_password("ExamplePassword!123")
        self.assertTrue(auth.verify_password("ExamplePassword!123", encoded))
        self.assertFalse(auth.verify_password("wrong-password", encoded))

    def test_scope_model_supports_global_guild_and_channel(self):
        global_id = self._insert_user("global_user", scopes="*")
        guild_id = self._insert_user("guild_user", scopes="guild:100")
        channel_id = self._insert_user("channel_user", scopes="channel:100/200")
        auth.sync_channel("999", "888", "全局范围测试频道")
        auth.sync_channel("100", "999", "服务器范围测试频道")
        auth.sync_channel("100", "200", "频道范围测试频道")
        self.assertTrue(auth.scope_allows(auth.get_user_by_id(global_id), "999", "888"))
        self.assertTrue(auth.scope_allows(auth.get_user_by_id(guild_id), "100", "999"))
        self.assertFalse(auth.scope_allows(auth.get_user_by_id(guild_id), "101", "999"))
        self.assertTrue(auth.scope_allows(auth.get_user_by_id(channel_id), "100", "200"))
        self.assertFalse(auth.scope_allows(auth.get_user_by_id(channel_id), "100", "201"))

    def test_scope_rejects_claimed_guild_that_does_not_own_channel(self):
        user_id = self._insert_user("guild_owner", scopes="guild:100")
        auth.sync_channel("200", "300", "其他服务器频道")
        user = auth.get_user_by_id(user_id)
        self.assertFalse(auth.scope_allows(user, "100", "300"))

    def test_request_resource_ids_reject_query_body_mismatch_and_duplicates(self):
        app = Flask(__name__)
        with app.test_request_context(
            "/api/play?guild_id=100",
            method="POST",
            json={"guild_id": "200", "channel_id": "300"},
        ):
            with self.assertRaises(ValueError):
                auth._request_resource_ids()
        with app.test_request_context("/api/play?guild_id=100&guild_id=100"):
            with self.assertRaises(ValueError):
                auth._request_resource_ids()
        with app.test_request_context(
            "/api/play?channel_id=300",
            method="POST",
            json={"guild_id": "200"},
        ):
            with self.assertRaises(ValueError):
                auth._request_resource_ids()
        with app.test_request_context(
            "/api/play",
            method="POST",
            json={"guild_id": 200, "channel_id": "300"},
        ):
            with self.assertRaises(ValueError):
                auth._request_resource_ids()
        with app.test_request_context(
            "/api/play",
            method="POST",
            json={"guild_id": " 200", "channel_id": "300"},
        ):
            with self.assertRaises(ValueError):
                auth._request_resource_ids()
        with app.test_request_context(
            "/api/play?guild_id=guild%0A1",
            method="POST",
            json={"channel_id": "300"},
        ):
            with self.assertRaises(ValueError):
                auth._request_resource_ids()

    def test_unauthenticated_control_plane_redirects_to_login(self):
        app = Flask(__name__)
        app.config["TESTING"] = True
        auth.register_auth(app)
        app.add_url_rule("/dashboard", "dashboard_test", lambda: "ok")
        client = app.test_client()
        response = client.get("/dashboard")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_first_login_requires_password_change_then_reissues_session(self):
        self._insert_user("tester")
        app = Flask(__name__)
        app.config["TESTING"] = True
        auth.register_auth(app)
        app.add_url_rule("/dashboard", "dashboard_test_2", lambda: "ok")
        client = app.test_client()
        login = client.post("/login", data={"username": "tester", "password": "TestPassword!123"}, follow_redirects=False)
        self.assertEqual(login.status_code, 302)
        self.assertTrue(login.headers["Location"].endswith("/change-password"))
        cookies = SimpleCookie()
        for value in login.headers.getlist("Set-Cookie"):
            cookies.load(value)
        csrf = cookies[auth.CSRF_COOKIE].value
        blocked = client.get("/dashboard", follow_redirects=False)
        self.assertEqual(blocked.status_code, 302)
        self.assertTrue(blocked.headers["Location"].endswith("/change-password"))
        changed = client.post(
            "/change-password",
            data={"_csrf": csrf, "current_password": "TestPassword!123", "new_password": "NewPassword!456", "confirm_password": "NewPassword!456"},
            follow_redirects=False,
        )
        self.assertEqual(changed.status_code, 302)
        self.assertTrue(changed.headers["Location"].endswith("/dashboard"))
        user = auth.get_user_by_username("tester")
        self.assertFalse(user["must_change_password"])
        self.assertTrue(auth.verify_password("NewPassword!456", user["password_hash"]))


if __name__ == "__main__":
    unittest.main()
