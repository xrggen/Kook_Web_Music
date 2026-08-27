import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


PLATFORM_DIR = Path(__file__).resolve().parents[1]
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

import qq_credential


class QQCredentialLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_cookie_path = qq_credential.QQ_COOKIE_TXT_PATH
        self.original_credential_path = qq_credential.QQ_CREDENTIAL_PATH
        root = Path(self.tempdir.name)
        qq_credential.QQ_COOKIE_TXT_PATH = str(root / "qq_cookie.txt")
        qq_credential.QQ_CREDENTIAL_PATH = str(root / "qq_credential.json")

    def tearDown(self):
        qq_credential.QQ_COOKIE_TXT_PATH = self.original_cookie_path
        qq_credential.QQ_CREDENTIAL_PATH = self.original_credential_path
        self.tempdir.cleanup()

    def test_migration_does_not_treat_access_token_expiry_as_login_expiry(self):
        future = int(time.time()) + 7 * 86400
        cookie = (
            "uin=o123456; "
            "qqmusic_key=Q_H_L_example; "
            "qm_keyst=Q_H_L_example; "
            "psrf_access_token_expiresAt=1; "
            f"qqmusic_key_expiresAt={future}"
        )
        Path(qq_credential.QQ_COOKIE_TXT_PATH).write_text(cookie, encoding="utf-8")

        stored = qq_credential.load_qq_credential()
        status = qq_credential._credential_status(stored)
        compatibility_cookie = Path(qq_credential.QQ_COOKIE_TXT_PATH).read_text(encoding="utf-8")

        self.assertEqual(stored["uin"], "123456")
        self.assertEqual(stored["access_expires_at"], 1)
        self.assertEqual(stored["key_expires_at"], future)
        self.assertTrue(status["valid"])
        self.assertNotIn("psrf_access_token_expiresAt", compatibility_cookie)

    def test_refresh_replaces_musickey_in_cookie_and_credential_store(self):
        cookie = "uin=o123456; qqmusic_key=Q_H_L_old; qm_keyst=Q_H_L_old"
        qq_credential.save_qq_cookie(cookie, source="login")
        now = int(time.time())
        response = {
            "musicid": 123456,
            "musickey": "Q_H_L_new",
            "musickeyCreateTime": now,
            "keyExpiresIn": 7776000,
        }

        with mock.patch.object(qq_credential, "_full_refresh_payload", return_value=None), \
             mock.patch.object(qq_credential, "_legacy_refresh", return_value=response):
            refreshed = qq_credential.refresh_qq_credential(reason="unit-test")

        compatibility_cookie = qq_credential.parse_cookie_string(
            Path(qq_credential.QQ_COOKIE_TXT_PATH).read_text(encoding="utf-8")
        )
        persisted = json.loads(
            Path(qq_credential.QQ_CREDENTIAL_PATH).read_text(encoding="utf-8")
        )

        self.assertEqual(refreshed["musickey"], "Q_H_L_new")
        self.assertEqual(compatibility_cookie["qqmusic_key"], "Q_H_L_new")
        self.assertEqual(compatibility_cookie["qm_keyst"], "Q_H_L_new")
        self.assertEqual(persisted["musickey"], "Q_H_L_new")
        self.assertGreater(refreshed["key_expires_at"], now)

    def test_transient_refresh_failure_keeps_unexpired_login(self):
        future = int(time.time()) + 3 * 86400
        cookie = (
            "uin=123456; qqmusic_key=Q_H_L_example; qm_keyst=Q_H_L_example; "
            f"qqmusic_key_expiresAt={future}"
        )
        qq_credential.save_qq_cookie(cookie, source="login")

        with mock.patch.object(
            qq_credential,
            "refresh_qq_credential",
            side_effect=RuntimeError("temporary network failure"),
        ):
            status = qq_credential.ensure_qq_credential(
                force_refresh=True,
                reason="unit-test",
            )

        self.assertTrue(status["valid"])
        self.assertFalse(status["need_relogin"])
        self.assertIn("继续使用现有登录态", status["message"])


if __name__ == "__main__":
    unittest.main()
