import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock


WINDOWS_DIR = Path(__file__).resolve().parents[1]
if str(WINDOWS_DIR) not in sys.path:
    sys.path.insert(0, str(WINDOWS_DIR))

from kookvoice import kookvoice
import qq_utils


class FakePlayHandler:
    created = []

    def __init__(self, channel_id, token):
        self.channel_id = channel_id
        self.token = token
        self.finished = threading.Event()
        self.started = False
        self.__class__.created.append(self)

    def start(self):
        self.started = True


class PlaybackStateTests(unittest.TestCase):
    def setUp(self):
        self.original_handler = kookvoice.PlayHandler
        self.original_ffmpeg = kookvoice.ffmpeg_bin
        FakePlayHandler.created.clear()
        with kookvoice.state_lock:
            kookvoice.play_list.clear()
            kookvoice.guild_status.clear()
            kookvoice.playlist_handle_status.clear()
            kookvoice._active_handlers.clear()
        kookvoice.PlayHandler = FakePlayHandler

    def tearDown(self):
        kookvoice.PlayHandler = self.original_handler
        kookvoice.ffmpeg_bin = self.original_ffmpeg
        with kookvoice.state_lock:
            kookvoice.play_list.clear()
            kookvoice.guild_status.clear()
            kookvoice.playlist_handle_status.clear()
            kookvoice._active_handlers.clear()

    def test_concurrent_join_creates_only_one_handler(self):
        results = []
        errors = []

        def join():
            try:
                results.append(kookvoice.Player("channel-1", "token").join("guild-1"))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=join) for _ in range(20)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        self.assertEqual(len(FakePlayHandler.created), 1)
        self.assertEqual(results.count(True), 1)
        self.assertEqual(results.count(False), 19)

    def test_concurrent_adds_share_handler_and_preserve_queue(self):
        player = kookvoice.Player("channel-2", "token")

        threads = [
            threading.Thread(
                target=player.add_music,
                args=(f"https://example.invalid/{index}.mp3", {"index": index}),
            )
            for index in range(25)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        snapshot = kookvoice.get_state_snapshot("channel-2")
        self.assertEqual(len(FakePlayHandler.created), 1)
        self.assertEqual(len(snapshot["play_list"]), 25)
        self.assertEqual(
            {item["extra"]["index"] for item in snapshot["play_list"]},
            set(range(25)),
        )

    def test_snapshot_is_independent_copy(self):
        player = kookvoice.Player("channel-3", "token")
        player.add_music("https://example.invalid/song.mp3", {"title": "before"})

        snapshot = kookvoice.get_state_snapshot("channel-3")
        snapshot["play_list"][0]["extra"]["title"] = "after"

        live = kookvoice.get_state_snapshot("channel-3")
        self.assertEqual(live["play_list"][0]["extra"]["title"], "before")

    def test_new_queue_waits_for_stopping_handler_cleanup(self):
        player = kookvoice.Player("channel-4", "token")
        player.join("guild-1")
        old_handler = FakePlayHandler.created[0]
        player.stop()

        errors = []
        wait_entered = threading.Event()
        original_wait = kookvoice._wait_for_stopping_channel

        def tracked_wait(channel_id, timeout=10.0):
            wait_entered.set()
            return original_wait(channel_id, timeout)

        def add_after_stop():
            try:
                kookvoice.Player("channel-4", "token").add_music(
                    "https://example.invalid/new.mp3",
                    guild_id="guild-1",
                )
            except Exception as exc:
                errors.append(exc)

        with mock.patch.object(
            kookvoice,
            "_wait_for_stopping_channel",
            side_effect=tracked_wait,
        ):
            thread = threading.Thread(target=add_after_stop)
            thread.start()
            self.assertTrue(wait_entered.wait(1))
            with kookvoice.state_lock:
                kookvoice.play_list.pop("channel-4", None)
                kookvoice.guild_status.pop("channel-4", None)
                kookvoice.playlist_handle_status.pop("channel-4", None)
                kookvoice._active_handlers.pop("channel-4", None)
            old_handler.finished.set()
            thread.join()

        self.assertEqual(errors, [])
        self.assertEqual(len(FakePlayHandler.created), 2)
        self.assertEqual(
            kookvoice.get_state_snapshot("channel-4")["guild_id"],
            "guild-1",
        )

    def test_reset_removes_inactive_stale_state(self):
        with kookvoice.state_lock:
            kookvoice.play_list["stale"] = kookvoice._new_channel_state(
                "stale",
                "token",
                "guild-1",
            )
            kookvoice.guild_status["stale"] = kookvoice.Status.WAIT

        channels = kookvoice.reset_playback_state()

        self.assertEqual(channels, {"stale"})
        self.assertIsNone(kookvoice.get_state_snapshot("stale"))

    def test_set_ffmpeg_fails_fast_for_missing_binary(self):
        with self.assertRaises(FileNotFoundError):
            kookvoice.set_ffmpeg("definitely-missing-ffmpeg-binary")

        with tempfile.TemporaryDirectory() as temp_dir:
            fake_binary = Path(temp_dir, "ffmpeg.exe")
            fake_binary.touch()
            kookvoice.set_ffmpeg(fake_binary)
            self.assertTrue(Path(kookvoice.ffmpeg_bin).samefile(fake_binary))


class FakeResponse:
    def __init__(self, data):
        self._data = data
        self.content = b"valid-json-response"

    def json(self):
        return self._data


class QqPaginationTests(unittest.TestCase):
    @staticmethod
    def response(songlist, total=60):
        return FakeResponse({
            "req_0": {
                "code": 0,
                "data": {
                    "dirinfo": {"title": "test", "songnum": total},
                    "songlist": songlist,
                },
            },
        })

    def test_empty_page_terminates_pagination(self):
        first_page = [{"songmid": str(index)} for index in range(30)]
        responses = [
            self.response(first_page),
            self.response([]),
        ]

        with mock.patch.object(qq_utils.requests, "post", side_effect=responses) as post:
            _, songs = qq_utils._qq_api_direct("123")

        self.assertEqual(len(songs), 30)
        self.assertEqual(post.call_count, 2)

    def test_repeated_page_terminates_pagination(self):
        first_page = [{"songmid": str(index)} for index in range(30)]
        responses = [
            self.response(first_page, total=90),
            self.response(first_page, total=90),
        ]

        with mock.patch.object(qq_utils.requests, "post", side_effect=responses) as post:
            _, songs = qq_utils._qq_api_direct("456")

        self.assertEqual(len(songs), 30)
        self.assertEqual(post.call_count, 2)

    def test_invalid_playlist_id_does_not_request_network(self):
        with mock.patch.object(qq_utils.requests, "post") as post:
            result = qq_utils._qq_api_direct("not-a-number")

        self.assertEqual(result, ({}, []))
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
