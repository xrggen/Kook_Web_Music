from flask import Flask, render_template, request, jsonify, redirect, url_for
import os
import json
import asyncio
import sys
import time
from typing import Dict, Any, List, Union, Optional
import threading
import requests
import logging
from logging.handlers import RotatingFileHandler
import shlex
from khl import Bot, Message, MessageTypes
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
    from .kookvoice.requestor import VoiceRequestor
    from .config import *
    from .runtime_health import runtime_health
    from .utils import search_music, get_music_url, get_playlist, get_playlist_urls, refill_playlist_queue, load_cookie_header
    from .qq_utils import search_qq_music, get_qq_music_url, get_qq_playlist, get_qq_playlist_urls, refill_qq_playlist_queue, verify_qq_cookie, get_qq_user_playlists, _format_expiry
    from .bili_utils import search_bili_music, get_bili_play_url, get_bili_favorite_collections, get_bili_favorite_all_tracks, refill_bili_playlist_queue, search_bili_bvid, verify_bili_cookie, get_bili_user_info
except ImportError:
    import kookvoice
    from kookvoice.requestor import VoiceRequestor
    from config import *
    from runtime_health import runtime_health
    from utils import search_music, get_music_url, get_playlist, get_playlist_urls, refill_playlist_queue, load_cookie_header
    from qq_utils import search_qq_music, get_qq_music_url, get_qq_playlist, get_qq_playlist_urls, refill_qq_playlist_queue, verify_qq_cookie, get_qq_user_playlists, _format_expiry
    from bili_utils import search_bili_music, get_bili_play_url, get_bili_favorite_collections, get_bili_favorite_all_tracks, refill_bili_playlist_queue, search_bili_bvid, verify_bili_cookie, get_bili_user_info

# 配置日志。run.py 可能已经初始化根日志器，因此不能再次依赖 basicConfig。
class _PrivateRotatingFileHandler(RotatingFileHandler):
    def _open(self):
        stream = super()._open()
        if os.name != 'nt':
            try:
                os.chmod(self.baseFilename, 0o600)
            except OSError:
                pass
        return stream


_log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'debug.log')
_root_logger = logging.getLogger()
_root_logger.setLevel(logging.INFO)
_formatter = logging.Formatter(
    '%(asctime)s - %(levelname)s - %(name)s - %(message)s'
)
if not any(
    isinstance(handler, logging.FileHandler)
    and os.path.abspath(getattr(handler, 'baseFilename', '')) == _log_path
    for handler in _root_logger.handlers
):
    _file_handler = _PrivateRotatingFileHandler(
        _log_path,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding='utf-8',
    )
    _file_handler.setFormatter(_formatter)
    _root_logger.addHandler(_file_handler)
if not any(type(handler) is logging.StreamHandler for handler in _root_logger.handlers):
    _stream_handler = logging.StreamHandler()
    _stream_handler.setFormatter(_formatter)
    _root_logger.addHandler(_stream_handler)
logger = logging.getLogger(__name__)

# 只关闭Flask的HTTP访问日志，保留其他日志
logging.getLogger('werkzeug').setLevel(logging.ERROR)

# Bot 与 Web 使用独立心跳，避免活跃的 Flask 请求掩盖 Bot 事件循环卡死。
BOT_HEARTBEAT_FILE = os.path.join(os.path.dirname(__file__), ".bot_heartbeat")
WEB_HEARTBEAT_FILE = os.path.join(os.path.dirname(__file__), ".web_heartbeat")


def _write_heartbeat(path):
    with open(path, "w", encoding="ascii") as heartbeat:
        heartbeat.write(str(time.time()))


def _update_heartbeat():
    """记录 Web 服务心跳；Bot 看门狗使用独立文件。"""
    try:
        _write_heartbeat(WEB_HEARTBEAT_FILE)
    except Exception:
        logger.exception("更新Web心跳失败")


# 配置KOOK机器人
# khl 在构造阶段要求非空字符串；占位值仅用于无凭据的导入、测试与配置
# 错误提示，实际联网前仍由 BOT_TOKEN 的空值检查阻断。
_BOT_CLIENT_TOKEN = BOT_TOKEN or "UNCONFIGURED_BOT_TOKEN"
bot = Bot(
    token=_BOT_CLIENT_TOKEN,
    compress=True  # 启用压缩
)


def _install_gateway_activity_probe():
    """把任意 KOOK 网关数据包（包括 Pong）记录为连接活动。"""
    receiver = getattr(getattr(bot.client, "gate", None), "receiver", None)
    original = getattr(receiver, "_handle_raw", None)
    if receiver is None or original is None:
        logger.warning("[机器人] 当前 khl.py 版本不支持网关活动探针")
        return False
    if getattr(receiver, "_kook_music_health_probe", False):
        runtime_health.mark_gateway_probe_available()
        return True

    async def _monitored_handle_raw(raw):
        runtime_health.mark_gateway_activity()
        return await original(raw)

    receiver._handle_raw = _monitored_handle_raw
    receiver._kook_music_health_probe = True
    runtime_health.mark_gateway_probe_available()
    return True


_install_gateway_activity_probe()

