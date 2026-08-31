import os
import secrets
import shutil
import sys

# 基本配置
DEBUG = False
HOST = os.environ.get("HOST", "0.0.0.0").strip() or "0.0.0.0"


def _env_port(name, default):
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        value = default
    return value if 1 <= value <= 65535 else default


def _env_positive_int(name, default, minimum=1, maximum=None):
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        value = default
    value = max(minimum, value)
    return min(value, maximum) if maximum is not None else value


DEFAULT_WEB_PORT = 18473
DEFAULT_MUSIC_API_PORT = 18474
DEFAULT_QQ_MUSIC_API_PORT = 18475
PORT = _env_port("PORT", DEFAULT_WEB_PORT)
MAX_REQUEST_BYTES = _env_positive_int(
    "MAX_REQUEST_BYTES", 1024 * 1024, 64 * 1024, 16 * 1024 * 1024
)
MAX_PLAYLIST_IMPORT_TRACKS = _env_positive_int(
    "MAX_PLAYLIST_IMPORT_TRACKS", 1000, 1, 10_000
)
MAX_QUEUE_TRACKS = _env_positive_int("MAX_QUEUE_TRACKS", 2000, 1, 10_000)
MAX_PLAYLIST_IMPORT_CONCURRENCY = _env_positive_int(
    "MAX_PLAYLIST_IMPORT_CONCURRENCY", 2, 1, 32
)

# KOOK机器人配置
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
APP_VERSION = os.environ.get("APP_VERSION", "desktop-ui-v2").strip() or "desktop-ui-v2"

# Windows / Ubuntu 共用同一份配置实现。所有相对路径统一以当前平台目录
# （windows/ 或 Ubuntu/）为基准，避免快捷方式、计划任务、systemd 或
# 看门狗重启后因工作目录变化而解析到错误位置。
current_dir = os.path.dirname(os.path.realpath(__file__))


def _resolve_project_path(value):
    value = os.path.expandvars(os.path.expanduser(str(value).strip()))
    if not os.path.isabs(value):
        value = os.path.join(current_dir, value)
    return os.path.realpath(os.path.abspath(value))


def _resolve_media_tool(env_name, windows_executable, posix_executable):
    """解析媒体工具路径，并把 OS 差异收敛在这一处。"""
    configured = os.environ.get(env_name, "").strip()
    if configured:
        # 显式配置既支持绝对/项目相对路径，也支持 PATH 中的命令名。
        project_candidate = _resolve_project_path(configured)
        if os.path.isfile(project_candidate):
            return project_candidate
        resolved = shutil.which(configured)
        if resolved:
            return os.path.realpath(resolved)
        return project_candidate

    if sys.platform == "win32":
        bundled = _resolve_project_path(
            os.path.join("ffmpeg", "bin", windows_executable)
        )
        if os.path.isfile(bundled):
            return bundled
        resolved = shutil.which(windows_executable)
        return os.path.realpath(resolved) if resolved else bundled

    resolved = shutil.which(posix_executable)
    if resolved:
        return os.path.realpath(resolved)
    return os.path.realpath(os.path.join("/usr/bin", posix_executable))


FFMPEG_PATH = _resolve_media_tool("FFMPEG_PATH", "ffmpeg.exe", "ffmpeg")
FFPROBE_PATH = _resolve_media_tool("FFPROBE_PATH", "ffprobe.exe", "ffprobe")

# 音乐API配置
MUSIC_API_PORT = _env_port("MUSIC_API_PORT", DEFAULT_MUSIC_API_PORT)
MUSIC_API_BASE = f"http://127.0.0.1:{MUSIC_API_PORT}"

# QQ音乐API配置
QQ_MUSIC_API_PORT = _env_port("QQ_MUSIC_API_PORT", DEFAULT_QQ_MUSIC_API_PORT)
QQ_MUSIC_API_BASE = f"http://127.0.0.1:{QQ_MUSIC_API_PORT}"
QQ_COOKIE_TXT_PATH = _resolve_project_path(
    os.environ.get("QQ_COOKIE_PATH", os.path.join("Cookie", "qq_cookie.txt"))
)
QQ_CREDENTIAL_PATH = _resolve_project_path(
    os.environ.get("QQ_CREDENTIAL_PATH", os.path.join("Cookie", "qq_credential.json"))
)

# B站配置
BILI_COOKIE_TXT_PATH = _resolve_project_path(
    os.environ.get("BILI_COOKIE_PATH", os.path.join("Cookie", "bili_cookie.txt"))
)

# 权限白名单。默认拒绝所有 Bot 指令；如需无白名单运行，必须显式开启开关。
# 格式: 逗号分隔的ID列表，例如 ALLOWGROUP=guild1,guild2
ALLOWGROUP = set(filter(None, (x.strip() for x in os.environ.get("ALLOWGROUP", "").split(","))))
ALLOWCHANNEL = set(filter(None, (x.strip() for x in os.environ.get("ALLOWCHANNEL", "").split(","))))
ALLOWUSER = set(filter(None, (x.strip() for x in os.environ.get("ALLOWUSER", "").split(","))))
BOT_ALLOW_UNRESTRICTED = os.environ.get("BOT_ALLOW_UNRESTRICTED", "false").strip().lower() in {
    "1", "true", "yes", "on"
}

# Web控制台配置
SECRET_KEY = os.environ.get("SECRET_KEY", "").strip() or secrets.token_urlsafe(48)
