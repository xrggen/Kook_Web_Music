#!/usr/bin/env python3
# -*- coding: utf-8 -*-

env_content = """# KOOK机器人配置
BOT_TOKEN=your_bot_token_here

# FFMPEG配置 — 按实际路径填写
FFMPEG_PATH=./ffmpeg/bin/ffmpeg.exe
FFPROBE_PATH=./ffprobe.exe

# 音乐API配置
MUSIC_API_BASE=http://localhost:3000

# Web控制台配置
SECRET_KEY=change_this_to_a_random_string
HOST=0.0.0.0
PORT=5000
DEBUG=True
"""

with open('.env', 'w', encoding='utf-8') as f:
    f.write(env_content)

print("✅ .env文件创建成功！")