# ========== 权限白名单 ==========
def _is_allowed(msg: Message) -> bool:
    """检查消息发送者是否在白名单内。全部白名单为空时默认拒绝；
       多个白名单均非空时取交集（必须同时满足）。"""
    if not ALLOWGROUP and not ALLOWCHANNEL and not ALLOWUSER:
        return BOT_ALLOW_UNRESTRICTED

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
        command_name = str(msg.content).split(maxsplit=1)[0][:32]
        logger.info(
            "[权限] 拒绝: 用户=%s 频道=%s 服务器=%s 指令=%s",
            msg.author_id, msg.ctx.channel.id, msg.ctx.guild.id,
            command_name,
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
        await channel.send(f"🎵 正在播放: {song_name}", type=MessageTypes.TEXT)
    except Exception as e:
        logger.error(f"[播放通知] 发送失败: {type(e).__name__}")

# 强制验证Token有效性
async def verify_token() -> bool:
    if not BOT_TOKEN:
        logger.error("未配置BOT_TOKEN，请先运行 create_env.py")
        return False
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
        logger.error("Token验证失败: %s", type(e).__name__)
        return False

# 配置FFMPEG
try:
    kookvoice.set_ffmpeg(FFMPEG_PATH)
    kookvoice.configure_logging(True)  # 启用日志记录
    logger.info(f"FFMPEG路径: {FFMPEG_PATH}")
    logger.info(f"FFPROBE路径: {FFPROBE_PATH}")
except Exception as e:
    logger.error("FFMPEG配置错误: %s", type(e).__name__)
    sys.exit(1)

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
        logger.error(f"获取语音频道ID异常: {type(e).__name__}")
        return None

# 获取服务器列表
async def get_guild_list():
    try:
        guilds = await bot.client.gate.request('GET', 'guild/list')
        if guilds and "items" in guilds:
            return guilds["items"]
        return []
    except Exception as e:
        logger.error(f"获取服务器列表异常: {type(e).__name__}")
        return []

# 获取频道列表
async def get_channel_list(guild_id):
    try:
        channels = await bot.client.gate.request('GET', 'channel/list', params={'guild_id': guild_id})
        if channels and "items" in channels:
            return channels["items"]
        return []
    except Exception as e:
        logger.error(f"获取频道列表异常: {type(e).__name__}")
        return []

# 根据用户所在频道或服务器内唯一活跃频道，定位控制目标
async def _resolve_channel(guild_id: str, user_id: str):
    """返回目标语音频道ID。先查用户所在频道，再回退到服务器内唯一活跃频道。"""
    playlists = kookvoice.get_state_snapshot()['play_list']
    user_ch = await find_user_voice_channel(guild_id, user_id)
    if user_ch and user_ch in playlists:
        return user_ch
    active = [ch_id for ch_id, data in playlists.items()
              if data.get('guild_id') == guild_id]
    if len(active) == 1:
        return active[0]
    return None


def _queue_has_capacity(channel_id, requested):
    snapshot = kookvoice.get_state_snapshot()
    state = snapshot['play_list'].get(str(channel_id), {})
    return len(state.get('play_list', [])) + max(0, int(requested)) <= MAX_QUEUE_TRACKS

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
            await msg.reply(f"✅ 已加入语音频道 #{voice_channel_info.name}", type=MessageTypes.TEXT)
            return True
        logger.warning(f"[命令:加入] 用户不在语音频道")
        await msg.reply("❌ 您当前不在语音频道中")
    except Exception as e:
        logger.error(f"[命令:加入] 出错: {type(e).__name__}")
        await msg.reply("⚠️ 加入失败，请检查权限或稍后再试")

@bot.command(name='wy')
async def play_music(msg: Message, music_input: str = ''):
    """播放音乐"""
    try:
        if not music_input.strip():
            await msg.reply("❌ 请指定歌曲名，例如: `/wy 晴天`")
            return
        logger.info(f"[命令:wy] 用户={msg.author_id}")
        voice_channel_id = await find_user_voice_channel(msg.ctx.guild.id, msg.author_id)
        if voice_channel_id is None:
            await msg.reply("❌ 请先加入语音频道")
            return

        if music_input.strip().lower().startswith(("http://", "https://")):
            await msg.reply("❌ 为保护服务主机，已禁用任意媒体直链；请使用歌曲名搜索")
            return
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

            logger.info("[命令:wy] 选中 name=%r artist=%r id=%r", str(song_name)[:120], str(artist_name)[:120], str(song_id)[:64])

            # 获取歌曲URL (utils.get_music_url already logs the API call)
            music_url = get_music_url(song_id)
            if not music_url:
                logger.warning(f"[命令:wy] 获取URL失败 song_id={song_id}")
                await msg.reply("❌ 获取播放地址失败，可能是VIP歌曲")
                return

        except requests.exceptions.Timeout:
            await msg.reply("❌ 网络超时，请稍后重试")
            return
        except requests.exceptions.ConnectionError:
            await msg.reply("❌ 无法连接到音乐API服务器")
            return
        except Exception as e:
            logger.error(f"[命令:wy] 搜索/取链异常: {type(e).__name__}")
            await msg.reply("❌ 搜索或获取播放地址失败")
            return

        # 添加音乐到播放队列
        player = kookvoice.Player(voice_channel_id, BOT_TOKEN)
        extra_data = {
            "音乐名字": song_name,
            "title": song_name,
            "歌手": artist_name,
            "artist": artist_name,
            "点歌人": msg.author_id,
            "文字频道": msg.ctx.channel.id,
        }
        player.add_music(music_url, extra_data, msg.ctx.guild.id)
        logger.info("[命令:wy] 已加入队列 name=%r", str(song_name)[:120])

        await msg.reply(f"✅ {song_name} 已加入播放队列", type=MessageTypes.TEXT)

    except Exception as e:
        logger.error(f"[命令:wy] 出错: {type(e).__name__}")
        await msg.reply("⚠️ 播放失败，请稍后再试")

@bot.command(name='qq')
async def qq_cmd(msg: Message, music_input: str = ''):
    """播放QQ音乐"""
    try:
        if not music_input.strip():
            await msg.reply("❌ 请指定歌曲名，例如: `/qq 晴天`")
            return
        logger.info(f"[命令:qq] 用户={msg.author_id}")
        voice_channel_id = await find_user_voice_channel(msg.ctx.guild.id, msg.author_id)
        if voice_channel_id is None:
            await msg.reply("❌ 请先加入语音频道")
            return

        if music_input.strip().lower().startswith(("http://", "https://")):
            await msg.reply("❌ 为保护服务主机，已禁用任意媒体直链；请使用歌曲名搜索")
            return
        songs = search_qq_music(music_input)
        if not songs:
            await msg.reply("❌ 未搜索到QQ音乐歌曲")
            return

        song = songs[0]
        songmid = song['id']
        song_name = song.get('name', music_input)
        artist_name = song.get('ar', [{}])[0].get('name', '未知')

        logger.info("[命令:qq] 选中 name=%r artist=%r songmid=%r", str(song_name)[:120], str(artist_name)[:120], str(songmid)[:64])

        music_url = get_qq_music_url(songmid)
        if not music_url:
            logger.warning(f"[命令:qq] 获取URL失败 songmid={songmid}")
            await msg.reply("❌ 获取播放地址失败，可能是VIP歌曲")
            return

        player = kookvoice.Player(voice_channel_id, BOT_TOKEN)
        extra_data = {
            "音乐名字": song_name,
            "title": song_name,
            "歌手": artist_name,
            "artist": artist_name,
            "点歌人": msg.author_id,
            "文字频道": msg.ctx.channel.id,
        }
        player.add_music(music_url, extra_data, msg.ctx.guild.id)
        logger.info("[命令:qq] 已加入队列 name=%r", str(song_name)[:120])

        await msg.reply(f"✅ {song_name} 已加入播放队列 (QQ音乐)", type=MessageTypes.TEXT)

    except Exception as e:
        logger.error(f"[命令:qq] 出错: {type(e).__name__}")
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
        logger.error(f"[命令:停止] 出错: {type(e).__name__}")
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
        logger.error(f"[命令:跳过] 出错: {type(e).__name__}")
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
        logger.error(f"[命令:暂停] 出错: {type(e).__name__}")
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
        logger.error(f"[命令:继续] 出错: {type(e).__name__}")
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
        suffix = "（列表循环已关闭）" if enabled else ""
        await msg.reply(f"🔂 单曲循环已{'开启' if enabled else '关闭'}{suffix}")
    except Exception as e:
        logger.error(f"[命令:单曲循环] 出错: {type(e).__name__}")
        await msg.reply("⚠️ 操作失败，请稍后再试")

@bot.command(name='循环播放列表')
async def playlist_repeat_cmd(msg: Message):
    """切换列表循环开关"""
    try:
        logger.info(f"[命令:循环播放列表] 用户={msg.author_id} 服务器={msg.ctx.guild.id}")
        ch = await _resolve_channel(msg.ctx.guild.id, msg.author_id)
        if not ch:
            await msg.reply("❌ 当前没有正在播放的频道")
            return
        player = kookvoice.Player(ch)
        enabled = player.playlist_repeat_toggle()
        suffix = "（单曲循环已关闭）" if enabled else ""
        await msg.reply(f"🔁 列表循环已{'开启' if enabled else '关闭'}{suffix}")
    except Exception as e:
        logger.error(f"[命令:循环播放列表] 出错: {type(e).__name__}")
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
            refill_playlist_queue(ch, kookvoice.play_list, lock=kookvoice.state_lock)
        except Exception:
            pass
        try:
            refill_qq_playlist_queue(ch, kookvoice.play_list, lock=kookvoice.state_lock)
        except Exception:
            pass
        if enabled:
            await msg.reply(f"🔀 随机播放已开启（{count} 首已打乱）")
        else:
            await msg.reply(f"🔀 随机播放已关闭（{count} 首已恢复原序）")
    except Exception as e:
        logger.error(f"[命令:随机播放] 出错: {type(e).__name__}")
        await msg.reply("⚠️ 操作失败，请稍后再试")

_playback_recovery_lock = threading.Lock()


async def _force_leave_voice_channels(channel_ids):
    """并发请求 KOOK 强制离开频道，返回确认成功与失败明细。"""
    if not channel_ids:
        return set(), {}

    requestor = VoiceRequestor(BOT_TOKEN)

    async def leave_one(channel_id):
        try:
            await asyncio.wait_for(requestor.leave(channel_id), timeout=5)
            logger.info("[脱离卡死] KOOK已确认离开频道: %s", channel_id)
            return channel_id, None
        except Exception as exc:
            logger.warning(
                "[脱离卡死] 离开频道 %s 未获确认（可能已经离开）: %s",
                channel_id,
                type(exc).__name__,
            )
            return channel_id, type(exc).__name__

    try:
        results = await asyncio.gather(
            *(leave_one(channel_id) for channel_id in channel_ids)
        )
    finally:
        try:
            await asyncio.wait_for(requestor.close(), timeout=2)
        except Exception:
            logger.exception("[脱离卡死] 关闭紧急KOOK请求会话失败")

    left = {channel_id for channel_id, error in results if error is None}
    failed = {
        channel_id: error
        for channel_id, error in results
        if error is not None
    }
    return left, failed


async def _perform_playback_recovery():
    """执行分阶段恢复，始终返回可用于用户反馈的恢复报告。"""
    all_channels = kookvoice.reset_playback_state()
    report = {
        'channels': set(all_channels),
        'left': set(),
        'leave_failed': {},
        'graceful': set(),
        'forced': set(),
        'detached': set(),
        'killed_processes': 0,
    }
    if not all_channels:
        return report

    unconfirmed_leave = set(all_channels)
    try:
        # KOOK脱离和本地Handler退出并行进行，避免多频道串行等待。
        leave_result, remaining = await asyncio.gather(
            _force_leave_voice_channels(all_channels),
            asyncio.to_thread(
                kookvoice.wait_for_handlers,
                all_channels,
                5.0,
            ),
        )
        report['left'], report['leave_failed'] = leave_result
        report['graceful'] = set(all_channels) - set(remaining)

        if remaining:
            report['killed_processes'] += await asyncio.to_thread(
                kookvoice.force_terminate_handler_processes,
                remaining,
            )
            remaining_after_force = await asyncio.to_thread(
                kookvoice.wait_for_handlers,
                remaining,
                2.0,
            )
            report['forced'] = set(remaining) - set(remaining_after_force)

            if remaining_after_force:
                report['killed_processes'] += await asyncio.to_thread(
                    kookvoice.force_terminate_handler_processes,
                    remaining_after_force,
                )
                # 最后手段：隔离旧Handler并释放频道注册表。旧线程迟到退出时会
                # 发现自己已失去所有权，因此不会离开或删除后续的新会话。
                report['detached'] = await asyncio.to_thread(
                    kookvoice.detach_stuck_handlers,
                    remaining_after_force,
                )
    finally:
        try:
            # 本地处理器已停止或隔离后再做一次最终脱离，覆盖“旧 join
            # 与首次 leave 交错”的窗口。恢复栅栏保证此时不会创建新会话。
            final_left, final_failed = await _force_leave_voice_channels(
                all_channels
            )
            report['left'].update(final_left)
            report['leave_failed'].update(final_failed)
            for channel_id in report['left']:
                report['leave_failed'].pop(channel_id, None)
            unconfirmed_leave = set(report['leave_failed'])
        finally:
            kookvoice.finish_playback_recovery(
                all_channels,
                unconfirmed_leave,
            )

    return report


@bot.command(name='脱离卡死')
async def reset_all_cmd(msg: Message):
    """分阶段恢复所有播放会话，并隔离无法退出的旧处理器。"""
    logger.info("[命令:脱离卡死] 用户=%s", msg.author_id)
    if not _playback_recovery_lock.acquire(blocking=False):
        await msg.reply("⏳ 紧急恢复正在执行，请勿重复触发")
        return

    try:
        report = await _perform_playback_recovery()
    except Exception:
        logger.exception("[命令:脱离卡死] 紧急恢复流程异常")
        await msg.reply("⚠️ 紧急恢复执行异常，请查看 debug.log；看门狗仍会继续检测")
        return
    finally:
        _playback_recovery_lock.release()

    channel_count = len(report['channels'])
    if channel_count == 0:
        await msg.reply("ℹ️ 当前没有需要恢复的播放会话")
        return

    logger.info(
        "[命令:脱离卡死] 完成 channels=%d left=%d graceful=%d "
        "forced=%d detached=%d killed_processes=%d leave_failed=%d",
        channel_count,
        len(report['left']),
        len(report['graceful']),
        len(report['forced']),
        len(report['detached']),
        report['killed_processes'],
        len(report['leave_failed']),
    )

    if report['leave_failed']:
        await msg.reply(
            "⚠️ 本地恢复已完成，但 KOOK 脱离未全部确认\n"
            f"▎处理频道: {channel_count}\n"
            f"▎未确认脱离: {len(report['leave_failed'])}\n"
            f"▎强制结束媒体进程: {report['killed_processes']}\n"
            f"▎隔离旧处理器: {len(report['detached'])}\n"
            "失败频道已保留，请再次执行 /脱离卡死 后再点歌"
        )
    elif report['detached']:
        await msg.reply(
            "⚠️ 紧急恢复已完成，可重新点歌\n"
            f"▎处理频道: {channel_count}\n"
            f"▎正常退出: {len(report['graceful'])}\n"
            f"▎强制结束媒体进程: {report['killed_processes']}\n"
            f"▎隔离旧处理器: {len(report['detached'])}\n"
            "旧处理器已失去会话所有权，不会清理后续新会话"
        )
    else:
        await msg.reply(
            "✅ 紧急恢复完成，可重新点歌\n"
            f"▎处理频道: {channel_count}\n"
            f"▎KOOK确认脱离: {len(report['left'])}\n"
            f"▎正常退出: {len(report['graceful'])}\n"
            f"▎强制退出: {len(report['forced'])}"
        )

@bot.command(name='wygd')
async def playlist_play(msg: Message, playlist_input: str = ''):
    """播放歌单 — 与 Web 控制台共用 get_playlist_urls 实现"""
    try:
        if not playlist_input.strip():
            await msg.reply("❌ 请指定歌单ID或链接，例如: `/wygd 123456789`")
            return
        logger.info(f"[命令:wygd] 用户={msg.author_id}")
        voice_channel_id = await find_user_voice_channel(msg.ctx.guild.id, msg.author_id)
        if voice_channel_id is None:
            await msg.reply("❌ 请先加入语音频道")
            return

        # 提取歌单ID（与前端 dashboard.js importPlaylist 逻辑一致）
        import re
        # 剥离 KOOK Markdown 链接: [text](url) → url
        m_md = re.match(r'\[.*?\]\((https?://[^)]+)\)', playlist_input)
        if m_md:
            playlist_input = m_md.group(1)
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
        logger.info("[命令:wygd] 歌单=%r 总数=%s", str(playlist_name)[:120], track_count)
        await msg.reply(f"🎶 正在获取歌单「{playlist_name}」({track_count}首)...", type=MessageTypes.TEXT)

        # 使用与 Web 控制台相同的 get_playlist_urls（按配置上限分页拉取）
        songs = get_playlist_urls(playlist_id)
        if not songs:
            await msg.reply("❌ 歌单为空或无法获取歌曲列表")
            return
        if not _queue_has_capacity(voice_channel_id, len(songs)):
            await msg.reply(f"❌ 导入后将超过队列上限（{MAX_QUEUE_TRACKS} 首）")
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
            player.add_music(song['marker'], extra_data, msg.ctx.guild.id)

        # 预取前5首URL，其余播放时自动补充
        prefetched = refill_playlist_queue(
            voice_channel_id, kookvoice.play_list, lock=kookvoice.state_lock
        )
        logger.info(f"[命令:wygd] 完成 导入{len(songs)}首 预取{prefetched}首")
        await msg.reply(f"✅ 已导入歌单「{playlist_name}」共 {len(songs)} 首歌曲", type=MessageTypes.TEXT)

    except Exception as e:
        logger.error(f"[命令:wygd] 出错: {type(e).__name__}")
        await msg.reply("⚠️ 播放歌单失败，请稍后再试")

@bot.command(name='qqgd')
async def qq_playlist_play(msg: Message, playlist_input: str = ''):
    """播放QQ音乐歌单"""
    try:
        if not playlist_input.strip():
            await msg.reply("❌ 请指定歌单ID或链接，例如: `/qqgd 123456789`")
            return
        logger.info(f"[命令:qqgd] 用户={msg.author_id}")
        voice_channel_id = await find_user_voice_channel(msg.ctx.guild.id, msg.author_id)
        if voice_channel_id is None:
            await msg.reply("❌ 请先加入语音频道")
            return

        # 提取歌单ID
        import re
        # 剥离 KOOK Markdown 链接: [text](url) → url
        m_md = re.match(r'\[.*?\]\((https?://[^)]+)\)', playlist_input)
        if m_md:
            playlist_input = m_md.group(1)
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
        logger.info("[命令:qqgd] 歌单=%r 总数=%s", str(playlist_name)[:120], track_count)
        await msg.reply(f"🎶 正在获取歌单「{playlist_name}」({track_count}首)...", type=MessageTypes.TEXT)

        songs = get_qq_playlist_urls(disstid)
        if not songs:
            await msg.reply("❌ 歌单为空或无法获取歌曲列表")
            return
        if not _queue_has_capacity(voice_channel_id, len(songs)):
            await msg.reply(f"❌ 导入后将超过队列上限（{MAX_QUEUE_TRACKS} 首）")
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
            player.add_music(song['marker'], extra_data, msg.ctx.guild.id)

        prefetched = refill_qq_playlist_queue(
            voice_channel_id, kookvoice.play_list, lock=kookvoice.state_lock
        )
        logger.info(f"[命令:qqgd] 完成 导入{len(songs)}首 预取{prefetched}首")
        await msg.reply(f"✅ 已导入歌单「{playlist_name}」共 {len(songs)} 首歌曲 (QQ音乐)", type=MessageTypes.TEXT)

    except Exception as e:
        logger.error(f"[命令:qqgd] 出错: {type(e).__name__}")
        await msg.reply("⚠️ 播放歌单失败，请稍后再试")

@bot.command(name='wy我的歌单')
async def wy_playlists_cmd(msg: Message):
    """列出当前登录网易云账号的歌单"""
    try:
        logger.info(f"[命令:wy我的歌单] 用户={msg.author_id}")
        cookie = load_cookie_header()
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        if cookie:
            headers["Cookie"] = cookie
        status_resp = requests.get(
            f"{MUSIC_API_BASE}/login/status",
            headers=headers,
            timeout=10,
            allow_redirects=False,
        )
        status_data = status_resp.json().get("data", {})
        uid = (status_data.get("account") or {}).get("id") or (status_data.get("profile") or {}).get("userId")
        if not uid:
            await msg.reply("❌ 当前未登录网易云账号\n请在Web控制台 /account 页面登录")
            return
        pl_resp = requests.get(
            f"{MUSIC_API_BASE}/user/playlist",
            params={"uid": str(uid), "limit": 50},
            headers=headers,
            timeout=15,
            allow_redirects=False,
        )
        pl_data = pl_resp.json()
        playlists = pl_data.get("playlist", [])
        if not playlists:
            await msg.reply("📋 暂无歌单")
            return
        lines = [f"🎵 我的网易云歌单 ({len(playlists)} 个):"]
        for pl in playlists[:30]:
            lines.append(f"  ▎{pl.get('name','?')}  (ID: {pl.get('id','?')})")
        await msg.reply("\n".join(lines), use_quote=False, type=MessageTypes.TEXT)
    except Exception as e:
        logger.error(f"[命令:wy我的歌单] 出错: {type(e).__name__}")
        await msg.reply("⚠️ 获取歌单失败，请稍后再试")

@bot.command(name='qq我的歌单')
async def qq_playlists_cmd(msg: Message):
    """列出当前登录QQ音乐账号的歌单"""
    try:
        logger.info(f"[命令:qq我的歌单] 用户={msg.author_id}")
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
        await msg.reply("\n".join(lines), use_quote=False, type=MessageTypes.TEXT)
    except Exception as e:
        logger.error(f"[命令:qq我的歌单] 出错: {type(e).__name__}")
        await msg.reply("⚠️ 获取歌单失败，请稍后再试")

@bot.command(name='当前账号')
async def account_info_cmd(msg: Message):
    """查询当前登录的网易云账号信息"""
    try:
        logger.info(f"[命令:当前账号] 用户={msg.author_id}")
        cookie = load_cookie_header()
        has_cookie = bool(cookie)
        logger.info(f"[命令:当前账号] Cookie状态: {'已设置' if has_cookie else '未设置'}")

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        if cookie:
            headers["Cookie"] = cookie

        api_url = f"{MUSIC_API_BASE}/login/status"
        logger.info(f"[命令:当前账号] 调用: GET {api_url}")
        res = requests.get(api_url, headers=headers, timeout=10, allow_redirects=False)
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

        logger.info("[命令:当前账号] 账号=%r uid=%r vip=%r", str(nickname)[:120], str(uid)[:64], str(vip_str)[:64])
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
        await msg.reply(info, use_quote=False, type=MessageTypes.TEXT)
    except Exception as e:
        logger.error(f"[命令:当前账号] 出错: {type(e).__name__}")
        await msg.reply("⚠️ 获取账号信息失败，请稍后再试")

@bot.command(name='qq当前账号')
async def qq_account_info_cmd(msg: Message):
    """查询当前登录的QQ音乐账号信息，含Cookie存活验证"""
    try:
        logger.info(f"[命令:qq当前账号] 用户={msg.author_id}")
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
        exp_str = _format_expiry(result.get("expires_in", -1)) if result.get("expires_in", -1) > 0 else "未知"
        info = (
            f"🎵 当前QQ音乐账号:\n"
            f"▎QQ号: {display_uin}\n"
            f"▎状态: Cookie有效 ({exp_str}后过期)"
        )
        await msg.reply(info, use_quote=False, type=MessageTypes.TEXT)
    except Exception as e:
        logger.error(f"[命令:qq当前账号] 出错: {type(e).__name__}")
        await msg.reply("⚠️ 获取QQ音乐账号信息失败，请稍后再试")

@bot.command(name='bili')
async def bili_cmd(msg: Message, music_input: str = '', page_input: str = '0'):
    """搜索并播放B站音频，支持 /bili BVxxxx [分P序号]"""
    try:
        if not music_input.strip():
            await msg.reply("❌ 请指定关键词，例如: `/bili 春日影`")
            return
        logger.info(f"[命令:bili] 用户={msg.author_id} 分P={page_input}")
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

            logger.info("[命令:bili] 选中 name=%r artist=%r bvid=%r", str(song_name)[:120], str(artist_name)[:120], str(bvid)[:64])

            play_info = get_bili_play_url(bvid)
        if not play_info:
            await msg.reply("❌ 获取音频流失败，可能是海外限制或版权原因")
            return

        music_url = play_info["raw_url"]

        if play_info.get("title") and not bv_match:
            song_name = f"[B站] {song_name} - {play_info['title']}"

        player = kookvoice.Player(voice_channel_id, BOT_TOKEN)
        extra_data = {
            "音乐名字": song_name,
            "title": song_name,
            "歌手": artist_name,
            "artist": artist_name,
            "点歌人": msg.author_id,
            "文字频道": msg.ctx.channel.id,
            "platform": "bili",
            "duration": play_info.get("duration", 0),  # 方案A：API已知时长
        }
        player.add_music(music_url, extra_data, msg.ctx.guild.id)
        logger.info("[命令:bili] 已加入队列 name=%r duration=%ss", str(song_name)[:120], play_info.get('duration', 0))

        _page_hint = ""
        if _total_pages > 1:
            _page_hint = f" (P{_target_page}/{_total_pages})"
        await msg.reply(f"✅ {song_name}{_page_hint} 已加入播放队列 (B站)", type=MessageTypes.TEXT)

    except Exception as e:
        logger.error(f"[命令:bili] 出错: {type(e).__name__}")
        await msg.reply("⚠️ 播放失败，请稍后再试")

@bot.command(name='bili歌单')
async def bili_playlist_cmd(msg: Message, fav_input: str = ''):
    """导入B站收藏夹"""
    try:
        if not fav_input.strip():
            await msg.reply("❌ 请指定收藏夹ID，例如: `/bili歌单 123456789`")
            return
        logger.info(f"[命令:bili歌单] 用户={msg.author_id}")
        voice_channel_id = await find_user_voice_channel(msg.ctx.guild.id, msg.author_id)
        if voice_channel_id is None:
            await msg.reply("❌ 请先加入语音频道")
            return

        import re
        # 剥离 KOOK Markdown 链接: [text](url) → url
        m_md = re.match(r'\[.*?\]\((https?://[^)]+)\)', fav_input)
        if m_md:
            fav_input = m_md.group(1)
        media_id = fav_input.strip()
        # 如果是B站收藏夹链接，提取 media_id
        if media_id.startswith("http") and "bilibili.com" in media_id:
            m = re.search(r'media_id=(\d+)', media_id) or re.search(r'fid=(\d+)', media_id)
            if m:
                media_id = m.group(1)
        if not media_id.isdigit():
            await msg.reply("❌ 收藏夹ID应为纯数字")
            return

        # 获取收藏夹名称
        fav_name = f"收藏夹{media_id}"
        try:
            cols = get_bili_favorite_collections()
            for c in cols:
                if str(c["id"]) == media_id:
                    fav_name = c["title"]
                    break
        except Exception:
            pass

        await msg.reply(f"🎶 正在获取B站收藏夹「{fav_name}」...", type=MessageTypes.TEXT)

        songs = get_bili_favorite_all_tracks(media_id)
        if not songs:
            await msg.reply("❌ 收藏夹为空或无法获取歌曲列表")
            return
        if not _queue_has_capacity(voice_channel_id, len(songs)):
            await msg.reply(f"❌ 导入后将超过队列上限（{MAX_QUEUE_TRACKS} 首）")
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
            player.add_music(song['marker'], extra_data, msg.ctx.guild.id)

        prefetched = refill_bili_playlist_queue(
            voice_channel_id, kookvoice.play_list, lock=kookvoice.state_lock
        )
        logger.info(f"[命令:bili歌单] 完成 导入{len(songs)}首 预取{prefetched}首")
        await msg.reply(f"✅ 已导入B站收藏夹「{fav_name}」共 {len(songs)} 首歌曲", type=MessageTypes.TEXT)

    except Exception as e:
        logger.error(f"[命令:bili歌单] 出错: {type(e).__name__}")
        await msg.reply("⚠️ 导入失败，请稍后再试")

@bot.command(name='bili我的歌单')
async def bili_playlists_cmd(msg: Message):
    """列出当前登录B站账号的收藏夹"""
    try:
        logger.info(f"[命令:bili我的歌单] 用户={msg.author_id}")
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
        await msg.reply("\n".join(lines), use_quote=False, type=MessageTypes.TEXT)
    except Exception as e:
        logger.error(f"[命令:bili我的歌单] 出错: {type(e).__name__}")
        await msg.reply("⚠️ 获取收藏夹失败，请稍后再试")

@bot.command(name='bili当前账号')
async def bili_account_cmd(msg: Message):
    """查询当前登录的B站账号信息"""
    try:
        logger.info(f"[命令:bili当前账号] 用户={msg.author_id}")
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
            await msg.reply(f"✅ 已登录B站 (UID: {display_uid})\n昵称: {vr['uname']}", type=MessageTypes.TEXT)
            return
        lines = [
            "🎬 B站账号信息",
            f"  昵称: {user['uname']}",
            f"  UID: {display_uid}",
            f"  等级: Lv{user['level']}",
        ]
        vip_map = {0: "无", 1: "月度大会员", 2: "年度大会员"}
        lines.append(f"  会员: {vip_map.get(user.get('vip_type', 0), '未知')}")
        await msg.reply("\n".join(lines), use_quote=False, type=MessageTypes.TEXT)
    except Exception as e:
        logger.error(f"[命令:bili当前账号] 出错: {type(e).__name__}")
        await msg.reply("⚠️ 获取B站账号信息失败，请稍后再试")

PAGE_SIZE = 20
PLAYLIST_TITLE_LIMIT = 72


def _playlist_display_name(item: Any) -> str:
    """将外部平台标题规整为可安全发送的单行纯文本。"""
    extra = item.get("extra", {}) if isinstance(item, dict) else {}
    if not isinstance(extra, dict):
        extra = {}
    raw_name = extra.get("音乐名字") or extra.get("title") or "未知歌曲"
    name = "".join(
        " " if char.isspace() else char
        for char in str(raw_name)
        if char.isspace() or (ord(char) >= 32 and ord(char) != 127)
    )
    name = " ".join(name.split()) or "未知歌曲"
    if len(name) > PLAYLIST_TITLE_LIMIT:
        name = f"{name[:PLAYLIST_TITLE_LIMIT - 1]}…"
    return name

@bot.command(name='播放列表')
async def playlist_cmd(msg: Message, page_input: str = ''):
    """查看当前播放列表，支持 /播放列表 <页数> 翻页"""
    try:
        ch = await _resolve_channel(msg.ctx.guild.id, msg.author_id)
        logger.info(f"[命令:播放列表] 用户={msg.author_id} 服务器={msg.ctx.guild.id} 页={page_input or '1'} 频道={ch}")
        if not ch:
            await msg.reply("📋 当前没有播放列表")
            return

        guild_pl = kookvoice.get_state_snapshot(ch)
        if guild_pl is None:
            await msg.reply("📋 当前没有播放列表")
            return
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
            name = _playlist_display_name(now_playing)
            lines.append(f"▶️ 正在播放: {name}")
        else:
            lines.append("▶️ 当前未在播放")

        if queue:
            for i in range(start, end):
                item = queue[i]
                name = _playlist_display_name(item)
                lines.append(f"  {i + 1}. {name}")
        elif not now_playing:
            lines.append("  (空)")

        if total_pages > 1:
            lines.append(f"💡 输入 /播放列表 <页数> 翻页")

        # khl.py 默认使用 KMarkdown；外部歌曲标题可能使 KOOK 返回 40011。
        # 列表不需要富文本或引用，明确按普通文本发送。
        await msg.reply(
            "\n".join(lines),
            use_quote=False,
            type=MessageTypes.TEXT,
        )
    except Exception as e:
        logger.error(f"[命令:播放列表] 出错: {type(e).__name__}")
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
        with kookvoice.state_lock:
            state = kookvoice.play_list.get(ch)
            queue_len = len(state.get('play_list', [])) if state else 0
            if queue_len:
                state['play_list'] = []
        logger.info(f"[命令:清空列表] 当前队列={queue_len}首")

        if queue_len == 0:
            await msg.reply("📋 播放列表本来就是空的")
            return

        await msg.reply(f"✅ 已清空播放列表（共移除 {queue_len} 首歌曲）")
    except Exception as e:
        logger.error(f"[命令:清空列表] 出错: {type(e).__name__}")
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

        state = kookvoice.get_state_snapshot(ch)
        queue = state.get('play_list', []) if state else []
        now_playing = state.get('now_playing') if state else None
        logger.info(f"[命令:播放第] 队列={len(queue)}首 目标={target}")

        if target < 1 or target > len(queue):
            await msg.reply(f"❌ 序号超出范围，当前队列共 {len(queue)} 首歌曲")
            return

        target_item = queue[target - 1]
        extra = target_item.get('extra', {})
        song_name = extra.get('音乐名字') or extra.get('title', '未知歌曲')

        if target > 1:
            with kookvoice.state_lock:
                live_state = kookvoice.play_list.get(ch)
                if live_state is None:
                    raise ValueError("播放会话已结束")
                live_queue = live_state.get('play_list', [])
                live_state['play_list'] = live_queue[target - 1:]
                remaining_count = len(live_state['play_list'])
            logger.info(f"[命令:播放第] 移除前 {target - 1} 首，剩余 {remaining_count} 首")

        player = kookvoice.Player(ch)
        player.skip()

        await msg.reply(f"⏭️ 已切至第 {target} 首: {song_name}", type=MessageTypes.TEXT)
    except Exception as e:
        logger.error(f"[命令:播放第] 出错: {type(e).__name__}")
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
        "/单曲循环 — 循环当前歌曲（与列表循环互斥）\n"
        "/循环播放列表 — 播完歌曲移到队尾并持续循环（与单曲循环互斥）\n"
        "/随机播放 — 切换随机播放开关\n"
        "/播放第N首 — 切到队列第N首歌\n"
        "/停止 — 停止播放\n"
        "/清空列表 — 清空播放队列\n"
        "/脱离卡死 — 分阶段强制恢复播放会话\n\n"
        "📋 **查询**\n"
        "/播放列表 `[页数]` — 查看当前播放队列（20首/页）\n"
        "/当前账号 — 查看登录的网易云账号\n"
        "/qq当前账号 — 查看登录的QQ音乐账号\n"
        "/bili当前账号 — 查看登录的B站账号\n"
        "/ping — 测试机器人连接\n"
        "/版本信息 — 查看当前构建标识\n"
        "/帮助 — 显示本帮助信息"
    )
    await msg.reply(help_text)

