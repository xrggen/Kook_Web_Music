#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import shutil
import sys
from getpass import getpass
from pathlib import Path
from secrets import token_urlsafe


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
MUSIC_API_BASE=http://localhost:3000
QQ_MUSIC_API_BASE=http://localhost:3200
QQ_COOKIE_PATH=./Cookie/qq_cookie.txt
QQ_CREDENTIAL_PATH=./Cookie/qq_credential.json

# QQ音乐登录态自动续期（秒）
QQ_CREDENTIAL_CHECK_INTERVAL=10800
QQ_CREDENTIAL_REFRESH_INTERVAL=64800
QQ_CREDENTIAL_REFRESH_WINDOW=86400

BILI_COOKIE_PATH=./Cookie/bili_cookie.txt

# KOOK Bot 指令权限白名单 — 留空表示不启用该维度过滤
ALLOWGROUP=
ALLOWCHANNEL=
ALLOWUSER=

# /cmd 强权限名单 — 留空表示无人可执行
CMD_ALLOWUSER=

# Web控制台配置
SECRET_KEY={token_urlsafe(48)}
HOST=0.0.0.0
PORT=5000
DEBUG=False

# Web控制面鉴权
AUTH_DATABASE_PATH=./data/kook_music.db
AUTH_SESSION_IDLE_SECONDS=86400
AUTH_SESSION_ABSOLUTE_SECONDS=604800
AUTH_LOGIN_WINDOW_SECONDS=600
AUTH_LOGIN_USER_FAILURES=5
AUTH_LOGIN_IP_FAILURES=20
AUTH_COOKIE_SECURE=false
AUTH_TRUST_PROXY_HEADERS=false
"""

env_path.write_text(env_content, encoding="utf-8")
print(f"✅ 已安全创建配置文件：{env_path}")
print("⚠️ 该文件包含凭据，禁止提交到 Git。")
print("ℹ️ 公网 HTTPS 部署请把 AUTH_COOKIE_SECURE 改为 true。")
