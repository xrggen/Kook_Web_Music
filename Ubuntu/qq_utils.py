import requests
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import QQ_MUSIC_API_BASE, QQ_COOKIE_TXT_PATH

logger = logging.getLogger(__name__)


def load_qq_cookie():
    """读取QQ音乐Cookie"""
    try:
        if os.path.exists(QQ_COOKIE_TXT_PATH):
            with open(QQ_COOKIE_TXT_PATH, "r", encoding="utf-8") as f:
                return f.read().strip()
    except Exception:
        pass
    return ""


def build_qq_params(extra=None):
    """构建QQ音乐API请求参数，含cookie（通过?cookie=传参）"""
    params = {}
    cookie_str = load_qq_cookie()
    if cookie_str:
        params["cookie"] = cookie_str
    if extra:
        params.update(extra)
    return params


_verify_cache = {"ts": 0, "result": None}
_VERIFY_CACHE_TTL = 120  # 缓存 2 分钟，避免频繁用歌曲测活


def verify_qq_cookie(force=False):
    """验证QQ音乐Cookie是否有效，返回 {valid, uin, message, need_relogin, expires_in}

    expires_in: 距离最早过期的秒数（-1 表示无法确定）"""
    import re, time

    # 短期缓存避免频繁请求
    if not force and _verify_cache["result"] is not None:
        if time.time() - _verify_cache["ts"] < _VERIFY_CACHE_TTL:
            return _verify_cache["result"]

    cookie = load_qq_cookie()
    if not cookie:
        result = {"valid": False, "uin": "", "message": "未设置Cookie", "need_relogin": True, "expires_in": 0}
        _verify_cache["ts"] = time.time()
        _verify_cache["result"] = result
        return result

    uin_match = re.search(r'uin=o?(\d+)', cookie)
    uin = uin_match.group(1) if uin_match else ""

    # 检查多个可能的过期字段，取最早到期的
    exp_fields = [
        r'psrf_access_token_expiresAt=(\d+)',
        r'qqmusic_key_expiresAt=(\d+)',
        r'musickey_expiresAt=(\d+)',
    ]
    earliest_exp = None
    now = time.time()
    for pattern in exp_fields:
        m = re.search(pattern, cookie)
        if m:
            ts = int(m.group(1))
            if earliest_exp is None or ts < earliest_exp:
                earliest_exp = ts

    expires_in = int(earliest_exp - now) if earliest_exp else -1

    # 已经过期
    if earliest_exp and now > earliest_exp:
        result = {
            "valid": False, "uin": uin,
            "message": "Cookie已过期，请重新登录", "need_relogin": True,
            "expires_in": expires_in,
        }
        _verify_cache["ts"] = time.time()
        _verify_cache["result"] = result
        return result

    # 轻量验证：cookie 中有 uin 且未过期，先信任
    if uin and earliest_exp and now < earliest_exp:
        result = {
            "valid": True, "uin": uin,
            "message": f"Cookie有效（{_format_expiry(expires_in)}后过期）",
            "need_relogin": False, "expires_in": expires_in,
        }
        _verify_cache["ts"] = time.time()
        _verify_cache["result"] = result
        return result

    # 无明确过期字段时，用歌曲测活
    test_songmid = "0039MnYb0qxYhV"
    try:
        test_url = get_qq_music_url(test_songmid, "128")
        if test_url:
            result = {"valid": True, "uin": uin, "message": "Cookie有效", "need_relogin": False, "expires_in": -1}
            _verify_cache["ts"] = time.time()
            _verify_cache["result"] = result
            return result
    except Exception:
        pass

    result = {"valid": False, "uin": uin, "message": "Cookie无效，请重新登录", "need_relogin": True, "expires_in": 0}
    _verify_cache["ts"] = time.time()
    _verify_cache["result"] = result
    return result


def _format_expiry(seconds):
    if seconds <= 0:
        return "已过期"
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    if days > 0:
        return f"{days}天{hours}小时"
    return f"{hours}小时"


def _normalize_song(item):
    """QQ音乐歌曲对象 → 内部统一格式 {id, name, ar, al}
    id 字段填入 songmid（QQ音乐播放URL用的主键）"""
    singers = item.get("singer", [])
    return {
        "id": item.get("songmid", ""),
        "name": item.get("songname", ""),
        "ar": [{"name": s.get("name", "")} for s in singers],
        "al": {"name": item.get("albumname", "")},
    }


