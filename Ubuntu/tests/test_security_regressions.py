import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PLATFORM_DIR = Path(__file__).resolve().parents[1]
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

import account_api
import bili_utils
import qq_credential
import qq_utils
import utils
from secure_storage import secure_write_text


class SecurityRegressionTests(unittest.TestCase):
    def test_music_api_bases_ignore_remote_environment_overrides(self):
        environment = os.environ.copy()
        environment.update({
            "MUSIC_API_PORT": "19474",
            "QQ_MUSIC_API_PORT": "19475",
            "MUSIC_API_BASE": "https://synthetic.invalid/netease",
            "QQ_MUSIC_API_BASE": "https://synthetic.invalid/qq",
        })
        command = (
            "import json, config; "
            "print(json.dumps([config.MUSIC_API_BASE, config.QQ_MUSIC_API_BASE]))"
        )
        completed = subprocess.run(
            [sys.executable, "-c", command],
            cwd=PLATFORM_DIR,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertEqual(
            json.loads(completed.stdout.strip()),
            ["http://127.0.0.1:19474", "http://127.0.0.1:19475"],
        )

    def test_qq_cookie_is_only_added_to_request_headers(self):
        synthetic_cookie = "uin=synthetic; session=not-a-real-secret"
        with mock.patch.object(qq_utils, "load_qq_cookie", return_value=synthetic_cookie):
            params = qq_utils.build_qq_params({"quality": "128"})
            headers = qq_utils.build_qq_headers()

        self.assertEqual(params, {"quality": "128"})
        self.assertNotIn("cookie", {str(key).lower() for key in params})
        self.assertEqual(headers, {"Cookie": synthetic_cookie})

    def test_external_account_payload_removes_credentials_recursively(self):
        payload = {
            "code": 200,
            "cookie": "synthetic-cookie",
            "data": {
                "accessToken": "synthetic-token",
                "refresh_token": "synthetic-refresh",
                "MUSIC_U": "synthetic-session",
                "__csrf": "synthetic-csrf",
                "authorization": "Bearer synthetic",
                "profile": {"nickname": "safe-name"},
            },
            "qrsig": "required-qr-state",
        }

        clean = account_api._sanitize_external_payload(payload)

        self.assertNotIn("cookie", clean)
        self.assertNotIn("accessToken", clean["data"])
        self.assertNotIn("refresh_token", clean["data"])
        self.assertNotIn("MUSIC_U", clean["data"])
        self.assertNotIn("__csrf", clean["data"])
        self.assertNotIn("authorization", clean["data"])
        self.assertEqual(clean["data"]["profile"]["nickname"], "safe-name")
        self.assertEqual(clean["qrsig"], "required-qr-state")

    def test_local_account_request_blocks_redirects_and_captures_cookie(self):
        response = mock.Mock()
        response.status_code = 200
        response.cookies = {}
        response.json.return_value = {
            "code": 803,
            "cookie": "synthetic-cookie",
            "data": {"profile": {"nickname": "safe-name"}},
        }
        with (
            mock.patch.object(account_api, "_load_cookie", return_value="stored-cookie"),
            mock.patch.object(account_api, "_save_cookie") as save_cookie,
            mock.patch.object(account_api.requests, "get", return_value=response) as get,
        ):
            result = account_api._api_get("/login/qr/check", key="synthetic-key")

        self.assertNotIn("cookie", result)
        save_cookie.assert_called_once_with("synthetic-cookie")
        self.assertFalse(get.call_args.kwargs["allow_redirects"])
        self.assertEqual(get.call_args.kwargs["headers"]["Cookie"], "stored-cookie")

    def test_secure_write_replaces_file_without_temporary_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "credential.txt"
            secure_write_text(target, "first")
            secure_write_text(target, "second")

            self.assertEqual(target.read_text(encoding="utf-8"), "second")
            self.assertEqual(list(Path(directory).glob(".credential-*")), [])

    def test_cookie_validators_reject_controls_and_extract_only_bili_sessdata(self):
        with self.assertRaises(ValueError):
            account_api._normalize_cookie("session=synthetic\r\nInjected: value")
        with self.assertRaises(ValueError):
            qq_credential._validate_cookie_string("uin=synthetic\nInjected=value")

        normalized = bili_utils.normalize_bili_cookie(
            "buvid3=synthetic-device; SESSDATA=synthetic-session; bili_jct=synthetic-csrf"
        )
        self.assertEqual(normalized, "SESSDATA=synthetic-session")

    def test_bili_logout_invalidates_cached_login_state(self):
        original_path = bili_utils.BILI_COOKIE_TXT_PATH
        original_cache = dict(bili_utils._verify_cache)
        try:
            with tempfile.TemporaryDirectory() as directory:
                target = Path(directory) / "bili_cookie.txt"
                target.write_text("SESSDATA=synthetic-session", encoding="utf-8")
                bili_utils.BILI_COOKIE_TXT_PATH = str(target)
                bili_utils._verify_cache.update({"ts": 123, "result": {"valid": True}})

                bili_utils.clear_bili_cookie()

                self.assertFalse(target.exists())
                self.assertEqual(bili_utils._verify_cache, {"ts": 0, "result": None})
        finally:
            bili_utils.BILI_COOKIE_TXT_PATH = original_path
            bili_utils._verify_cache.clear()
            bili_utils._verify_cache.update(original_cache)

    def test_playlist_display_accepts_artist_metadata_aliases(self):
        playlist = utils.format_playlist_data({
            "now_playing": {
                "file": "https://example.invalid/playing.mp3",
                "extra": {"音乐名字": "正在播放", "artist_name": "歌手甲"},
            },
            "play_list": [{
                "file": "https://example.invalid/queued.mp3",
                "extra": {"title": "下一首", "author": "歌手乙"},
            }],
        })

        self.assertEqual(playlist[0]["artist"], "歌手甲")
        self.assertEqual(playlist[1]["artist"], "歌手乙")


if __name__ == "__main__":
    unittest.main()