@bot.command(name='版本信息')
async def version_cmd(msg: Message):
    """回复当前构建标识；发布标识由 APP_VERSION 配置。"""
    try:
        logger.info(f"[命令:版本信息] 用户={msg.author_id}")
        await msg.reply(f"**KOOK 音乐机器人**\n当前构建: {APP_VERSION}")
    except Exception as e:
        logger.error(f"[命令:版本信息] 出错: {type(e).__name__}")
        await msg.reply("当前构建信息不可用")

# 启动异步事件循环
def start_bot_loop():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    kookvoice.set_loop(loop)  # 建立线程安全的桥接，使 PlayHandler 能调度事件到 bot 事件循环
    runtime_health.mark_bot_state("starting")

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
            state = "configuration_error" if not str(BOT_TOKEN).strip() else "failed"
            runtime_health.mark_bot_state(state, "Token验证失败")
            _shutdown_loop()
            return

        # 预先在事件循环中启动心跳任务（必须在 bot.start() 前调度，因为 bot.start() 是长连接协程不返回）
        async def _heartbeat_task():
            while True:
                runtime_health.mark_loop_heartbeat()
                try:
                    _write_heartbeat(BOT_HEARTBEAT_FILE)
                except Exception:
                    logger.warning("更新Bot心跳文件失败（内存心跳仍有效）", exc_info=True)
                await asyncio.sleep(30)
        loop.create_task(_heartbeat_task())
        logger.info("[机器人] 心跳任务已就绪")

        # 启动机器人（阻塞协程，处理 WebSocket 网关直到断开）
        logger.info("[机器人] 启动中...")
        loop.run_until_complete(bot.start())
        runtime_health.mark_bot_state("failed", "bot.start() 意外返回")
        logger.error("[机器人] bot.start() 意外返回，交由看门狗恢复")

    except Exception as e:
        logger.error("[机器人] 启动异常: %s", type(e).__name__)
        runtime_health.mark_bot_state("failed", type(e).__name__)
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

