from flask import render_template, request, jsonify, abort
import logging
import os
import time
import re
from functools import wraps
try:
    from . import kookvoice
    from .config import BOT_TOKEN, MAX_QUEUE_TRACKS, MAX_PLAYLIST_IMPORT_CONCURRENCY
    from .utils import search_music, get_music_url, get_playlist, get_playlist_urls, format_playlist_data, refill_playlist_queue
    from .qq_utils import search_qq_music, get_qq_music_url, get_qq_playlist_urls, refill_qq_playlist_queue
    from .bili_utils import search_bili_music, get_bili_play_url, get_bili_favorite_all_tracks, refill_bili_playlist_queue
    from .auth import sync_guild, sync_channel
except ImportError:
    import kookvoice
    from config import BOT_TOKEN, MAX_QUEUE_TRACKS, MAX_PLAYLIST_IMPORT_CONCURRENCY
    from utils import search_music, get_music_url, get_playlist, get_playlist_urls, format_playlist_data, refill_playlist_queue
    from qq_utils import search_qq_music, get_qq_music_url, get_qq_playlist_urls, refill_qq_playlist_queue
    from bili_utils import search_bili_music, get_bili_play_url, get_bili_favorite_all_tracks, refill_bili_playlist_queue
    from auth import sync_guild, sync_channel
import threading

logger = logging.getLogger(__name__)
_RUNTIME_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'debug.log')
_PLAYLIST_IMPORT_SLOTS = threading.BoundedSemaphore(MAX_PLAYLIST_IMPORT_CONCURRENCY)
MAX_LOG_LINES = 1000
MAX_LOG_READ_BYTES = 1024 * 1024
MAX_ROUTE_INPUT_LENGTH = 256
_ALLOWED_PLATFORMS = frozenset({'wy', 'qq', 'bili'})
_LOG_QUERY_SECRET_RE = re.compile(
    r"(?i)([?&](?:cookie|set-cookie|token|access[_-]?token|refresh[_-]?token|"
    r"authorization|signature|sign|qrsig|ptqrtoken|sessdata|music[_-]?[ua]|"
    r"expires?|deadline)=)[^&#\s\"']+"
)
_LOG_ASSIGNMENT_SECRET_RE = re.compile(
    r"(?i)((?:cookie|set-cookie|authorization|token|access[_-]?token|"
    r"refresh[_-]?token|signature|qrsig|ptqrtoken|sessdata|music[_-]?[ua])"
    r"\s*[:=]\s*[\"']?)[^\s,;\"']+"
)
_LOG_COOKIE_PAIR_RE = re.compile(
    r"(?i)\b(?:MUSIC_U|MUSIC_A|SESSDATA|qqmusic_key|qm_keyst|"
    r"psrf_qq(?:refresh|access)_(?:token|key)|bili_jct)=[^;\s,\"']+"
)


def _redact_log_text(value, limit=MAX_LOG_READ_BYTES):
    text = str(value or "")
    text = _LOG_QUERY_SECRET_RE.sub(r"\1<redacted>", text)
    text = _LOG_ASSIGNMENT_SECRET_RE.sub(r"\1<redacted>", text)
    text = _LOG_COOKIE_PAIR_RE.sub(
        lambda match: match.group(0).split("=", 1)[0] + "=<redacted>",
        text,
    )
    return text[:limit]


def _route_input(value, name, allow_empty=False):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError(f'{name}参数格式无效')
    text = str(value).strip()
    if (
        (not text and not allow_empty)
        or len(text) > MAX_ROUTE_INPUT_LENGTH
        or any(ord(char) < 32 or ord(char) == 127 for char in text)
    ):
        raise ValueError(f'{name}参数格式无效')
    return text


def _route_error(error):
    safe_messages = (
        '播放队列已达到上限', '该频道没有正在播放的歌曲', '播放列表不存在',
        '索引超出范围', '频道id不能为空', '文件不存在',
    )
    message = str(error)
    if not isinstance(error, ValueError) or not message.startswith(safe_messages):
        message = '服务器处理请求失败'
    return jsonify({'success': False, 'error': message}), 400 if isinstance(error, ValueError) else 500


