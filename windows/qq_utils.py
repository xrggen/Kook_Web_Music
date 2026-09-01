import requests
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
try:
    from .config import QQ_MUSIC_API_BASE, MAX_PLAYLIST_IMPORT_TRACKS
    from .qq_credential import load_qq_cookie as _load_managed_qq_cookie
except ImportError:
    from config import QQ_MUSIC_API_BASE, MAX_PLAYLIST_IMPORT_TRACKS
    from qq_credential import load_qq_cookie as _load_managed_qq_cookie

logger = logging.getLogger(__name__)

MAX_SEARCH_KEYWORD_LENGTH = 256
MAX_SEARCH_LIMIT = 30
MAX_SEARCH_PAGE = 10_000
MAX_ACCOUNT_PLAYLIST_LIMIT = 100
MAX_ACCOUNT_PLAYLIST_OFFSET = 1_000_000
MAX_NUMERIC_ID_LENGTH = 20
MAX_SONGMID_LENGTH = 64
MAX_METADATA_TEXT_LENGTH = 512
_NUMERIC_ID_RE = re.compile(r"[0-9]+")
_SONGMID_RE = re.compile(r"[A-Za-z0-9]{1,64}")


def _safe_text(value, limit=MAX_METADATA_TEXT_LENGTH):
    text = str(value or "")
    text = "".join(
        " " if ord(char) < 32 or ord(char) == 127 else char
        for char in text
    )
    return text.strip()[:limit]


def _bounded_int(value, minimum, maximum):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str):
        if value != value.strip() or not value.isascii() or not value.isdigit():
            return None
        if len(value) > 12:
            return None
        parsed = int(value)
    else:
        return None
    return parsed if minimum <= parsed <= maximum else None


def _normalize_numeric_id(value, label="ID"):
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
        logger.warning("[QQ] 非法%s", label)
        return ""
    return text


def _normalize_songmid(value):
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if len(value) > MAX_SONGMID_LENGTH or _SONGMID_RE.fullmatch(value) is None:
        return ""
    return value


def load_qq_cookie():
    """通过统一凭证存储读取已经校验的QQ音乐Cookie。"""
    return _load_managed_qq_cookie()


def build_qq_params(extra=None):
    """构建不含凭据的QQ音乐API查询参数。"""
    return dict(extra or {})


def build_qq_headers(extra=None):
    """通过请求头向本机QQ API传递Cookie，避免凭据进入URL和访问日志。"""
    headers = {}
    cookie_str = load_qq_cookie()
    if cookie_str:
        headers["Cookie"] = cookie_str
    if extra:
        headers.update(extra)
    return headers


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
    if not isinstance(item, dict):
        return {"id": "", "name": "", "ar": [], "al": {"name": ""}}
    singers = item.get("singer", [])
    if not isinstance(singers, list):
        singers = []
    return {
        "id": _normalize_songmid(item.get("songmid", "")),
        "name": _safe_text(item.get("songname", "")),
        "ar": [
            {"name": _safe_text(s.get("name", ""))}
            for s in singers if isinstance(s, dict)
        ],
        "al": {"name": _safe_text(item.get("albumname", ""))},
    }


def search_qq_music(keyword, limit=10, page=1):
    """搜索QQ音乐"""
    import urllib.parse
    if not isinstance(keyword, str):
        return []
    keyword = keyword.strip()
    if (
        not keyword
        or len(keyword) > MAX_SEARCH_KEYWORD_LENGTH
        or any(ord(char) < 32 or ord(char) == 127 for char in keyword)
    ):
        return []
    safe_limit = _bounded_int(limit, 1, MAX_SEARCH_LIMIT)
    safe_page = _bounded_int(page, 1, MAX_SEARCH_PAGE)
    if safe_limit is None or safe_page is None:
        return []
    encoded_key = urllib.parse.quote(keyword, safe='')
    url = f"{QQ_MUSIC_API_BASE}/getSearchByKey/{encoded_key}"
    logger.info(f"[QQ搜索] 请求: GET {url}")
    try:
        res = requests.get(
            url,
            params=build_qq_params({"limit": safe_limit, "page": safe_page}),
            headers=build_qq_headers(),
            timeout=15,
            allow_redirects=False,
        )
        data = res.json()
        response = data.get("response", data)
        song_list = response.get("data", {}).get("song", {}).get("list", [])
        if not isinstance(song_list, list):
            return []
        songs = [
            song for song in (_normalize_song(item) for item in song_list[:safe_limit])
            if song["id"]
        ]
        logger.info(f"[QQ搜索] 状态={res.status_code} 结果数={len(songs)}")
        if songs:
            top = songs[0]
            logger.info(
                "[QQ搜索] 首条 name=%r artist=%r id=%r",
                str(top.get('name', '?'))[:120],
                str(top.get('ar', [{}])[0].get('name', '?'))[:120],
                str(top.get('id', ''))[:64],
            )
        return songs
    except Exception as e:
        logger.error(f"[QQ搜索] 异常: {type(e).__name__}")
        return []


