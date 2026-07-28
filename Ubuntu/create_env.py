#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os

env_content = """# KOOK机器人配置
BOT_TOKEN=your_bot_token_here

# FFMPEG配置
FFMPEG_PATH=/usr/bin/ffmpeg
FFPROBE_PATH=/usr/bin/ffprobe

# 音乐API配置
MUSIC_API_BASE=http://localhost:3000

# Web控制台配置
SECRET_KEY=change_this_to_a_random_string
HOST=0.0.0.0
PORT=5000
DEBUG=True
"""

env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
with open(env_path, 'w', encoding='utf-8') as f:
    f.write(env_content)

print(f"✅ .env文件创建成功：{env_path}")
