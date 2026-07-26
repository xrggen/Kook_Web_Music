#!/usr/bin/env python3
import os
import sys
import logging
import subprocess
import signal
import atexit
import time
import threading
import shutil
import asyncio
import requests
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv

try:
    import psutil
except ImportError:
    psutil = None

try:
    from .runtime_health import runtime_health
    from .service_watchdog import WatchdogConfig, WatchdogEvaluator
except ImportError:
    from runtime_health import runtime_health
    from service_watchdog import WatchdogConfig, WatchdogEvaluator

APP_DIR = os.path.dirname(os.path.realpath(__file__))
RUN_SCRIPT = os.path.realpath(__file__)
ENV_FILE = os.path.join(APP_DIR, ".env")
PYTHON_EXECUTABLE = os.path.realpath(sys.executable)


def _resolve_executable(name):
    resolved = shutil.which(name)
    return os.path.realpath(resolved) if resolved else None


NODE_EXECUTABLE = _resolve_executable("node")
NPM_EXECUTABLE = _resolve_executable("npm")

# 配置基础日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)
_log_path = os.path.join(APP_DIR, "debug.log")
if not any(
    isinstance(handler, logging.FileHandler)
    and os.path.abspath(getattr(handler, "baseFilename", "")) == _log_path
    for handler in logging.getLogger().handlers
):
    _file_handler = RotatingFileHandler(
        _log_path,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    _file_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")
    )
    logging.getLogger().addHandler(_file_handler)

# 只关闭Flask的HTTP访问日志，保留其他日志
logging.getLogger('werkzeug').setLevel(logging.ERROR)

# 全局进程引用
_music_api_process = None
_qq_music_api_process = None


def _process_belongs_to_dir(pid: int, expected_dir: str) -> bool:
    """仅允许清理工作目录与目标 API 目录一致的进程。"""
    if psutil is None:
        logger.warning(
            "[端口清理] 未安装 psutil，无法验证 PID=%s 的归属，跳过清理",
            pid,
        )
        return False
    try:
        process_dir = os.path.normcase(os.path.realpath(psutil.Process(pid).cwd()))
        expected = os.path.normcase(os.path.realpath(expected_dir))
        return process_dir == expected
    except (psutil.Error, OSError) as exc:
        logger.warning("[端口清理] 无法验证 PID=%s 的归属: %s", pid, exc)
        return False


def _kill_port(port: int, expected_dir: str):
    """终止指定 API 目录中占用端口的残留进程（仅 Windows）。"""
    try:
        out = subprocess.check_output(
            ['netstat', '-ano'],
            text=True,
            timeout=5,
            errors='replace',
        )
        pids = set()
        for line in out.splitlines():
            parts = line.strip().split()
            if len(parts) < 4 or parts[0].upper() not in ('TCP', 'UDP'):
                continue
            local_address = parts[1]
            if local_address.rsplit(':', 1)[-1] != str(port):
                continue
            pid = parts[-1]
            if pid.isdigit() and pid != '0':
                pids.add(int(pid))
        for pid in pids:
            if not _process_belongs_to_dir(pid, expected_dir):
                logger.warning(
                    "[端口清理] 端口 %d 被非本项目进程占用，拒绝终止 PID=%s",
                    port,
                    pid,
                )
                continue
            result = subprocess.run(
                ['taskkill', '/F', '/PID', str(pid)],
                capture_output=True, timeout=5,
            )
            if result.returncode == 0:
                logger.info("[端口清理] 已终止端口 %d 上的进程 PID=%s", port, pid)
            else:
                logger.warning(
                    "[端口清理] 终止 PID=%s 失败（returncode=%s）",
                    pid,
                    result.returncode,
                )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("[端口清理] 检查端口 %d 失败: %s", port, exc)


def _terminate_process_tree(process, label):
    """先请求进程组退出，再回收仍存活的根进程和后代进程。"""
    if process is None:
        return

    descendants = []
    if psutil is not None:
        try:
            descendants = psutil.Process(process.pid).children(recursive=True)
        except (psutil.Error, OSError):
            descendants = []

    if process.poll() is None:
        try:
            if sys.platform == "win32":
                process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            process.wait(timeout=5)
        except Exception:
            try:
                process.kill()
                process.wait(timeout=3)
            except Exception:
                logger.warning("[%s] 根进程 PID=%s 未能确认退出", label, process.pid)

    if descendants and psutil is not None:
        for child in descendants:
            try:
                if child.is_running():
                    child.terminate()
            except (psutil.Error, OSError):
                pass
        _, alive = psutil.wait_procs(descendants, timeout=2)
        for child in alive:
            try:
                child.kill()
            except (psutil.Error, OSError):
                pass


