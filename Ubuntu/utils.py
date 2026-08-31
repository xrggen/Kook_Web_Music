import requests
import logging
import json
import os
import re
from urllib.parse import urlsplit
try:
    from .config import MUSIC_API_BASE, MAX_PLAYLIST_IMPORT_TRACKS
    from .secure_storage import secure_read_text
except ImportError:
    from config import MUSIC_API_BASE, MAX_PLAYLIST_IMPORT_TRACKS
    from secure_storage import secure_read_text

logger = logging.getLogger(__name__)

COOKIE_TXT_PATH = os.path.join(os.path.dirname(__file__), "Cookie", "cookie.txt")
MAX_COOKIE_CHARS = 64 * 1024
MAX_SEARCH_KEYWORD_LENGTH = 256
MAX_SEARCH_RESULTS = 30
MAX_NUMERIC_ID_LENGTH = 20
MAX_MEDIA_URL_LENGTH = 8192
MAX_METADATA_TEXT_LENGTH = 512
_NUMERIC_ID_RE = re.compile(r"[0-9]+")


def _normalize_numeric_id(value):
    if isinstance(value, bool):
        return ""
    text = str(value) if isinstance(value, int) else value
    if (
        not isinstance(text, str)
        or not text
        or text != text.strip()
        or len(text) > MAX_NUMERIC_ID_LENGTH
        or not text.isascii()
        or _NUMERIC_ID_RE.fullmatch(text) is None
        or int(text) <= 0
    ):
        return ""
    return text


def _safe_text(value, limit=MAX_METADATA_TEXT_LENGTH):
    if value is None:
        return ""
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return ""
    text = str(value)[:limit]
    text = "".join(
        " " if ord(char) < 32 or ord(char) == 127 else char
        for char in text
    )
    return text.strip()


def _normalize_media_url(value):
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if (
        not value
        or len(value) > MAX_MEDIA_URL_LENGTH
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        return ""
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return ""
        if parsed.username is not None or parsed.password is not None:
            return ""
        _ = parsed.port
    except ValueError:
        return ""
    return value


def _normalize_artist_list(value):
    if not isinstance(value, list):
        return []
    return [
        {"name": _safe_text(item.get("name", ""))}
        for item in value[:16]
        if isinstance(item, dict)
    ]


def _normalize_song(item):
    if not isinstance(item, dict):
        return None
    song_id = _normalize_numeric_id(item.get("id"))
    if not song_id:
        return None
    album = item.get("al") if isinstance(item.get("al"), dict) else {}
    return {
        "id": song_id,
        "name": _safe_text(item.get("name", "")),
        "ar": _normalize_artist_list(item.get("ar", [])),
        "al": {"name": _safe_text(album.get("name", ""))},
    }


def _normalize_track(item):
    return _normalize_song(item)


def load_cookie_header():
    try:
        if os.path.exists(COOKIE_TXT_PATH):
            cookie = secure_read_text(
                COOKIE_TXT_PATH,
                max_chars=MAX_COOKIE_CHARS + 1,
            ).strip()
            if len(cookie) <= MAX_COOKIE_CHARS and not any(
                char in cookie for char in ("\r", "\n", "\0")
            ):
                return cookie
    except Exception:
        pass
    return ""


def build_headers(extra: dict | None = None):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127 Safari/537.36",
    }
    cookie_str = load_cookie_header()
    if cookie_str:
        headers["Cookie"] = cookie_str
    if extra:
        headers.update(extra)
    return headers

# 搜索音乐
def search_music(keyword):
    if not isinstance(keyword, str):
        return []
    keyword = keyword.strip()
    if (
        not keyword
        or len(keyword) > MAX_SEARCH_KEYWORD_LENGTH
        or any(ord(char) < 32 or ord(char) == 127 for char in keyword)
    ):
        return []
    url = f"{MUSIC_API_BASE}/cloudsearch"
    logger.info("[搜索] 请求本机API")
    try:
        res = requests.get(
            url,
            params={"keywords": keyword, "limit": MAX_SEARCH_RESULTS},
            headers=build_headers(),
            timeout=15,
            allow_redirects=False,
        )
        data = res.json()
        result = data.get('result', {}) if isinstance(data, dict) else {}
        if not isinstance(result, dict):
            return []
        raw_songs = result.get('songs', [])
        if not isinstance(raw_songs, list):
            return []
        songs = [
            song for song in (_normalize_song(item) for item in raw_songs[:MAX_SEARCH_RESULTS])
            if song is not None
        ]
        song_count = result.get('songCount', len(songs))
        logger.info(f"[搜索] 状态={res.status_code} 结果数={len(songs)} 总数={song_count}")
        if songs:
            top = songs[0]
            logger.info(
                "[搜索] 首条 name=%r artist=%r id=%r",
                str(top.get('name', '?'))[:120],
                str((top.get('ar') or [{}])[0].get('name', '?'))[:120],
                str(top.get('id', ''))[:64],
            )
        return songs
    except Exception as e:
        logger.error(f"[搜索] 本地API异常: {type(e).__name__}")
        return []

