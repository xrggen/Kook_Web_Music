from flask import render_template, request, jsonify, redirect, url_for, Blueprint
import logging
import asyncio
import json
import os
import time
import subprocess
import kookvoice
from utils import search_music, get_music_url, get_playlist, get_playlist_urls, format_playlist_data
from qq_utils import search_qq_music, get_qq_music_url, get_qq_playlist_urls, refill_qq_playlist_queue
from bili_utils import search_bili_music, get_bili_play_url, get_bili_favorite_all_tracks, refill_bili_playlist_queue
import threading

logger = logging.getLogger(__name__)

# 全局变量
guild_data = {}  # 存储服务器信息
current_guild_id = None  # 当前选中的服务器ID

# 异步函数运行器
def run_async(coro):
    """在Flask中运行异步函数"""
    try:
        # 创建新的事件循环在线程中运行
        result = [None]
        exception = [None]
        
        def run_in_thread():
            try:
                # 创建新的事件循环
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                
                # 运行协程
                result[0] = new_loop.run_until_complete(coro)
            except Exception as e:
                exception[0] = e
            finally:
                # 清理事件循环
                try:
                    new_loop.close()
                except:
                    pass
        
        # 在新线程中运行
        thread = threading.Thread(target=run_in_thread)
        thread.start()
        thread.join(timeout=15)  # 15秒超时
        
        if thread.is_alive():
            # 超时处理
            logger.warning("异步函数执行超时")
            return None
            
        if exception[0]:
            raise exception[0]
        return result[0]
        
    except Exception as e:
        logger.error(f"运行异步函数异常: {e}")
        return None

def _find_channel_for_guild(guild_id):
    """同步查找服务器内的活跃语音频道。多频道时返回第一个但记录警告。"""
    matches = []
    for ch_id, data in kookvoice.play_list.items():
        if data.get('guild_id') == str(guild_id):
            matches.append(ch_id)
    if len(matches) > 1:
        logger.warning("[频道定位] 服务器 %s 有 %d 个活跃频道，应传 channel_id 精确定位", guild_id, len(matches))
    return matches[0] if matches else None


