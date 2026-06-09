from flask import Flask, render_template, request, jsonify, redirect, url_for
import os
import json
import asyncio
import sys
from typing import Dict, Any, List, Union, Optional
import threading
import requests
import logging
import shlex
from khl import Bot, Message
from khl.command.lexer import DefaultLexer
from khl.command.exception import Exceptions

# 修复命令行解析器的两个问题：
# 1. shlex.split 遇到未闭合英文引号会崩溃（如 /wy "hello）
# 2. 中文引号 ""''「」『』 不被 shlex 识别，导致搜索结果包含引号字符
_CHINESE_QUOTES = str.maketrans({
    '“': '"', '”': '"',   # "" → ""
    '‘': "'", '’': "'",   # '' → ''
    '「': '"', '」': '"',   # 「」 → ""
    '『': '"', '』': '"',   # 『』 → ""
})
def _patched_lex(self, msg):
    """与原始 lex 相同，但先规一化中文引号，失败时回退到 str.split()"""
    matched_prefixes = [p for p in self.prefixes if msg.content.startswith(p)]
    if not matched_prefixes:
        raise Exceptions.Lexer.NotMatched()

    for prefix in matched_prefixes:
        content_after_prefix = msg.content[len(prefix):]
        # 规一化中文引号为英文引号，使 shlex 正确分组带空格的参数
        content_after_prefix = content_after_prefix.translate(_CHINESE_QUOTES)
        try:
            arg_list = shlex.split(content_after_prefix)
        except ValueError:
            arg_list = content_after_prefix.split()
        a0 = arg_list[0] if len(arg_list) > 0 else ''
        if (a0 if self.case_sensitive else a0.lower()) not in self.triggers:
            raise Exceptions.Lexer.NotMatched()
        return arg_list[1:]

DefaultLexer.lex = _patched_lex

# 修复相对导入
try:
    from . import kookvoice
    from .config import *
    from .utils import search_music, get_music_url, get_playlist, get_playlist_urls
except ImportError:
    import kookvoice
    from config import *
    from utils import search_music, get_music_url, get_playlist, get_playlist_urls
    from qq_utils import search_qq_music, get_qq_music_url, get_qq_playlist, get_qq_playlist_urls, refill_qq_playlist_queue
    from bili_utils import search_bili_music, get_bili_play_url, get_bili_favorite_collections, get_bili_favorite_all_tracks, refill_bili_playlist_queue, search_bili_bvid

