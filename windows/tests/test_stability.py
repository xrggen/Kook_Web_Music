import asyncio
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
import app as windows_app


class FakePlayHandler:
    created = []

    def __init__(self, channel_id, token):
        self.channel_id = channel_id
        self.token = token
        self.finished = threading.Event()
        self.started = False
        self.stop_requests = 0
        self.detached = False
        self.processes_to_kill = 0
        self.__class__.created.append(self)

    def start(self):
        self.started = True

    def request_stop(self):
        self.stop_requests += 1
        return True

    def mark_detached(self):
        self.detached = True

    def force_terminate_subprocesses(self):
        return self.processes_to_kill


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
            kookvoice._recovering_channels.clear()
            kookvoice._pending_leave_channels.clear()
        kookvoice.PlayHandler = FakePlayHandler

    def tearDown(self):
        kookvoice.PlayHandler = self.original_handler
        kookvoice.ffmpeg_bin = self.original_ffmpeg
        with kookvoice.state_lock:
            kookvoice.play_list.clear()
            kookvoice.guild_status.clear()
            kookvoice.playlist_handle_status.clear()
            kookvoice._active_handlers.clear()
            kookvoice._recovering_channels.clear()
            kookvoice._pending_leave_channels.clear()

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

    def test_queue_metadata_is_bounded_and_drops_decoder_options(self):
        player = kookvoice.Player("metadata-bounds", "token")
        metadata = {
            "title": "x" * 1000,
            "extra_command": '-headers "Cookie: synthetic"',
            "cookies": "synthetic-cookie",
        }
        metadata.update({f"field-{index}": index for index in range(40)})

        player.add_music("https://example.invalid/song.mp3", metadata)
        stored = kookvoice.get_state_snapshot("metadata-bounds")["play_list"][0]["extra"]

        self.assertEqual(len(stored["title"]), 512)
        self.assertNotIn("extra_command", stored)
        self.assertNotIn("cookies", stored)
        self.assertLessEqual(len(stored), 32)

    def test_rtp_config_rejects_output_descriptor_injection(self):
        valid = kookvoice._validated_rtp_config({
            "ip": "203.0.113.10",
            "port": 5004,
            "rtcp_port": 5005,
            "audio_ssrc": 1111,
            "audio_pt": 111,
            "bitrate": 128000,
        })
        self.assertEqual(valid["url"], "rtp://203.0.113.10:5004?rtcpport=5005")

        with self.assertRaises(ValueError):
            kookvoice._validated_rtp_config({
                "ip": "203.0.113.10|[f=segment]file:///tmp/output",
                "port": 5004,
                "rtcp_port": 5005,
                "bitrate": 128000,
            })

    def test_single_and_playlist_repeat_are_mutually_exclusive(self):
        player = kookvoice.Player("repeat-modes", "token")
        player.add_music("https://example.invalid/song.mp3")

        self.assertTrue(player.playlist_repeat_toggle())
        snapshot = kookvoice.get_state_snapshot("repeat-modes")
        self.assertTrue(snapshot["playlist_repeat"])
        self.assertFalse(snapshot["repeat"])

        self.assertTrue(player.repeat_toggle())
        snapshot = kookvoice.get_state_snapshot("repeat-modes")
        self.assertTrue(snapshot["repeat"])
        self.assertFalse(snapshot["playlist_repeat"])

    def test_playlist_repeat_moves_completed_track_to_queue_tail(self):
        state = kookvoice._new_channel_state(
            "playlist-repeat",
            "token",
            "guild-1",
        )
        state["playlist_repeat"] = True
        state["now_playing"] = {
            "file": "https://example.invalid/current.mp3",
            "ss": 42,
            "start": 123.0,
            "extra": {"title": "current"},
        }
        state["play_list"] = [
            {
                "file": "https://example.invalid/next.mp3",
                "ss": 0,
                "extra": {"title": "next"},
            }
        ]
        with kookvoice.state_lock:
            kookvoice.play_list["playlist-repeat"] = state
            completion = kookvoice._complete_current_track_locked(
                "playlist-repeat"
            )

        snapshot = kookvoice.get_state_snapshot("playlist-repeat")
        self.assertEqual(completion["mode"], "playlist")
        self.assertFalse(completion["queue_empty"])
        self.assertIsNone(snapshot["now_playing"])
        self.assertEqual(
            [item["extra"]["title"] for item in snapshot["play_list"]],
            ["next", "current"],
        )
        self.assertEqual(snapshot["play_list"][1]["ss"], 0)
        self.assertNotIn("start", snapshot["play_list"][1])

    def test_completed_track_is_not_requeued_when_loops_are_off(self):
        state = kookvoice._new_channel_state("no-repeat", "token", "guild-1")
        state["now_playing"] = {
            "file": "https://example.invalid/current.mp3",
            "ss": 0,
            "extra": {},
        }
        with kookvoice.state_lock:
            kookvoice.play_list["no-repeat"] = state
            completion = kookvoice._complete_current_track_locked("no-repeat")

        self.assertIsNone(completion["mode"])
        self.assertTrue(completion["queue_empty"])
        self.assertEqual(
            kookvoice.get_state_snapshot("no-repeat")["play_list"],
            [],
        )

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

    def test_reset_actively_cancels_registered_handler(self):
        player = kookvoice.Player("active", "token")
        player.join("guild-1")
        handler = FakePlayHandler.created[0]

        channels = kookvoice.reset_playback_state()

        self.assertEqual(channels, {"active"})
        self.assertEqual(handler.stop_requests, 1)
        self.assertEqual(
            kookvoice.get_state_snapshot()["guild_status"]["active"],
            kookvoice.Status.STOP,
        )
        self.assertTrue(kookvoice.get_state_snapshot("active")["_stopping"])
        with self.assertRaisesRegex(RuntimeError, "紧急恢复"):
            kookvoice.Player("active", "token").add_music(
                "https://example.invalid/too-early.mp3",
                guild_id="guild-1",
            )
        kookvoice.finish_playback_recovery(channels, {"active"})
        with kookvoice.state_lock:
            self.assertEqual(kookvoice._pending_leave_channels, {"active"})
        kookvoice.finish_playback_recovery(channels)
        with kookvoice.state_lock:
            self.assertEqual(kookvoice._pending_leave_channels, set())

    def test_force_cleanup_kills_processes_and_detaches_handler(self):
        player = kookvoice.Player("stuck", "token")
        player.join("guild-1")
        handler = FakePlayHandler.created[0]
        handler.processes_to_kill = 2

        killed = kookvoice.force_terminate_handler_processes({"stuck"})
        detached = kookvoice.detach_stuck_handlers({"stuck"})

        self.assertEqual(killed, 2)
        self.assertEqual(detached, {"stuck"})
        self.assertTrue(handler.detached)
        self.assertGreaterEqual(handler.stop_requests, 1)
        self.assertIsNone(kookvoice.get_state_snapshot("stuck"))
        with kookvoice.state_lock:
            self.assertNotIn("stuck", kookvoice._active_handlers)

        # 隔离后同一频道可立即建立新会话。
        kookvoice.Player("stuck", "token").add_music(
            "https://example.invalid/recovered.mp3",
            guild_id="guild-1",
        )
        self.assertEqual(len(FakePlayHandler.created), 2)

    def test_real_handler_request_stop_cancels_push_task(self):
        handler = self.original_handler("cancel-test", "token")

        class FakeTask:
            def __init__(self):
                self.cancelled = False

            def done(self):
                return False

            def cancel(self):
                self.cancelled = True

        class FakeLoop:
            def is_closed(self):
                return False

            def call_soon_threadsafe(self, callback):
                callback()

        task = FakeTask()
        handler._loop = FakeLoop()
        handler._push_task = task
        with kookvoice.state_lock:
            kookvoice._active_handlers["cancel-test"] = handler
            kookvoice.play_list["cancel-test"] = kookvoice._new_channel_state(
                "cancel-test",
                "token",
                "guild-1",
            )

        scheduled = handler.request_stop()

        self.assertTrue(scheduled)
        self.assertTrue(task.cancelled)
        self.assertTrue(handler.stop_requested.is_set())
        self.assertEqual(
            kookvoice.get_state_snapshot()["guild_status"]["cancel-test"],
            kookvoice.Status.STOP,
        )

    def test_force_terminate_validates_tracked_media_process_identity(self):
        if kookvoice.psutil is None:
            self.skipTest("psutil is not installed")

        handler = self.original_handler("process-test", "token")
        async_process = mock.Mock(pid=4242, returncode=None)
        tracked_process = mock.Mock(pid=4242)
        tracked_process.create_time.return_value = 100.0
        tracked_process.name.return_value = "ffmpeg.exe"
        tracked_process.children.return_value = []
        with handler._control_lock:
            handler._subprocesses[4242] = {
                "proc": async_process,
                "label": "ffmpeg-decode",
                "create_time": 100.0,
            }

        with (
            mock.patch.object(
                kookvoice.psutil,
                "Process",
                return_value=tracked_process,
            ),
            mock.patch.object(
                kookvoice.psutil,
                "wait_procs",
                return_value=([tracked_process], []),
            ) as wait_procs,
        ):
            killed = handler.force_terminate_subprocesses()

        self.assertEqual(killed, 1)
        tracked_process.kill.assert_called_once_with()
        wait_procs.assert_called_once()
        self.assertEqual(handler._subprocesses, {})

    def test_force_terminate_refuses_reused_pid(self):
        if kookvoice.psutil is None:
            self.skipTest("psutil is not installed")

        handler = self.original_handler("reused-pid-test", "token")
        async_process = mock.Mock(pid=4243, returncode=None)
        reused_process = mock.Mock(pid=4243)
        reused_process.create_time.return_value = 200.0
        with handler._control_lock:
            handler._subprocesses[4243] = {
                "proc": async_process,
                "label": "ffmpeg-decode",
                "create_time": 100.0,
            }

        with mock.patch.object(
            kookvoice.psutil,
            "Process",
            return_value=reused_process,
        ):
            killed = handler.force_terminate_subprocesses()

        self.assertEqual(killed, 0)
        reused_process.kill.assert_not_called()
        async_process.kill.assert_not_called()

    def test_set_ffmpeg_fails_fast_for_missing_binary(self):
        with self.assertRaises(FileNotFoundError):
            kookvoice.set_ffmpeg("definitely-missing-ffmpeg-binary")

        with tempfile.TemporaryDirectory() as temp_dir:
            fake_binary = Path(temp_dir, "ffmpeg.exe")
            fake_binary.touch()
            kookvoice.set_ffmpeg(fake_binary)
            self.assertTrue(Path(kookvoice.ffmpeg_bin).samefile(fake_binary))

    def test_bili_decoder_uses_supported_io_timeout_and_input_options(self):
        command = kookvoice._build_decoder_command(
            "https://example.invalid/audio.m4s",
            ss_value=12,
            is_bili=True,
        )

        self.assertNotIn("-timeout", command)
        self.assertNotIn("-headers", command)
        self.assertNotIn("-cookies", command)
        self.assertIn("-rw_timeout", command)
        timeout_index = command.index("-rw_timeout")
        self.assertEqual(command[timeout_index + 1], "60000000")
        self.assertEqual(command[command.index("-loglevel") + 1], "error")
        self.assertLess(command.index("-user_agent"), command.index("-i"))
        self.assertLess(command.index("-referer"), command.index("-i"))
        self.assertEqual(command[command.index("-ss") + 1], "12")

        with self.assertRaises(ValueError):
            kookvoice._build_decoder_command(
                "https://example.invalid/audio.m4s",
                ss_value="nan",
            )

        with self.assertRaises(TypeError):
            kookvoice._build_decoder_command(
                "https://example.invalid/audio.m4s",
                extra_command='-headers "Cookie: test=1"',
            )

    def test_decoder_rejects_non_http_protocols_and_embedded_credentials(self):
        invalid_sources = (
            "file:///etc/passwd",
            "concat:https://example.invalid/a|https://example.invalid/b",
            "ftp://example.invalid/audio.mp3",
            "https://user:password@example.invalid/audio.mp3",
            " https://example.invalid/audio.mp3",
            "https://example.invalid/audio.mp3\n",
        )
        for source in invalid_sources:
            with self.subTest(source=source):
                with self.assertRaises(ValueError):
                    kookvoice._build_decoder_command(source)

    def test_handler_reaps_subprocess_pipes_before_closing_thread_loop(self):
        handler = self.original_handler("subprocess-cleanup-test", "token")
        created = {}

        async def spawn_tracked_subprocess():
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-c",
                (
                    "import sys,time;"
                    "sys.stdout.write('out');sys.stdout.flush();"
                    "sys.stderr.write('err');sys.stderr.flush();"
                    "time.sleep(30)"
                ),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            created["proc"] = handler._track_subprocess(
                proc,
                "ffmpeg-cleanup-test",
            )
            await asyncio.sleep(0)

        handler.main = spawn_tracked_subprocess
        handler.run()

        proc = created["proc"]
        self.assertIsNotNone(proc.returncode)
        self.assertTrue(proc.stdin.is_closing())
        self.assertTrue(proc.stdout.at_eof())
        self.assertTrue(proc.stderr.at_eof())
        self.assertEqual(handler._subprocesses, {})
        self.assertIsNone(handler._loop)


class PlaylistCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_playlist_is_sent_as_sanitized_plain_text(self):
        class Guild:
            id = "guild-1"

        class Context:
            guild = Guild()

        class FakeMessage:
            author_id = "user-1"
            ctx = Context()

            def __init__(self):
                self.reply = mock.AsyncMock()

        message = FakeMessage()
        state = {
            "now_playing": {
                "extra": {"title": "正在\n播放\x00的歌曲"},
            },
            "play_list": [
                {
                    "extra": {
                        "音乐名字": "很长的歌名" * 30,
                    }
                }
            ],
        }

        with (
            mock.patch.object(
                windows_app,
                "_resolve_channel",
                new=mock.AsyncMock(return_value="voice-1"),
            ),
            mock.patch.object(
                windows_app.kookvoice,
                "get_state_snapshot",
                return_value=state,
            ),
        ):
            await windows_app.playlist_cmd.handler(message, "")

        message.reply.assert_awaited_once()
        content = message.reply.await_args.args[0]
        self.assertNotIn("\n播放", content)
        self.assertNotIn("\x00", content)
        self.assertIn("正在 播放的歌曲", content)
        self.assertIn("…", content)
        self.assertFalse(message.reply.await_args.kwargs["use_quote"])
        self.assertEqual(
            message.reply.await_args.kwargs["type"],
            windows_app.MessageTypes.TEXT,
        )


class EmergencyRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        with kookvoice.state_lock:
            kookvoice.play_list.clear()
            kookvoice.guild_status.clear()
            kookvoice.playlist_handle_status.clear()
            kookvoice._active_handlers.clear()
            kookvoice._recovering_channels.clear()
            kookvoice._pending_leave_channels.clear()

    def tearDown(self):
        with kookvoice.state_lock:
            kookvoice.play_list.clear()
            kookvoice.guild_status.clear()
            kookvoice.playlist_handle_status.clear()
            kookvoice._active_handlers.clear()
            kookvoice._recovering_channels.clear()
            kookvoice._pending_leave_channels.clear()

    async def test_recovery_finishes_without_force_when_handlers_exit(self):
        channels = {"channel-a", "channel-b"}
        with (
            mock.patch.object(
                windows_app.kookvoice,
                "reset_playback_state",
                return_value=channels,
            ),
            mock.patch.object(
                windows_app,
                "_force_leave_voice_channels",
                new=mock.AsyncMock(return_value=({"channel-a"}, {"channel-b": "gone"})),
            ),
            mock.patch.object(
                windows_app.kookvoice,
                "wait_for_handlers",
                return_value=set(),
            ),
            mock.patch.object(
                windows_app.kookvoice,
                "force_terminate_handler_processes",
            ) as force_kill,
            mock.patch.object(
                windows_app.kookvoice,
                "finish_playback_recovery",
            ) as finish_recovery,
        ):
            report = await windows_app._perform_playback_recovery()

        self.assertEqual(report["channels"], channels)
        self.assertEqual(report["graceful"], channels)
        self.assertEqual(report["left"], {"channel-a"})
        self.assertEqual(report["leave_failed"], {"channel-b": "gone"})
        self.assertEqual(report["killed_processes"], 0)
        force_kill.assert_not_called()
        finish_recovery.assert_called_once_with(channels, {"channel-b"})

    async def test_recovery_escalates_to_kill_and_detach(self):
        channels = {"channel-a"}
        with (
            mock.patch.object(
                windows_app.kookvoice,
                "reset_playback_state",
                return_value=channels,
            ),
            mock.patch.object(
                windows_app,
                "_force_leave_voice_channels",
                new=mock.AsyncMock(return_value=(channels, {})),
            ),
            mock.patch.object(
                windows_app.kookvoice,
                "wait_for_handlers",
                side_effect=[channels, channels],
            ),
            mock.patch.object(
                windows_app.kookvoice,
                "force_terminate_handler_processes",
                side_effect=[2, 1],
            ),
            mock.patch.object(
                windows_app.kookvoice,
                "detach_stuck_handlers",
                return_value=channels,
            ),
            mock.patch.object(
                windows_app.kookvoice,
                "finish_playback_recovery",
            ) as finish_recovery,
        ):
            report = await windows_app._perform_playback_recovery()

        self.assertEqual(report["graceful"], set())
        self.assertEqual(report["forced"], set())
        self.assertEqual(report["detached"], channels)
        self.assertEqual(report["killed_processes"], 3)
        finish_recovery.assert_called_once_with(channels, set())

    async def test_detach_waits_for_inflight_leave_before_releasing_channel(self):
        channel_id = "leave-race"
        leave_started = threading.Event()
        leave_cancelled = threading.Event()
        allow_leave_to_finish = threading.Event()

        class BlockingRequestor:
            async def leave(self, _channel_id):
                leave_started.set()
                try:
                    while not allow_leave_to_finish.is_set():
                        await asyncio.sleep(0.01)
                except asyncio.CancelledError:
                    # 模拟底层网络调用未立即响应取消，验证隔离握手仍会等待。
                    leave_cancelled.set()
                    while not allow_leave_to_finish.is_set():
                        await asyncio.sleep(0.01)

            async def close(self):
                return None

        handler = kookvoice.PlayHandler(channel_id, "token")
        handler.requestor = BlockingRequestor()
        handler._loop = asyncio.get_running_loop()
        with kookvoice.state_lock:
            kookvoice._active_handlers[channel_id] = handler
            kookvoice.play_list[channel_id] = kookvoice._new_channel_state(
                channel_id,
                "token",
                "guild-1",
            )
            kookvoice.guild_status[channel_id] = kookvoice.Status.STOP

        start_event = asyncio.Event()
        start_event.set()
        stop_task = asyncio.create_task(handler.stop(start_event))
        self.assertTrue(await asyncio.to_thread(leave_started.wait, 1.0))

        detach_task = asyncio.create_task(
            asyncio.to_thread(
                kookvoice.detach_stuck_handlers,
                {channel_id},
            )
        )
        await asyncio.sleep(0.05)

        self.assertTrue(leave_cancelled.is_set())
        self.assertFalse(detach_task.done())
        with kookvoice.state_lock:
            self.assertIs(kookvoice._active_handlers[channel_id], handler)

        allow_leave_to_finish.set()
        await asyncio.wait_for(stop_task, timeout=1.0)
        await asyncio.wait_for(detach_task, timeout=1.0)
        with kookvoice.state_lock:
            self.assertNotIn(channel_id, kookvoice._active_handlers)

    async def test_emergency_stop_delegates_leave_to_command_requestor(self):
        channel_id = "delegated-leave"

        class RecordingRequestor:
            def __init__(self):
                self.leave_calls = 0
                self.close_calls = 0

            async def leave(self, _channel_id):
                self.leave_calls += 1

            async def close(self):
                self.close_calls += 1

        handler = kookvoice.PlayHandler(channel_id, "token")
        requestor = RecordingRequestor()
        handler.requestor = requestor
        with kookvoice.state_lock:
            kookvoice._active_handlers[channel_id] = handler
            kookvoice.play_list[channel_id] = kookvoice._new_channel_state(
                channel_id,
                "token",
                "guild-1",
            )

        handler.request_stop()
        start_event = asyncio.Event()
        start_event.set()
        await handler.stop(start_event)

        self.assertEqual(requestor.leave_calls, 0)
        self.assertEqual(requestor.close_calls, 1)
        self.assertTrue(handler.finished.is_set())


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