def search_qq_music(keyword, limit=10, page=1):
    """搜索QQ音乐"""
    import urllib.parse
    encoded_key = urllib.parse.quote(keyword, safe='')
    url = f"{QQ_MUSIC_API_BASE}/getSearchByKey/{encoded_key}?limit={limit}&page={page}"
    logger.info(f"[QQ搜索] 请求: GET {url}")
    try:
        res = requests.get(url, params=build_qq_params(), timeout=15)
        data = res.json()
        response = data.get("response", data)
        song_list = response.get("data", {}).get("song", {}).get("list", [])
        songs = [_normalize_song(item) for item in song_list]
        logger.info(f"[QQ搜索] 状态={res.status_code} 结果数={len(songs)}")
        if songs:
            top = songs[0]
            logger.info(f"[QQ搜索] 首条: {top.get('name','?')} - {top.get('ar',[{}])[0].get('name','?')} (id={top.get('id')})")
        return songs
    except Exception as e:
        logger.error(f"[QQ搜索] 异常: {e}")
        return []


def get_qq_music_url(songmid, quality="128"):
    """获取QQ音乐歌曲播放URL"""
    params = build_qq_params({"quality": quality})
    url = f"{QQ_MUSIC_API_BASE}/getMusicPlay/{songmid}"
    logger.info(f"[QQ取链] 请求: GET {url} quality={quality}")
    try:
        res = requests.get(url, params=params, timeout=15)
        data = res.json()
        response = data.get("response", data)
        play_urls = response.get("data", {}).get("playUrl", {})
        entry = play_urls.get(songmid, {})
        music_url = entry.get("url", "")
        error_msg = entry.get("error", "")
        logger.info(f"[QQ取链] 状态={res.status_code} {'成功' if music_url else '失败(无链接)'}"
                    f"{' error=' + error_msg if error_msg else ''}")
        if music_url:
            logger.info(f"[QQ取链] URL: {music_url[:80]}...")
        elif error_msg:
            logger.warning(f"[QQ取链] 服务端错误: {error_msg}")
        return music_url
    except Exception as e:
        logger.error(f"[QQ取链] 异常: {e}")
        return ""


def _parse_qq_playlist_detail(data):
    """从 qq-music-api getSongListDetail 响应中提取歌单信息
    返回 (name, songlist) 或 ({}, [])"""
    response = data.get("response", data)
    cdlist = response.get("cdlist", [])
    if cdlist and isinstance(cdlist, list):
        detail = cdlist[0]
        return detail, detail.get("songlist", [])
    return {}, []


def get_qq_playlist(disstid):
    """获取QQ音乐歌单信息，返回 {name, trackCount}"""
    url = f"{QQ_MUSIC_API_BASE}/getSongListDetail?disstid={disstid}"
    logger.info(f"[QQ歌单] 请求: GET {url}")
    try:
        res = requests.get(url, params=build_qq_params(), timeout=30)
        data = res.json()
        detail, songlist = _parse_qq_playlist_detail(data)
        name = detail.get("dissname", "未知歌单")
        track_count = len(songlist)
        logger.info(f"[QQ歌单] 状态={res.status_code} 名称={name} 歌曲数={track_count}")
        return {"name": name, "trackCount": track_count}
    except Exception as e:
        logger.error(f"[QQ歌单] 异常: {e}")
        return {}


def get_qq_playlist_all_tracks(disstid):
    """获取QQ音乐歌单中所有歌曲（单次请求，无分页）"""
    url = f"{QQ_MUSIC_API_BASE}/getSongListDetail?disstid={disstid}"
    logger.info(f"[QQ歌单分页] 请求: GET {url}")
    try:
        res = requests.get(url, params=build_qq_params(), timeout=30)
        data = res.json()
        detail, songlist = _parse_qq_playlist_detail(data)
        name = detail.get("dissname", "?")
        logger.info(f"[QQ歌单分页] 歌单={name} 共 {len(songlist)} 首")
        return songlist
    except Exception as e:
        logger.error(f"[QQ歌单分页] 异常: {e}")
        return []


def get_qq_playlist_urls(disstid):
    """获取QQ音乐歌单中所有歌曲信息，生成 QQ_PLAYLIST_SONG: 标记"""
    tracks = get_qq_playlist_all_tracks(disstid)
    result = []
    logger.info(f"[QQ歌单处理] 处理 {len(tracks)} 首歌曲...")
    for track in tracks:
        songmid = track.get("mid", "") or track.get("songmid", "")
        song_name = track.get("name", "") or track.get("songname", "")
        singers = track.get("singer", [])
        artist_name = singers[0].get("name", "") if singers else ""
        song_marker = f"QQ_PLAYLIST_SONG:{songmid}:{song_name}:{artist_name}"
        result.append({
            "id": songmid,
            "name": song_name,
            "artist": artist_name,
            "marker": song_marker
        })
    logger.info(f"[QQ歌单处理] 完成 {len(result)} 首")
    return result


