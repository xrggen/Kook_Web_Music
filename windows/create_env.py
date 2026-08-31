#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import shutil
import sys
from getpass import getpass
from pathlib import Path
from secrets import token_urlsafe

try:
    from .secure_storage import secure_write_text
except ImportError:
    from secure_storage import secure_write_text


env_path = Path(__file__).resolve().parent / ".env"
if env_path.exists():
    raise SystemExit("❌ .env 已存在。为避免覆盖现有凭据，脚本已停止。")

bot_token = getpass("请输入 KOOK Bot Token（输入不会显示）: ").strip()
if not bot_token:
    raise SystemExit("❌ BOT_TOKEN 不能为空。")
if sys.platform == "win32":
    ffmpeg_path = "./ffmpeg/bin/ffmpeg.exe"
    ffprobe_path = "./ffmpeg/bin/ffprobe.exe"
else:
    ffmpeg_path = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
    ffprobe_path = shutil.which("ffprobe") or "/usr/bin/ffprobe"

env_content = f"""# KOOK机器人配置
BOT_TOKEN={bot_token}
APP_VERSION=desktop-ui-v2

# 媒体工具。Windows 默认使用随包 ffmpeg；Linux 默认使用系统 PATH。
FFMPEG_PATH={ffmpeg_path}
FFPROBE_PATH={ffprobe_path}

# 本机音乐API配置
MUSIC_API_PORT=18474
QQ_MUSIC_API_PORT=18475
QQ_COOKIE_PATH=./Cookie/qq_cookie.txt
QQ_CREDENTIAL_PATH=./Cookie/qq_credential.json

# QQ音乐登录态自动续期（秒）
QQ_CREDENTIAL_CHECK_INTERVAL=10800
QQ_CREDENTIAL_REFRESH_INTERVAL=64800
QQ_CREDENTIAL_REFRESH_WINDOW=86400

BILI_COOKIE_PATH=./Cookie/bili_cookie.txt

# KOOK Bot 指令权限白名单。全部留空时默认拒绝所有指令。
ALLOWGROUP=
ALLOWCHANNEL=
ALLOWUSER=
BOT_ALLOW_UNRESTRICTED=false

# Web控制台配置
SECRET_KEY={token_urlsafe(48)}
HOST=0.0.0.0
PORT=18473
DEBUG=False
MAX_REQUEST_BYTES=1048576
MAX_PLAYLIST_IMPORT_TRACKS=1000
MAX_QUEUE_TRACKS=2000
MAX_PLAYLIST_IMPORT_CONCURRENCY=2

# Web控制面鉴权
AUTH_DATABASE_PATH=./data/kook_music.db
INITIAL_ADMIN_USERNAME=gen
INITIAL_ADMIN_PASSWORD=
INITIAL_ADMIN_CREDENTIAL_PATH=./data/bootstrap-admin.json
AUTH_SESSION_IDLE_SECONDS=86400
AUTH_SESSION_ABSOLUTE_SECONDS=604800
AUTH_LOGIN_WINDOW_SECONDS=600
AUTH_LOGIN_USER_FAILURES=5
AUTH_LOGIN_IP_FAILURES=20
AUTH_COOKIE_SECURE=false
AUTH_TRUST_PROXY_HEADERS=false
"""

secure_write_text(env_path, env_content)
print(f"✅ 已安全创建配置文件：{env_path}")
print("⚠️ 该文件包含凭据，禁止提交到 Git。")
print("🔐 Web 初始化管理员：gen")
print("🔐 首次启动后，从 ./data/bootstrap-admin.json 读取一次性初始化密码。")
print("⚠️ 首次登录后必须立即修改密码。")
print("ℹ️ 公网 HTTPS 部署请把 AUTH_COOKIE_SECURE 改为 true。")
