import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import urlsplit


WINDOWS_DIR = Path(__file__).resolve().parents[1]
if str(WINDOWS_DIR) not in sys.path:
    sys.path.insert(0, str(WINDOWS_DIR))

import config
import run
import app as windows_app
from runtime_health import RuntimeHealth
from service_watchdog import WatchdogConfig, WatchdogEvaluator


class FakeClock:
    def __init__(self, value=100.0):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class WatchdogEvaluatorTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.health = RuntimeHealth(self.clock)
        self.evaluator = WatchdogEvaluator(
            WatchdogConfig(
                startup_grace=180,
                loop_timeout=90,
                gateway_timeout=90,
                failures_before_restart=3,
            )
        )
        self.health.mark_supervisor_ready()
        self.health.mark_gateway_probe_available()

    def test_startup_grace_ignores_missing_heartbeats_and_dependencies(self):
        self.clock.advance(179)
        decision = self.evaluator.evaluate(
            self.health.snapshot(),
            ("netease_api:process_not_running",),
        )
        self.assertEqual("startup_grace", decision.phase)
        self.assertEqual(0, decision.consecutive_failures)
        self.assertFalse(decision.should_restart)

    def test_fresh_loop_does_not_hide_stale_gateway(self):
        self.clock.advance(181)
        self.health.mark_loop_heartbeat()
        self.health.mark_gateway_activity()
        self.clock.advance(91)

        for expected_count in (1, 2, 3):
            self.health.mark_loop_heartbeat()
            decision = self.evaluator.evaluate(self.health.snapshot())
            self.assertEqual(expected_count, decision.consecutive_failures)

        self.assertTrue(decision.should_restart)
        self.assertIn("kook_gateway:stale:91.0s", decision.reasons)

    def test_recovery_resets_consecutive_failures(self):
        self.clock.advance(181)
        self.health.mark_loop_heartbeat()
        self.health.mark_gateway_activity()
        first = self.evaluator.evaluate(
            self.health.snapshot(),
            ("web:http_unresponsive",),
        )
        self.assertEqual(1, first.consecutive_failures)

        healthy = self.evaluator.evaluate(self.health.snapshot())
        self.assertEqual("healthy", healthy.phase)
        self.assertEqual(0, healthy.consecutive_failures)

    def test_configuration_error_never_restarts(self):
        self.clock.advance(181)
        self.health.mark_loop_heartbeat()
        self.health.mark_gateway_activity()
        self.health.mark_bot_state("configuration_error", "Token为空")

        for _ in range(4):
            decision = self.evaluator.evaluate(self.health.snapshot())

        self.assertTrue(decision.restart_blocked)
        self.assertFalse(decision.should_restart)

    def test_missing_gateway_probe_capability_degrades_without_false_restart(self):
        clock = FakeClock()
        health = RuntimeHealth(clock)
        health.mark_supervisor_ready()
        clock.advance(181)
        health.mark_loop_heartbeat()
        health.mark_bot_state("online")
        evaluator = WatchdogEvaluator(
            WatchdogConfig(startup_grace=180, failures_before_restart=1)
        )

        decision = evaluator.evaluate(health.snapshot())

        self.assertEqual("healthy", decision.phase)
        self.assertFalse(decision.should_restart)

    def test_music_api_failures_only_degrade_even_when_persistent(self):
        self.clock.advance(181)
        self.health.mark_loop_heartbeat()
        self.health.mark_gateway_activity()
        for failures in (
            ("qq_music_api:http_unresponsive",),
            ("netease_api:process_not_running",),
            ("qq_music_api:process_not_running", "netease_api:http_unresponsive"),
        ):
            for _ in range(6):
                decision = self.evaluator.evaluate(self.health.snapshot(), failures)
                self.assertEqual("degraded", decision.phase)
                self.assertEqual(failures, decision.reasons)
                self.assertEqual(0, decision.consecutive_failures)
                self.assertFalse(decision.should_restart)

    def test_web_failure_still_restarts_without_inheriting_api_failures(self):
        self.clock.advance(181)
        self.health.mark_loop_heartbeat()
        self.health.mark_gateway_activity()
        api_failure = ("qq_music_api:http_unresponsive",)
        for _ in range(6):
            self.evaluator.evaluate(self.health.snapshot(), api_failure)
        for count in (1, 2, 3):
            decision = self.evaluator.evaluate(
                self.health.snapshot(), (*api_failure, "web:http_unresponsive")
            )
            self.assertEqual(count, decision.consecutive_failures)
            self.assertEqual(count == 3, decision.should_restart)

        recovered = self.evaluator.evaluate(self.health.snapshot(), api_failure)
        self.assertEqual("degraded", recovered.phase)
        self.assertEqual(0, recovered.consecutive_failures)
        self.assertFalse(recovered.should_restart)