def get_qq_music_url(songmid, quality="128"):
    """获取QQ音乐歌曲播放URL"""
    songmid = _normalize_songmid(songmid)
    if not songmid:
        return ""
    if not isinstance(quality, str) or not quality or len(quality) > 16:
        return ""
    if re.fullmatch(r"[A-Za-z0-9_-]+", quality) is None:
        return ""
    params = build_qq_params({"quality": quality})
    url = f"{QQ_MUSIC_API_BASE}/getMusicPlay/{songmid}"
    logger.info(f"[QQ取链] 请求: GET {url} quality={quality}")
    try:
        res = requests.get(url, params=params, headers=build_qq_headers(), timeout=15, allow_redirects=False)
        data = res.json()
        response = data.get("response", data)
        play_urls = response.get("data", {}).get("playUrl", {})
        if not isinstance(play_urls, dict):
            return ""
        entry = play_urls.get(songmid, {})
        if not isinstance(entry, dict):
            return ""
        music_url = entry.get("url", "")
        error_msg = _safe_text(entry.get("error", ""), 160)
        logger.info(f"[QQ取链] 状态={res.status_code} {'成功' if music_url else '失败(无链接)'}"
                    f"{' error=' + error_msg if error_msg else ''}")
        if not music_url and error_msg:
            logger.warning(f"[QQ取链] 服务端错误: {error_msg}")
        return music_url
    except Exception as e:
        logger.error(f"[QQ取链] 异常: {type(e).__name__}")
        return ""


def _parse_qq_playlist_detail(data):
    """从 qq-music-api getSongListDetail 响应中提取歌单信息
    返回 (name, songlist) 或 ({}, [])"""
    if not isinstance(data, dict):
        return {}, []
    response = data.get("response", data)
    if not isinstance(response, dict):
        return {}, []
    cdlist = response.get("cdlist", [])
    if cdlist and isinstance(cdlist, list):
        detail = cdlist[0]
        if not isinstance(detail, dict):
            return {}, []
        songlist = detail.get("songlist", [])
        if not isinstance(songlist, list):
            return detail, []
        return detail, [
            item for item in songlist[:MAX_PLAYLIST_IMPORT_TRACKS]
            if isinstance(item, dict)
        ]
    return {}, []


def _qqmusic_sign(param_str: str) -> str:
    """QQ Music API 签名算法 — 移植自 GoMusic 项目 (Bistutu/GoMusic)"""
    import hashlib
    k1 = {str(i): i for i in range(10)}
    k1.update({'A': 10, 'B': 11, 'C': 12, 'D': 13, 'E': 14, 'F': 15})
    l1 = [212, 45, 80, 68, 195, 163, 163, 203, 157, 220, 254, 91, 204, 79, 104, 6]
    t = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/='

    md5_str = hashlib.md5(param_str.encode()).hexdigest().upper()
    t1 = ''.join(md5_str[i] for i in [21, 4, 9, 26, 16, 20, 27, 30])
    t3 = ''.join(md5_str[i] for i in [18, 11, 3, 2, 1, 7, 6, 25])

    ls2 = []
    for i in range(16):
        x1 = k1[md5_str[i * 2]]
        x2 = k1[md5_str[i * 2 + 1]]
        ls2.append((x1 * 16 ^ x2) ^ l1[i])

    ls3 = []
    for i in range(6):
        if i == 5:
            ls3.append(t[ls2[-1] >> 2])
            ls3.append(t[(ls2[-1] & 3) << 4])
        else:
            ls3.append(t[ls2[i * 3] >> 2])
            ls3.append(t[(ls2[i * 3 + 1] >> 4) ^ ((ls2[i * 3] & 3) << 4)])
            ls3.append(t[(ls2[i * 3 + 2] >> 6) ^ ((ls2[i * 3 + 1] & 15) << 2)])
            ls3.append(t[63 & ls2[i * 3 + 2]])

    import re as _re
    t2 = _re.sub(r'[\\\\/+]', '', ''.join(ls3))
    return 'zzb' + (t1 + t2 + t3).lower()