# 获取音乐URL
def get_music_url(song_id):
    song_id = _normalize_numeric_id(song_id)
    if not song_id:
        return ''
    url = f"{MUSIC_API_BASE}/song/url"
    logger.info("[取链] 请求本机API")
    try:
        res = requests.get(
            url,
            params={"id": song_id},
            headers=build_headers(),
            timeout=15,
            allow_redirects=False,
        )
        data = res.json()
        entries = data.get('data', []) if isinstance(data, dict) else []
        entry = entries[0] if isinstance(entries, list) and entries and isinstance(entries[0], dict) else {}
        music_url = _normalize_media_url(entry.get('url', ''))
        br = entry.get('br', 0)
        logger.info(f"[取链] 状态={res.status_code} 码率={br}  {'成功' if music_url else '失败(无链接)'}")
        return music_url
    except Exception as e:
        logger.error(f"[取链] 本地API异常: {type(e).__name__}")
        return ''

# 获取歌单
def get_playlist(playlist_id):
    playlist_id = _normalize_numeric_id(playlist_id)
    if not playlist_id:
        return {}
    url = f"{MUSIC_API_BASE}/playlist/detail"
    logger.info("[歌单] 请求本机API")
    try:
        res = requests.get(
            url,
            params={"id": playlist_id},
            headers=build_headers(),
            timeout=20,
            allow_redirects=False,
        )
        data = res.json()
        raw_playlist = data.get('playlist', {}) if isinstance(data, dict) else {}
        if not isinstance(raw_playlist, dict):
            return {}
        try:
            count = max(0, min(int(raw_playlist.get('trackCount', 0) or 0), 1_000_000_000))
        except (TypeError, ValueError, OverflowError):
            count = 0
        playlist = {
            'id': playlist_id,
            'name': _safe_text(raw_playlist.get('name', '?')),
            'trackCount': count,
        }
        name = playlist['name']
        logger.info("[歌单] 状态=%s 名称=%r 歌曲数=%s", res.status_code, str(name)[:120], count)
        return playlist
    except Exception as e:
        logger.error(f"[歌单] 本地API异常: {type(e).__name__}")
        return {}

# 获取歌单中所有歌曲（支持分页）
def get_playlist_all_tracks(playlist_id):
    """获取歌单中所有歌曲，支持分页"""
    playlist_id = _normalize_numeric_id(playlist_id)
    if not playlist_id:
        return []
    try:
        playlist = get_playlist(playlist_id)
        if not playlist:
            return []

        reported_count = max(0, int(playlist.get('trackCount', 0) or 0))
        track_count = min(reported_count, MAX_PLAYLIST_IMPORT_TRACKS)
        if track_count < reported_count:
            logger.warning(
                "[歌单分页] 歌曲数 %d 超过安全上限，截断为 %d",
                reported_count,
                track_count,
            )
        logger.info(f"[歌单分页] 总数={track_count} 开始分页拉取...")

        all_tracks = []
        limit = 1000
        offset = 0

        while offset < track_count:
            try:
                url = f"{MUSIC_API_BASE}/playlist/track/all"
                logger.info("[歌单分页] 请求本机API offset=%d", offset)
                res = requests.get(
                    url,
                    params={"id": str(playlist_id), "limit": limit, "offset": offset},
                    timeout=10,
                    headers=build_headers(),
                    allow_redirects=False,
                )
                if res.status_code == 200:
                    data = res.json()
                    raw_tracks = data.get('songs', []) if isinstance(data, dict) else []
                    if not isinstance(raw_tracks, list) or not raw_tracks:
                        break
                    requested = min(limit, track_count - offset,
                                    MAX_PLAYLIST_IMPORT_TRACKS - len(all_tracks))
                    tracks = [
                        track for track in (_normalize_track(item) for item in raw_tracks[:requested])
                        if track is not None
                    ]
                    all_tracks.extend(tracks)
                    logger.info(
                        f"[歌单分页] offset={offset} 本次={len(tracks)} 累计={len(all_tracks)}"
                    )
                    if len(raw_tracks) < requested:
                        break
                    offset += requested
                    if requested <= 0:
                        break
                else:
                    logger.error(f"[歌单分页] HTTP {res.status_code}")
                    break
            except Exception as e:
                logger.error(f"[歌单分页] 异常: {type(e).__name__}")
                break

        logger.info(f"[歌单分页] 完成 共获取 {len(all_tracks)} 首")
        return all_tracks[:MAX_PLAYLIST_IMPORT_TRACKS]

    except Exception as e:
        logger.error(f"[歌单分页] 获取异常: {type(e).__name__}")
        return []