_bot_thread = None
_bot_thread_lock = threading.Lock()


def _start_bot_thread_once():
    """仅在应用首次创建时启动一个 Bot 事件循环线程。"""
    global _bot_thread
    with _bot_thread_lock:
        if _bot_thread is not None and _bot_thread.is_alive():
            return _bot_thread
        _bot_thread = threading.Thread(
            target=start_bot_loop,
            name='kook-bot',
            daemon=True,
        )
        _bot_thread.start()
        return _bot_thread

# 测试路由
def debug():
    try:
        health = runtime_health.snapshot()
        loop_age = health.age(health.loop_heartbeat_at)
        gateway_age = health.age(health.gateway_heartbeat_at)
        bot_status = "运行中" if runtime_health.bot_is_healthy() else "异常或启动中"
        
        # 添加播放列表信息
        snapshot = kookvoice.get_state_snapshot()
        playlists = snapshot['play_list']
        active_guilds = len(playlists)
        playing_songs = 0
        queued_songs = 0
        for guild_data in playlists.values():
            if guild_data.get('now_playing'):
                playing_songs += 1
            queued_songs += len(guild_data.get('play_list', []))
        
        return jsonify({
            "status": "success",
            "bot_status": bot_status,
            "bot_state": health.bot_state,
            "bot_failure_reason": health.bot_failure_reason,
            "bot_loop_heartbeat_age": loop_age,
            "kook_gateway_probe_available": health.gateway_probe_available,
            "kook_gateway_heartbeat_age": gateway_age,
            "active_guilds": active_guilds,
            "playing_songs": playing_songs,
            "queued_songs": queued_songs,
            "token_valid": bool(BOT_TOKEN),
            "ffmpeg_path": os.path.exists(FFMPEG_PATH)
        })
    except Exception:
        logger.exception("获取调试状态失败")
        return jsonify({"status": "error", "error": "无法获取调试状态"}), 500


