#!/usr/bin/env python3
import os
import sys
import logging
import subprocess
import signal
import atexit
import time
import threading
import requests
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv

try:
    import psutil
except ImportError:
    psutil = None

# 配置基础日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)
_log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug.log")
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


def _api_dir():
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "NeteaseCloudMusicApi", "NeteaseCloudMusicApiBackup-main"
    )


def _qq_api_dir():
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "qq-music-api"
    )


def start_music_api():
    """启动本地网易云音乐API服务"""
    global _music_api_process
    api_dir = _api_dir()
    if not os.path.isdir(api_dir):
        logger.warning("本地音乐API目录不存在，跳过启动: %s", api_dir)
        logger.warning("音乐API将使用 .env 中配置的 MUSIC_API_BASE")
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
            ["node", "app.js"],
            cwd=api_dir,
            env=child_env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    else:
        _music_api_process = subprocess.Popen(
            ["node", "app.js"],
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
    try:
        if sys.platform == "win32":
            p.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            os.killpg(os.getpgid(p.pid), signal.SIGTERM)
        p.wait(timeout=5)
    except Exception:
        try:
            p.kill()
            p.wait(timeout=3)
        except Exception:
            pass
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
        try:
            build_result = subprocess.run(
                ["npm", "run", "build"],
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
    cmd = ["node", dist_main]

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
    try:
        if sys.platform == "win32":
            p.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            os.killpg(os.getpgid(p.pid), signal.SIGTERM)
        p.wait(timeout=5)
    except Exception:
        try:
            p.kill()
            p.wait(timeout=3)
        except Exception:
            pass
    _qq_music_api_process = None
    logger.info("QQ音乐API服务已停止")


# 看门狗只监控 Bot 事件循环；Web 请求使用独立心跳，不能掩盖 Bot 卡死。
HEARTBEAT_FILE = os.path.join(os.path.dirname(__file__), ".bot_heartbeat")


def _watchdog_thread():
    """
    后台看门狗：检测机器人事件循环是否卡死，并尝试自愈恢复。
    心跳由 app.py 中的事件循环任务每30秒更新一次。
    """
    watchdog_started_at = time.time()
    time.sleep(90)  # 启动后等待90秒（bot启动+心跳首写最多30s+余量）
    freeze_count = 0
    while True:
        time.sleep(15)
        try:
            if os.path.exists(HEARTBEAT_FILE):
                with open(HEARTBEAT_FILE, "r") as f:
                    raw = f.read().strip()
                if raw:
                    last_beat = float(raw)
                    elapsed = time.time() - last_beat
                else:
                    elapsed = time.time() - os.path.getmtime(HEARTBEAT_FILE)
            else:
                elapsed = time.time() - watchdog_started_at
        except Exception:
            elapsed = time.time() - watchdog_started_at

        if elapsed > 90:  # 超过90秒无心跳（正常每30s写入一次+60s容错）
            freeze_count += 1
            logger.warning("[看门狗] 事件循环无心跳 %ds (第 %d 次)", elapsed, freeze_count)

            if freeze_count >= 3:  # 连续3次 ≈ 135秒
                logger.error("[看门狗] 事件循环可能卡死，尝试自愈...")
                # HTTP 探针只用于记录故障范围；Bot 持续失联仍需重启整个进程。
                port = int(os.getenv("PORT", 5000))
                try:
                    r = requests.get(f"http://localhost:{port}/api/debug", timeout=5)
                    if r.status_code == 200:
                        logger.error("[看门狗] Flask 正常，但 Bot 事件循环已失联")
                except Exception:
                    logger.error("[看门狗] Flask HTTP服务也无响应，进程整体异常")

                logger.critical("[看门狗] 正在执行完整进程重启以恢复 Bot")
                try:
                    stop_music_api()
                except Exception:
                    pass
                try:
                    stop_qq_music_api()
                except Exception:
                    pass
                try:
                    os.execv(sys.executable, [sys.executable, *sys.argv])
                except Exception:
                    logger.exception("[看门狗] 进程重启失败，强制退出交由外部守护器拉起")
                    os._exit(1)
        else:
            freeze_count = 0


_watchdog = threading.Thread(target=_watchdog_thread, daemon=True)
_watchdog.start()

atexit.register(stop_music_api)
atexit.register(stop_qq_music_api)


def _signal_handler(signum, frame):
    stop_music_api()
    stop_qq_music_api()
    sys.exit(0)


signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)

try:
    # 加载环境变量
    logger.info("正在加载环境变量...")
    load_dotenv()

    # 启动本地音乐API
    start_music_api()
    start_qq_music_api()

    logger.info("正在初始化应用...")
    from app import create_app
    app = create_app()

    if __name__ == '__main__':
        host = os.getenv('HOST', '0.0.0.0')
        port = int(os.getenv('PORT', 5000))
        debug = os.getenv('DEBUG', 'False').lower() in ('true', '1', 't')

        logger.info(f"启动服务器: http://{host}:{port} [DEBUG: {debug}]")
        app.run(host=host, port=port, debug=debug, use_reloader=False)

except Exception as e:
    logger.critical(f"启动失败: {str(e)}", exc_info=True)
    sys.exit(1)