# 获取歌单中所有歌曲信息（不获取URL）
def get_playlist_urls(playlist_id):
    """获取歌单中所有歌曲信息，使用.env中配置的API，不获取URL"""
    tracks = get_playlist_all_tracks(playlist_id)
    result = []
    logger.info(f"[歌单处理] 处理 {len(tracks)} 首歌曲...")
    for track in tracks:
        if not isinstance(track, dict):
            continue
        song_id = _normalize_numeric_id(track.get('id'))
        if not song_id:
            continue
        song_name = _safe_text(track.get('name', ''))
        artists = track.get('ar', [])
        artist_name = (
            _safe_text(artists[0].get('name', ''))
            if isinstance(artists, list) and artists and isinstance(artists[0], dict)
            else ''
        )
        song_marker = f"PLAYLIST_SONG:{song_id}:{song_name}:{artist_name}"
        result.append({
            'id': song_id,
            'name': song_name,
            'artist': artist_name,
            'marker': song_marker
        })
    logger.info(f"[歌单处理] 完成 {len(result)} 首")
    return result

BATCH_SIZE = 5  # 歌单每批预取URL数量


def resolve_marker_batch(markers, count=BATCH_SIZE):
    """批量解析 PLAYLIST_SONG:id:name:artist 标记为实际播放URL
    返回 {marker: url} dict，只包含成功获取到URL的项"""
    if not isinstance(markers, (list, tuple)):
        return {}
    if isinstance(count, bool):
        return {}
    try:
        count = int(count)
    except (TypeError, ValueError, OverflowError):
        return {}
    if not 1 <= count <= 20:
        return {}
    resolved = {}
    to_resolve = []
    for m in markers:
        if not isinstance(m, str):
            continue
        parts = m.split(":", 3)
        if (
            len(parts) >= 2
            and parts[0] == "PLAYLIST_SONG"
            and _normalize_numeric_id(parts[1])
            and m not in resolved
        ):
            to_resolve.append(m)
            if len(to_resolve) >= count:
                break
    if not to_resolve:
        return resolved

    ids = []
    for m in to_resolve:
        parts = m.split(":")
        if len(parts) >= 2:
            song_id = _normalize_numeric_id(parts[1])
            if song_id:
                ids.append(song_id)

    logger.info(f"[批量取链] 解析 {len(ids)} 个标记: {ids}")
    url = f"{MUSIC_API_BASE}/song/url"
    try:
        res = requests.get(
            url,
            params={"id": ",".join(ids)},
            headers=build_headers(),
            timeout=15,
            allow_redirects=False,
        )
        if res.status_code == 200:
            data = res.json()
            entries = data.get('data', []) if isinstance(data, dict) else []
            if not isinstance(entries, list):
                entries = []
            for item in entries[:len(ids)]:
                if not isinstance(item, dict):
                    continue
                song_id = _normalize_numeric_id(item.get('id'))
                song_url = _normalize_media_url(item.get('url', ''))
                if song_id and song_url:
                    for m in to_resolve:
                        parts = m.split(":")
                        if len(parts) >= 2 and parts[1] == song_id:
                            resolved[m] = song_url
                            break
        logger.info(f"[批量取链] 成功 {len(resolved)}/{len(ids)}")
    except Exception as e:
        logger.error(f"[批量取链] 异常: {type(e).__name__}")
    return resolved


