import os

# 基本配置
DEBUG = False
HOST = "0.0.0.0"
PORT = 5000

# KOOK机器人配置
BOT_TOKEN = os.environ.get("BOT_TOKEN", "your_bot_token_here")

# FFMPEG配置 - 优先使用有效的显式配置，项目搬迁后自动回退到随包二进制
current_dir = os.path.dirname(os.path.abspath(__file__))


def _resolve_bundled_tool(env_name, executable):
    configured = os.environ.get(env_name, "").strip()
    bundled = os.path.join(current_dir, "ffmpeg", "bin", executable)
    if configured and os.path.isfile(configured):
        return os.path.abspath(configured)
    if os.path.isfile(bundled):
        return os.path.abspath(bundled)
    return configured or bundled


FFMPEG_PATH = _resolve_bundled_tool("FFMPEG_PATH", "ffmpeg.exe")
FFPROBE_PATH = _resolve_bundled_tool("FFPROBE_PATH", "ffprobe.exe")

# 音乐API配置
MUSIC_API_BASE = os.environ.get("MUSIC_API_BASE", "http://localhost:3000")

# 备用API地址
BACKUP_MUSIC_API = "https://api.music.liuzhijin.cn"

# QQ音乐API配置
QQ_MUSIC_API_BASE = os.environ.get("QQ_MUSIC_API_BASE", "http://localhost:3200")
QQ_COOKIE_TXT_PATH = os.environ.get(
    "QQ_COOKIE_PATH",
    os.path.join(current_dir, "Cookie", "qq_cookie.txt")
)

# B站配置
BILI_COOKIE_TXT_PATH = os.environ.get(
    "BILI_COOKIE_PATH",
    os.path.join(current_dir, "Cookie", "bili_cookie.txt")
)

# 权限白名单 — 留空表示不启用该维度过滤，全部非空时取交集
# 格式: 逗号分隔的ID列表，例如 ALLOWGROUP=guild1,guild2
ALLOWGROUP  = set(filter(None, (x.strip() for x in os.environ.get("ALLOWGROUP",  "").split(","))))
ALLOWCHANNEL = set(filter(None, (x.strip() for x in os.environ.get("ALLOWCHANNEL", "").split(","))))
ALLOWUSER   = set(filter(None, (x.strip() for x in os.environ.get("ALLOWUSER",   "").split(","))))

# CMD指令强管控 — 仅名单内用户可执行 /cmd；留空则全员无权限（最安全策略）
CMD_ALLOWUSER = set(filter(None, (x.strip() for x in os.environ.get("CMD_ALLOWUSER", "").split(","))))

# Web控制台配置
SECRET_KEY = os.environ.get("SECRET_KEY", "change_this_to_a_random_string")