def _api_dir():
    return os.path.realpath(
        os.path.join(
            APP_DIR, "NeteaseCloudMusicApi", "NeteaseCloudMusicApiBackup-main"
        )
    )


def _qq_api_dir():
    return os.path.realpath(os.path.join(APP_DIR, "qq-music-api"))


def start_music_api():
    """启动本地网易云音乐API服务"""
    global _music_api_process
    api_dir = _api_dir()
    if not os.path.isdir(api_dir):
        logger.warning("本地音乐API目录不存在，跳过启动: %s", api_dir)
        logger.warning("音乐API将使用 .env 中配置的 MUSIC_API_BASE")
        return
    if NODE_EXECUTABLE is None:
        logger.error("[API启动] 未在 PATH 中找到 node.exe，无法启动本地音乐API")
        return

    # 清理占用本服务端口的残留进程（Windows），避免误杀其他Node应用
    if sys.platform == "win32":
        _kill_port(3000, api_dir)

    logger.info("正在启动本地音乐API服务: %s", api_dir)
    api_log = os.path.join(api_dir, "api_output.log")
    log_file = open(api_log, "w")

    # 构造子进程环境变量：强制 PORT=3000 避免继承 .env 中的 PORT=5000
    child_env = os.environ.copy()
    child_env["PORT"] = "3000"

    logger.info("[API启动] 拉起 Node 进程 (PORT=3000)...")
    if sys.platform == "win32":
        _music_api_process = subprocess.Popen(
            [NODE_EXECUTABLE, os.path.join(api_dir, "app.js")],
            cwd=api_dir,
            env=child_env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    else:
        _music_api_process = subprocess.Popen(
            [NODE_EXECUTABLE, os.path.join(api_dir, "app.js")],
            cwd=api_dir,
            env=child_env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid,
        )
    logger.info("[API启动] PID=%d", _music_api_process.pid)

    # 检查进程是否立即退出
    time.sleep(1.5)
    if _music_api_process.poll() is not None:
        log_file.close()
        logger.error("[API启动] 进程立即退出 (exit code=%d)", _music_api_process.returncode)
        logger.error("[API启动] 请检查: %s", api_log)
        try:
            with open(api_log, "r") as f:
                tail = f.read()
            if tail:
                for line in tail.strip().split("\n")[-5:]:
                    logger.error("[API启动] %s", line)
        except Exception:
            pass
        _music_api_process = None
        logger.warning("[API启动] 回退使用 MUSIC_API_BASE 配置的地址")
        return

    # 轮询等待API就绪（最多10次，每次间隔1秒，请求超时2秒）
    logger.info("[API启动] 等待服务就绪...")
    ready = False
    for i in range(10):
        if _music_api_process.poll() is not None:
            log_file.close()
            logger.error("[API启动] 进程意外退出 (exit code=%d)", _music_api_process.returncode)
            _music_api_process = None
            return
        try:
            r = requests.get("http://localhost:3000/login/status", timeout=(2, 2))
            if r.status_code == 200:
                ready = True
                logger.info("[API启动] 服务已就绪 (等待 %ds)", i + 2)
                break
        except Exception:
            pass
        time.sleep(1)

    if ready:
        logger.info("[API启动] 完成 PID=%d", _music_api_process.pid)
    else:
        logger.warning("[API启动] 10秒内未就绪，继续运行（后续API调用将自动重试）")
    log_file.close()


def stop_music_api():
    """停止本地音乐API服务"""
    global _music_api_process
    p = _music_api_process
    if p is None:
        return
    logger.info("正在停止本地音乐API服务...")
    _terminate_process_tree(p, "本地音乐API")
    _music_api_process = None
    logger.info("本地音乐API服务已停止")


def start_qq_music_api():
    """启动本地QQ音乐API服务"""
    global _qq_music_api_process
    api_dir = _qq_api_dir()
    if not os.path.isdir(api_dir):
        logger.warning("QQ音乐API目录不存在，跳过启动: %s", api_dir)
        return
    if not os.path.isfile(os.path.join(api_dir, "package.json")):
        logger.warning("QQ音乐API缺少package.json，可能未安装依赖")
        return
    if NODE_EXECUTABLE is None:
        logger.error("[QQ-API启动] 未在 PATH 中找到 node.exe，无法启动QQ音乐API")
        return
    if sys.platform == "win32":
        _kill_port(3200, api_dir)

    logger.info("正在启动QQ音乐API服务: %s", api_dir)
    api_log = os.path.join(api_dir, "api_output.log")
    log_file = open(api_log, "w")

    child_env = os.environ.copy()
    child_env["PORT"] = "3200"

    dist_main = os.path.join(api_dir, "dist", "app.js")
    if not os.path.isfile(dist_main):
        logger.info("[QQ-API启动] 未找到编译产物，执行 npm run build...")
        if NPM_EXECUTABLE is None:
            logger.error("[QQ-API启动] 未在 PATH 中找到 npm，无法构建QQ音乐API")
            log_file.close()
            return
        try:
            build_result = subprocess.run(
                [NPM_EXECUTABLE, "run", "build"],
                cwd=api_dir,
                env=child_env,
                capture_output=True,
                timeout=60,
            )
            if build_result.returncode != 0:
                stderr_tail = build_result.stderr.decode("utf-8", errors="replace")[-300:]
                logger.error("[QQ-API启动] 编译失败: %s", stderr_tail)
                log_file.close()
                return
        except Exception as e:
            logger.error("[QQ-API启动] 编译异常: %s", e)
            log_file.close()
            return
    cmd = [NODE_EXECUTABLE, os.path.realpath(dist_main)]

    logger.info("[QQ-API启动] 拉起 Node 进程 (PORT=3200)...")
    if sys.platform == "win32":
        _qq_music_api_process = subprocess.Popen(
            cmd,
            cwd=api_dir,
            env=child_env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    else:
        _qq_music_api_process = subprocess.Popen(
            cmd,
            cwd=api_dir,
            env=child_env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid,
        )
    logger.info("[QQ-API启动] PID=%d", _qq_music_api_process.pid)

    time.sleep(1.5)
    if _qq_music_api_process.poll() is not None:
        log_file.close()
        logger.error("[QQ-API启动] 进程立即退出 (exit code=%d)", _qq_music_api_process.returncode)
        logger.error("[QQ-API启动] 请检查: %s", api_log)
        try:
            with open(api_log, "r") as f:
                tail = f.read()
            if tail:
                for line in tail.strip().split("\n")[-5:]:
                    logger.error("[QQ-API启动] %s", line)
        except Exception:
            pass
        _qq_music_api_process = None
        return

    logger.info("[QQ-API启动] 等待服务就绪...")
    ready = False
    for i in range(10):
        if _qq_music_api_process.poll() is not None:
            log_file.close()
            logger.error("[QQ-API启动] 进程意外退出 (exit code=%d)", _qq_music_api_process.returncode)
            _qq_music_api_process = None
            return
        try:
            r = requests.get("http://localhost:3200/getSearchByKey/test", timeout=(2, 2))
            if r.status_code in (200, 400, 502):
                ready = True
                logger.info("[QQ-API启动] 服务已就绪 (等待 %ds)", i + 2)
                break
        except Exception:
            pass
        time.sleep(1)

    if ready:
        logger.info("[QQ-API启动] 完成 PID=%d", _qq_music_api_process.pid)
    else:
        logger.warning("[QQ-API启动] 10秒内未就绪，继续运行")
    log_file.close()


def stop_qq_music_api():
    """停止本地QQ音乐API服务"""
    global _qq_music_api_process
    p = _qq_music_api_process
    if p is None:
        return
    logger.info("正在停止QQ音乐API服务...")
    _terminate_process_tree(p, "QQ音乐API")
    _qq_music_api_process = None
    logger.info("QQ音乐API服务已停止")


def _env_float(name, default, minimum=0.0):
    try:
        return max(minimum, float(os.getenv(name, default)))
    except (TypeError, ValueError):
        logger.warning("[看门狗] %s 配置无效，使用默认值 %s", name, default)
        return float(default)


def _env_int(name, default, minimum=1):
    try:
        return max(minimum, int(os.getenv(name, default)))
    except (TypeError, ValueError):
        logger.warning("[看门狗] %s 配置无效，使用默认值 %s", name, default)
        return int(default)


def _probe_url(url):
    try:
        requests.get(url, timeout=(1.5, 2.5))
        return True
    except requests.RequestException:
        return False


def _web_probe_url():
    host = os.getenv("HOST", "0.0.0.0").strip()
    if host in {"", "0.0.0.0", "::", "[::]"}:
        host = "127.0.0.1"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = _env_int("PORT", 5000)
    return f"http://{host}:{port}/api/debug"


def _dependency_failures():
    failures = []
    services = (
        (
            "netease_api",
            _api_dir(),
            _music_api_process,
            "http://127.0.0.1:3000/login/status",
        ),
        (
            "qq_music_api",
            _qq_api_dir(),
            _qq_music_api_process,
            "http://127.0.0.1:3200/",
        ),
    )
    for name, service_dir, process, url in services:
        if not os.path.isdir(service_dir):
            continue
        if process is None or process.poll() is not None:
            failures.append(f"{name}:process_not_running")
        elif not _probe_url(url):
            failures.append(f"{name}:http_unresponsive")

    if not _probe_url(_web_probe_url()):
        failures.append("web:http_unresponsive")
    return tuple(failures)


def _repair_dependencies(failures, counters, last_repairs, cooldown):
    failed_services = {reason.split(":", 1)[0] for reason in failures}
    for service in ("netease_api", "qq_music_api"):
        if service not in failed_services:
            counters.pop(service, None)
            continue
        counters[service] = counters.get(service, 0) + 1
        if counters[service] < 2:
            continue
        now = time.monotonic()
        if now - last_repairs.get(service, float("-inf")) < cooldown:
            continue
        last_repairs[service] = now
        logger.warning("[看门狗] 尝试单独恢复外部组件: %s", service)
        try:
            if service == "netease_api":
                stop_music_api()
                start_music_api()
            else:
                stop_qq_music_api()
                start_qq_music_api()
        except Exception:
            logger.exception("[看门狗] 单独恢复 %s 失败", service)


def _build_restart_command():
    """返回与当前工作目录无关的确定性重启命令。"""
    return [PYTHON_EXECUTABLE, RUN_SCRIPT, *sys.argv[1:]]


def _prepare_restart_environment(now=None):
    """应用时间窗重启预算，防止不可恢复故障形成无限重启风暴。"""
    now = time.time() if now is None else float(now)
    window = _env_float("WATCHDOG_RESTART_WINDOW", 900.0, 60.0)
    maximum = _env_int("WATCHDOG_MAX_RESTARTS", 3)
    try:
        window_started = float(os.getenv("KOOK_WATCHDOG_WINDOW_START", now))
        restart_count = int(os.getenv("KOOK_WATCHDOG_RESTART_COUNT", "0"))
    except (TypeError, ValueError):
        window_started = now
        restart_count = 0

    if now < window_started or now - window_started >= window:
        window_started = now
        restart_count = 0
    if restart_count >= maximum:
        return None

    restart_count += 1
    delays = (0.0, 30.0, 120.0)
    delay = delays[min(restart_count - 1, len(delays) - 1)]
    environment = os.environ.copy()
    environment["KOOK_WATCHDOG_WINDOW_START"] = str(window_started)
    environment["KOOK_WATCHDOG_RESTART_COUNT"] = str(restart_count)
    environment["KOOK_MUSIC_APP_DIR"] = APP_DIR
    return environment, delay, restart_count, maximum


def _cleanup_playback_before_restart(timeout=20.0):
    """在独立线程执行播放恢复，避免卡住的状态锁阻断整个重启。"""
    app_module = sys.modules.get("app") or sys.modules.get("windows.app")
    recovery = getattr(app_module, "_perform_playback_recovery", None)
    if recovery is None:
        return

    def _runner():
        try:
            asyncio.run(recovery())
        except Exception:
            logger.exception("[看门狗] 重启前清理播放会话失败")

    worker = threading.Thread(
        target=_runner,
        name="watchdog-playback-cleanup",
        daemon=True,
    )
    worker.start()
    worker.join(timeout=timeout)
    if worker.is_alive():
        logger.error("[看门狗] 播放会话清理超时，继续执行进程重启")


_restart_in_progress = threading.Event()


def _perform_full_restart(reasons):
    if _restart_in_progress.is_set():
        return "in_progress"

    restart_plan = _prepare_restart_environment()
    if restart_plan is None:
        logger.critical(
            "[看门狗] 已耗尽重启预算，停止自动重启；请检查 debug.log 后人工处理"
        )
        return "budget_exhausted"

    _restart_in_progress.set()
    environment, delay, restart_count, maximum = restart_plan
    logger.critical(
        "[看门狗] 将执行第 %d/%d 次完整重启，原因=%s，延迟=%.0fs",
        restart_count,
        maximum,
        ", ".join(reasons),
        delay,
    )
    if delay:
        time.sleep(delay)

    _cleanup_playback_before_restart()
    stop_music_api()
    stop_qq_music_api()

    command = _build_restart_command()
    logger.critical(
        "[看门狗] 重启命令=%s；工作目录=%s",
        command,
        APP_DIR,
    )
    for handler in logging.getLogger().handlers:
        try:
            handler.flush()
        except Exception:
            pass

    os.chdir(APP_DIR)
    try:
        os.execve(PYTHON_EXECUTABLE, command, environment)
    except Exception as exec_error:
        logger.exception("[看门狗] 原位重启失败，尝试启动替代进程: %s", exec_error)
        try:
            creation_flags = (
                subprocess.CREATE_NEW_PROCESS_GROUP
                if sys.platform == "win32"
                else 0
            )
            subprocess.Popen(
                command,
                cwd=APP_DIR,
                env=environment,
                creationflags=creation_flags,
                close_fds=True,
            )
        except Exception:
            logger.critical("[看门狗] 替代进程启动失败", exc_info=True)
            _restart_in_progress.clear()
            return "failed"
        logging.shutdown()
        os._exit(0)


def _watchdog_thread():
    config = WatchdogConfig(
        startup_grace=_env_float("WATCHDOG_STARTUP_GRACE", 180.0, 30.0),
        loop_timeout=_env_float("WATCHDOG_LOOP_TIMEOUT", 90.0, 30.0),
        gateway_timeout=_env_float("WATCHDOG_GATEWAY_TIMEOUT", 90.0, 30.0),
        failures_before_restart=_env_int("WATCHDOG_FAILURES", 3),
    )
    evaluator = WatchdogEvaluator(config)
    interval = _env_float("WATCHDOG_INTERVAL", 15.0, 5.0)
    repair_cooldown = _env_float("WATCHDOG_REPAIR_COOLDOWN", 60.0, 15.0)
    dependency_counters = {}
    last_repairs = {}
    previous_signature = None

    while True:
        time.sleep(interval)
        failures = _dependency_failures()
        decision = evaluator.evaluate(runtime_health.snapshot(), failures)
        if decision.phase not in {"starting", "startup_grace"}:
            _repair_dependencies(
                failures,
                dependency_counters,
                last_repairs,
                repair_cooldown,
            )

        signature = (
            decision.phase,
            decision.reasons,
            decision.consecutive_failures,
            decision.restart_blocked,
        )
        if decision.phase == "unhealthy" and signature != previous_signature:
            logger.warning(
                "[看门狗] 健康检查失败（连续 %d/%d）: %s",
                decision.consecutive_failures,
                config.failures_before_restart,
                ", ".join(decision.reasons),
            )
        if decision.restart_blocked and signature != previous_signature:
            logger.error("[看门狗] 配置错误不执行自动重启，请人工修正配置")
        previous_signature = signature

        if decision.should_restart:
            result = _perform_full_restart(decision.reasons)
            if result == "budget_exhausted":
                return


_watchdog = None
_watchdog_lock = threading.Lock()


def _start_watchdog_once():
    global _watchdog
    with _watchdog_lock:
        if _watchdog is not None and _watchdog.is_alive():
            return _watchdog
        _watchdog = threading.Thread(
            target=_watchdog_thread,
            name="service-watchdog",
            daemon=True,
        )
        _watchdog.start()
        return _watchdog


_shutdown_hooks_installed = False


def _signal_handler(signum, frame):
    stop_music_api()
    stop_qq_music_api()
    raise SystemExit(0)


def _install_shutdown_hooks():
    global _shutdown_hooks_installed
    if _shutdown_hooks_installed:
        return
    atexit.register(stop_music_api)
    atexit.register(stop_qq_music_api)
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)
    _shutdown_hooks_installed = True


def main():
    # 固定工作目录，并显式加载 windows/.env。后续所有相对配置仍会由
    # config.py 再次按 APP_DIR 解析，重启和手工启动的行为保持一致。
    os.chdir(APP_DIR)
    logger.info("正在加载环境变量: %s", ENV_FILE)
    load_dotenv(dotenv_path=ENV_FILE, override=False)
    _install_shutdown_hooks()

    start_music_api()
    start_qq_music_api()

    logger.info("正在初始化应用...")
    try:
        from .app import create_app
    except ImportError:
        from app import create_app
    application = create_app()
    runtime_health.mark_supervisor_ready()
    _start_watchdog_once()

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("DEBUG", "False").lower() in ("true", "1", "t")
    logger.info("启动服务器: http://%s:%d [DEBUG: %s]", host, port, debug)
    application.run(
        host=host,
        port=port,
        debug=debug,
        use_reloader=False,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        logger.critical("启动失败: %s", error, exc_info=True)
        sys.exit(1)
