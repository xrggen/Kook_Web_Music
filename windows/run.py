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
import json
import re
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
PROJECT_ROOT = os.path.dirname(APP_DIR)
RUN_SCRIPT = os.path.realpath(__file__)
ENV_FILE = os.path.join(APP_DIR, ".env")
PYTHON_EXECUTABLE = os.path.realpath(sys.executable)
MINIMUM_NODE_MAJOR = 20
NETEASE_NODE_PACKAGE = "NeteaseCloudMusicApi"
NETEASE_NODE_VERSION = "4.25.0"
QQ_NODE_PACKAGE = "@sansenjian/qq-music-api"
QQ_NODE_VERSION = "2.3.1"
NODE_PACKAGE_VERSIONS = {
    NETEASE_NODE_PACKAGE: NETEASE_NODE_VERSION,
    QQ_NODE_PACKAGE: QQ_NODE_VERSION,
}
DEFAULT_WEB_PORT = 18473
DEFAULT_MUSIC_API_PORT = 18474
DEFAULT_QQ_MUSIC_API_PORT = 18475
SYSTEM_NODE_INSTALL_COMMAND = (
    f"npm install --global {NETEASE_NODE_PACKAGE}@{NETEASE_NODE_VERSION} "
    f"{QQ_NODE_PACKAGE}@{QQ_NODE_VERSION}"
)


def _path_is_within(path, parent):
    try:
        resolved_path = os.path.normcase(os.path.realpath(path))
        resolved_parent = os.path.normcase(os.path.realpath(parent))
        return os.path.commonpath((resolved_path, resolved_parent)) == resolved_parent
    except (OSError, ValueError):
        return False


def _resolve_system_executable(name):
    """只接受系统 PATH 中、项目目录之外的可执行文件。"""
    resolved = shutil.which(name)
    if not resolved:
        return None
    resolved = os.path.realpath(resolved)
    return None if _path_is_within(resolved, PROJECT_ROOT) else resolved


class _PrivateRotatingFileHandler(RotatingFileHandler):
    def _open(self):
        stream = super()._open()
        if os.name != "nt":
            try:
                os.chmod(self.baseFilename, 0o600)
            except OSError:
                pass
        return stream


def _open_private_log(path):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        if os.name != "nt":
            os.fchmod(descriptor, 0o600)
        return os.fdopen(descriptor, "w", encoding="utf-8")
    except Exception:
        os.close(descriptor)
        raise


_LOG_QUERY_SECRET_RE = re.compile(
    r"(?i)([?&](?:cookie|set-cookie|token|access[_-]?token|refresh[_-]?token|"
    r"authorization|signature|sign|qrsig|ptqrtoken|sessdata|music[_-]?[ua])=)"
    r"[^&#\s\"']+"
)
_LOG_ASSIGNMENT_SECRET_RE = re.compile(
    r"(?i)((?:cookie|set-cookie|authorization|token|access[_-]?token|"
    r"refresh[_-]?token|signature|qrsig|ptqrtoken|sessdata|music[_-]?[ua])"
    r"\s*[:=]\s*[\"']?)[^\s,;\"']+"
)
_LOG_COOKIE_PAIR_RE = re.compile(
    r"(?i)\b(?:MUSIC_U|MUSIC_A|SESSDATA|qqmusic_key|qm_keyst|"
    r"psrf_qq(?:refresh|access)_(?:token|key)|bili_jct)=[^;\s,\"']+"
)


def _redact_log_text(value, limit=4096):
    """在诊断输出前移除 URL、Cookie 和令牌值。"""
    text = str(value or "").replace("\r", " ").replace("\n", " ")
    text = _LOG_QUERY_SECRET_RE.sub(r"\1<redacted>", text)
    text = _LOG_ASSIGNMENT_SECRET_RE.sub(r"\1<redacted>", text)
    text = _LOG_COOKIE_PAIR_RE.sub(
        lambda match: match.group(0).split("=", 1)[0] + "=<redacted>",
        text,
    )
    return text[:limit]


