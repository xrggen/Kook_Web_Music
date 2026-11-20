import os
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from edge import agent, run as edge_run


class EdgeStartupTests(unittest.TestCase):
    def test_startup_registers_edge_restart_before_starting_watchdog(self):
        platform_dir = ROOT / "windows"
        calls = mock.Mock()
        platform_run = types.ModuleType("run")
        for name in (
            "_configure_restart_entrypoint", "_install_shutdown_hooks",
            "start_music_api", "start_qq_music_api", "_start_watchdog_once",
        ):
            method = mock.Mock()
            setattr(platform_run, name, method)
            calls.attach_mock(method, name)
        application = mock.Mock()
        application.jinja_env.globals = {}
        application.extensions = {}
        app_module = types.ModuleType("app")
        app_module.create_app = mock.Mock(return_value=application)
        health_module = types.ModuleType("runtime_health")
        health_module.runtime_health = mock.Mock()
        modules = {"run": platform_run, "app": app_module, "runtime_health": health_module}

        with (
            mock.patch.dict(os.environ, {"PORT": "18473"}, clear=True),
            mock.patch.dict(sys.modules, modules),
            mock.patch.object(sys, "path", sys.path.copy()),
            mock.patch.object(edge_run, "_platform_dir", return_value=platform_dir),
            mock.patch.object(edge_run, "_load_configuration"),
            mock.patch.object(edge_run.os, "chdir"),
            mock.patch.object(agent, "EdgeAgentSupervisor") as supervisor_class,
            mock.patch("edge.config_store.EdgeConfigStore"),
            mock.patch("edge.secret_store.EdgeSecretStore"),
            mock.patch("edge.management.register_edge_management"),
        ):
            edge_run.main()

        platform_run._configure_restart_entrypoint.assert_called_once_with(
            edge_run.EDGE_DIR / "run.py"
        )
        self.assertLess(
            calls.mock_calls.index(mock.call._configure_restart_entrypoint(edge_run.EDGE_DIR / "run.py")),
            calls.mock_calls.index(mock.call._start_watchdog_once()),
        )
        self.assertEqual("edge", application.jinja_env.globals["deployment_role"])
        supervisor_class.return_value.start.assert_called_once_with()
        application.run.assert_called_once_with(
            host="127.0.0.1", port=18473, debug=False, use_reloader=False, threaded=True
        )


if __name__ == "__main__":
    unittest.main()
