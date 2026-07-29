import os
import secrets

# 基本配置
DEBUG = False
HOST = "0.0.0.0"
PORT = 5000

# KOOK机器人配置
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()

# Windows 版的相对路径统一相对于本文件所在目录解析，避免从快捷方式、
# 计划任务或看门狗重启后因工作目录变化而指向错误位置。
current_dir = os.path.dirname(os.path.realpath(__file__))


def _resolve_project_path(value):
    value = os.path.expandvars(os.path.expanduser(str(value).strip()))
    if not os.path.isabs(value):
        value = os.path.join(current_dir, value)
    return os.path.realpath(os.path.abspath(value))


def _resolve_bundled_tool(env_name, executable):
    configured = os.environ.get(env_name, "").strip()
    bundled = _resolve_project_path(os.path.join("ffmpeg", "bin", executable))
    if configured:
        configured = _resolve_project_path(configured)
    if configured and os.path.isfile(configured):
        return configured
    if os.path.isfile(bundled):
        return bundled
    return configured or bundled


FFMPEG_PATH = _resolve_bundled_tool("FFMPEG_PATH", "ffmpeg.exe")
FFPROBE_PATH = _resolve_bundled_tool("FFPROBE_PATH", "ffprobe.exe")

# 音乐API配置
MUSIC_API_BASE = os.environ.get("MUSIC_API_BASE", "http://localhost:3000")

# 备用API地址
BACKUP_MUSIC_API = "https://api.music.liuzhijin.cn"

# QQ音乐API配置
QQ_MUSIC_API_BASE = os.environ.get("QQ_MUSIC_API_BASE", "http://localhost:3200")
QQ_COOKIE_TXT_PATH = _resolve_project_path(
    os.environ.get("QQ_COOKIE_PATH", os.path.join("Cookie", "qq_cookie.txt"))
)

# B站配置
BILI_COOKIE_TXT_PATH = _resolve_project_path(
    os.environ.get("BILI_COOKIE_PATH", os.path.join("Cookie", "bili_cookie.txt"))
)

# 权限白名单 — 留空表示不启用该维度过滤，全部非空时取交集
# 格式: 逗号分隔的ID列表，例如 ALLOWGROUP=guild1,guild2
ALLOWGROUP  = set(filter(None, (x.strip() for x in os.environ.get("ALLOWGROUP",  "").split(","))))
ALLOWCHANNEL = set(filter(None, (x.strip() for x in os.environ.get("ALLOWCHANNEL", "").split(","))))
ALLOWUSER   = set(filter(None, (x.strip() for x in os.environ.get("ALLOWUSER",   "").split(","))))

# CMD指令强管控 — 仅名单内用户可执行 /cmd；留空则全员无权限（最安全策略）
CMD_ALLOWUSER = set(filter(None, (x.strip() for x in os.environ.get("CMD_ALLOWUSER", "").split(","))))

# Web控制台配置
SECRET_KEY = os.environ.get("SECRET_KEY", "").strip() or secrets.token_urlsafe(48)
