import requests
import logging
import json
import os
from config import MUSIC_API_BASE, BACKUP_MUSIC_API

logger = logging.getLogger(__name__)

COOKIE_TXT_PATH = os.path.join(os.path.dirname(__file__), "Cookie", "cookie.txt")


def load_cookie_header():
    try:
        if os.path.exists(COOKIE_TXT_PATH):
            with open(COOKIE_TXT_PATH, "r", encoding="utf-8") as f:
                return f.read().strip()
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
    url = f"{MUSIC_API_BASE}/cloudsearch?keywords={keyword}"
    logger.info(f"[搜索] 请求: GET {url}")
    try:
        res = requests.get(url, headers=build_headers(), timeout=15)
        data = res.json()
        songs = data.get('result', {}).get('songs', [])
        song_count = data.get('result', {}).get('songCount', len(songs))
        logger.info(f"[搜索] 状态={res.status_code} 结果数={len(songs)} 总数={song_count}")
        if songs:
            top = songs[0]
            logger.info(f"[搜索] 首条: {top.get('name','?')} - {top.get('ar',[{}])[0].get('name','?')} (id={top.get('id')})")
        return songs
    except Exception as e:
        logger.error(f"[搜索] 主API异常: {e}")
        fallback_url = f"{BACKUP_MUSIC_API}/search?keywords={keyword}"
        logger.info(f"[搜索] 备用: GET {fallback_url}")
        try:
            res = requests.get(fallback_url, headers=build_headers(), timeout=15)
            data = res.json()
            songs = data.get('result', {}).get('songs', [])
            logger.info(f"[搜索] 备用: 状态={res.status_code} 结果数={len(songs)}")
            return songs
        except Exception as e2:
            logger.error(f"[搜索] 备用API异常: {e2}")
            return []

# 获取音乐URL
def get_music_url(song_id):
    url = f"{MUSIC_API_BASE}/song/url?id={song_id}"
    logger.info(f"[取链] 请求: GET {url}")
    try:
        res = requests.get(url, headers=build_headers(), timeout=15)
        data = res.json()
        music_url = data.get('data', [{}])[0].get('url', '')
        br = data.get('data', [{}])[0].get('br', 0) if data.get('data') else 0
        logger.info(f"[取链] 状态={res.status_code} 码率={br}  {'成功' if music_url else '失败(无链接)'}")
        if music_url:
            logger.info(f"[取链] URL: {music_url[:80]}...")
        return music_url
    except Exception as e:
        logger.error(f"[取链] 主API异常: {e}")
        fallback_url = f"{BACKUP_MUSIC_API}/song/url?id={song_id}"
        logger.info(f"[取链] 备用: GET {fallback_url}")
        try:
            res = requests.get(fallback_url, headers=build_headers(), timeout=15)
            data = res.json()
            music_url = data.get('data', [{}])[0].get('url', '')
            logger.info(f"[取链] 备用: 状态={res.status_code} {'成功' if music_url else '失败'}")
            return music_url
        except Exception as e2:
            logger.error(f"[取链] 备用API异常: {e2}")
            return ''

# 获取歌单
def get_playlist(playlist_id):
    url = f"{MUSIC_API_BASE}/playlist/detail?id={playlist_id}"
    logger.info(f"[歌单] 请求: GET {url}")
    try:
        res = requests.get(url, headers=build_headers(), timeout=20)
        data = res.json()
        playlist = data.get('playlist', {})
        name = playlist.get('name', '?')
        count = playlist.get('trackCount', 0)
        logger.info(f"[歌单] 状态={res.status_code} 名称={name} 歌曲数={count}")
        return playlist
    except Exception as e:
        logger.error(f"[歌单] 主API异常: {e}")
        fallback_url = f"{BACKUP_MUSIC_API}/playlist/detail?id={playlist_id}"
        logger.info(f"[歌单] 备用: GET {fallback_url}")
        try:
            res = requests.get(fallback_url, headers=build_headers(), timeout=20)
            data = res.json()
            playlist = data.get('playlist', {})
            logger.info(f"[歌单] 备用: 状态={res.status_code} 名称={playlist.get('name','?')}")
            return playlist
        except Exception as e2:
            logger.error(f"[歌单] 备用API异常: {e2}")
            return {}