class WatchdogPathTests(unittest.TestCase):
    def tearDown(self):
        run._restart_in_progress.clear()

    def test_relative_project_paths_are_resolved_from_windows_directory(self):
        expected = os.path.realpath(
            os.path.join(config.current_dir, "Cookie", "test-cookie.txt")
        )
        actual = config._resolve_project_path("./Cookie/test-cookie.txt")
        self.assertEqual(expected, actual)
        self.assertTrue(os.path.isabs(actual))

    def test_restart_command_uses_absolute_python_and_run_script(self):
        command = run._build_restart_command()
        self.assertTrue(os.path.isabs(command[0]))
        self.assertTrue(os.path.isabs(command[1]))
        self.assertEqual(os.path.realpath(run.RUN_SCRIPT), command[1])
        self.assertEqual(
            os.path.normcase(os.path.dirname(command[1])),
            os.path.normcase(run.APP_DIR),
        )
        if run.NODE_EXECUTABLE is not None:
            self.assertTrue(os.path.isabs(run.NODE_EXECUTABLE))

    def test_edge_restart_preserves_entrypoint_and_original_arguments(self):
        edge_entrypoint = os.path.realpath(
            os.path.join(run.PROJECT_ROOT, "edge", "run.py")
        )
        with (
            mock.patch.object(run, "_restart_entrypoint", run.RUN_SCRIPT, create=True),
            mock.patch.object(run, "_restart_arguments", None, create=True),
            mock.patch.object(sys, "argv", [edge_entrypoint, "--example", "two words"]),
        ):
            run._configure_restart_entrypoint(edge_entrypoint)
            with mock.patch.object(sys, "argv", [run.RUN_SCRIPT, "changed"]):
                self.assertEqual(
                    [run.PYTHON_EXECUTABLE, edge_entrypoint, "--example", "two words"],
                    run._build_restart_command(),
                )

    def test_restart_entrypoint_rejects_other_scripts(self):
        with (
            mock.patch.object(run, "_restart_entrypoint", run.RUN_SCRIPT, create=True),
            mock.patch.object(run, "_restart_arguments", None, create=True),
        ):
            with self.assertRaises(ValueError):
                run._configure_restart_entrypoint(
                    os.path.join(run.PROJECT_ROOT, "cloud", "run.py")
                )
            self.assertEqual(run.RUN_SCRIPT, run._build_restart_command()[1])

    def test_edge_role_is_preserved_by_exec_and_fallback_restart(self):
        edge_entrypoint = os.path.realpath(
            os.path.join(run.PROJECT_ROOT, "edge", "run.py")
        )
        run._restart_in_progress.clear()
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(run, "_restart_entrypoint", run.RUN_SCRIPT, create=True),
            mock.patch.object(run, "_restart_arguments", None, create=True),
            mock.patch.object(sys, "argv", [edge_entrypoint]),
            mock.patch.object(run, "_cleanup_playback_before_restart"),
            mock.patch.object(run, "stop_music_api"),
            mock.patch.object(run, "stop_qq_music_api"),
            mock.patch.object(run.os, "chdir"),
            mock.patch.object(run.os, "execve", side_effect=OSError("exec unavailable")) as execve,
            mock.patch.object(run.subprocess, "Popen") as popen,
            mock.patch.object(run.logging, "shutdown"),
            mock.patch.object(run.os, "_exit"),
        ):
            run._configure_restart_entrypoint(edge_entrypoint)
            run._perform_full_restart(("bot_loop:stale",))
            command = [run.PYTHON_EXECUTABLE, edge_entrypoint]
            self.assertEqual(command, execve.call_args.args[1])
            self.assertEqual(command, popen.call_args.args[0])
            self.assertEqual(run.APP_DIR, popen.call_args.kwargs["cwd"])

    def test_restart_budget_is_bounded_and_carried_in_environment(self):
        base = {
            "WATCHDOG_RESTART_WINDOW": "900",
            "WATCHDOG_MAX_RESTARTS": "1",
        }
        with mock.patch.dict(os.environ, base, clear=True):
            prepared = run._prepare_restart_environment(now=1000)
        self.assertIsNotNone(prepared)
        environment, delay, count, maximum = prepared
        self.assertEqual((0.0, 1, 1), (delay, count, maximum))
        self.assertEqual("1", environment["KOOK_WATCHDOG_RESTART_COUNT"])
        self.assertEqual(run.APP_DIR, environment["KOOK_MUSIC_APP_DIR"])

        exhausted = dict(base)
        exhausted.update(
            {
                "KOOK_WATCHDOG_WINDOW_START": "1000",
                "KOOK_WATCHDOG_RESTART_COUNT": "1",
            }
        )
        with mock.patch.dict(os.environ, exhausted, clear=True):
            self.assertIsNone(run._prepare_restart_environment(now=1001))

    def test_importing_run_does_not_start_services_or_watchdog(self):
        self.assertIsNone(run._music_api_process)
        self.assertIsNone(run._qq_music_api_process)
        self.assertIsNone(run._watchdog)

    def test_debug_endpoint_uses_runtime_health_snapshot(self):
        self.assertFalse(hasattr(windows_app, "app"))
        with tempfile.TemporaryDirectory() as tempdir:
            database = str(Path(tempdir) / "auth.db")
            credential = str(Path(tempdir) / "bootstrap-admin.json")
            with mock.patch.dict(
                os.environ,
                {
                    "AUTH_DATABASE_PATH": database,
                    "INITIAL_ADMIN_CREDENTIAL_PATH": credential,
                },
            ):
                application = windows_app.create_app(start_bot=False)
                client = application.test_client()
                self.assertEqual(200, client.get("/healthz").status_code)
                self.assertEqual(401, client.get("/api/debug").status_code)
                with application.test_request_context("/api/debug"):
                    response = windows_app.debug()
                    payload = response.get_json()
                    self.assertEqual("success", payload["status"])
                    self.assertIn("bot_state", payload)
                    self.assertIn("kook_gateway_heartbeat_age", payload)

    def test_all_api_routes_are_guarded_and_health_has_security_headers(self):
        with tempfile.TemporaryDirectory() as tempdir:
            database = str(Path(tempdir) / "auth.db")
            credential = str(Path(tempdir) / "bootstrap-admin.json")
            with mock.patch.dict(
                os.environ,
                {
                    "AUTH_DATABASE_PATH": database,
                    "INITIAL_ADMIN_CREDENTIAL_PATH": credential,
                },
            ):
                application = windows_app.create_app(start_bot=False)
                client = application.test_client()

                health = client.get("/healthz")
                self.assertEqual(200, health.status_code)
                self.assertIn("no-store", health.headers.get("Cache-Control", ""))
                self.assertIn("default-src 'self'", health.headers.get("Content-Security-Policy", ""))

                for rule in application.url_map.iter_rules():
                    if not rule.rule.startswith("/api/"):
                        continue
                    methods = rule.methods - {"HEAD", "OPTIONS"}
                    method = "GET" if "GET" in methods else sorted(methods)[0]
                    with self.subTest(route=rule.rule, method=method):
                        response = client.open(rule.rule, method=method, json={})
                        expected = 400 if rule.rule == "/api/auth/wechat/login" and method == "POST" else 401
                        self.assertEqual(expected, response.status_code)
                        self.assertIn("no-store", response.headers.get("Cache-Control", ""))

    def test_dependency_repair_requires_two_consecutive_failures(self):
        counters = {}
        last_repairs = {}
        failures = ("netease_api:http_unresponsive",)
        with (
            mock.patch.object(run, "stop_music_api") as stop,
            mock.patch.object(run, "start_music_api") as start,
        ):
            run._repair_dependencies(
                failures, counters, last_repairs, cooldown=60
            )
            stop.assert_not_called()
            start.assert_not_called()

            run._repair_dependencies(
                failures, counters, last_repairs, cooldown=60
            )
            stop.assert_called_once_with()
            start.assert_called_once_with()

    def test_api_startup_probes_do_not_call_upstream_routes(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            (root / "dist").mkdir()
            (root / "package.json").write_text("{}", encoding="utf-8")
            (root / "dist" / "app.js").touch()
            for starter in (run.start_music_api, run.start_qq_music_api):
                process = mock.Mock()
                process.poll.return_value = None
                process.pid = 12345
                with (
                    mock.patch.object(run, "_music_api_process", None),
                    mock.patch.object(run, "_qq_music_api_process", None),
                    mock.patch.object(run, "_api_dir", return_value=tempdir),
                    mock.patch.object(run, "_qq_api_dir", return_value=tempdir),
                    mock.patch.object(run, "_system_node_environment", return_value={}),
                    mock.patch.object(run, "_system_node_modules", return_value=tempdir),
                    mock.patch.object(run, "_kill_port"),
                    mock.patch.object(run, "_open_private_log"),
                    mock.patch.object(run.subprocess, "Popen", return_value=process),
                    mock.patch.object(run.time, "sleep"),
                    mock.patch.object(run.requests, "get", return_value=mock.Mock(status_code=200)) as get,
                ):
                    starter()
                    self.assertEqual(1, get.call_count)
                    url = get.call_args.args[0]
                    self.assertTrue(url.startswith("http://127.0.0.1:"))
                    self.assertEqual("/", urlsplit(url).path)

    def test_dependency_probes_use_local_static_pages(self):
        process = mock.Mock()
        process.poll.return_value = None
        with (
            mock.patch.object(run, "_music_api_process", process),
            mock.patch.object(run, "_qq_music_api_process", process),
            mock.patch.object(run, "_api_dir", return_value=run.APP_DIR),
            mock.patch.object(run, "_qq_api_dir", return_value=run.APP_DIR),
            mock.patch.object(run.requests, "get", return_value=mock.Mock(status_code=200)) as get,
        ):
            self.assertEqual((), run._dependency_failures())
        paths = [urlsplit(call.args[0]).path for call in get.call_args_list]
        self.assertEqual(["/", "/", "/healthz"], paths)

    def test_failed_api_repairs_never_clear_playback_or_restart_bot(self):
        clock = FakeClock()
        health = RuntimeHealth(clock)
        health.mark_supervisor_ready()
        clock.advance(181)
        iterations = 0

        def next_tick(_delay):
            nonlocal iterations
            iterations += 1
            if iterations > 6:
                raise InterruptedError("end watchdog test")
            clock.advance(20)
            health.mark_loop_heartbeat()
            health.mark_gateway_activity()

        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(run, "runtime_health", health),
            mock.patch.object(run, "_dependency_failures", return_value=("qq_music_api:http_unresponsive",)),
            mock.patch.object(run, "stop_qq_music_api") as stop,
            mock.patch.object(run, "start_qq_music_api", side_effect=RuntimeError("still down")) as start,
            mock.patch.object(run, "_cleanup_playback_before_restart") as cleanup,
            mock.patch.object(run, "_perform_full_restart") as restart,
            mock.patch.object(run.time, "sleep", side_effect=next_tick),
            mock.patch.object(run.time, "monotonic", side_effect=clock),
        ):
            with self.assertRaises(InterruptedError):
                run._watchdog_thread()
        self.assertGreaterEqual(stop.call_count, 1)
        self.assertGreaterEqual(start.call_count, 1)
        restart.assert_not_called()
        cleanup.assert_not_called()

    def test_exec_failure_falls_back_with_absolute_command_and_cwd(self):
        environment = {
            "WATCHDOG_RESTART_WINDOW": "900",
            "WATCHDOG_MAX_RESTARTS": "3",
        }
        run._restart_in_progress.clear()
        with (
            mock.patch.dict(os.environ, environment, clear=True),
            mock.patch.object(run, "_cleanup_playback_before_restart"),
            mock.patch.object(run, "stop_music_api"),
            mock.patch.object(run, "stop_qq_music_api"),
            mock.patch.object(run.os, "chdir") as chdir,
            mock.patch.object(
                run.os, "execve", side_effect=OSError("exec unavailable")
            ),
            mock.patch.object(run.subprocess, "Popen") as popen,
            mock.patch.object(run.logging, "shutdown"),
            mock.patch.object(run.os, "_exit"),
        ):
            run._perform_full_restart(("bot_loop:stale",))

        command = run._build_restart_command()
        chdir.assert_called_once_with(run.APP_DIR)
        popen.assert_called_once()
        call = popen.call_args
        self.assertEqual(command, call.args[0])
        self.assertEqual(run.APP_DIR, call.kwargs["cwd"])
        self.assertTrue(os.path.isabs(call.args[0][0]))
        self.assertTrue(os.path.isabs(call.args[0][1]))


if __name__ == "__main__":
    unittest.main()