def refill_playlist_queue(channel_id, play_list_dict, count=BATCH_SIZE, lock=None):
    """检查播放队列并将前 count 个 PLAYLIST_SONG 标记替换为真实URL"""
    def collect_markers():
        state = play_list_dict.get(channel_id)
        queue = state.get('play_list', []) if state else []
        return [
            item['file']
            for item in queue
            if isinstance(item, dict)
            and isinstance(item.get('file', ''), str)
            and item.get('file', '').startswith('PLAYLIST_SONG:')
        ]

    if lock is not None:
        with lock:
            markers = collect_markers()
    else:
        markers = collect_markers()
    if not markers:
        return 0

    resolved = resolve_marker_batch(markers, count)
    def apply_resolved():
        state = play_list_dict.get(channel_id)
        queue = state.get('play_list', []) if state else []
        replaced = 0
        for item in queue:
            if not isinstance(item, dict):
                continue
            marker = item.get('file', '')
            if marker in resolved:
                item['file'] = resolved[marker]
                replaced += 1
                if replaced >= count:
                    break
        return replaced

    if lock is not None:
        with lock:
            replaced = apply_resolved()
    else:
        replaced = apply_resolved()
    if replaced:
        logger.info(f"[批量取链] 已替换 {replaced} 个标记为真实URL")
    return replaced


def _display_metadata(file_path, extra_data):
    """Return stable display metadata for Web UI without exposing playback URLs as titles.

    Web-originated tracks use ``title``/``artist`` while legacy KOOK command tracks store
    the title in ``音乐名字``. Prefer explicit metadata from either source and only fall
    back to a local filename for actual local files.
    """
    extra_data = extra_data if isinstance(extra_data, dict) else {}
    title = extra_data.get('title') or extra_data.get('音乐名字')
    artist = extra_data.get('artist') or extra_data.get('歌手')

    if not title:
        if file_path.startswith(('http://', 'https://')):
            title = '未知歌曲'
        else:
            normalized_path = file_path.replace('\\', '/')
            title = normalized_path.rsplit('/', 1)[-1] or '未知歌曲'

    if not artist:
        artist = '未知歌手' if file_path.startswith(('http://', 'https://')) else '本地文件'

    return title, artist


# 格式化播放列表数据
def format_playlist_data(play_list_data):
    if not isinstance(play_list_data, dict):
        return []
    result = []
    
    # 处理当前播放的歌曲
    now_playing = play_list_data.get('now_playing')
    if now_playing:
        if not isinstance(now_playing, dict):
            now_playing = None
        file_path = now_playing.get('file', '') if now_playing else ''
        if not isinstance(file_path, str):
            file_path = ''
        extra_data = now_playing.get('extra', {}) if now_playing else {}
        
        # 检查是否是歌单歌曲标记（网易云 / QQ音乐）
        if file_path.startswith("PLAYLIST_SONG:") or file_path.startswith("QQ_PLAYLIST_SONG:"):
            parts = file_path.split(":")
            if len(parts) >= 4:
                song_id = parts[1]
                song_name = parts[2]
                artist_name = parts[3]

                result.append({
                    'id': song_id,
                    'name': song_name,
                    'artist': artist_name,
                    'duration': now_playing.get('duration', 0),
                    'playing': True,
                    'position': now_playing.get('ss', 0),
                    'start_time': now_playing.get('start', 0)
                })
        else:
            song_name, artist_name = _display_metadata(file_path, extra_data)
            result.append({
                'id': 'local',
                'name': song_name,
                'artist': artist_name,
                'duration': now_playing.get('duration', 0),
                'playing': True,
                'position': now_playing.get('ss', 0),
                'start_time': now_playing.get('start', 0)
            })
    
    # 处理播放列表中的歌曲
    play_list = play_list_data.get('play_list', [])
    if not isinstance(play_list, list):
        play_list = []
    for queue_index, item in enumerate(play_list):
        if not isinstance(item, dict):
            continue
        file_path = item.get('file', '')
        if not isinstance(file_path, str):
            file_path = ''
        extra_data = item.get('extra', {})
        
        # 检查是否是歌单歌曲标记（网易云 / QQ音乐）
        if file_path.startswith("PLAYLIST_SONG:") or file_path.startswith("QQ_PLAYLIST_SONG:"):
            parts = file_path.split(":")
            if len(parts) >= 4:
                song_id = parts[1]
                song_name = parts[2]
                artist_name = parts[3]

                result.append({
                    'id': song_id,
                    'name': song_name,
                    'artist': artist_name,
                    'duration': 0,
                    'queue_index': queue_index,
                    'playing': False
                })
        else:
            song_name, artist_name = _display_metadata(file_path, extra_data)
            result.append({
                'id': 'local',
                'name': song_name,
                'artist': artist_name,
                'queue_index': queue_index,
                'playing': False
            })
    
    return result

# 保存配置到文件
def save_config(config_data, file_path='config.json'):
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"保存配置异常: {type(e).__name__}")
        return False

# 从文件加载配置
def load_config(file_path='config.json'):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"加载配置异常: {type(e).__name__}")
        return {}