NODE_EXECUTABLE = _resolve_system_executable("node")
NPM_EXECUTABLE = _resolve_system_executable("npm")

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
    _file_handler = _PrivateRotatingFileHandler(
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
_system_node_modules_cache = None


def _system_node_version():
    if NODE_EXECUTABLE is None:
        return None, None
    try:
        result = subprocess.run(
            [NODE_EXECUTABLE, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        version = result.stdout.strip().lstrip("v")
        return version, int(version.split(".", 1)[0])
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        logger.error("[Node环境] 无法读取系统 Node 版本: %s", type(exc).__name__)
        return None, None


def _system_node_modules():
    """读取系统 npm 的全局模块根，拒绝落在项目目录内的伪全局环境。"""
    global _system_node_modules_cache
    if _system_node_modules_cache is not None:
        return _system_node_modules_cache or None
    if NPM_EXECUTABLE is None:
        logger.error("[Node环境] 未在系统 PATH 中找到 npm")
        _system_node_modules_cache = ""
        return None
    try:
        result = subprocess.run(
            [NPM_EXECUTABLE, "root", "--global"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        module_root = os.path.realpath(result.stdout.strip())
    except (OSError, subprocess.SubprocessError) as exc:
        logger.error("[Node环境] 无法读取系统 npm 全局模块目录: %s", type(exc).__name__)
        _system_node_modules_cache = ""
        return None
    if not module_root or _path_is_within(module_root, PROJECT_ROOT):
        logger.error("[Node环境] npm 全局模块目录不得位于项目内: %s", module_root)
        _system_node_modules_cache = ""
        return None
    _system_node_modules_cache = module_root
    return module_root


def _system_package_dir(package_name):
    module_root = _system_node_modules()
    if not module_root:
        return ""
    return os.path.realpath(os.path.join(module_root, *package_name.split("/")))


def _project_node_modules():
    """查找项目内遗留的 Node 依赖目录。"""
    for current, directories, _ in os.walk(PROJECT_ROOT):
        directories[:] = [
            name for name in directories if name not in {".git", "__pycache__"}
        ]
        if "node_modules" in directories:
            return os.path.join(current, "node_modules")
    return None


def _system_node_path():
    """构造只暴露系统 Node/npm、过滤项目本地工具链的 PATH。"""
    entries = [os.path.dirname(NODE_EXECUTABLE), os.path.dirname(NPM_EXECUTABLE)]
    entries.extend(os.environ.get("PATH", "").split(os.pathsep))
    result = []
    seen = set()
    for entry in entries:
        if not entry:
            continue
        resolved = os.path.normcase(os.path.realpath(entry))
        if _path_is_within(resolved, PROJECT_ROOT):
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        result.append(entry)
    return os.pathsep.join(result)


def _system_node_environment(api_dir, port, package_name):
    """返回所有 Node 服务共用的系统全局运行环境。"""
    if NODE_EXECUTABLE is None:
        logger.error(
            "[Node环境] 未在系统 PATH 中找到项目目录外的 node，无法启动 Node 服务"
        )
        return None

    version, major = _system_node_version()
    if major is None or major < MINIMUM_NODE_MAJOR:
        logger.error(
            "[Node环境] 需要系统 Node.js %d+，当前版本=%s",
            MINIMUM_NODE_MAJOR,
            version or "未知",
        )
        return None
    module_root = _system_node_modules()
    if not module_root:
        return None
    local_modules = _project_node_modules()
    if local_modules:
        logger.error(
            "[Node环境] 检测到项目内自带 Node 环境: %s；请清理后重试",
            local_modules,
        )
        return None
    if not os.path.isfile(os.path.join(api_dir, "package.json")):
        logger.error(
            "[Node环境] 系统全局包 %s 未安装；请执行: %s",
            package_name,
            SYSTEM_NODE_INSTALL_COMMAND,
        )
        return None
    try:
        with open(os.path.join(api_dir, "package.json"), "r", encoding="utf-8") as package_file:
            installed_version = str(json.load(package_file).get("version", "")).strip()
    except (OSError, ValueError, TypeError) as error:
        logger.error(
            "[Node环境] 无法读取系统全局包 %s 的版本: %s",
            package_name,
            type(error).__name__,
        )
        return None
    expected_version = NODE_PACKAGE_VERSIONS.get(package_name)
    if expected_version and installed_version != expected_version:
        logger.error(
            "[Node环境] 系统全局包 %s 版本不匹配：需要 %s，当前 %s；请执行: %s",
            package_name,
            expected_version,
            installed_version or "未知",
            SYSTEM_NODE_INSTALL_COMMAND,
        )
        return None

    child_env = os.environ.copy()
    child_env["PORT"] = str(port)
    child_env["HOST"] = "127.0.0.1"
    child_env["PATH"] = _system_node_path()
    child_env["NODE"] = NODE_EXECUTABLE
    child_env["NODE_PATH"] = module_root
    child_env["KOOK_NODE_RUNTIME"] = "system"
    child_env["KOOK_NODE_MODULES"] = module_root
    child_env.pop("npm_execpath", None)
    child_env.pop("npm_node_execpath", None)
    return child_env


def _env_port(name, default):
    try:
        value = int(os.getenv(name, default))
    except (TypeError, ValueError):
        logger.warning("[端口] %s 配置无效，使用默认值 %d", name, default)
        return default
    if not 1 <= value <= 65535:
        logger.warning("[端口] %s 超出 1-65535 范围，使用默认值 %d", name, default)
        return default
    return value


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
        logger.warning(
            "[端口清理] 无法验证 PID=%s 的归属: %s", pid, type(exc).__name__
        )
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
        logger.warning(
            "[端口清理] 检查端口 %d 失败: %s", port, type(exc).__name__
        )


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
    return _system_package_dir(NETEASE_NODE_PACKAGE)


def _qq_api_dir():
    return _system_package_dir(QQ_NODE_PACKAGE)


def start_music_api():
    """启动本地网易云音乐API服务"""
    global _music_api_process
    port = _env_port("MUSIC_API_PORT", DEFAULT_MUSIC_API_PORT)
    api_dir = _api_dir()
    if not os.path.isdir(api_dir):
        logger.warning("系统网易云音乐API包不存在，跳过启动: %s", api_dir)
        logger.warning("请执行: %s", SYSTEM_NODE_INSTALL_COMMAND)
        logger.warning("网易云音乐功能保持不可用，项目不会回退到远程API")
        return
    child_env = _system_node_environment(api_dir, port, NETEASE_NODE_PACKAGE)
    if child_env is None:
        return

    # 清理占用本服务端口的残留进程（Windows），避免误杀其他Node应用
    if sys.platform == "win32":
        _kill_port(port, api_dir)

    logger.info("正在启动系统网易云音乐API服务: %s", api_dir)
    api_log = os.path.join(APP_DIR, "netease_api_output.log")
    log_file = _open_private_log(api_log)

    logger.info(
        "[API启动] 使用系统 Node=%s，全局模块=%s (PORT=%d)",
        NODE_EXECUTABLE,
        _system_node_modules(),
        port,
    )
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
                    logger.error("[API启动] %s", _redact_log_text(line))
        except Exception:
            pass
        _music_api_process = None
        logger.warning("[API启动] 网易云音乐功能保持不可用，不回退到远程API")
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
            r = requests.get(
                f"http://127.0.0.1:{port}/login/status",
                timeout=(2, 2),
                allow_redirects=False,
            )
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
    port = _env_port("QQ_MUSIC_API_PORT", DEFAULT_QQ_MUSIC_API_PORT)
    api_dir = _qq_api_dir()
    if not os.path.isdir(api_dir):
        logger.warning("系统QQ音乐API包不存在，跳过启动: %s", api_dir)
        logger.warning("请执行: %s", SYSTEM_NODE_INSTALL_COMMAND)
        return
    if not os.path.isfile(os.path.join(api_dir, "package.json")):
        logger.warning("QQ音乐API缺少package.json，可能未安装依赖")
        return
    dist_main = os.path.join(api_dir, "dist", "app.js")
    if not os.path.isfile(dist_main):
        logger.error("系统QQ音乐API包缺少运行产物: %s", dist_main)
        return
    child_env = _system_node_environment(api_dir, port, QQ_NODE_PACKAGE)
    if child_env is None:
        return
    if sys.platform == "win32":
        _kill_port(port, api_dir)

    logger.info("正在启动系统QQ音乐API服务: %s", api_dir)
    api_log = os.path.join(APP_DIR, "qq_api_output.log")
    log_file = _open_private_log(api_log)
    qq_bootstrap = (
        "const loaded=require(process.argv[1]);"
        "const app=loaded.default||loaded;"
        "app.listen(Number(process.env.PORT),'127.0.0.1');"
    )
    cmd = [NODE_EXECUTABLE, "-e", qq_bootstrap, os.path.realpath(dist_main)]

    logger.info(
        "[QQ-API启动] 使用系统 Node=%s，全局模块=%s (PORT=%d)",
        NODE_EXECUTABLE,
        _system_node_modules(),
        port,
    )
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
                    logger.error("[QQ-API启动] %s", _redact_log_text(line))
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
            r = requests.get(
                f"http://127.0.0.1:{port}/getSearchByKey/test",
                timeout=(2, 2),
                allow_redirects=False,
            )
            if r.status_code == 200:
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


def _probe_url(url, acceptable_statuses=(200,)):
    try:
        response = requests.get(
            url,
            timeout=(1.5, 2.5),
            allow_redirects=False,
        )
        return response.status_code in acceptable_statuses
    except requests.RequestException:
        return False


def _web_probe_url():
    host = os.getenv("HOST", "0.0.0.0").strip()
    if host in {"", "0.0.0.0", "::", "[::]"}:
        host = "127.0.0.1"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = _env_port("PORT", DEFAULT_WEB_PORT)
    return f"http://{host}:{port}/healthz"


def _dependency_failures():
    failures = []
    services = (
        (
            "netease_api",
            _api_dir(),
            _music_api_process,
            f"http://127.0.0.1:{_env_port('MUSIC_API_PORT', DEFAULT_MUSIC_API_PORT)}/login/status",
        ),
        (
            "qq_music_api",
            _qq_api_dir(),
            _qq_music_api_process,
            f"http://127.0.0.1:{_env_port('QQ_MUSIC_API_PORT', DEFAULT_QQ_MUSIC_API_PORT)}/getSearchByKey/test",
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
        except Exception as exc:
            logger.error(
                "[看门狗] 单独恢复 %s 失败: %s", service, type(exc).__name__
            )


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
        except Exception as exc:
            logger.error(
                "[看门狗] 重启前清理播放会话失败: %s", type(exc).__name__
            )

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
    logger.critical("[看门狗] 已准备完整重启；工作目录=%s", APP_DIR)
    for handler in logging.getLogger().handlers:
        try:
            handler.flush()
        except Exception:
            pass

    os.chdir(APP_DIR)
    try:
        os.execve(PYTHON_EXECUTABLE, command, environment)
    except Exception as exec_error:
        logger.error(
            "[看门狗] 原位重启失败，尝试启动替代进程: %s",
            type(exec_error).__name__,
        )
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
        except Exception as exc:
            logger.critical(
                "[看门狗] 替代进程启动失败: %s", type(exc).__name__
            )
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
    port = _env_port("PORT", DEFAULT_WEB_PORT)
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
        logger.critical("启动失败: %s", type(error).__name__)
        sys.exit(1)