def register_routes(app, bot, socketio=None):
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
        return render_template('monitor.html')
    
    @app.route('/api/guilds', methods=['GET'])
    def get_guilds():
        """获取服务器列表"""
        try:
            # 使用同步方式调用KOOK API获取服务器列表
            try:
                import requests
                from config import BOT_TOKEN
                headers = {
                    'Authorization': f'Bot {BOT_TOKEN}',
                    'Content-Type': 'application/json'
                }
                url = 'https://www.kookapp.cn/api/v3/guild/list'
                
                logger.info(f"请求服务器列表API: {url}")
                response = requests.get(url, headers=headers, timeout=10)
                logger.info(f"服务器列表API响应状态: {response.status_code}")
                
                if response.status_code == 200:
                    data = response.json()
                    logger.info(f"服务器列表API响应数据: {data}")
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
                logger.error(f"获取服务器列表异常: {e}")
                guilds = []
            
            # 格式化数据
            formatted_guilds = []
            for guild in guilds:
                formatted_guilds.append({
                    'id': guild.get('id', ''),
                    'name': guild.get('name', '未知服务器'),
                    'icon': guild.get('icon', ''),
                    'master_id': guild.get('master_id', '')
                })
            
            return jsonify({'success': True, 'guilds': formatted_guilds})
        except Exception as e:
            logger.error(f"获取服务器列表异常: {e}")
            return jsonify({'success': False, 'error': str(e)})
    
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
                from config import BOT_TOKEN
                headers = {
                    'Authorization': f'Bot {BOT_TOKEN}',
                    'Content-Type': 'application/json'
                }
                url = f'https://www.kookapp.cn/api/v3/channel/list?guild_id={guild_id}'
                
                response = requests.get(url, headers=headers, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    if data.get('code') == 0 and 'data' in data:
                        channels = data['data'].get('items', [])
                    else:
                        channels = []
                else:
                    channels = []
            except Exception as e:
                logger.error(f"获取频道列表异常: {e}")
                channels = []
            
            # 格式化数据，只返回语音频道
            formatted_channels = []
            for channel in channels:
                # 只返回语音频道 (type=2)
                if channel.get('type') == 2:
                    formatted_channels.append({
                        'id': channel.get('id', ''),
                        'name': channel.get('name', '未知频道'),
                        'type': channel.get('type', 2)
                    })
            
            return jsonify({'success': True, 'channels': formatted_channels})
        except Exception as e:
            logger.error(f"获取频道列表异常: {e}")
            return jsonify({'success': False, 'error': str(e)})

    @app.route('/api/channels/active', methods=['GET'])
    def get_active_channels():
        """获取指定服务器内所有活跃语音频道的播放状态"""
        guild_id = request.args.get('guild_id')
        if not guild_id:
            return jsonify({'success': False, 'error': '缺少guild_id参数'})
        active = {}
        for ch_id, data in kookvoice.play_list.items():
            if data.get('guild_id') == str(guild_id):
                status = 'idle'
                if ch_id in kookvoice.guild_status:
                    s = kookvoice.guild_status[ch_id]
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
            from config import BOT_TOKEN
            player = kookvoice.Player(channel_id, BOT_TOKEN)
            player.join(guild_id)

            global current_guild_id
            current_guild_id = guild_id

            return jsonify({'success': True})
        except Exception as e:
            logger.error(f"加入语音频道异常: {e}")
            return jsonify({'success': False, 'error': str(e)})

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
            logger.error(f"离开语音频道异常: {e}")
            return jsonify({'success': False, 'error': str(e)})
    
    @app.route('/api/search', methods=['GET'])
    def search():
        """搜索音乐"""
        keyword = request.args.get('keyword')
        platform = request.args.get('platform', 'wy')
        if not keyword:
            return jsonify({'success': False, 'error': '缺少keyword参数'})

        try:
            if platform == 'qq':
                songs = search_qq_music(keyword)
            elif platform == 'bili':
                songs = search_bili_music(keyword)
            else:
                songs = search_music(keyword)
            return jsonify({'success': True, 'songs': songs})
        except Exception as e:
            logger.error(f"搜索音乐异常: {e}")
            return jsonify({'success': False, 'error': str(e)})

    @app.route('/api/play', methods=['POST'])
    def play_music():
        """播放音乐"""
        data = request.json
        if not data:
            return jsonify({'success': False, 'error': '请求数据为空'})

        guild_id = data.get('guild_id')
        channel_id = data.get('channel_id')
        song_id = data.get('song_id')
        song_name = data.get('song_name', '')
        artist_name = data.get('artist_name', '')
        platform = data.get('platform', 'wy')

        if not guild_id or not song_id:
            return jsonify({'success': False, 'error': '缺少必要参数'})

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

            from config import BOT_TOKEN
            player = kookvoice.Player(channel_id, BOT_TOKEN)
            extra = {'title': song_name, 'artist': artist_name}
            if platform == 'bili':
                extra['platform'] = 'bili'
                extra['duration'] = bili_duration
            player.add_music(url, extra)

            return jsonify({'success': True})
        except Exception as e:
            logger.error(f"播放音乐异常: {e}")
            return jsonify({'success': False, 'error': str(e)})
    
    @app.route('/api/playlist', methods=['POST'])
    def add_playlist():
        """添加歌单"""
        data = request.json
        if not data:
            return jsonify({'success': False, 'error': '请求数据为空'})

        guild_id = data.get('guild_id')
        channel_id = data.get('channel_id')
        playlist_id = data.get('playlist_id')
        platform = data.get('platform', 'wy')

        if not guild_id or not playlist_id:
            return jsonify({'success': False, 'error': '缺少必要参数'})

        try:
            from config import BOT_TOKEN
            player = kookvoice.Player(channel_id, BOT_TOKEN)

            if platform == 'qq':
                songs = get_qq_playlist_urls(playlist_id)
                if not songs:
                    return jsonify({'success': False, 'error': '歌单为空或无法获取歌单'})
                for song in songs:
                    player.add_music(song['marker'], {
                        'title': song['name'],
                        'artist': song['artist'],
                        '音乐名字': song['name'],
                    })
                prefetched = refill_qq_playlist_queue(channel_id, kookvoice.play_list)
            elif platform == 'bili':
                songs = get_bili_favorite_all_tracks(playlist_id)
                if not songs:
                    return jsonify({'success': False, 'error': '收藏夹为空或无法获取'})
                for song in songs:
                    player.add_music(song['marker'], {
                        'title': song['name'],
                        'artist': song['artist'],
                        '音乐名字': song['name'],
                        'platform': 'bili',
                    })
                prefetched = refill_bili_playlist_queue(channel_id, kookvoice.play_list)
            else:
                songs = get_playlist_urls(playlist_id)
                if not songs:
                    return jsonify({'success': False, 'error': '歌单为空或无法获取歌单'})
                for song in songs:
                    player.add_music(song['marker'], {
                        'title': song['name'],
                        'artist': song['artist'],
                        '音乐名字': song['name'],
                    })
                from utils import refill_playlist_queue
                prefetched = refill_playlist_queue(channel_id, kookvoice.play_list)

            logger.info(f"[歌单导入] platform={platform} {len(songs)}首 预取{prefetched}首")
            return jsonify({'success': True, 'count': len(songs)})
        except Exception as e:
            logger.error(f"添加歌单异常: {e}")
            return jsonify({'success': False, 'error': str(e)})
    
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
            logger.error(f"跳过歌曲异常: {e}")
            return jsonify({'success': False, 'error': str(e)})
    
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
            logger.error(f"跳转位置异常: {e}")
            return jsonify({'success': False, 'error': str(e)})
    
    @app.route('/api/playlist/current', methods=['GET'])
    def get_current_playlist():
        """获取当前播放列表"""
        guild_id = request.args.get('guild_id')
        channel_id = request.args.get('channel_id') or _find_channel_for_guild(guild_id)

        if not channel_id:
            return jsonify({'success': True, 'playlist': []})

        try:
            if channel_id in kookvoice.play_list:
                playlist_data = format_playlist_data(kookvoice.play_list[channel_id])
                return jsonify({'success': True, 'playlist': playlist_data})
            else:
                return jsonify({'success': True, 'playlist': []})
        except Exception as e:
            logger.error(f"获取播放列表异常: {e}")
            return jsonify({'success': False, 'error': str(e)})
    
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
            logger.error(f"暂停播放异常: {e}")
            return jsonify({'success': False, 'error': str(e)})

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
            logger.error(f"继续播放异常: {e}")
            return jsonify({'success': False, 'error': str(e)})

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
            logger.error(f"停止播放异常: {e}")
            return jsonify({'success': False, 'error': str(e)})
    
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
            if channel_id in kookvoice.play_list:
                kookvoice.play_list[channel_id]['play_list'] = []
                return jsonify({'success': True})
            else:
                return jsonify({'success': True})
        except Exception as e:
            logger.error(f"清空播放列表异常: {e}")
            return jsonify({'success': False, 'error': str(e)})

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
            if channel_id in kookvoice.play_list:
                playlist = kookvoice.play_list[channel_id]['play_list']
                if 0 <= int(index) < len(playlist):
                    playlist.pop(int(index))
                    return jsonify({'success': True})
                else:
                    return jsonify({'success': False, 'error': '索引超出范围'})
            else:
                return jsonify({'success': False, 'error': '播放列表不存在'})
        except Exception as e:
            logger.error(f"移除歌曲异常: {e}")
            return jsonify({'success': False, 'error': str(e)})
    
    @app.route('/api/system/status', methods=['GET'])
    def get_system_status():
        """获取系统状态信息"""
        try:
            import psutil
            import os as _os

            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')

            process = psutil.Process()
            process_memory = process.memory_info()
            process_cpu = process.cpu_percent()

            network = psutil.net_io_counters()

            active_guilds = len(kookvoice.play_list)
            playing_songs = 0
            queued_songs = 0

            for gd in kookvoice.play_list.values():
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
            logger.error(f"获取系统状态异常: {e}")
            return jsonify({'success': False, 'error': str(e)})

    @app.route('/api/logs', methods=['GET'])
    def get_logs():
        """获取日志信息"""
        try:
            lines = request.args.get('lines', 100, type=int)
            log_type = request.args.get('type', 'app', type=str)

            log_file = 'app.log' if log_type == 'app' else ('debug.log' if log_type == 'debug' else None)
            if not log_file:
                return jsonify({'success': False, 'error': '无效的日志类型'})

            if not os.path.exists(log_file):
                return jsonify({'success': False, 'error': '日志文件不存在'})

            with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                all_lines = f.readlines()
                recent_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines

            logs = []
            for line in recent_lines:
                line = line.strip()
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

            return jsonify({'success': True, 'logs': logs, 'total_lines': len(all_lines), 'returned_lines': len(logs), 'log_type': log_type})
        except Exception as e:
            logger.error(f"获取日志异常: {e}")
            return jsonify({'success': False, 'error': str(e)})

    @app.route('/api/logs/clear', methods=['POST'])
    def clear_logs():
        """清空日志文件"""
        try:
            log_type = request.json.get('type', 'app') if request.json else 'app'
            log_file = 'app.log' if log_type == 'app' else ('debug.log' if log_type == 'debug' else None)
            if not log_file:
                return jsonify({'success': False, 'error': '无效的日志类型'})
            with open(log_file, 'w', encoding='utf-8') as f:
                f.write('')
            return jsonify({'success': True, 'message': f'{log_type}日志已清空'})
        except Exception as e:
            logger.error(f"清空日志异常: {e}")
            return jsonify({'success': False, 'error': str(e)})

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
            logger.error(f"手动清理异常: {e}")
            return jsonify({'success': False, 'error': str(e)})

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
            logger.error(f"更新清理配置异常: {e}")
            return jsonify({'success': False, 'error': str(e)})

    @app.route('/api/terminal/output', methods=['GET'])
    def get_terminal_output():
        """获取终端输出（增量）"""
        try:
            last_position = request.args.get('last_position', 0, type=int)
            log_file = 'app.log'
            if os.path.exists(log_file):
                file_size = os.path.getsize(log_file)
                if file_size < last_position:
                    last_position = 0
                output = ""
                if file_size > last_position:
                    with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                        f.seek(last_position)
                        output = f.read()
                return jsonify({'success': True, 'output': output, 'timestamp': time.time(), 'file_size': file_size, 'last_position': last_position})
            return jsonify({'success': True, 'output': '日志文件不存在', 'timestamp': time.time(), 'file_size': 0, 'last_position': 0})
        except Exception as e:
            logger.error(f"获取终端输出异常: {e}")
            return jsonify({'success': False, 'error': str(e)})

    @app.route('/api/terminal/command', methods=['POST'])
    def execute_terminal_command():
        """执行安全的终端命令"""
        try:
            data = request.json
            if not data or 'command' not in data:
                return jsonify({'success': False, 'error': '缺少命令参数'})
            command = data['command']
            allowed = {'ps', 'top', 'htop', 'df', 'free', 'uptime', 'whoami', 'pwd', 'ls', 'cat', 'tail', 'head', 'grep', 'find'}
            command_base = command.split()[0] if command.split() else ''
            if command_base not in allowed:
                return jsonify({'success': False, 'error': f'不允许执行命令: {command_base}'})
            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
            return jsonify({'success': True, 'stdout': result.stdout, 'stderr': result.stderr, 'returncode': result.returncode, 'command': command})
        except subprocess.TimeoutExpired:
            return jsonify({'success': False, 'error': '命令执行超时'})
        except Exception as e:
            logger.error(f"执行终端命令异常: {e}")
            return jsonify({'success': False, 'error': str(e)})

    @app.route('/api/cache/test', methods=['POST'])
    def test_cache():
        """测试缓存功能"""
        try:
            import threading
            from kookvoice.kookvoice import audio_cache
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
                    logger.error(f'测试缓存失败: {e}')

            test_thread = threading.Thread(target=run_test_preload)
            test_thread.daemon = True
            test_thread.start()
            return jsonify({'success': True, 'message': '测试缓存已启动', 'cache_count': len(audio_cache)})
        except Exception as e:
            logger.error(f"测试缓存异常: {e}")
            return jsonify({'success': False, 'error': str(e)})

    # 如果SocketIO可用，注册SocketIO事件
    if socketio:
        @socketio.on('connect')
        def handle_connect():
            logger.info('客户端已连接')

        @socketio.on('disconnect')
        def handle_disconnect():
            logger.info('客户端已断开连接')
        
        @socketio.on('join_room')
        def handle_join_room(data):
            guild_id = data.get('guild_id')
            if guild_id:
                socketio.join_room(guild_id)
                logger.info(f'客户端加入房间: {guild_id}')
        
        @socketio.on('leave_room')
        def handle_leave_room(data):
            guild_id = data.get('guild_id')
            if guild_id:
                socketio.leave_room(guild_id)
                logger.info(f'客户端离开房间: {guild_id}')

# 辅助函数
async def get_guild_list(bot):
    """获取服务器列表"""
    try:
        guilds = await bot.client.gate.request('GET', 'guild/list')
        if guilds and "items" in guilds:
            return guilds["items"]
        return []
    except Exception as e:
        logger.error(f"获取服务器列表异常: {e}")
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
        logger.error(f"获取频道列表异常: {e}")
        return []