# 获取歌单中所有歌曲（支持分页）
def get_playlist_all_tracks(playlist_id):
    """获取歌单中所有歌曲，支持分页"""
    try:
        playlist = get_playlist(playlist_id)
        if not playlist:
            return []

        track_count = playlist.get('trackCount', 0)
        logger.info(f"[歌单分页] 总数={track_count} 开始分页拉取...")

        all_tracks = []
        limit = 1000
        offset = 0

        while offset < track_count:
            try:
                url = f"{MUSIC_API_BASE}/playlist/track/all?id={playlist_id}&limit={limit}&offset={offset}"
                logger.info(f"[歌单分页] GET {url}")
                res = requests.get(url, timeout=10, headers=build_headers())
                if res.status_code == 200:
                    data = res.json()
                    tracks = data.get('songs', [])
                    if not tracks:
                        break
                    all_tracks.extend(tracks)
                    logger.info(f"[歌单分页] offset={offset} 本次={len(tracks)} 累计={len(all_tracks)}")
                    if len(tracks) < limit:
                        break
                    offset += limit
                else:
                    logger.error(f"[歌单分页] HTTP {res.status_code}")
                    break
            except Exception as e:
                logger.error(f"[歌单分页] 异常: {e}")
                break

        logger.info(f"[歌单分页] 完成 共获取 {len(all_tracks)} 首")
        return all_tracks

    except Exception as e:
        logger.error(f"[歌单分页] 获取异常: {e}")
        return []

# 获取歌单中所有歌曲信息（不获取URL）
def get_playlist_urls(playlist_id):
    """获取歌单中所有歌曲信息，使用.env中配置的API，不获取URL"""
    tracks = get_playlist_all_tracks(playlist_id)
    result = []
    logger.info(f"[歌单处理] 处理 {len(tracks)} 首歌曲...")
    for track in tracks:
        song_id = track.get('id')
        song_name = track.get('name', '')
        artists = track.get('ar', [])
        artist_name = artists[0].get('name', '') if artists else ''
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
    resolved = {}
    to_resolve = []
    for m in markers:
        if m.startswith("PLAYLIST_SONG:") and m not in resolved:
            to_resolve.append(m)
            if len(to_resolve) >= count:
                break
    if not to_resolve:
        return resolved

    ids = []
    for m in to_resolve:
        parts = m.split(":")
        if len(parts) >= 2:
            ids.append(parts[1])

    logger.info(f"[批量取链] 解析 {len(ids)} 个标记: {ids}")
    url = f"{MUSIC_API_BASE}/song/url?id={','.join(ids)}"
    try:
        res = requests.get(url, headers=build_headers(), timeout=15)
        if res.status_code == 200:
            data = res.json()
            for item in data.get('data', []):
                song_id = str(item.get('id', ''))
                song_url = item.get('url', '')
                if song_id and song_url:
                    for m in to_resolve:
                        parts = m.split(":")
                        if len(parts) >= 2 and parts[1] == song_id:
                            resolved[m] = song_url
                            break
        logger.info(f"[批量取链] 成功 {len(resolved)}/{len(ids)}")
    except Exception as e:
        logger.error(f"[批量取链] 异常: {e}")
    return resolved


def refill_playlist_queue(channel_id, play_list_dict, count=BATCH_SIZE):
    """检查播放队列并将前 count 个 PLAYLIST_SONG 标记替换为真实URL"""
    if channel_id not in play_list_dict:
        return 0
    queue = play_list_dict[channel_id].get('play_list', [])
    markers = [item['file'] for item in queue if item.get('file', '').startswith('PLAYLIST_SONG:')]
    if not markers:
        return 0

    resolved = resolve_marker_batch(markers, count)
    replaced = 0
    for item in queue:
        marker = item.get('file', '')
        if marker in resolved:
            item['file'] = resolved[marker]
            replaced += 1
            if replaced >= count:
                break
    if replaced:
        logger.info(f"[批量取链] 已替换 {replaced} 个标记为真实URL")
    return replaced


# 格式化播放列表数据
def format_playlist_data(play_list_data):
    result = []
    
    # 处理当前播放的歌曲
    now_playing = play_list_data.get('now_playing')
    if now_playing:
        file_path = now_playing.get('file', '')
        extra_data = now_playing.get('extra', {})
        
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
            # 普通文件
            file_name = file_path.split('/')[-1] if '/' in file_path else file_path
            result.append({
                'id': 'local',
                'name': extra_data.get('title', file_name),
                'artist': extra_data.get('artist', '本地文件'),
                'duration': now_playing.get('duration', 0),
                'playing': True,
                'position': now_playing.get('ss', 0),
                'start_time': now_playing.get('start', 0)
            })
    
    # 处理播放列表中的歌曲
    play_list = play_list_data.get('play_list', [])
    for queue_index, item in enumerate(play_list):
        file_path = item.get('file', '')
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
            # 普通文件
            file_name = file_path.split('/')[-1] if '/' in file_path else file_path
            result.append({
                'id': 'local',
                'name': extra_data.get('title', file_name),
                'artist': extra_data.get('artist', '本地文件'),
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
        logger.error(f"保存配置异常: {e}")
        return False

# 从文件加载配置
def load_config(file_path='config.json'):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"加载配置异常: {e}")
        return {}