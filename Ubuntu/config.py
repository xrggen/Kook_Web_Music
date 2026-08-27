import os
import secrets
import shutil
import sys

# 基本配置
DEBUG = False
HOST = "0.0.0.0"
PORT = 5000

# KOOK机器人配置
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()

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
ALLOWGROUP = set(filter(None, (x.strip() for x in os.environ.get("ALLOWGROUP", "").split(","))))
ALLOWCHANNEL = set(filter(None, (x.strip() for x in os.environ.get("ALLOWCHANNEL", "").split(","))))
ALLOWUSER = set(filter(None, (x.strip() for x in os.environ.get("ALLOWUSER", "").split(","))))

# CMD指令强管控 — 仅名单内用户可执行 /cmd；留空则全员无权限（最安全策略）
CMD_ALLOWUSER = set(filter(None, (x.strip() for x in os.environ.get("CMD_ALLOWUSER", "").split(","))))

# Web控制台配置
SECRET_KEY = os.environ.get("SECRET_KEY", "").strip() or secrets.token_urlsafe(48)
