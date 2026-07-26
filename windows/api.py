from flask import Blueprint, current_app, jsonify
import logging
import os

try:
    from .kookvoice import kookvoice
    from .config import FFMPEG_PATH
except ImportError:
    from kookvoice import kookvoice
    from config import FFMPEG_PATH

logger = logging.getLogger(__name__)
api_bp = Blueprint('api', __name__)

@api_bp.route('/stats', methods=['GET'])
def get_stats():
    """获取系统统计数据"""
    try:
        snapshot = kookvoice.get_state_snapshot()
        playlists = snapshot['play_list']
        active_guilds = len(playlists)

        playing_songs = 0
        queued_songs = 0
        for channel_id, guild_data in playlists.items():
            if guild_data.get('now_playing'):
                playing_songs += 1
            queued_songs += len(guild_data.get('play_list', []))

        bot = current_app.extensions.get('kook_bot')
        bot_status = 'online' if bot and getattr(bot, 'is_running', False) else 'offline'
        ffmpeg_status = 'normal' if os.path.exists(FFMPEG_PATH) else 'error'

        return jsonify({
            'active_guilds': active_guilds,
            'playing_songs': playing_songs,
            'queued_songs': queued_songs,
            'bot_status': bot_status,
            'api_status': 'normal',
            'ffmpeg_status': ffmpeg_status
        })
    except Exception as e:
        logger.error(f"获取统计数据异常: {e}")
        return jsonify({
            'active_guilds': 0,
            'playing_songs': 0,
            'queued_songs': 0,
            'bot_status': 'error',
            'api_status': 'error',
            'ffmpeg_status': 'error'
        })