# 配置日志
logging.basicConfig(
    level=logging.INFO,  # 保持INFO级别，显示正常信息
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
    handlers=[
        logging.FileHandler('debug.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 只关闭Flask的HTTP访问日志，保留其他日志
logging.getLogger('werkzeug').setLevel(logging.ERROR)

# 初始化Flask应用
app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY

# 后台看门狗心跳文件路径
HEARTBEAT_FILE = os.path.join(os.path.dirname(__file__), ".heartbeat")


@app.before_request
def _update_heartbeat():
    """每个请求更新心跳时间戳，供看门狗检测进程是否卡死"""
    try:
        with open(HEARTBEAT_FILE, "w") as f:
            f.write(str(time.time()))
    except Exception:
        pass


# 尝试导入SocketIO，如果不可用则提供备用方案
try:
    from flask_socketio import SocketIO, emit
    socketio = SocketIO(app, cors_allowed_origins="*")
    socketio_available = True
except ImportError:
    logger.warning("flask_socketio未安装，将使用备用方案")
    socketio = None
    socketio_available = False

# 配置KOOK机器人
bot = Bot(
    token=BOT_TOKEN,
    compress=True  # 启用压缩
)

# ========== 权限白名单 ==========
def _is_allowed(msg: Message) -> bool:
    """检查消息发送者是否在白名单内。全部白名单为空 → 允许所有人；
       多个白名单均非空时取交集（必须同时满足）。"""
    if not ALLOWGROUP and not ALLOWCHANNEL and not ALLOWUSER:
        return True

    guild_id   = msg.ctx.guild.id
    channel_id = msg.ctx.channel.id
    user_id    = msg.author_id

    if ALLOWUSER and user_id not in ALLOWUSER:
        return False
    if ALLOWCHANNEL and channel_id not in ALLOWCHANNEL:
        return False
    if ALLOWGROUP and guild_id not in ALLOWGROUP:
        return False
    return True


# 包装 bot.command.handle，使所有命令自动经过白名单检查
_original_handle = bot.command.handle

async def _patched_handle(loop, client, msg: Message, *args, **kwargs):
    if not _is_allowed(msg):
        logger.info(
            "[权限] 拒绝: 用户=%s 频道=%s 服务器=%s 指令=%s",
            msg.author_id, msg.ctx.channel.id, msg.ctx.guild.id,
            msg.content[:120],
        )
        return
    return await _original_handle(loop, client, msg, *args, **kwargs)

bot.command.handle = _patched_handle

# 注册歌曲开始播放事件：当新歌曲开始播放时，向对应文字频道发送通知
@kookvoice.on_event(kookvoice.Status.START)
async def on_song_start(play_info: kookvoice.PlayInfo):
    """歌曲开始播放回调：在文字频道通知当前播放的歌曲"""
    try:
        extra = play_info.extra_data or {}
        song_name = extra.get("音乐名字") or extra.get("title", "未知歌曲")
        text_channel_id = extra.get("文字频道")
        if not text_channel_id:
            logger.warning("[播放通知] 缺少文字频道ID，跳过通知")
            return
        logger.info("[播放通知] 正在播放: %s (频道=%s)", song_name, text_channel_id)
        channel = await bot.client.fetch_public_channel(text_channel_id)
        await channel.send(f"🎵 正在播放: **{song_name}**")
    except Exception as e:
        logger.error(f"[播放通知] 发送失败: {e}")

# 强制验证Token有效性
async def verify_token() -> bool:
    try:
        response = await bot.client.gate.request('GET', 'guild/list')
        if not isinstance(response, dict):
            raise ValueError("API响应格式错误")
        items = response.get('items', [])
        if not isinstance(items, list):
            raise ValueError("items应为列表类型")
        print(f"Token验证成功，可访问 {len(items)} 个服务器")
        return True
    except Exception as e:
        print(f"Token验证失败: {str(e)}")
        return False

# 配置FFMPEG
try:
    kookvoice.set_ffmpeg(FFMPEG_PATH)
    kookvoice.configure_logging(True)  # 启用日志记录
    logger.info(f"FFMPEG路径: {FFMPEG_PATH}")
    logger.info(f"FFPROBE路径: {FFPROBE_PATH}")
except Exception as e:
    logger.error(f"FFMPEG配置错误: {str(e)}")
    sys.exit(1)

# 全局变量
guild_data = {}  # 存储服务器信息
current_guild_id = None  # 当前选中的服务器ID

# 获取用户所在的语音频道
async def find_user_voice_channel(gid: str, aid: str) -> Union[str, None]:
    """查找用户所在的语音频道"""
    logger.info(f"获取用户 {aid} 在服务器 {gid} 的语音频道ID")
    try:
        voice_channel_ = await bot.client.gate.request('GET', 'channel-user/get-joined-channel',
                                                   params={'guild_id': gid, 'user_id': aid})
        if voice_channel_ and "items" in voice_channel_:
            voice_channel = voice_channel_["items"]
            if voice_channel:
                logger.info(f"用户 {aid} 当前语音频道ID: {voice_channel[0]['id']}")
                return voice_channel[0]['id']
        logger.warning(f"用户 {aid} 不在任何语音频道")
        return None
    except Exception as e:
        logger.error(f"获取语音频道ID异常: {e}")
        return None

# 获取服务器列表
async def get_guild_list():
    try:
        guilds = await bot.client.gate.request('GET', 'guild/list')
        if guilds and "items" in guilds:
            return guilds["items"]
        return []
    except Exception as e:
        logger.error(f"获取服务器列表异常: {e}")
        return []

# 获取频道列表
async def get_channel_list(guild_id):
    try:
        channels = await bot.client.gate.request('GET', 'channel/list', params={'guild_id': guild_id})
        if channels and "items" in channels:
            return channels["items"]
        return []
    except Exception as e:
        logger.error(f"获取频道列表异常: {e}")
        return []

# 根据用户所在频道或服务器内唯一活跃频道，定位控制目标
async def _resolve_channel(guild_id: str, user_id: str):
    """返回目标语音频道ID。先查用户所在频道，再回退到服务器内唯一活跃频道。"""
    user_ch = await find_user_voice_channel(guild_id, user_id)
    if user_ch and user_ch in kookvoice.play_list:
        return user_ch
    active = [ch_id for ch_id, data in kookvoice.play_list.items()
              if data.get('guild_id') == guild_id]
    if len(active) == 1:
        return active[0]
    return None

# 机器人命令
@bot.command(name='ping')
async def ping_cmd(msg: Message):
    logger.info(f"[命令:ping] 用户={msg.author_id} 频道={msg.ctx.channel.id}")
    await msg.reply('pong!')

@bot.command(name='加入')
async def join_cmd(msg: Message):
    """加入用户所在语音频道"""
    try:
        logger.info(f"[命令:加入] 用户={msg.author_id} 服务器={msg.ctx.guild.id}")
        voice_channel = await find_user_voice_channel(msg.ctx.guild.id, msg.author_id)
        if voice_channel:
            player = kookvoice.Player(voice_channel, BOT_TOKEN)
            player.join(msg.ctx.guild.id)
            voice_channel_info = await bot.client.fetch_public_channel(voice_channel)
            logger.info(f"[命令:加入] 成功 频道=#{voice_channel_info.name}({voice_channel})")
            await msg.reply(f"✅ 已加入语音频道 #{voice_channel_info.name}")
            return True
        logger.warning(f"[命令:加入] 用户不在语音频道")
        await msg.reply("❌ 您当前不在语音频道中")
    except Exception as e:
        logger.error(f"[命令:加入] 出错: {e}")
        await msg.reply("⚠️ 加入失败，请检查权限或稍后再试")

@bot.command(name='wy')
async def play_music(msg: Message, music_input: str = ''):
    """播放音乐"""
    try:
        if not music_input.strip():
            await msg.reply("❌ 请指定歌曲名，例如: `/wy 晴天`")
            return
        logger.info(f"[命令:wy] 用户={msg.author_id} 输入={music_input}")
        voice_channel_id = await find_user_voice_channel(msg.ctx.guild.id, msg.author_id)
        if voice_channel_id is None:
            await msg.reply("❌ 请先加入语音频道")
            return

        # 判断是否为直链
        if music_input.startswith("http"):
            music_url = music_input
            song_name = "直链音乐"
            logger.info(f"[命令:wy] 直链模式: {music_url[:80]}...")
        else:
            try:
                # 搜索歌曲 (utils.search_music already logs the API call)
                songs = search_music(music_input)
                if not songs:
                    await msg.reply("❌ 未搜索到歌曲")
                    return

                song = songs[0]
                song_id = song['id']
                song_name = song.get('name', music_input)
                artist_name = song.get('ar', [{}])[0].get('name', '未知')

                logger.info(f"[命令:wy] 选中: {song_name} - {artist_name} (id={song_id})")

                # 获取歌曲URL (utils.get_music_url already logs the API call)
                music_url = get_music_url(song_id)
                if not music_url:
                    logger.warning(f"[命令:wy] 获取URL失败 song_id={song_id}")
                    await msg.reply("❌ 获取直链失败，可能是VIP歌曲")
                    return

                logger.info(f"[命令:wy] 获取到URL: {music_url[:80]}...")

            except requests.exceptions.Timeout:
                await msg.reply("❌ 网络超时，请稍后重试")
                return
            except requests.exceptions.ConnectionError:
                await msg.reply("❌ 无法连接到音乐API服务器")
                return
            except Exception as e:
                logger.error(f"[命令:wy] 搜索/取链异常: {e}")
                await msg.reply(f"❌ 发生未知错误: {str(e)}")
                return

        # 添加音乐到播放队列
        player = kookvoice.Player(voice_channel_id, BOT_TOKEN)
        extra_data = {"音乐名字": song_name, "点歌人": msg.author_id, "文字频道": msg.ctx.channel.id}
        player.add_music(music_url, extra_data)
        logger.info(f"[命令:wy] 已加入队列: {song_name}")

        await msg.reply(f"✅ {song_name} 已加入播放队列")

    except Exception as e:
        logger.error(f"[命令:wy] 出错: {e}")
        await msg.reply("⚠️ 播放失败，请稍后再试")

@bot.command(name='qq')
async def qq_cmd(msg: Message, music_input: str = ''):
    """播放QQ音乐"""
    try:
        if not music_input.strip():
            await msg.reply("❌ 请指定歌曲名，例如: `/qq 晴天`")
            return
        logger.info(f"[命令:qq] 用户={msg.author_id} 输入={music_input}")
        voice_channel_id = await find_user_voice_channel(msg.ctx.guild.id, msg.author_id)
        if voice_channel_id is None:
            await msg.reply("❌ 请先加入语音频道")
            return

        # 判断是否为直链
        if music_input.startswith("http"):
            music_url = music_input
            song_name = "直链音乐"
            logger.info(f"[命令:qq] 直链模式: {music_url[:80]}...")
        else:
            songs = search_qq_music(music_input)
            if not songs:
                await msg.reply("❌ 未搜索到QQ音乐歌曲")
                return

            song = songs[0]
            songmid = song['id']
            song_name = song.get('name', music_input)
            artist_name = song.get('ar', [{}])[0].get('name', '未知')

            logger.info(f"[命令:qq] 选中: {song_name} - {artist_name} (songmid={songmid})")

            music_url = get_qq_music_url(songmid)
            if not music_url:
                logger.warning(f"[命令:qq] 获取URL失败 songmid={songmid}")
                await msg.reply("❌ 获取直链失败，可能是VIP歌曲")
                return

            logger.info(f"[命令:qq] 获取到URL: {music_url[:80]}...")

        player = kookvoice.Player(voice_channel_id, BOT_TOKEN)
        extra_data = {"音乐名字": song_name, "点歌人": msg.author_id, "文字频道": msg.ctx.channel.id}
        player.add_music(music_url, extra_data)
        logger.info(f"[命令:qq] 已加入队列: {song_name}")

        await msg.reply(f"✅ {song_name} 已加入播放队列 (QQ音乐)")

    except Exception as e:
        logger.error(f"[命令:qq] 出错: {e}")
        await msg.reply("⚠️ 播放失败，请稍后再试")

@bot.command(name='停止')
async def stop_music(msg: Message):
    """停止播放"""
    try:
        logger.info(f"[命令:停止] 用户={msg.author_id} 服务器={msg.ctx.guild.id}")
        ch = await _resolve_channel(msg.ctx.guild.id, msg.author_id)
        if not ch:
            await msg.reply("❌ 当前没有正在播放的频道")
            return
        player = kookvoice.Player(ch)
        player.stop()
        await msg.reply("⏹️ 已停止播放")
    except Exception as e:
        logger.error(f"[命令:停止] 出错: {e}")
        await msg.reply("⚠️ 停止失败")

@bot.command(name='跳过')
async def skip_music(msg: Message):
    """跳过当前歌曲"""
    try:
        logger.info(f"[命令:跳过] 用户={msg.author_id} 服务器={msg.ctx.guild.id}")
        ch = await _resolve_channel(msg.ctx.guild.id, msg.author_id)
        if not ch:
            await msg.reply("❌ 当前没有正在播放的频道")
            return
        player = kookvoice.Player(ch)
        player.skip()
        await msg.reply("⏭️ 已跳过当前歌曲")
    except Exception as e:
        logger.error(f"[命令:跳过] 出错: {e}")
        await msg.reply("⚠️ 跳过失败")

@bot.command(name='暂停')
async def pause_music(msg: Message):
    """暂停播放"""
    try:
        logger.info(f"[命令:暂停] 用户={msg.author_id} 服务器={msg.ctx.guild.id}")
        ch = await _resolve_channel(msg.ctx.guild.id, msg.author_id)
        if not ch:
            await msg.reply("❌ 当前没有正在播放的频道")
            return
        player = kookvoice.Player(ch)
        player.pause()
        await msg.reply("⏸️ 已暂停播放")
    except Exception as e:
        logger.error(f"[命令:暂停] 出错: {e}")
        await msg.reply("⚠️ 暂停失败")

@bot.command(name='继续')
async def resume_music(msg: Message):
    """继续播放"""
    try:
        logger.info(f"[命令:继续] 用户={msg.author_id} 服务器={msg.ctx.guild.id}")
        ch = await _resolve_channel(msg.ctx.guild.id, msg.author_id)
        if not ch:
            await msg.reply("❌ 当前没有正在播放的频道")
            return
        player = kookvoice.Player(ch)
        player.resume()
        await msg.reply("▶️ 已继续播放")
    except Exception as e:
        logger.error(f"[命令:继续] 出错: {e}")
        await msg.reply("⚠️ 继续播放失败")

@bot.command(name='单曲循环')
async def repeat_cmd(msg: Message):
    """切换单曲循环开关"""
    try:
        logger.info(f"[命令:单曲循环] 用户={msg.author_id} 服务器={msg.ctx.guild.id}")
        ch = await _resolve_channel(msg.ctx.guild.id, msg.author_id)
        if not ch:
            await msg.reply("❌ 当前没有正在播放的频道")
            return
        player = kookvoice.Player(ch)
        enabled = player.repeat_toggle()
        await msg.reply(f"🔂 单曲循环已{'开启' if enabled else '关闭'}")
    except Exception as e:
        logger.error(f"[命令:单曲循环] 出错: {e}")
        await msg.reply("⚠️ 操作失败，请稍后再试")

@bot.command(name='随机播放')
async def shuffle_cmd(msg: Message):
    """切换随机播放开关"""
    try:
        logger.info(f"[命令:随机播放] 用户={msg.author_id} 服务器={msg.ctx.guild.id}")
        ch = await _resolve_channel(msg.ctx.guild.id, msg.author_id)
        if not ch:
            await msg.reply("❌ 当前没有正在播放的频道")
            return
        player = kookvoice.Player(ch)
        enabled, count = player.shuffle_toggle()
        # 重新预取前 5 首 URL
        try:
            from utils import refill_playlist_queue
            refill_playlist_queue(ch, kookvoice.play_list)
        except Exception:
            pass
        try:
            from qq_utils import refill_qq_playlist_queue
            refill_qq_playlist_queue(ch, kookvoice.play_list)
        except Exception:
            pass
        if enabled:
            await msg.reply(f"🔀 随机播放已开启（{count} 首已打乱）")
        else:
            await msg.reply(f"🔀 随机播放已关闭（{count} 首已恢复原序）")
    except Exception as e:
        logger.error(f"[命令:随机播放] 出错: {e}")
        await msg.reply("⚠️ 操作失败，请稍后再试")

@bot.command(name='脱离卡死')
async def reset_all_cmd(msg: Message):
    """重置所有播放状态与服务器监听"""
    global guild_data, current_guild_id

    logger.info(f"[命令:脱离卡死] 用户={msg.author_id}")

    # 收集所有需要清理的频道ID
    all_channels = set()
    for d in (kookvoice.play_list, kookvoice.guild_status, kookvoice.playlist_handle_status):
        try:
            all_channels.update(d.keys())
        except Exception:
            pass
    stopped = len(all_channels)

    # 第一步：通过 KOOK API 强制离开所有语音频道，从根源切断 RTP 连接
    # 即使 PlayHandler 线程卡死在 I/O 上，RTP 断开后 FFmpeg 也会因 broken pipe 退出
    from kookvoice.requestor import VoiceRequestor
    for ch_id in all_channels:
        try:
            vr = VoiceRequestor(BOT_TOKEN)
            await vr.leave(ch_id)
            logger.info(f"[脱离卡死] 已离开语音频道: {ch_id}")
        except Exception as e:
            logger.warning(f"[脱离卡死] 离开频道 {ch_id} 失败（可忽略）: {e}")

    # 第二步：发送 STOP 信号 + 清空队列
    for ch_id in all_channels:
        try:
            kookvoice.guild_status[ch_id] = kookvoice.Status.STOP
        except Exception:
            pass
    for ch_id in list(kookvoice.play_list.keys()):
        try:
            kookvoice.play_list[ch_id]['play_list'] = []
        except Exception:
            pass

    # 第三步：等待 Handler 感知 RTP 断开或 STOP 信号
    await asyncio.sleep(0.5)

    # 第四步：清空所有全局状态
    for d in (kookvoice.play_list, kookvoice.guild_status, kookvoice.playlist_handle_status):
        try:
            d.clear()
        except Exception:
            pass
    try:
        guild_data.clear()
    except Exception:
        pass
    current_guild_id = None

    logger.info(f"[命令:脱离卡死] 已重置 {stopped} 个频道")
    await msg.reply(f"✅ 已重置所有状态（共 {stopped} 个频道）")

@bot.command(name='wygd')
async def playlist_play(msg: Message, playlist_input: str = ''):
    """播放歌单 — 与 Web 控制台共用 get_playlist_urls 实现"""
    try:
        if not playlist_input.strip():
            await msg.reply("❌ 请指定歌单ID或链接，例如: `/wygd 123456789`")
            return
        logger.info(f"[命令:wygd] 用户={msg.author_id} 输入={playlist_input}")
        voice_channel_id = await find_user_voice_channel(msg.ctx.guild.id, msg.author_id)
        if voice_channel_id is None:
            await msg.reply("❌ 请先加入语音频道")
            return

        # 提取歌单ID（与前端 dashboard.js importPlaylist 逻辑一致）
        import re
        playlist_id = playlist_input
        if playlist_input.startswith("http") and "music.163.com" in playlist_input:
            # 标准链接: https://music.163.com/playlist?id=123456
            m = re.search(r'[?&]id=(\d+)', playlist_input)
            if m:
                playlist_id = m.group(1)
            else:
                # /playlist/123456 形式
                m = re.search(r'playlist/(\d+)', playlist_input)
                if m:
                    playlist_id = m.group(1)
        elif playlist_input.isdigit():
            playlist_id = playlist_input
        else:
            # 可能是纯文本，尝试提取数字
            m = re.search(r'(\d{6,})', playlist_input)
            if m:
                playlist_id = m.group(1)

        logger.info(f"[命令:wygd] 歌单id={playlist_id}")

        # 先用 get_playlist 获取歌单名称
        playlist_info = get_playlist(playlist_id)
        playlist_name = playlist_info.get('name', '未知歌单') if playlist_info else f'歌单{playlist_id}'
        track_count = playlist_info.get('trackCount', 0) if playlist_info else 0
        logger.info(f"[命令:wygd] 歌单: {playlist_name} 总数: {track_count}")
        await msg.reply(f"🎶 正在获取歌单「{playlist_name}」({track_count}首)...")

        # 使用与 Web 控制台相同的 get_playlist_urls（分页拉取全部歌曲，无上限）
        songs = get_playlist_urls(playlist_id)
        if not songs:
            await msg.reply("❌ 歌单为空或无法获取歌曲列表")
            return

        # 添加到播放队列（使用 PLAYLIST_SONG 标记，URL 播放时实时获取）
        player = kookvoice.Player(voice_channel_id, BOT_TOKEN)
        for song in songs:
            extra_data = {
                "音乐名字": song['name'],
                "title": song['name'],
                "artist": song['artist'],
                "点歌人": msg.author_id,
                "文字频道": msg.ctx.channel.id,
                "歌单来源": playlist_name,
            }
            player.add_music(song['marker'], extra_data)

        # 预取前5首URL，其余播放时自动补充
        from utils import refill_playlist_queue
        prefetched = refill_playlist_queue(voice_channel_id, kookvoice.play_list)
        logger.info(f"[命令:wygd] 完成 导入{len(songs)}首 预取{prefetched}首")
        await msg.reply(f"✅ 已导入歌单「{playlist_name}」共 {len(songs)} 首歌曲")

    except Exception as e:
        logger.error(f"[命令:wygd] 出错: {e}")
        await msg.reply("⚠️ 播放歌单失败，请稍后再试")

@bot.command(name='qqgd')
async def qq_playlist_play(msg: Message, playlist_input: str = ''):
    """播放QQ音乐歌单"""
    try:
        if not playlist_input.strip():
            await msg.reply("❌ 请指定歌单ID或链接，例如: `/qqgd 123456789`")
            return
        logger.info(f"[命令:qqgd] 用户={msg.author_id} 输入={playlist_input}")
        voice_channel_id = await find_user_voice_channel(msg.ctx.guild.id, msg.author_id)
        if voice_channel_id is None:
            await msg.reply("❌ 请先加入语音频道")
            return

        # 提取歌单ID
        import re
        disstid = playlist_input
        if playlist_input.startswith("http") and "y.qq.com" in playlist_input:
            # y.qq.com/n/ryqq/playlist/123456 形式
            m = re.search(r'playlist/(\d+)', playlist_input)
            if m:
                disstid = m.group(1)
            else:
                # ?id=123456 形式
                m = re.search(r'[?&]id=(\d+)', playlist_input)
                if m:
                    disstid = m.group(1)
        elif playlist_input.isdigit():
            disstid = playlist_input
        else:
            m = re.search(r'(\d{6,})', playlist_input)
            if m:
                disstid = m.group(1)

        logger.info(f"[命令:qqgd] 歌单id={disstid}")

        playlist_info = get_qq_playlist(disstid)
        playlist_name = playlist_info.get('name', f'歌单{disstid}') if playlist_info else f'歌单{disstid}'
        track_count = playlist_info.get('trackCount', 0) if playlist_info else 0
        logger.info(f"[命令:qqgd] 歌单: {playlist_name} 总数: {track_count}")
        await msg.reply(f"🎶 正在获取歌单「{playlist_name}」({track_count}首)...")

        songs = get_qq_playlist_urls(disstid)
        if not songs:
            await msg.reply("❌ 歌单为空或无法获取歌曲列表")
            return

        player = kookvoice.Player(voice_channel_id, BOT_TOKEN)
        for song in songs:
            extra_data = {
                "音乐名字": song['name'],
                "title": song['name'],
                "artist": song['artist'],
                "点歌人": msg.author_id,
                "文字频道": msg.ctx.channel.id,
                "歌单来源": playlist_name,
            }
            player.add_music(song['marker'], extra_data)

        prefetched = refill_qq_playlist_queue(voice_channel_id, kookvoice.play_list)
        logger.info(f"[命令:qqgd] 完成 导入{len(songs)}首 预取{prefetched}首")
        await msg.reply(f"✅ 已导入歌单「{playlist_name}」共 {len(songs)} 首歌曲 (QQ音乐)")

    except Exception as e:
        logger.error(f"[命令:qqgd] 出错: {e}")
        await msg.reply("⚠️ 播放歌单失败，请稍后再试")

@bot.command(name='wy我的歌单')
async def wy_playlists_cmd(msg: Message):
    """列出当前登录网易云账号的歌单"""
    try:
        logger.info(f"[命令:wy我的歌单] 用户={msg.author_id}")
        cookie_path = os.path.join(os.path.dirname(__file__), "Cookie", "cookie.txt")
        cookie = ""
        if os.path.exists(cookie_path):
            with open(cookie_path, "r", encoding="utf-8") as f:
                cookie = f.read().strip()
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        if cookie:
            headers["Cookie"] = cookie
        status_resp = requests.get(f"{MUSIC_API_BASE}/login/status", headers=headers, timeout=10)
        status_data = status_resp.json().get("data", {})
        uid = (status_data.get("account") or {}).get("id") or (status_data.get("profile") or {}).get("userId")
        if not uid:
            await msg.reply("❌ 当前未登录网易云账号\n请在Web控制台 /account 页面登录")
            return
        pl_resp = requests.get(f"{MUSIC_API_BASE}/user/playlist?uid={uid}&limit=50", headers=headers, timeout=15)
        pl_data = pl_resp.json()
        playlists = pl_data.get("playlist", [])
        if not playlists:
            await msg.reply("📋 暂无歌单")
            return
        lines = [f"🎵 我的网易云歌单 ({len(playlists)} 个):"]
        for pl in playlists[:30]:
            lines.append(f"  ▎{pl.get('name','?')}  (ID: {pl.get('id','?')})")
        await msg.reply("\n".join(lines))
    except Exception as e:
        logger.error(f"[命令:wy我的歌单] 出错: {e}")
        await msg.reply("⚠️ 获取歌单失败，请稍后再试")

@bot.command(name='qq我的歌单')
async def qq_playlists_cmd(msg: Message):
    """列出当前登录QQ音乐账号的歌单"""
    try:
        logger.info(f"[命令:qq我的歌单] 用户={msg.author_id}")
        from qq_utils import verify_qq_cookie, get_qq_user_playlists
        vr = verify_qq_cookie()
        if not vr["valid"]:
            await msg.reply(f"❌ {vr['message']}\n请在Web控制台 /account 页面登录QQ音乐")
            return
        uin = vr["uin"]
        playlists = get_qq_user_playlists(uin, limit=50)
        if not playlists:
            await msg.reply("📋 暂无歌单")
            return
        lines = [f"🎵 我的QQ音乐歌单 ({len(playlists)} 个):"]
        for pl in playlists[:30]:
            tc = pl.get("trackCount", 0)
            lines.append(f"  ▎{pl['name']} ({tc}首)  (ID: {pl['id']})")
        await msg.reply("\n".join(lines))
    except Exception as e:
        logger.error(f"[命令:qq我的歌单] 出错: {e}")
        await msg.reply("⚠️ 获取歌单失败，请稍后再试")

@bot.command(name='当前账号')
async def account_info_cmd(msg: Message):
    """查询当前登录的网易云账号信息"""
    try:
        logger.info(f"[命令:当前账号] 用户={msg.author_id}")
        cookie_path = os.path.join(os.path.dirname(__file__), "Cookie", "cookie.txt")
        cookie = ""
        if os.path.exists(cookie_path):
            with open(cookie_path, "r", encoding="utf-8") as f:
                cookie = f.read().strip()
        has_cookie = bool(cookie)
        logger.info(f"[命令:当前账号] Cookie状态: {'已设置' if has_cookie else '未设置'}")

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        if cookie:
            headers["Cookie"] = cookie

        api_url = f"{MUSIC_API_BASE}/login/status"
        logger.info(f"[命令:当前账号] 调用: GET {api_url}")
        res = requests.get(api_url, headers=headers, timeout=10)
        body = res.json()
        data = body.get("data", {})
        account = data.get("account")
        profile = data.get("profile")
        logger.info(f"[命令:当前账号] 状态={res.status_code} 已登录={account is not None}")

        if not account:
            await msg.reply("❌ 当前未登录网易云账号\n请在Web控制台 /account 页面登录")
            return

        nickname = profile.get("nickname", "未知") if profile else "未知"
        uid = account.get("id", "?")
        vip_type = account.get("vipType", 0)
        if vip_type >= 7:
            vip_str = "SVIP"
        elif vip_type > 0:
            vip_str = "VIP"
        else:
            vip_str = "普通用户"

        logger.info(f"[命令:当前账号] 账号={nickname} uid={uid} vip={vip_str}")
        uid_str = str(uid)
        n = len(uid_str)
        if n > 4:
            head = (n - 4) // 2
            uid_str = uid_str[:head] + "****" + uid_str[head + 4:]
        info = (
            f"🎵 当前网易云账号:\n"
            f"▎昵称: {nickname}\n"
            f"▎UID: {uid_str}\n"
            f"▎身份: {vip_str}"
        )
        await msg.reply(info)
    except Exception as e:
        logger.error(f"[命令:当前账号] 出错: {e}")
        await msg.reply("⚠️ 获取账号信息失败，请稍后再试")

@bot.command(name='qq当前账号')
async def qq_account_info_cmd(msg: Message):
    """查询当前登录的QQ音乐账号信息，含Cookie存活验证"""
    try:
        logger.info(f"[命令:qq当前账号] 用户={msg.author_id}")
        from qq_utils import verify_qq_cookie
        result = verify_qq_cookie()
        raw_uin = result["uin"] or ""

        def _mask_uin(uin):
            """QQ号中间四位脱敏"""
            n = len(uin)
            if n <= 4:
                return uin[:1] + "****" if n > 0 else "未知"
            head_len = (n - 4) // 2
            return uin[:head_len] + "****" + uin[head_len + 4:]

        display_uin = _mask_uin(raw_uin) if raw_uin else "未知"

        if not result["valid"]:
            if raw_uin:
                await msg.reply(
                    f"⚠️ QQ音乐Cookie已失效\n"
                    f"▎QQ号: {display_uin}\n"
                    f"▎原因: {result['message']}\n\n"
                    f"请在Web控制台 /account 页面重新登录"
                )
            else:
                await msg.reply("❌ 当前未登录QQ音乐账号\n请在Web控制台 /account 页面切换到QQ音乐登录")
            return

        logger.info(f"[命令:qq当前账号] UIN={raw_uin} 验证通过")
        from qq_utils import _format_expiry
        exp_str = _format_expiry(result.get("expires_in", -1)) if result.get("expires_in", -1) > 0 else "未知"
        info = (
            f"🎵 当前QQ音乐账号:\n"
            f"▎QQ号: {display_uin}\n"
            f"▎状态: Cookie有效 ({exp_str}后过期)"
        )
        await msg.reply(info)
    except Exception as e:
        logger.error(f"[命令:qq当前账号] 出错: {e}")
        await msg.reply("⚠️ 获取QQ音乐账号信息失败，请稍后再试")

@bot.command(name='bili')
async def bili_cmd(msg: Message, music_input: str = '', page_input: str = '0'):
    """搜索并播放B站音频，支持 /bili BVxxxx [分P序号]"""
    try:
        if not music_input.strip():
            await msg.reply("❌ 请指定关键词，例如: `/bili 春日影`")
            return
        logger.info(f"[命令:bili] 用户={msg.author_id} 输入={music_input} 分P={page_input}")
        voice_channel_id = await find_user_voice_channel(msg.ctx.guild.id, msg.author_id)
        if voice_channel_id is None:
            await msg.reply("❌ 请先加入语音频道")
            return

        import re
        bv_match = re.match(r'(BV[0-9A-Za-z]{10})', music_input, re.IGNORECASE)
        _target_page = max(1, int(page_input)) if page_input.isdigit() else 1
        _total_pages = 0
        if bv_match:
            # P0：BV号直解析，跳过搜索API（避免被风控ban）
            bvid = bv_match.group(1)
            logger.info(f"[命令:bili] BV直解析: {bvid} 目标分P={_target_page}")
            bv_songs = search_bili_bvid(bvid)
            if not bv_songs:
                await msg.reply("❌ 无法解析该BV号，请确认BV号正确")
                return
            _total_pages = len(bv_songs)
            if _target_page > _total_pages:
                await msg.reply(f"❌ 分P序号超出范围（共 {_total_pages} P）")
                return
            idx = _target_page - 1
            song = bv_songs[idx]
            song_name = song.get('name', music_input)
            artist_name = song.get('ar', [{}])[0].get('name', '未知')
            page = song.get('page_number', _target_page)
            play_info = get_bili_play_url(bvid, page)
        else:
            songs = search_bili_music(music_input)
            if not songs:
                await msg.reply("❌ 未搜索到B站视频")
                return

            song = songs[0]
            bvid = song.get('bvid', '')
            song_name = song.get('name', music_input)
            artist_name = song.get('ar', [{}])[0].get('name', '未知')

            logger.info(f"[命令:bili] 选中: {song_name} - {artist_name} (bvid={bvid})")

            play_info = get_bili_play_url(bvid)
        if not play_info:
            await msg.reply("❌ 获取音频流失败，可能是海外限制或版权原因")
            return

        music_url = play_info["raw_url"]
        logger.info(f"[命令:bili] 获取到URL: {music_url[:80]}...")

        if play_info.get("title") and not bv_match:
            song_name = f"[B站] {song_name} - {play_info['title']}"

        player = kookvoice.Player(voice_channel_id, BOT_TOKEN)
        extra_data = {
            "音乐名字": song_name, "点歌人": msg.author_id, "文字频道": msg.ctx.channel.id,
            "platform": "bili",
            "duration": play_info.get("duration", 0),  # 方案A：API已知时长
        }
        player.add_music(music_url, extra_data)
        logger.info(f"[命令:bili] 已加入队列: {song_name} (时长={play_info.get('duration', 0)}s)")

        _page_hint = ""
        if _total_pages > 1:
            _page_hint = f" (P{_target_page}/{_total_pages})"
        await msg.reply(f"✅ {song_name}{_page_hint} 已加入播放队列 (B站)")

    except Exception as e:
        logger.error(f"[命令:bili] 出错: {e}")
        await msg.reply("⚠️ 播放失败，请稍后再试")

@bot.command(name='bili歌单')
async def bili_playlist_cmd(msg: Message, fav_input: str = ''):
    """导入B站收藏夹"""
    try:
        if not fav_input.strip():
            await msg.reply("❌ 请指定收藏夹ID，例如: `/bili歌单 123456789`")
            return
        logger.info(f"[命令:bili歌单] 用户={msg.author_id} 输入={fav_input}")
        voice_channel_id = await find_user_voice_channel(msg.ctx.guild.id, msg.author_id)
        if voice_channel_id is None:
            await msg.reply("❌ 请先加入语音频道")
            return

        media_id = fav_input.strip()
        if not media_id.isdigit():
            await msg.reply("❌ 收藏夹ID应为纯数字")
            return

        # 获取收藏夹名称
        from bili_utils import get_bili_favorite_collections as _get_cols
        fav_name = f"收藏夹{media_id}"
        try:
            cols = _get_cols()
            for c in cols:
                if str(c["id"]) == media_id:
                    fav_name = c["title"]
                    break
        except Exception:
            pass

        await msg.reply(f"🎶 正在获取B站收藏夹「{fav_name}」...")

        songs = get_bili_favorite_all_tracks(media_id)
        if not songs:
            await msg.reply("❌ 收藏夹为空或无法获取歌曲列表")
            return

        player = kookvoice.Player(voice_channel_id, BOT_TOKEN)
        for song in songs:
            extra_data = {
                "音乐名字": song['name'],
                "title": song['name'],
                "artist": song['artist'],
                "点歌人": msg.author_id,
                "文字频道": msg.ctx.channel.id,
                "歌单来源": fav_name,
                "platform": "bili",
            }
            player.add_music(song['marker'], extra_data)

        prefetched = refill_bili_playlist_queue(voice_channel_id, kookvoice.play_list)
        logger.info(f"[命令:bili歌单] 完成 导入{len(songs)}首 预取{prefetched}首")
        await msg.reply(f"✅ 已导入B站收藏夹「{fav_name}」共 {len(songs)} 首歌曲")

    except Exception as e:
        logger.error(f"[命令:bili歌单] 出错: {e}")
        await msg.reply("⚠️ 导入失败，请稍后再试")

@bot.command(name='bili我的歌单')
async def bili_playlists_cmd(msg: Message):
    """列出当前登录B站账号的收藏夹"""
    try:
        logger.info(f"[命令:bili我的歌单] 用户={msg.author_id}")
        from bili_utils import verify_bili_cookie
        vr = verify_bili_cookie()
        if not vr["valid"]:
            await msg.reply(f"❌ {vr['message']}\n请在Web控制台 /account 页面登录B站")
            return
        playlists = get_bili_favorite_collections()
        if not playlists:
            await msg.reply("📋 暂无收藏夹")
            return
        lines = [f"🎵 我的B站收藏夹 ({len(playlists)} 个):"]
        for pl in playlists[:30]:
            lines.append(f"  ▎{pl['title']} ({pl.get('count', 0)}个视频)  (ID: {pl['id']})")
        await msg.reply("\n".join(lines))
    except Exception as e:
        logger.error(f"[命令:bili我的歌单] 出错: {e}")
        await msg.reply("⚠️ 获取收藏夹失败，请稍后再试")

@bot.command(name='bili当前账号')
async def bili_account_cmd(msg: Message):
    """查询当前登录的B站账号信息"""
    try:
        logger.info(f"[命令:bili当前账号] 用户={msg.author_id}")
        from bili_utils import verify_bili_cookie, get_bili_user_info
        vr = verify_bili_cookie()
        if not vr["valid"]:
            await msg.reply(f"❌ {vr['message']}")
            return
        user = get_bili_user_info()
        raw_uid = str(vr.get('uid', '') or '')
        def _mask_bili_uid(uid):
            n = len(uid)
            if n <= 4:
                return uid[:1] + "****" if n > 0 else "未知"
            head_len = (n - 4) // 2
            return uid[:head_len] + "****" + uid[head_len + 4:]
        display_uid = _mask_bili_uid(raw_uid) if raw_uid else "未知"
        if not user:
            await msg.reply(f"✅ 已登录B站 (UID: {display_uid})\n昵称: {vr['uname']}")
            return
        lines = [
            "🎬 B站账号信息",
            f"  昵称: {user['uname']}",
            f"  UID: {display_uid}",
            f"  等级: Lv{user['level']}",
        ]
        vip_map = {0: "无", 1: "月度大会员", 2: "年度大会员"}
        lines.append(f"  会员: {vip_map.get(user.get('vip_type', 0), '未知')}")
        await msg.reply("\n".join(lines))
    except Exception as e:
        logger.error(f"[命令:bili当前账号] 出错: {e}")
        await msg.reply("⚠️ 获取B站账号信息失败，请稍后再试")

PAGE_SIZE = 20

@bot.command(name='播放列表')
async def playlist_cmd(msg: Message, page_input: str = ''):
    """查看当前播放列表，支持 /播放列表 <页数> 翻页"""
    try:
        ch = await _resolve_channel(msg.ctx.guild.id, msg.author_id)
        logger.info(f"[命令:播放列表] 用户={msg.author_id} 服务器={msg.ctx.guild.id} 页={page_input or '1'} 频道={ch}")
        if not ch:
            await msg.reply("📋 当前没有播放列表")
            return

        guild_pl = kookvoice.play_list[ch]
        now_playing = guild_pl.get("now_playing")
        queue = guild_pl.get("play_list", [])
        total = len(queue)
        total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        logger.info(f"[命令:播放列表] 正在播放={now_playing is not None} 队列={total}首")

        page = 1
        if page_input.strip():
            try:
                page = int(page_input.strip())
                if page < 1 or page > total_pages:
                    await msg.reply(f"❌ 页数超出范围，共 {total_pages} 页")
                    return
            except ValueError:
                await msg.reply(f"❌ 页数格式错误，请输入数字（1~{total_pages}）")
                return

        start = (page - 1) * PAGE_SIZE
        end = min(start + PAGE_SIZE, total)

        lines = [f"📋 播放列表 (第 {page}/{total_pages} 页，共 {total} 首):"]

        if now_playing:
            extra = now_playing.get("extra", {})
            name = extra.get("音乐名字") or extra.get("title", "未知歌曲")
            lines.append(f"▶️ 正在播放: {name}")
        else:
            lines.append("▶️ 当前未在播放")

        if queue:
            for i in range(start, end):
                item = queue[i]
                extra = item.get("extra", {})
                name = extra.get("音乐名字") or extra.get("title", "未知歌曲")
                lines.append(f"  {i + 1}. {name}")
        elif not now_playing:
            lines.append("  (空)")

        if total_pages > 1:
            lines.append(f"💡 输入 /播放列表 <页数> 翻页")

        await msg.reply("\n".join(lines))
    except Exception as e:
        logger.error(f"[命令:播放列表] 出错: {e}")
        await msg.reply("⚠️ 获取播放列表失败，请稍后再试")

@bot.command(name='清空列表')
async def clear_playlist_cmd(msg: Message):
    """清空当前播放列表"""
    try:
        ch = await _resolve_channel(msg.ctx.guild.id, msg.author_id)
        logger.info(f"[命令:清空列表] 用户={msg.author_id} 服务器={msg.ctx.guild.id} 频道={ch}")
        if not ch:
            await msg.reply("📋 当前没有播放列表")
            return
        queue_len = len(kookvoice.play_list[ch].get('play_list', []))
        logger.info(f"[命令:清空列表] 当前队列={queue_len}首")

        if queue_len == 0:
            await msg.reply("📋 播放列表本来就是空的")
            return

        kookvoice.play_list[ch]['play_list'] = []
        await msg.reply(f"✅ 已清空播放列表（共移除 {queue_len} 首歌曲）")
    except Exception as e:
        logger.error(f"[命令:清空列表] 出错: {e}")
        await msg.reply("⚠️ 清空播放列表失败，请稍后再试")

@bot.command(name='播放第')
async def play_index_cmd(msg: Message, index_input: str = ''):
    """跳转到播放队列中指定序号的歌曲"""
    try:
        if not index_input.strip():
            await msg.reply("❌ 请指定歌曲序号，例如: `/播放第3首`")
            return
        ch = await _resolve_channel(msg.ctx.guild.id, msg.author_id)
        logger.info(f"[命令:播放第] 用户={msg.author_id} 输入={index_input} 频道={ch}")

        import re
        m = re.search(r'(\d+)', str(index_input))
        if not m:
            await msg.reply("❌ 请指定歌曲序号，例如: `/播放第3首`")
            return
        target = int(m.group(1))

        if not ch:
            await msg.reply("📋 当前没有播放列表")
            return

        queue = kookvoice.play_list[ch].get('play_list', [])
        now_playing = kookvoice.play_list[ch].get('now_playing')
        logger.info(f"[命令:播放第] 队列={len(queue)}首 目标={target}")

        if target < 1 or target > len(queue):
            await msg.reply(f"❌ 序号超出范围，当前队列共 {len(queue)} 首歌曲")
            return

        target_item = queue[target - 1]
        extra = target_item.get('extra', {})
        song_name = extra.get('音乐名字') or extra.get('title', '未知歌曲')

        if target > 1:
            kookvoice.play_list[ch]['play_list'] = queue[target - 1:]
            logger.info(f"[命令:播放第] 移除前 {target - 1} 首，剩余 {len(kookvoice.play_list[ch]['play_list'])} 首")

        player = kookvoice.Player(ch)
        player.skip()

        await msg.reply(f"⏭️ 已切至第 {target} 首: **{song_name}**")
    except Exception as e:
        logger.error(f"[命令:播放第] 出错: {e}")
        await msg.reply("⚠️ 切换失败，请稍后再试")

@bot.command(name='帮助')
async def help_cmd(msg: Message):
    """显示所有可用指令"""
    logger.info(f"[命令:帮助] 用户={msg.author_id}")
    help_text = (
        "📋 **KOOK 音乐机器人 指令列表**\n"
        "*Built by @gen*\n\n"
        "🎵 **网易云音乐**\n"
        "/wy `歌曲名` — 搜索并播放网易云音乐\n"
        "/wygd `歌单ID/链接` — 导入网易云歌单\n"
        "/wy我的歌单 — 查看我的网易云歌单\n\n"
        "🎵 **QQ音乐**\n"
        "/qq `歌曲名` — 搜索并播放QQ音乐\n"
        "/qqgd `歌单ID/链接` — 导入QQ音乐歌单\n"
        "/qq我的歌单 — 查看我的QQ音乐歌单\n\n"
        "🎬 **B站**\n"
        "/bili `关键词` `[分P]` — 搜索/BV直解析B站音频，可指定分P\n"
        "/bili歌单 `收藏夹ID` — 导入B站收藏夹\n"
        "/bili我的歌单 — 查看我的B站收藏夹\n\n"
        "🎵 **音乐控制**\n"
        "/加入 — 加入你所在的语音频道\n"
        "/暂停 — 暂停当前播放\n"
        "/继续 — 继续播放\n"
        "/跳过 — 跳过当前歌曲\n"
        "/单曲循环 — 切换单曲循环开关\n"
        "/随机播放 — 切换随机播放开关\n"
        "/播放第N首 — 切到队列第N首歌\n"
        "/停止 — 停止播放\n"
        "/清空列表 — 清空播放队列\n"
        "/脱离卡死 — 重置所有播放状态\n\n"
        "📋 **查询**\n"
        "/播放列表 `[页数]` — 查看当前播放队列（20首/页）\n"
        "/当前账号 — 查看登录的网易云账号\n"
        "/qq当前账号 — 查看登录的QQ音乐账号\n"
        "/bili当前账号 — 查看登录的B站账号\n"
        "/ping — 测试机器人连接\n"
        "/版本信息 — 查看当前版本与历史版本\n"
        "/帮助 — 显示本帮助信息"
    )
    await msg.reply(help_text)

@bot.command(name='版本信息')
async def version_cmd(msg: Message):
    """从 README 读取并回复当前版本及最近历史版本"""
    try:
        logger.info(f"[命令:版本信息] 用户={msg.author_id}")
        readme_path = os.path.join(os.path.dirname(__file__), "README.md")
        if not os.path.exists(readme_path):
            await msg.reply("V2.2 (2026-05-27)")
            return

        with open(readme_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        current = ""
        versions = []
        in_table = False
        for line in lines:
            s = line.strip()
            # 解析当前版本行: > **当前版本**: V2.2 | **发布日期**: 2026-05-27
            if s.startswith("> **当前版本**:"):
                current = s.replace("> **当前版本**:", "").replace("**", "").strip()
            # 版本表格行: | **V2.2** | 2026-05-27 | 功能增强 | ... |
            if s.startswith("| **V") and "|" in s:
                in_table = True
                parts = [p.strip() for p in s.split("|")]
                if len(parts) >= 4:
                    ver = parts[1].replace("**", "")
                    date = parts[2]
                    vtype = parts[3]
                    desc = parts[4] if len(parts) > 4 else ""
                    versions.append((ver, date, vtype, desc))
            elif in_table and not s.startswith("|"):
                break

        lines_out = [f"**KOOK 音乐机器人**", f"当前: {current}", ""]
        show = versions[:3]
        for i, (ver, date, vtype, desc) in enumerate(show):
            prefix = "●" if i == 0 else "○"
            lines_out.append(f"{prefix} **{ver}** ({date}) [{vtype}]")
            if desc:
                lines_out.append(f"  {desc[:80]}{'…' if len(desc) > 80 else ''}")

        await msg.reply("\n".join(lines_out))
    except Exception as e:
        logger.error(f"[命令:版本信息] 出错: {e}")
        await msg.reply("V2.2 (2026-05-27)")

# 启动异步事件循环
def start_bot_loop():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    kookvoice.set_loop(loop)  # 建立线程安全的桥接，使 PlayHandler 能调度事件到 bot 事件循环

    def _shutdown_loop():
        """优雅关闭事件循环：取消所有待处理任务，避免 Windows ProactorEventLoop 管道泄漏"""
        pending = asyncio.all_tasks(loop)
        if not pending:
            return
        logger.info("[机器人] 正在取消 %d 个待处理任务...", len(pending))
        for task in pending:
            task.cancel()
        # 等待所有任务完成取消
        try:
            loop.run_until_complete(
                asyncio.wait(pending, timeout=5)
            )
        except Exception:
            pass
        logger.info("[机器人] 任务已清理")

    try:
        # 验证Token
        logger.info("[机器人] 验证Token...")
        if not loop.run_until_complete(verify_token()):
            logger.error("Token验证失败，请检查配置")
            _shutdown_loop()
            return

        # 预先在事件循环中启动心跳任务（必须在 bot.start() 前调度，因为 bot.start() 是长连接协程不返回）
        async def _heartbeat_task():
            while True:
                try:
                    with open(HEARTBEAT_FILE, "w") as f:
                        f.write(str(time.time()))
                except Exception:
                    pass
                await asyncio.sleep(30)
        loop.create_task(_heartbeat_task())
        logger.info("[机器人] 心跳任务已就绪")

        # 启动机器人（阻塞协程，处理 WebSocket 网关直到断开）
        logger.info("[机器人] 启动中...")
        loop.run_until_complete(bot.start())

    except Exception as e:
        logger.error(f"[机器人] 启动异常: {str(e)}")
        _shutdown_loop()
        return

    # 保持运行
    try:
        loop.run_forever()
    except (KeyboardInterrupt, SystemExit):
        logger.info("[机器人] 收到退出信号")
    except Exception as e:
        logger.error(f"[机器人] 运行异常: {e}")
    finally:
        _shutdown_loop()
        try:
            loop.close()
        except Exception:
            pass
        logger.info("[机器人] 事件循环已关闭")

# 导入路由
try:
    from .routes import register_routes
    from .account_api import register_account_routes
except ImportError:
    from routes import register_routes
    from account_api import register_account_routes

# 启动机器人线程
bot_thread = threading.Thread(target=start_bot_loop)
bot_thread.daemon = True
bot_thread.start()

def create_app():
    # 注册路由
    register_routes(app, bot, socketio if socketio_available else None)
    register_account_routes(app)

    # 注册QQ音乐账号路由
    try:
        from .qq_account_api import register_qq_account_routes
    except ImportError:
        from qq_account_api import register_qq_account_routes
    register_qq_account_routes(app)

    # 注册B站账号路由
    try:
        from .bili_account_api import register_bili_account_routes
    except ImportError:
        from bili_account_api import register_bili_account_routes
    register_bili_account_routes(app)

    return app

# 测试路由
@app.route('/api/debug')
def debug():
    try:
        # 测试基础功能
        bot_status = "运行中" if bot.is_running else "未运行"
        
        # 添加播放列表信息
        import kookvoice
        active_guilds = len(kookvoice.play_list) if hasattr(kookvoice, 'play_list') else 0
        playing_songs = 0
        queued_songs = 0
        
        if hasattr(kookvoice, 'play_list'):
            for guild_data in kookvoice.play_list.values():
                if guild_data.get('now_playing'):
                    playing_songs += 1
                queued_songs += len(guild_data.get('play_list', []))
        
        return jsonify({
            "status": "success",
            "bot_status": bot_status,
            "active_guilds": active_guilds,
            "playing_songs": playing_songs,
            "queued_songs": queued_songs,
            "token_valid": bool(BOT_TOKEN),
            "ffmpeg_path": os.path.exists(FFMPEG_PATH)
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)})

if __name__ == '__main__':
    if socketio_available and socketio:
        socketio.run(app, host=HOST, port=PORT, debug=DEBUG, log_output=False)
    else:
        app.run(host=HOST, port=PORT, debug=DEBUG, use_reloader=False)