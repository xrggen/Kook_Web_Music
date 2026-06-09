import os

# 基本配置
DEBUG = False
HOST = "0.0.0.0"
PORT = 5000

# KOOK机器人配置
BOT_TOKEN = os.environ.get("BOT_TOKEN", "your_bot_token_here")

# FFMPEG配置 - 使用相对路径
current_dir = os.path.dirname(os.path.abspath(__file__))
FFMPEG_PATH = os.environ.get("FFMPEG_PATH", os.path.join(current_dir, "ffmpeg", "bin", "ffmpeg.exe"))
FFPROBE_PATH = os.environ.get("FFPROBE_PATH", "").strip()

# 音乐API配置
MUSIC_API_BASE = os.environ.get("MUSIC_API_BASE", "http://localhost:3000")

# 备用API地址
BACKUP_MUSIC_API = ""  # 可填写第三方网易云API备用地址

# QQ音乐API配置
QQ_MUSIC_API_BASE = os.environ.get("QQ_MUSIC_API_BASE", "http://localhost:3200")
QQ_COOKIE_TXT_PATH = os.environ.get(
    "QQ_COOKIE_PATH",
    os.path.join(current_dir, "Cookie", "qq_cookie.txt")
)

# 权限白名单 — 留空表示不启用该维度过滤，全部非空时取交集
# 格式: 逗号分隔的ID列表，例如 ALLOWGROUP=guild1,guild2
ALLOWGROUP  = set(filter(None, (x.strip() for x in os.environ.get("ALLOWGROUP",  "").split(","))))
ALLOWCHANNEL = set(filter(None, (x.strip() for x in os.environ.get("ALLOWCHANNEL", "").split(","))))
ALLOWUSER   = set(filter(None, (x.strip() for x in os.environ.get("ALLOWUSER",   "").split(","))))

# Web控制台配置
SECRET_KEY = os.environ.get("SECRET_KEY", "change_this_to_a_random_string")