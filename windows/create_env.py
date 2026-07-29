#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from getpass import getpass
from pathlib import Path
from secrets import token_urlsafe


env_path = Path(__file__).resolve().parent / ".env"
if env_path.exists():
    raise SystemExit("❌ .env 已存在。为避免覆盖现有凭据，脚本已停止。")

bot_token = getpass("请输入 KOOK Bot Token（输入不会显示）: ").strip()
if not bot_token:
    raise SystemExit("❌ BOT_TOKEN 不能为空。")

env_content = f"""# KOOK机器人配置
BOT_TOKEN={bot_token}

# FFMPEG配置 — 相对路径以 windows 目录为基准
FFMPEG_PATH=./ffmpeg/bin/ffmpeg.exe
FFPROBE_PATH=./ffmpeg/bin/ffprobe.exe

# 本机音乐API配置
MUSIC_API_BASE=http://localhost:3000
QQ_MUSIC_API_BASE=http://localhost:3200
QQ_COOKIE_PATH=./Cookie/qq_cookie.txt
BILI_COOKIE_PATH=./Cookie/bili_cookie.txt

# 权限白名单 — 留空表示不启用该维度过滤
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
"""

env_path.write_text(env_content, encoding="utf-8")
print(f"✅ 已安全创建配置文件：{env_path}")
print("⚠️ 该文件包含凭据，禁止提交到 Git。")