def resolve_qq_marker_batch(markers, count=5):
    """批量解析 QQ_PLAYLIST_SONG: 标记为实际播放URL（并发请求）
    返回 {marker: url} dict"""
    resolved = {}
    to_resolve = []
    for m in markers:
        if m.startswith("QQ_PLAYLIST_SONG:") and m not in resolved:
            to_resolve.append(m)
            if len(to_resolve) >= count:
                break
    if not to_resolve:
        return resolved

    logger.info(f"[QQ批量取链] 解析 {len(to_resolve)} 个标记")

    def fetch_one(marker):
        parts = marker.split(":")
        if len(parts) >= 2:
            songmid = parts[1]
            url = get_qq_music_url(songmid)
            return marker, url
        return marker, ""

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(fetch_one, m): m for m in to_resolve}
        for future in as_completed(futures):
            try:
                marker, url = future.result()
                if url:
                    resolved[marker] = url
            except Exception as e:
                logger.error(f"[QQ批量取链] 并发异常: {e}")

    logger.info(f"[QQ批量取链] 成功 {len(resolved)}/{len(to_resolve)}")
    return resolved


def refill_qq_playlist_queue(channel_id, play_list_dict, count=5):
    """检查播放队列并将前 count 个 QQ_PLAYLIST_SONG 标记替换为真实URL"""
    if channel_id not in play_list_dict:
        return 0
    queue = play_list_dict[channel_id].get("play_list", [])
    markers = [item["file"] for item in queue if item.get("file", "").startswith("QQ_PLAYLIST_SONG:")]
    if not markers:
        return 0

    resolved = resolve_qq_marker_batch(markers, count)
    replaced = 0
    for item in queue:
        marker = item.get("file", "")
        if marker in resolved:
            item["file"] = resolved[marker]
            replaced += 1
            if replaced >= count:
                break
    if replaced:
        logger.info(f"[QQ批量取链] 已替换 {replaced} 个标记为真实URL")
    return replaced


def get_qq_user_avatar(uin):
    """获取QQ用户头像URL"""
    url = f"{QQ_MUSIC_API_BASE}/user/getUserAvatar?uin={uin}&size=140"
    logger.info(f"[QQ头像] 请求: GET {url}")
    try:
        res = requests.get(url, params=build_qq_params(), timeout=10)
        data = res.json()
        response = data.get("response", data)
        inner = response.get("data", response)
        avatar = inner.get("avatarUrl", "")
        logger.info(f"[QQ头像] {'成功' if avatar else '失败'}")
        return avatar
    except Exception as e:
        logger.error(f"[QQ头像] 异常: {e}")
        return ""


def _parse_subtitle(subtitle):
    """从 '100首    8次播放' 中解析出 (trackCount, playCount)"""
    import re
    tc, pc = 0, 0
    m = re.search(r'(\d+)\s*首', subtitle or '')
    if m:
        tc = int(m.group(1))
    m = re.search(r'(\d+)\s*次播放', subtitle or '')
    if m:
        pc = int(m.group(1))
    return tc, pc


def get_qq_user_playlists(uin, offset=0, limit=30):
    """获取QQ用户歌单列表，返回 [{id, name, cover, trackCount, playCount}]"""
    url = f"{QQ_MUSIC_API_BASE}/user/getUserPlaylists"
    params = build_qq_params({"uin": uin, "offset": offset, "limit": limit})
    logger.info(f"[QQ歌单列表] 请求: GET {url} uin={uin}")
    try:
        res = requests.get(url, params=params, timeout=15)
        data = res.json()
        response = data.get("response", data)
        inner = response.get("data", response)
        playlist_list = inner.get("playlists", [])
        result = []
        for pl in playlist_list:
            tc, pc = _parse_subtitle(pl.get("subtitle", ""))
            result.append({
                "id": str(pl.get("dissid", pl.get("dirid", ""))),
                "name": pl.get("title", pl.get("dissname", "未知歌单")),
                "cover": pl.get("picurl", pl.get("diss_cover", pl.get("imgurl", ""))),
                "trackCount": tc,
                "playCount": pc,
            })
        logger.info(f"[QQ歌单列表] 共 {len(result)} 个歌单")
        return result
    except Exception as e:
        logger.error(f"[QQ歌单列表] 异常: {e}")
        return []
