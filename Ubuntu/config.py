import os
import secrets

# 基本配置
DEBUG = False
HOST = "0.0.0.0"
PORT = 5000

# KOOK机器人配置
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()

# FFmpeg 使用 Ubuntu 系统安装路径，禁止回退到 Windows 内置二进制。
current_dir = os.path.dirname(os.path.abspath(__file__))
FFMPEG_PATH = os.environ.get("FFMPEG_PATH", "/usr/bin/ffmpeg").strip()
FFPROBE_PATH = os.environ.get("FFPROBE_PATH", "/usr/bin/ffprobe").strip()

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
SECRET_KEY = os.environ.get("SECRET_KEY", "").strip() or secrets.token_urlsafe(48)