def _limit_playlist_import(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not _PLAYLIST_IMPORT_SLOTS.acquire(blocking=False):
            return jsonify({'success': False, 'error': '歌单导入任务已满，请稍后重试'}), 429
        try:
            return view(*args, **kwargs)
        finally:
            _PLAYLIST_IMPORT_SLOTS.release()
    return wrapped


def _resolve_log_path(log_type):
    # 兼容旧前端的 app/debug 两种类型，二者都指向统一的运行日志。
    return _RUNTIME_LOG_PATH if log_type in ('app', 'debug') else None


def _read_log_tail(path, line_limit):
    file_size = os.path.getsize(path)
    start = max(0, file_size - MAX_LOG_READ_BYTES)
    with open(path, 'rb') as handle:
        handle.seek(start)
        payload = handle.read(MAX_LOG_READ_BYTES)
    if start and b'\n' in payload:
        payload = payload.split(b'\n', 1)[1]
    lines = payload.decode('utf-8', errors='replace').splitlines()
    return lines[-line_limit:], len(lines), bool(start)


def _truncate_private_file(path):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        if os.name != 'nt':
            os.fchmod(descriptor, 0o600)
    finally:
        os.close(descriptor)

def _find_channel_for_guild(guild_id):
    """同步查找服务器内的活跃语音频道。多频道时返回第一个但记录警告。"""
    if guild_id is None:
        return None
    snapshot = kookvoice.get_state_snapshot()
    matches = []
    for ch_id, data in snapshot['play_list'].items():
        if data.get('guild_id') == str(guild_id):
            matches.append(ch_id)
    if len(matches) > 1:
        logger.warning("[频道定位] 服务器 %s 有 %d 个活跃频道，应传 channel_id 精确定位", guild_id, len(matches))
    return matches[0] if matches else None


def _playback_modes_from_state(channel_state):
    channel_state = channel_state or {}
    return {
        'single_repeat': bool(channel_state.get('repeat', False)),
        'playlist_repeat': bool(channel_state.get('playlist_repeat', False)),
        'shuffle': channel_state.get('_queue_backup') is not None,
    }


def _queue_has_capacity(channel_id, requested):
    snapshot = kookvoice.get_state_snapshot()
    state = snapshot['play_list'].get(str(channel_id), {})
    queued = len(state.get('play_list', []))
    return queued + max(0, int(requested)) <= MAX_QUEUE_TRACKS


def register_routes(app, bot):
    """注册所有路由"""
    
    @app.route('/')
    def index():
        """首页"""
        return render_template('index.html')
    
    @app.route('/dashboard')
    def dashboard():
        """控制台页面"""
        return render_template('dashboard.html')

    @app.route('/monitor')
    def monitor():
        """监控页面"""
        template_root = app.template_folder or 'templates'
        if not os.path.isabs(template_root):
            template_root = os.path.join(app.root_path, template_root)
        if not os.path.isfile(os.path.join(template_root, 'monitor.html')):
            abort(404)
        return render_template('monitor.html')
    
    @app.route('/api/guilds', methods=['GET'])
    def get_guilds():
        """获取服务器列表"""
        try:
            # 使用同步方式调用KOOK API获取服务器列表
            try:
                import requests
                headers = {
                    'Authorization': f'Bot {BOT_TOKEN}',
                    'Content-Type': 'application/json'
                }
                url = 'https://www.kookapp.cn/api/v3/guild/list'
                
                logger.info(f"请求服务器列表API: {url}")
                response = requests.get(url, headers=headers, timeout=10, allow_redirects=False)
                logger.info(f"服务器列表API响应状态: {response.status_code}")
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get('code') == 0 and 'data' in data:
                        guilds = data['data'].get('items', [])
                        logger.info(f"获取到 {len(guilds)} 个服务器")
                    else:
                        guilds = []
                        logger.warning(f"服务器列表API返回错误: {data.get('message', '未知错误')}")
                else:
                    guilds = []
                    logger.error(f"服务器列表API HTTP错误: {response.status_code}")
            except Exception as e:
                logger.error(f"获取服务器列表异常: {type(e).__name__}")
                guilds = []
            
            # 格式化数据
            formatted_guilds = []
            for guild in guilds:
                guild_id = str(guild.get('id', '')).strip()
                if not guild_id:
                    continue
                guild_name = str(guild.get('name', '未知服务器'))
                sync_guild(guild_id, guild_name)
                formatted_guilds.append({
                    'id': guild_id,
                    'name': guild_name,
                    'icon': guild.get('icon', ''),
                    'master_id': guild.get('master_id', '')
                })
            
            return jsonify({'success': True, 'guilds': formatted_guilds})
        except Exception as e:
            logger.error(f"获取服务器列表异常: {type(e).__name__}")
            return _route_error(e)
    
    @app.route('/api/channels', methods=['GET'])
    def get_channels():
        """获取频道列表"""
        guild_id = request.args.get('guild_id')
        if not guild_id:
            return jsonify({'success': False, 'error': '缺少guild_id参数'})
        
        try:
            # 使用同步方式调用KOOK API获取频道列表
            try:
                import requests
                headers = {
                    'Authorization': f'Bot {BOT_TOKEN}',
                    'Content-Type': 'application/json'
                }
                url = 'https://www.kookapp.cn/api/v3/channel/list'

                response = requests.get(
                    url,
                    headers=headers,
                    params={'guild_id': guild_id},
                    timeout=10,
                    allow_redirects=False,
                )
                if response.status_code == 200:
                    data = response.json()
                    if data.get('code') == 0 and 'data' in data:
                        channels = data['data'].get('items', [])
                    else:
                        channels = []
                else:
                    channels = []
            except Exception as e:
                logger.error(f"获取频道列表异常: {type(e).__name__}")
                channels = []
            
            # 格式化数据，只返回语音频道
            formatted_channels = []
            for channel in channels:
                # 只返回语音频道 (type=2)
                if channel.get('type') == 2:
                    channel_id = str(channel.get('id', '')).strip()
                    if not channel_id:
                        continue
                    channel_name = str(channel.get('name', '未知频道'))
                    sync_channel(guild_id, channel_id, channel_name, 'voice')
                    formatted_channels.append({
                        'id': channel_id,
                        'name': channel_name,
                        'type': channel.get('type', 2)
                    })
            
            return jsonify({'success': True, 'channels': formatted_channels})
        except Exception as e:
            logger.error(f"获取频道列表异常: {type(e).__name__}")
            return _route_error(e)

    @app.route('/api/channels/active', methods=['GET'])
    def get_active_channels():
        """获取指定服务器内所有活跃语音频道的播放状态"""
        guild_id = request.args.get('guild_id')
        if not guild_id:
            return jsonify({'success': False, 'error': '缺少guild_id参数'})
        snapshot = kookvoice.get_state_snapshot()
        active = {}
        for ch_id, data in snapshot['play_list'].items():
            if data.get('guild_id') == str(guild_id):
                status = 'idle'
                if ch_id in snapshot['guild_status']:
                    s = snapshot['guild_status'][ch_id]
                    if s == kookvoice.Status.PLAYING:
                        status = 'playing'
                    elif s == kookvoice.Status.PAUSE:
                        status = 'paused'
                    else:
                        status = 'connected'
                active[ch_id] = status
        return jsonify({'success': True, 'active': active})

    @app.route('/api/join', methods=['POST'])
    def join_channel():
        """加入语音频道"""
        data = request.json
        if not data:
            return jsonify({'success': False, 'error': '请求数据为空'})
            
        guild_id = data.get('guild_id')
        channel_id = data.get('channel_id')
        
        if not guild_id or not channel_id:
            return jsonify({'success': False, 'error': '缺少必要参数'})
        
        try:
            player = kookvoice.Player(channel_id, BOT_TOKEN)
            player.join(guild_id)

            return jsonify({'success': True})
        except Exception as e:
            logger.error(f"加入语音频道异常: {type(e).__name__}")
            return _route_error(e)

    @app.route('/api/leave', methods=['POST'])
    def leave_channel():
        """离开语音频道"""
        data = request.json
        if not data:
            return jsonify({'success': False, 'error': '请求数据为空'})

        guild_id = data.get('guild_id')
        channel_id = data.get('channel_id') or _find_channel_for_guild(guild_id)

        if not channel_id:
            return jsonify({'success': False, 'error': '缺少必要参数'})

        try:
            player = kookvoice.Player(channel_id)
            player.stop()
            return jsonify({'success': True})
        except Exception as e:
            logger.error(f"离开语音频道异常: {type(e).__name__}")
            return _route_error(e)
    
    @app.route('/api/search', methods=['GET'])
    def search():
        """搜索音乐"""
        keyword = request.args.get('keyword')
        platform = request.args.get('platform', 'wy')
        if not keyword:
            return jsonify({'success': False, 'error': '缺少keyword参数'})
        try:
            keyword = _route_input(keyword, 'keyword')
            platform = _route_input(platform, 'platform')
        except ValueError as exc:
            return jsonify({'success': False, 'error': str(exc)}), 400
        if platform not in _ALLOWED_PLATFORMS:
            return jsonify({'success': False, 'error': '不支持的平台'}), 400

        try:
            if platform == 'qq':
                songs = search_qq_music(keyword)
            elif platform == 'bili':
                songs = search_bili_music(keyword)
            else:
                songs = search_music(keyword)
            return jsonify({'success': True, 'songs': songs})
        except Exception as e:
            logger.error(f"搜索音乐异常: {type(e).__name__}")
            return _route_error(e)

    @app.route('/api/play', methods=['POST'])
    @app.route('/api/playlist/add', methods=['POST'])
    def play_music():
        """将单曲添加到指定频道的播放列表（/api/play 保留兼容）"""
        data = request.json
        if not isinstance(data, dict) or not data:
            return jsonify({'success': False, 'error': '请求数据为空'})

        guild_id = data.get('guild_id')
        channel_id = data.get('channel_id')
        song_id = data.get('song_id')
        song_name = data.get('song_name', '')
        artist_name = data.get('artist_name', '')
        platform = data.get('platform', 'wy')

        if not guild_id or not channel_id or not song_id:
            return jsonify({'success': False, 'error': '缺少必要参数'})
        try:
            song_id = _route_input(song_id, 'song_id')
            song_name = _route_input(song_name, 'song_name', allow_empty=True)
            artist_name = _route_input(artist_name, 'artist_name', allow_empty=True)
            platform = _route_input(platform, 'platform')
        except ValueError as exc:
            return jsonify({'success': False, 'error': str(exc)}), 400
        if platform not in _ALLOWED_PLATFORMS:
            return jsonify({'success': False, 'error': '不支持的平台'}), 400
        if not _queue_has_capacity(channel_id, 1):
            return jsonify({'success': False, 'error': f'播放队列已达到上限（{MAX_QUEUE_TRACKS} 首）'}), 409

        try:
            if platform == 'qq':
                url = get_qq_music_url(song_id)
            elif platform == 'bili':
                info = get_bili_play_url(song_id)
                if not info:
                    return jsonify({'success': False, 'error': '无法获取B站音频URL'})
                url = info.get('raw_url', '')
                if not url:
                    return jsonify({'success': False, 'error': 'B站音频URL为空'})
                bili_duration = info.get('duration', 0)
            else:
                url = get_music_url(song_id)
            if not url:
                return jsonify({'success': False, 'error': '无法获取音乐URL'})

            player = kookvoice.Player(channel_id, BOT_TOKEN)
            extra = {'title': song_name, 'artist': artist_name}
            if platform == 'bili':
                extra['platform'] = 'bili'
                extra['duration'] = bili_duration
            player.add_music(url, extra, guild_id)

            return jsonify({
                'success': True,
                'channel_id': channel_id,
                'message': '歌曲已添加到播放列表',
            })
        except Exception as e:
            logger.error(f"播放音乐异常: {type(e).__name__}")
            return _route_error(e)
    
    @app.route('/api/playlist', methods=['POST'])
    @_limit_playlist_import
    def add_playlist():
        """添加歌单"""
        data = request.json
        if not isinstance(data, dict) or not data:
            return jsonify({'success': False, 'error': '请求数据为空'})

        guild_id = data.get('guild_id')
        channel_id = data.get('channel_id')
        playlist_id = data.get('playlist_id')
        platform = data.get('platform', 'wy')

        if not guild_id or not channel_id or not playlist_id:
            return jsonify({'success': False, 'error': '缺少必要参数'})
        try:
            playlist_id = _route_input(playlist_id, 'playlist_id')
            platform = _route_input(platform, 'platform')
        except ValueError as exc:
            return jsonify({'success': False, 'error': str(exc)}), 400
        if platform not in _ALLOWED_PLATFORMS:
            return jsonify({'success': False, 'error': '不支持的平台'}), 400

        try:
            player = kookvoice.Player(channel_id, BOT_TOKEN)

            if platform == 'qq':
                songs = get_qq_playlist_urls(playlist_id)
                if not songs:
                    return jsonify({'success': False, 'error': '歌单为空或无法获取歌单'})
                if not _queue_has_capacity(channel_id, len(songs)):
                    return jsonify({'success': False, 'error': f'导入后将超过队列上限（{MAX_QUEUE_TRACKS} 首）'}), 409
                for song in songs:
                    player.add_music(song['marker'], {
                        'title': song['name'],
                        'artist': song['artist'],
                        '音乐名字': song['name'],
                    }, guild_id)
                prefetched = refill_qq_playlist_queue(
                    channel_id, kookvoice.play_list, lock=kookvoice.state_lock
                )
            elif platform == 'bili':
                songs = get_bili_favorite_all_tracks(playlist_id)
                if not songs:
                    return jsonify({'success': False, 'error': '收藏夹为空或无法获取'})
                if not _queue_has_capacity(channel_id, len(songs)):
                    return jsonify({'success': False, 'error': f'导入后将超过队列上限（{MAX_QUEUE_TRACKS} 首）'}), 409
                for song in songs:
                    player.add_music(song['marker'], {
                        'title': song['name'],
                        'artist': song['artist'],
                        '音乐名字': song['name'],
                        'platform': 'bili',
                    }, guild_id)
                prefetched = refill_bili_playlist_queue(
                    channel_id, kookvoice.play_list, lock=kookvoice.state_lock
                )
            else:
                songs = get_playlist_urls(playlist_id)
                if not songs:
                    return jsonify({'success': False, 'error': '歌单为空或无法获取歌单'})
                if not _queue_has_capacity(channel_id, len(songs)):
                    return jsonify({'success': False, 'error': f'导入后将超过队列上限（{MAX_QUEUE_TRACKS} 首）'}), 409
                for song in songs:
                    player.add_music(song['marker'], {
                        'title': song['name'],
                        'artist': song['artist'],
                        '音乐名字': song['name'],
                    }, guild_id)
                prefetched = refill_playlist_queue(
                    channel_id, kookvoice.play_list, lock=kookvoice.state_lock
                )

            logger.info(f"[歌单导入] platform={platform} {len(songs)}首 预取{prefetched}首")
            return jsonify({'success': True, 'count': len(songs)})
        except Exception as e:
            logger.error(f"添加歌单异常: {type(e).__name__}")
            return _route_error(e)
    
    @app.route('/api/skip', methods=['POST'])
    def skip_music():
        """跳过当前歌曲"""
        data = request.json
        if not data:
            return jsonify({'success': False, 'error': '请求数据为空'})

        guild_id = data.get('guild_id')
        channel_id = data.get('channel_id') or _find_channel_for_guild(guild_id)

        if not channel_id:
            return jsonify({'success': False, 'error': '缺少必要参数'})

        try:
            player = kookvoice.Player(channel_id)
            player.skip()
            return jsonify({'success': True})
        except Exception as e:
            logger.error(f"跳过歌曲异常: {type(e).__name__}")
            return _route_error(e)
    
    @app.route('/api/seek', methods=['POST'])
    def seek_music():
        """跳转到指定位置"""
        data = request.json
        if not data:
            return jsonify({'success': False, 'error': '请求数据为空'})

        guild_id = data.get('guild_id')
        channel_id = data.get('channel_id') or _find_channel_for_guild(guild_id)
        position = data.get('position')

        if not channel_id or position is None:
            return jsonify({'success': False, 'error': '缺少必要参数'})

        try:
            player = kookvoice.Player(channel_id)
            player.seek(int(position))
            return jsonify({'success': True})
        except Exception as e:
            logger.error(f"跳转位置异常: {type(e).__name__}")
            return _route_error(e)
    
    @app.route('/api/playlist/current', methods=['GET'])
    def get_current_playlist():
        """获取当前播放列表"""
        guild_id = request.args.get('guild_id')
        channel_id = request.args.get('channel_id') or _find_channel_for_guild(guild_id)

        if not channel_id:
            return jsonify({
                'success': True,
                'playlist': [],
                'playback_modes': _playback_modes_from_state(None),
            })

        try:
            channel_state = kookvoice.get_state_snapshot(channel_id)
            if channel_state is not None:
                playlist_data = format_playlist_data(channel_state)
                return jsonify({
                    'success': True,
                    'playlist': playlist_data,
                    'playback_modes': _playback_modes_from_state(channel_state),
                })
            else:
                return jsonify({
                    'success': True,
                    'playlist': [],
                    'playback_modes': _playback_modes_from_state(None),
                })
        except Exception as e:
            logger.error(f"获取播放列表异常: {type(e).__name__}")
            return _route_error(e)

    @app.route('/api/playlist/repeat', methods=['POST'])
    def toggle_playlist_repeat():
        """切换指定频道的列表循环模式"""
        data = request.get_json(silent=True) or {}
        guild_id = data.get('guild_id')
        channel_id = data.get('channel_id') or _find_channel_for_guild(guild_id)

        if not channel_id:
            return jsonify({'success': False, 'error': '缺少必要参数'})

        try:
            enabled = kookvoice.Player(channel_id).playlist_repeat_toggle()
            channel_state = kookvoice.get_state_snapshot(channel_id)
            return jsonify({
                'success': True,
                'enabled': enabled,
                'playback_modes': _playback_modes_from_state(channel_state),
            })
        except Exception as e:
            logger.error(f"切换列表循环异常: {type(e).__name__}")
            return _route_error(e)
    
    @app.route('/api/pause', methods=['POST'])
    def pause_music():
        """暂停播放"""
        data = request.json
        if not data:
            return jsonify({'success': False, 'error': '请求数据为空'})

        guild_id = data.get('guild_id')
        channel_id = data.get('channel_id') or _find_channel_for_guild(guild_id)

        if not channel_id:
            return jsonify({'success': False, 'error': '缺少必要参数'})

        try:
            player = kookvoice.Player(channel_id)
            player.pause()
            return jsonify({'success': True})
        except Exception as e:
            logger.error(f"暂停播放异常: {type(e).__name__}")
            return _route_error(e)

    @app.route('/api/resume', methods=['POST'])
    def resume_music():
        """继续播放"""
        data = request.json
        if not data:
            return jsonify({'success': False, 'error': '请求数据为空'})

        guild_id = data.get('guild_id')
        channel_id = data.get('channel_id') or _find_channel_for_guild(guild_id)

        if not channel_id:
            return jsonify({'success': False, 'error': '缺少必要参数'})

        try:
            player = kookvoice.Player(channel_id)
            player.resume()
            return jsonify({'success': True})
        except Exception as e:
            logger.error(f"继续播放异常: {type(e).__name__}")
            return _route_error(e)

    @app.route('/api/stop', methods=['POST'])
    def stop_music():
        """停止播放"""
        data = request.json
        if not data:
            return jsonify({'success': False, 'error': '请求数据为空'})

        guild_id = data.get('guild_id')
        channel_id = data.get('channel_id') or _find_channel_for_guild(guild_id)

        if not channel_id:
            return jsonify({'success': False, 'error': '缺少必要参数'})

        try:
            player = kookvoice.Player(channel_id)
            player.stop()
            return jsonify({'success': True})
        except Exception as e:
            logger.error(f"停止播放异常: {type(e).__name__}")
            return _route_error(e)
    
    @app.route('/api/clear', methods=['POST'])
    def clear_playlist():
        """清空播放列表"""
        data = request.json
        if not data:
            return jsonify({'success': False, 'error': '请求数据为空'})

        guild_id = data.get('guild_id')
        channel_id = data.get('channel_id') or _find_channel_for_guild(guild_id)

        if not channel_id:
            return jsonify({'success': False, 'error': '缺少必要参数'})

        try:
            with kookvoice.state_lock:
                if channel_id in kookvoice.play_list:
                    kookvoice.play_list[channel_id]['play_list'] = []
                return jsonify({'success': True})
        except Exception as e:
            logger.error(f"清空播放列表异常: {type(e).__name__}")
            return _route_error(e)

    @app.route('/api/remove', methods=['POST'])
    def remove_from_playlist():
        """从播放列表中移除歌曲"""
        data = request.json
        if not data:
            return jsonify({'success': False, 'error': '请求数据为空'})

        guild_id = data.get('guild_id')
        channel_id = data.get('channel_id') or _find_channel_for_guild(guild_id)
        index = data.get('index')

        if not channel_id or index is None:
            return jsonify({'success': False, 'error': '缺少必要参数'})

        try:
            with kookvoice.state_lock:
                if channel_id in kookvoice.play_list:
                    playlist = kookvoice.play_list[channel_id]['play_list']
                    if 0 <= int(index) < len(playlist):
                        playlist.pop(int(index))
                        return jsonify({'success': True})
                    return jsonify({'success': False, 'error': '索引超出范围'})
                return jsonify({'success': False, 'error': '播放列表不存在'})
        except Exception as e:
            logger.error(f"移除歌曲异常: {type(e).__name__}")
            return _route_error(e)
    
    @app.route('/api/system/status', methods=['GET'])
    def get_system_status():
        """获取系统状态信息"""
        try:
            import psutil
            import os as _os

            cpu_percent = psutil.cpu_percent(interval=None)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')

            process = psutil.Process()
            process_memory = process.memory_info()
            process_cpu = process.cpu_percent()

            network = psutil.net_io_counters()

            snapshot = kookvoice.get_state_snapshot()
            playlists = snapshot['play_list']
            active_guilds = len(playlists)
            playing_songs = 0
            queued_songs = 0

            for gd in playlists.values():
                if gd.get('now_playing'):
                    playing_songs += 1
                queued_songs += len(gd.get('play_list', []))

            return jsonify({
                'success': True,
                'system': {
                    'cpu_percent': cpu_percent,
                    'memory': {
                        'total': memory.total, 'available': memory.available,
                        'percent': memory.percent, 'used': memory.used,
                    },
                    'disk': {
                        'total': disk.total, 'used': disk.used,
                        'free': disk.free, 'percent': (disk.used / disk.total) * 100,
                    },
                    'network': {
                        'bytes_sent': network.bytes_sent, 'bytes_recv': network.bytes_recv,
                        'packets_sent': network.packets_sent, 'packets_recv': network.packets_recv,
                    },
                },
                'process': {
                    'pid': process.pid,
                    'memory_rss': process_memory.rss, 'memory_vms': process_memory.vms,
                    'cpu_percent': process_cpu,
                    'create_time': process.create_time(),
                    'uptime': time.time() - process.create_time(),
                },
                'playback': {
                    'active_guilds': active_guilds,
                    'playing_songs': playing_songs, 'queued_songs': queued_songs,
                },
                'timestamp': time.time(),
            })
        except Exception as e:
            logger.error(f"获取系统状态异常: {type(e).__name__}")
            return _route_error(e)

    @app.route('/api/logs', methods=['GET'])
    def get_logs():
        """获取日志信息"""
        try:
            lines = request.args.get('lines', 100, type=int)
            lines = max(1, min(lines if lines is not None else 100, MAX_LOG_LINES))
            log_type = request.args.get('type', 'app', type=str)

            log_file = _resolve_log_path(log_type)
            if not log_file:
                return jsonify({'success': False, 'error': '无效的日志类型'})

            if not os.path.exists(log_file):
                return jsonify({'success': False, 'error': '日志文件不存在'})

            recent_lines, scanned_lines, truncated = _read_log_tail(log_file, lines)

            logs = []
            for line in recent_lines:
                line = _redact_log_text(line.strip(), 4096)
                if line:
                    if ' - ' in line:
                        parts = line.split(' - ', 2)
                        if len(parts) >= 3:
                            level = 'error' if 'ERROR' in parts[1] else ('warning' if 'WARNING' in parts[1] else ('debug' if 'DEBUG' in parts[1] else 'info'))
                            logs.append({'timestamp': parts[0], 'level': level, 'message': parts[2], 'raw': line})
                        else:
                            logs.append({'timestamp': '', 'level': 'info', 'message': line, 'raw': line})
                    else:
                        logs.append({'timestamp': '', 'level': 'info', 'message': line, 'raw': line})

            return jsonify({
                'success': True,
                'logs': logs,
                'total_lines': scanned_lines,
                'returned_lines': len(logs),
                'log_type': log_type,
                'truncated': truncated,
            })
        except Exception as e:
            logger.error(f"获取日志异常: {type(e).__name__}")
            return _route_error(e)

    @app.route('/api/logs/clear', methods=['POST'])
    def clear_logs():
        """清空日志文件"""
        try:
            log_type = request.json.get('type', 'app') if request.json else 'app'
            log_file = _resolve_log_path(log_type)
            if not log_file:
                return jsonify({'success': False, 'error': '无效的日志类型'})
            _truncate_private_file(log_file)
            return jsonify({'success': True, 'message': f'{log_type}日志已清空'})
        except Exception as e:
            logger.error(f"清空日志异常: {type(e).__name__}")
            return _route_error(e)

    @app.route('/api/system/cleanup', methods=['POST'])
    def manual_cleanup():
        """手动清理缓存和内存"""
        try:
            import psutil
            import gc
            process = psutil.Process()
            memory_before = process.memory_info()
            cache_before = 0
            try:
                from kookvoice.kookvoice import audio_cache
                cache_before = len(audio_cache)
                audio_cache.clear()
            except Exception:
                pass
            try:
                from kookvoice.kookvoice import song_play_count
                song_play_count.clear()
            except Exception:
                pass
            gc.collect()
            memory_after = process.memory_info()
            memory_freed = (memory_before.rss - memory_after.rss) / 1024 / 1024
            return jsonify({
                'success': True, 'message': '手动清理完成',
                'details': {
                    'cache_cleared': cache_before,
                    'memory_freed_mb': round(memory_freed, 2),
                    'memory_before_mb': round(memory_before.rss / 1024 / 1024, 2),
                    'memory_after_mb': round(memory_after.rss / 1024 / 1024, 2),
                }
            })
        except Exception as e:
            logger.error(f"手动清理异常: {type(e).__name__}")
            return _route_error(e)

    @app.route('/api/system/cleanup/config', methods=['POST'])
    def update_cleanup_config():
        """更新清理配置"""
        try:
            data = request.json
            if not data:
                return jsonify({'success': False, 'error': '请求数据为空'})
            new_threshold = data.get('threshold')
            if new_threshold is not None:
                if not isinstance(new_threshold, int) or new_threshold < 1 or new_threshold > 10:
                    return jsonify({'success': False, 'error': '清理阈值必须在1-10之间'})
                import kookvoice.kookvoice as kv
                kv.cleanup_threshold = new_threshold
                return jsonify({'success': True, 'message': f'清理阈值已更新为 {new_threshold} 首歌曲', 'new_threshold': new_threshold})
            return jsonify({'success': False, 'error': '缺少threshold参数'})
        except Exception as e:
            logger.error(f"更新清理配置异常: {type(e).__name__}")
            return _route_error(e)

    @app.route('/api/terminal/output', methods=['GET'])
    def get_terminal_output():
        """获取终端输出（增量）"""
        try:
            last_position = request.args.get('last_position', 0, type=int)
            last_position = max(0, last_position if last_position is not None else 0)
            log_file = _RUNTIME_LOG_PATH
            if os.path.exists(log_file):
                file_size = os.path.getsize(log_file)
                if file_size < last_position:
                    last_position = 0
                output = ""
                truncated = False
                if file_size > last_position:
                    read_position = last_position
                    if file_size - read_position > MAX_LOG_READ_BYTES:
                        read_position = file_size - MAX_LOG_READ_BYTES
                        truncated = True
                    with open(log_file, 'rb') as f:
                        f.seek(read_position)
                        output = f.read(MAX_LOG_READ_BYTES).decode('utf-8', errors='replace')
                output = _redact_log_text(output)
                return jsonify({
                    'success': True,
                    'output': output,
                    'timestamp': time.time(),
                    'file_size': file_size,
                    'last_position': file_size,
                    'truncated': truncated,
                })
            return jsonify({'success': True, 'output': '日志文件不存在', 'timestamp': time.time(), 'file_size': 0, 'last_position': 0})
        except Exception as e:
            logger.error(f"获取终端输出异常: {type(e).__name__}")
            return _route_error(e)

    @app.route('/api/cache/test', methods=['POST'])
    def test_cache():
        """测试缓存功能"""
        try:
            import threading
            try:
                from kookvoice.kookvoice import audio_cache
            except ImportError:
                return jsonify({
                    'success': True,
                    'message': '当前版本未启用音频缓存',
                    'cache_count': 0,
                })
            test_file = "test_audio.mp3"

            def run_test_preload():
                try:
                    cache_key = f"{test_file}:0"
                    if cache_key not in audio_cache:
                        audio_cache[cache_key] = {
                            'data': b'test_audio_data_' + str(time.time()).encode(),
                            'timestamp': time.time(),
                            'size': 1024 * 1024,
                        }
                        logger.info(f'测试缓存添加成功: {cache_key}')
                except Exception as e:
                    logger.error(f'测试缓存失败: {type(e).__name__}')

            test_thread = threading.Thread(target=run_test_preload)
            test_thread.daemon = True
            test_thread.start()
            return jsonify({'success': True, 'message': '测试缓存已启动', 'cache_count': len(audio_cache)})
        except Exception as e:
            logger.error(f"测试缓存异常: {type(e).__name__}")
            return _route_error(e)

# 辅助函数
async def get_guild_list(bot):
    """获取服务器列表"""
    try:
        guilds = await bot.client.gate.request('GET', 'guild/list')
        if guilds and "items" in guilds:
            return guilds["items"]
        return []
    except Exception as e:
        logger.error(f"获取服务器列表异常: {type(e).__name__}")
        return []

async def get_channel_list(bot, guild_id):
    """获取频道列表"""
    try:
        channels = await bot.client.gate.request('GET', 'channel/list', params={'guild_id': guild_id})
        if channels and "items" in channels:
            # 过滤出语音频道
            voice_channels = [c for c in channels["items"] if c.get('type') == 2]
            return voice_channels
        return []
    except Exception as e:
        logger.error(f"获取频道列表异常: {type(e).__name__}")
        return []