def healthz():
    return jsonify({"status": "ok"})


def create_app(start_bot=True):
    """创建完整的 Flask 应用；模块不再暴露未安装鉴权的全局 app。"""
    application = Flask(__name__)
    application.config['SECRET_KEY'] = SECRET_KEY
    application.config['MAX_CONTENT_LENGTH'] = MAX_REQUEST_BYTES
    application.before_request(_update_heartbeat)

    register_routes(application, bot)
    register_account_routes(application)

    try:
        from .qq_account_api import register_qq_account_routes
    except ImportError:
        from qq_account_api import register_qq_account_routes
    register_qq_account_routes(application, start_maintenance=start_bot)

    try:
        from .bili_account_api import register_bili_account_routes
    except ImportError:
        from bili_account_api import register_bili_account_routes
    register_bili_account_routes(application)

    application.add_url_rule('/api/debug', 'debug', debug, methods=['GET'])
    application.add_url_rule('/healthz', 'healthz', healthz, methods=['GET'])

    try:
        from .api import api_bp
    except ImportError:
        from api import api_bp
    application.register_blueprint(api_bp, url_prefix='/api')
    application.extensions['kook_bot'] = bot
    if start_bot:
        _start_bot_thread_once()
    return application

if __name__ == '__main__':
    raise SystemExit("请通过 python run.py 启动完整服务")