def _qq_api_direct(disstid):
    """通过 u6.y.qq.com 签名 API 获取歌单（GoMusic 方案）。
    无需 cookie，支持任意公开歌单，支持分页（>30首）。"""
    import json as _json, time as _time

    playlist_id_text = _normalize_numeric_id(disstid, "歌单ID")
    if not playlist_id_text:
        return {}, []
    playlist_id = int(playlist_id_text)

    def _fetch_page(song_begin, song_num, preferred_platform=None):
        """获取单页歌单数据，尝试多个 platform"""
        platforms = ['-1', 'android', 'iphone', 'h5', 'wxfshare', 'iphone_wx']
        if preferred_platform in platforms:
            platforms = [preferred_platform]
        deadline = _time.monotonic() + 30
        for platform in platforms:
            remaining = deadline - _time.monotonic()
            if remaining <= 0:
                break
            body = _json.dumps({
                'req_0': {
                    'module': 'music.srfDissInfo.aiDissInfo',
                    'method': 'uniform_get_Dissinfo',
                    'param': {
                        'disstid': playlist_id, 'enc_host_uin': '',
                        'tag': 1, 'userinfo': 1,
                        'song_begin': song_begin, 'song_num': song_num,
                    }
                },
                'comm': {'g_tk': 5381, 'uin': 0, 'format': 'json', 'platform': platform}
            }, separators=(',', ':'))
            sign = _qqmusic_sign(body)
            url = f'https://u6.y.qq.com/cgi-bin/musics.fcg?sign={sign}&_={int(_time.time() * 1000)}'
            try:
                res = requests.post(url, data=body, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Content-Type': 'application/json',
                }, timeout=(min(3, remaining), min(8, remaining)), allow_redirects=False)
                # 108 字节 = 错误响应（GoMusic 经验值）
                if len(res.content) == 108:
                    continue
                data = res.json()
                req0 = data.get('req_0', {})
                if req0.get('code') == 0:
                    return req0.get('data', {}), platform
            except (requests.RequestException, ValueError):
                continue
        return None, preferred_platform

    # 先拉第一页
    data, preferred_platform = _fetch_page(0, 30)
    if not isinstance(data, dict) or not data:
        return {}, []

    dirinfo = data.get('dirinfo', {})
    if not isinstance(dirinfo, dict):
        dirinfo = {}
    raw_first_page = data.get('songlist', [])
    if not isinstance(raw_first_page, list):
        return {}, []
    all_songs = [
        item for item in raw_first_page[:30]
        if isinstance(item, dict)
    ]
    try:
        reported_total = max(
            int(dirinfo.get('songnum', len(raw_first_page))),
            len(raw_first_page),
        )
    except (TypeError, ValueError):
        reported_total = len(all_songs)
    total = min(reported_total, MAX_PLAYLIST_IMPORT_TRACKS)
    if total < reported_total:
        logger.warning("[QQ歌单直连] 歌曲数 %d 超过安全上限，截断为 %d", reported_total, total)

    # 分页拉取剩余歌曲
    seen_pages = set()
    first_fingerprint = _json.dumps(
        all_songs,
        sort_keys=True,
        ensure_ascii=False,
        separators=(',', ':'),
    )
    seen_pages.add(first_fingerprint)
    max_pages = max(1, (total + 29) // 30)
    for _ in range(1, max_pages):
        if len(all_songs) >= total:
            break
        page, preferred_platform = _fetch_page(
            len(all_songs),
            min(30, total - len(all_songs)),
            preferred_platform,
        )
        if not isinstance(page, dict) or not page:
            break
        raw_page_songs = page.get('songlist', [])
        if not isinstance(raw_page_songs, list) or not raw_page_songs:
            logger.warning("[QQ歌单直连] 分页提前返回空列表，停止继续拉取")
            break
        requested = min(30, total - len(all_songs))
        page_songs = [
            item for item in raw_page_songs[:requested]
            if isinstance(item, dict)
        ]
        if not page_songs:
            logger.warning("[QQ歌单直连] 分页没有有效歌曲，停止继续拉取")
            break
        fingerprint = _json.dumps(
            page_songs,
            sort_keys=True,
            ensure_ascii=False,
            separators=(',', ':'),
        )
        if fingerprint in seen_pages:
            logger.warning("[QQ歌单直连] 检测到重复分页，停止继续拉取")
            break
        seen_pages.add(fingerprint)
        all_songs.extend(page_songs)

    all_songs = all_songs[:total]
    logger.info(
        "[QQ歌单直连] 名称=%s 歌曲数=%d total=%d",
        dirinfo.get('title', '?'),
        len(all_songs),
        reported_total,
    )
    return dirinfo, all_songs


def get_qq_playlist(disstid):
    """获取QQ音乐歌单信息，返回 {name, trackCount}"""
    playlist_id = _normalize_numeric_id(disstid, "歌单ID")
    if not playlist_id:
        return {}
    # 优先直连 u6.y.qq.com 签名 API（无需 cookie，支持任何公开歌单）
    dirinfo, songlist = _qq_api_direct(playlist_id)
    if songlist:
        return {"name": dirinfo.get('title', '未知歌单'), "trackCount": len(songlist)}

    # 回退 qq-music-api
    url = f"{QQ_MUSIC_API_BASE}/getSongListDetail"
    params = build_qq_params({"disstid": playlist_id})
    logger.info(f"[QQ歌单] 直连失败，回退本地API: GET {url}")
    try:
        res = requests.get(url, params=params, headers=build_qq_headers(), timeout=30, allow_redirects=False)
        data = res.json()
        detail, songlist = _parse_qq_playlist_detail(data)
        name = detail.get("dissname", "未知歌单")
        logger.info("[QQ歌单] 状态=%s 名称=%r 歌曲数=%d", res.status_code, str(name)[:120], len(songlist))
        return {"name": name, "trackCount": len(songlist)}
    except Exception as e:
        logger.error(f"[QQ歌单] 异常: {type(e).__name__}")
        return {}


def get_qq_playlist_all_tracks(disstid):
    """获取QQ音乐歌单中所有歌曲（支持分页，无上限）"""
    playlist_id = _normalize_numeric_id(disstid, "歌单ID")
    if not playlist_id:
        return []
    dirinfo, songlist = _qq_api_direct(playlist_id)
    if songlist:
        return songlist[:MAX_PLAYLIST_IMPORT_TRACKS]

    url = f"{QQ_MUSIC_API_BASE}/getSongListDetail"
    params = build_qq_params({"disstid": playlist_id})
    logger.info(f"[QQ歌单分页] 直连失败，回退本地API: GET {url}")
    try:
        res = requests.get(url, params=params, headers=build_qq_headers(), timeout=30, allow_redirects=False)
        data = res.json()
        detail, songlist = _parse_qq_playlist_detail(data)
        logger.info("[QQ歌单分页] 歌单=%r 共 %d 首", str(detail.get('dissname', '?'))[:120], len(songlist))
        return songlist[:MAX_PLAYLIST_IMPORT_TRACKS]
    except Exception as e:
        logger.error(f"[QQ歌单分页] 异常: {type(e).__name__}")
        return []


def get_qq_playlist_urls(disstid):
    """获取QQ音乐歌单中所有歌曲信息，生成 QQ_PLAYLIST_SONG: 标记"""
    tracks = get_qq_playlist_all_tracks(disstid)
    result = []
    logger.info(f"[QQ歌单处理] 处理 {len(tracks)} 首歌曲...")
    for track in tracks:
        if not isinstance(track, dict):
            continue
        songmid = _normalize_songmid(track.get("mid", "") or track.get("songmid", ""))
        if not songmid:
            continue
        song_name = _safe_text(track.get("name", "") or track.get("songname", ""))
        singers = track.get("singer", [])
        artist_name = (
            _safe_text(singers[0].get("name", ""))
            if isinstance(singers, list) and singers and isinstance(singers[0], dict)
            else ""
        )
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
    safe_count = _bounded_int(count, 1, 20)
    if safe_count is None or not isinstance(markers, (list, tuple)):
        return {}
    resolved = {}
    to_resolve = []
    for m in markers:
        if not isinstance(m, str):
            continue
        parts = m.split(":", 2)
        if (
            len(parts) >= 2
            and parts[0] == "QQ_PLAYLIST_SONG"
            and _normalize_songmid(parts[1])
            and m not in resolved
        ):
            to_resolve.append(m)
            if len(to_resolve) >= safe_count:
                break
    if not to_resolve:
        return resolved

    logger.info(f"[QQ批量取链] 解析 {len(to_resolve)} 个标记")

    def fetch_one(marker):
        parts = marker.split(":", 2)
        if len(parts) >= 2:
            songmid = _normalize_songmid(parts[1])
            if not songmid:
                return marker, ""
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
                logger.error(f"[QQ批量取链] 并发异常: {type(e).__name__}")

    logger.info(f"[QQ批量取链] 成功 {len(resolved)}/{len(to_resolve)}")
    return resolved


def refill_qq_playlist_queue(channel_id, play_list_dict, count=5, lock=None):
    """检查播放队列并将前 count 个 QQ_PLAYLIST_SONG 标记替换为真实URL"""
    safe_count = _bounded_int(count, 1, 20)
    if safe_count is None or not isinstance(play_list_dict, dict):
        return 0

    def collect_markers():
        state = play_list_dict.get(channel_id)
        queue = state.get("play_list", []) if state else []
        return [
            item["file"]
            for item in queue
            if isinstance(item, dict)
            and isinstance(item.get("file", ""), str)
            and item.get("file", "").startswith("QQ_PLAYLIST_SONG:")
        ]

    if lock is not None:
        with lock:
            markers = collect_markers()
    else:
        markers = collect_markers()
    if not markers:
        return 0

    resolved = resolve_qq_marker_batch(markers, safe_count)
    def apply_resolved():
        state = play_list_dict.get(channel_id)
        queue = state.get("play_list", []) if state else []
        replaced = 0
        for item in queue:
            if not isinstance(item, dict):
                continue
            marker = item.get("file", "")
            if marker in resolved:
                item["file"] = resolved[marker]
                replaced += 1
                if replaced >= safe_count:
                    break
        return replaced

    if lock is not None:
        with lock:
            replaced = apply_resolved()
    else:
        replaced = apply_resolved()
    if replaced:
        logger.info(f"[QQ批量取链] 已替换 {replaced} 个标记为真实URL")
    return replaced


def get_qq_user_avatar(uin):
    """获取QQ用户头像URL"""
    uin = _normalize_numeric_id(uin, "用户ID")
    if not uin:
        return ""
    url = f"{QQ_MUSIC_API_BASE}/user/getUserAvatar"
    logger.info(f"[QQ头像] 请求: GET {url}")
    try:
        res = requests.get(
            url,
            params=build_qq_params({"uin": uin, "size": 140}),
            headers=build_qq_headers(),
            timeout=10,
            allow_redirects=False,
        )
        data = res.json()
        response = data.get("response", data)
        inner = response.get("data", response)
        avatar = inner.get("avatarUrl", "")
        logger.info(f"[QQ头像] {'成功' if avatar else '失败'}")
        return avatar
    except Exception as e:
        logger.error(f"[QQ头像] 异常: {type(e).__name__}")
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
    uin = _normalize_numeric_id(uin, "用户ID")
    safe_offset = _bounded_int(offset, 0, MAX_ACCOUNT_PLAYLIST_OFFSET)
    safe_limit = _bounded_int(limit, 1, MAX_ACCOUNT_PLAYLIST_LIMIT)
    if not uin or safe_offset is None or safe_limit is None:
        return []
    url = f"{QQ_MUSIC_API_BASE}/user/getUserPlaylists"
    params = build_qq_params({"uin": uin, "offset": safe_offset, "limit": safe_limit})
    logger.info(f"[QQ歌单列表] 请求: GET {url} uin={uin}")
    try:
        res = requests.get(url, params=params, headers=build_qq_headers(), timeout=15, allow_redirects=False)
        data = res.json()
        response = data.get("response", data)
        inner = response.get("data", response)
        playlist_list = inner.get("playlists", [])
        if not isinstance(playlist_list, list):
            return []
        result = []
        for pl in playlist_list[:safe_limit]:
            if not isinstance(pl, dict):
                continue
            tc, pc = _parse_subtitle(pl.get("subtitle", ""))
            cover = next(
                (
                    pl.get(key)
                    for key in ("logo", "picurl", "diss_cover", "imgurl", "cover", "pic", "picUrl")
                    if isinstance(pl.get(key), str) and pl.get(key).strip()
                ),
                "",
            )
            result.append({
                "id": _safe_text(pl.get("dissid", pl.get("dirid", "")), 64),
                "name": _safe_text(pl.get("title", pl.get("dissname", "未知歌单"))),
                "cover": _safe_text(cover, 2048),
                "trackCount": tc,
                "playCount": pc,
            })
        logger.info(f"[QQ歌单列表] 共 {len(result)} 个歌单")
        return result
    except Exception as e:
        logger.error(f"[QQ歌单列表] 异常: {type(e).__name__}")
        return []
