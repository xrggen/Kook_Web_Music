import requests
import logging
import os
import re
import time
import io
import base64
import threading
import qrcode as _qrcode_mod
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

# B站 API 无需本地代理，直接调用公开 REST API
BILI_API = "https://api.bilibili.com"
BILI_PASSPORT = "https://passport.bilibili.com"
BILI_WWW = "https://www.bilibili.com"

# 共享 Session（保持设备Cookie如buvid3，避免风控-412）
_session = None
_session_lock = threading.Lock()
_verify_cache = {"ts": 0, "result": None}
_VERIFY_CACHE_TTL = 120
MAX_COOKIE_CHARS = 64 * 1024


def _get_session():
    """获取或创建带设备Cookie的共享Session"""
    global _session
    if _session is not None:
        return _session
    with _session_lock:
        if _session is None:
            session = requests.Session()
            session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept-Language": "zh-CN,zh;q=0.9",
            })
            # 预热：访问B站首页及API域名获取buvid3等设备标识Cookie
            for warm_url in (
                "https://www.bilibili.com/",
                "https://api.bilibili.com/x/web-interface/nav",
            ):
                try:
                    session.get(
                        warm_url,
                        headers={"Accept": "text/html,application/xhtml+xml,*/*"},
                        timeout=10,
                        allow_redirects=False,
                    )
                except Exception:
                    pass
            _session = session
            logger.info("[Bili] Session已预热（设备Cookie已获取）")
    return _session


_BV_PATTERN = re.compile(r'BV[0-9A-Za-z]{10}', re.IGNORECASE)
MAX_SEARCH_KEYWORD_LENGTH = 256
MAX_SEARCH_LIMIT = 30
MAX_SEARCH_PAGE = 10_000
MAX_BILI_VIDEO_PAGES = 1_000
MAX_BILI_COLLECTIONS = 100
MAX_NUMERIC_ID_LENGTH = 20
_NUMERIC_ID_PATTERN = re.compile(r'[0-9]+')

# Cookie 存储路径（由 config.py 注入）
try:
    from .config import BILI_COOKIE_TXT_PATH as _bili_config_path, MAX_PLAYLIST_IMPORT_TRACKS
    from .secure_storage import secure_read_text, secure_write_text
except ImportError:
    from config import BILI_COOKIE_TXT_PATH as _bili_config_path, MAX_PLAYLIST_IMPORT_TRACKS
    from secure_storage import secure_read_text, secure_write_text
BILI_COOKIE_TXT_PATH = _bili_config_path


def _normalize_bvid(value):
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if _BV_PATTERN.fullmatch(value) is None:
        return ""
    return "BV" + value[2:]


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
        or _NUMERIC_ID_PATTERN.fullmatch(text) is None
        or int(text) <= 0
    ):
        logger.warning("[Bili] 非法%s", label)
        return ""
    return text


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


def _safe_text(value, limit=512):
    text = str(value or "")
    text = "".join(
        " " if ord(char) < 32 or ord(char) == 127 else char
        for char in text
    )
    return text.strip()[:limit]


def normalize_bili_cookie(cookie_str):
    if not isinstance(cookie_str, str):
        raise ValueError("B站Cookie必须是字符串")
    cookie_str = cookie_str.strip()
    if not cookie_str:
        raise ValueError("B站Cookie不能为空")
    if len(cookie_str) > MAX_COOKIE_CHARS:
        raise ValueError("B站Cookie过长")
    if any(char in cookie_str for char in ("\r", "\n", "\0")):
        raise ValueError("B站Cookie包含非法控制字符")
    if "=" not in cookie_str:
        sessdata = cookie_str
    else:
        sessdata = ""
        for part in cookie_str.split(";"):
            key, separator, value = part.strip().partition("=")
            if separator and key == "SESSDATA":
                sessdata = value.strip()
                break
    if not sessdata or ";" in sessdata:
        raise ValueError("B站Cookie中未找到有效SESSDATA")
    return f"SESSDATA={sessdata}"


def load_bili_cookie():
    """读取B站Cookie"""
    try:
        if BILI_COOKIE_TXT_PATH and os.path.exists(BILI_COOKIE_TXT_PATH):
            return normalize_bili_cookie(
                secure_read_text(
                    BILI_COOKIE_TXT_PATH,
                    max_chars=MAX_COOKIE_CHARS + 1,
                )
            )
    except Exception:
        pass
    return ""


def save_bili_cookie(cookie_str):
    """保存B站Cookie到文件"""
    try:
        if BILI_COOKIE_TXT_PATH:
            secure_write_text(BILI_COOKIE_TXT_PATH, normalize_bili_cookie(cookie_str))
            _verify_cache.update({"ts": 0, "result": None})
            logger.info("[Bili] Cookie已保存")
    except Exception as e:
        logger.error("[Bili] 保存Cookie失败: %s", type(e).__name__)
        raise


def clear_bili_cookie():
    """删除B站Cookie文件"""
    try:
        if BILI_COOKIE_TXT_PATH:
            try:
                os.remove(BILI_COOKIE_TXT_PATH)
            except FileNotFoundError:
                pass
        _verify_cache.update({"ts": 0, "result": None})
        logger.info("[Bili] Cookie已删除")
    except Exception as e:
        logger.error("[Bili] 删除Cookie失败: %s", type(e).__name__)
        raise




def _bili_headers(extra=None):
    """构建B站API请求头，含User-Agent/Referer及Cookie"""
    h = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.bilibili.com/",
        "Accept": "application/json, text/plain, */*",
    }
    cookie = load_bili_cookie()
    if cookie:
        h["Cookie"] = cookie
    if extra:
        h.update(extra)
    return h


def _bili_headers_anon(extra=None):
    """构建不含Cookie的B站API请求头（用于登录流程）"""
    h = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.bilibili.com/",
        "Accept": "application/json, text/plain, */*",
    }
    if extra:
        h.update(extra)
    return h


# ====== 登录相关 ======

def generate_bili_qr():
    """生成B站扫码登录二维码，返回 {qrcode_b64, qrcode_key}
    qrcode_b64: base64 编码的 PNG 二维码图片（data URL）"""
    try:
        resp = requests.get(
            f"{BILI_PASSPORT}/x/passport-login/web/qrcode/generate",
            headers=_bili_headers_anon(), timeout=10, allow_redirects=False
        )
        data = resp.json()
        if data.get("code") != 0:
            logger.error("[Bili] 生成二维码失败 code=%s", data.get("code", "?"))
            return None
        inner = data["data"]
        qr_url = inner["url"]
        qr_key = inner["qrcode_key"]
        # 服务端本地生成二维码（避免前端依赖第三方QR API）
        qr_img = _qrcode_mod.make(qr_url, border=2)
        buf = io.BytesIO()
        qr_img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        logger.info("[Bili] 已生成登录二维码")
        return {
            "qrcode_b64": f"data:image/png;base64,{b64}",
            "qrcode_key": qr_key,
        }
    except Exception as e:
        logger.error("[Bili] 生成二维码异常: %s", type(e).__name__)
        return None


def poll_bili_qr(qrcode_key):
    """轮询扫码状态，返回 {status, message, sessdata}
    status: waiting | scanned | expired | success"""
    qrcode_key = str(qrcode_key or "").strip()
    if not qrcode_key or len(qrcode_key) > 256:
        return {"status": "error", "message": "二维码状态参数无效"}
    try:
        resp = requests.get(
            f"{BILI_PASSPORT}/x/passport-login/web/qrcode/poll",
            params={"qrcode_key": qrcode_key},
            headers=_bili_headers_anon(),
            timeout=10,
            allow_redirects=False,
        )
        data = resp.json()
        inner = data.get("data", {})
        code = inner.get("code")  # B站轮询用 data.code
        msg_map = {
            86101: ("waiting", "等待扫码"),
            86090: ("scanned", "已扫码，等待确认"),
            86038: ("expired", "二维码已过期"),
            0: ("success", "登录成功"),
        }
        status, message = msg_map.get(code, ("error", "二维码状态异常"))
        sessdata = None
        if status == "success":
            # 从响应的 Cookie 中提取 SESSDATA
            for c in resp.cookies:
                if c.name == "SESSDATA" and c.value:
                    sessdata = c.value
            # 也尝试从 Set-Cookie 头中解析
            if not sessdata:
                set_cookie = resp.headers.get("Set-Cookie", "")
                m = re.search(r'SESSDATA=([^;]+)', set_cookie)
                if m:
                    sessdata = m.group(1)
            if sessdata:
                save_bili_cookie(f"SESSDATA={sessdata}")
                logger.info("[Bili] 扫码登录成功，SESSDATA已保存")
        return {"status": status, "message": message, "sessdata": sessdata}
    except Exception as e:
        logger.error("[Bili] 轮询异常: %s", type(e).__name__)
        return {"status": "error", "message": "B站登录状态查询失败"}


def verify_bili_cookie(force=False):
    """验证B站Cookie是否有效，返回 {valid, uid, uname, face, message}"""
    if not force and _verify_cache["result"] is not None:
        if time.time() - _verify_cache["ts"] < _VERIFY_CACHE_TTL:
            return _verify_cache["result"]

    cookie = load_bili_cookie()
    if not cookie:
        result = {"valid": False, "uid": 0, "uname": "", "face": "",
                   "message": "未设置Cookie，请登录B站"}
        _verify_cache["ts"] = time.time()
        _verify_cache["result"] = result
        return result

    try:
        resp = requests.get(
            f"{BILI_API}/x/web-interface/nav",
            headers=_bili_headers(), timeout=10, allow_redirects=False
        )
        data = resp.json()
        if data.get("code") != 0:
            result = {"valid": False, "uid": 0, "uname": "", "face": "",
                       "message": "Cookie已失效，请重新登录"}
        else:
            inner = data["data"]
            result = {
                "valid": inner.get("isLogin", False),
                "uid": inner.get("mid", 0),
                "uname": inner.get("uname", ""),
                "face": inner.get("face", ""),
                "message": "Cookie有效" if inner.get("isLogin") else "未登录",
            }
    except Exception as e:
        logger.error("[Bili] 验证Cookie异常: %s", type(e).__name__)
        result = {"valid": False, "uid": 0, "uname": "", "face": "",
                   "message": "验证失败，请稍后重试"}

    _verify_cache["ts"] = time.time()
    _verify_cache["result"] = result
    return result


def get_bili_user_info():
    """获取B站用户信息"""
    try:
        resp = requests.get(
            f"{BILI_API}/x/web-interface/nav",
            headers=_bili_headers(), timeout=10, allow_redirects=False
        )
        data = resp.json()
        if data.get("code") != 0:
            return None
        inner = data["data"]
        return {
            "uid": inner.get("mid", 0),
            "uname": inner.get("uname", ""),
            "face": inner.get("face", ""),
            "level": (inner.get("level_info") or {}).get("current_level", 0),
            "vip_type": inner.get("vipType", 0),
        }
    except Exception as e:
        logger.error("[Bili] 获取用户信息异常: %s", type(e).__name__)
        return None


# ====== 搜索相关 ======

def _normalize_bili_song(item):
    """B站搜索结果 → 内部统一格式 {id, name, ar, al, bvid, cover}"""
    # 用 BVID 作为 id（后续获取播放URL需用 bvid）
    bvid = _normalize_bvid(item.get("bvid", ""))
    return {
        "id": bvid,
        "bvid": bvid,
        "name": _safe_text(item.get("title", "")),
        "ar": [{"name": _safe_text(item.get("author", ""))}],
        "al": {"name": ""},
        "cover": _normalize_bili_pic(item.get("pic", "")),
    }


def search_bili_music(keyword, limit=10, page=1):
    """搜索B站视频（按综合排序，获取可作为音频播放的视频）"""
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
    params = {
        "search_type": "video",
        "keyword": keyword,
        "page": safe_page,
        "page_size": safe_limit,
        "order": "totalrank",
    }
    url = f"{BILI_API}/x/web-interface/search/type"
    logger.info(f"[Bili搜索] 请求: GET {url}")
    try:
        s = _get_session()
        resp = s.get(
            url,
            params=params,
            headers=_bili_headers(),
            timeout=15,
            allow_redirects=False,
        )
        data = resp.json()
        if data.get("code") != 0:
            logger.error("[Bili搜索] API错误 code=%s", data.get("code", "?"))
            return []
        results = data.get("data", {}).get("result", [])
        if not isinstance(results, list):
            return []
        songs = [
            song for song in (
                _normalize_bili_song(item)
                for item in results[:safe_limit]
                if isinstance(item, dict)
            )
            if song.get("bvid")
        ]
        logger.info(f"[Bili搜索] 结果数={len(songs)}")
        if songs:
            top = songs[0]
            logger.info(
                "[Bili搜索] 首条 name=%r artist=%r bvid=%r",
                str(top['name'])[:120],
                str(top['ar'][0]['name'])[:120],
                str(top['bvid'])[:64],
            )
        return songs
    except Exception as e:
        logger.error("[Bili搜索] 异常: %s", type(e).__name__)
        return []


def search_bili_bvid(bvid):
    """按BV号搜索，返回单个分P的视频信息"""
    video_info = get_bili_complete_video_info(bvid)
    if not video_info:
        return []
    results = []
    for page in video_info.get("pages", []):
        song_name = _format_bili_song_name(
            video_info["title"], page["page"], page.get("part", ""), len(video_info["pages"])
        )
        results.append({
            "id": bvid,
            "bvid": bvid,
            "name": song_name,
            "ar": [{"name": video_info.get("author", "")}],
            "al": {"name": ""},
            "cover": video_info.get("cover", ""),
            "page_number": page["page"],
            "page_title": page.get("part", ""),
            "video_title": video_info["title"],
            "total_pages": len(video_info["pages"]),
        })
    return results


# ====== 音频流获取 ======

def _get_bili_pagelist(bvid):
    """获取视频分P列表，返回 [{page, cid, part, duration}]"""
    bvid = _normalize_bvid(bvid)
    if not bvid:
        return []
    url = f"{BILI_API}/x/player/pagelist"
    try:
        resp = requests.get(
            url,
            params={"bvid": bvid},
            headers=_bili_headers(),
            timeout=10,
            allow_redirects=False,
        )
        data = resp.json()
        if data.get("code") != 0:
            logger.error("[Bili分P] API错误 bvid=%s code=%s", bvid, data.get("code", "?"))
            return []
        pages = data.get("data", [])
        if not isinstance(pages, list):
            return []
        return [
            item for item in pages[:MAX_BILI_VIDEO_PAGES]
            if isinstance(item, dict)
        ]
    except Exception as e:
        logger.error("[Bili分P] 异常 bvid=%s: %s", bvid, type(e).__name__)
        return []


def _get_bili_audio_url(bvid, cid):
    """获取DASH音频流URL，返回 (url, expires_at)"""
    bvid = _normalize_bvid(bvid)
    cid = _normalize_numeric_id(cid, "分P CID")
    if not bvid or not cid:
        return "", None
    url = f"{BILI_API}/x/player/playurl"
    try:
        resp = requests.get(
            url,
            params={"bvid": bvid, "cid": cid, "fnval": 4048},
            headers=_bili_headers(),
            timeout=10,
            allow_redirects=False,
        )
        data = resp.json()
        if data.get("code") != 0:
            logger.error("[Bili取链] API错误 bvid=%s cid=%s code=%s", bvid, cid, data.get("code", "?"))
            return "", None
        dash = data.get("data", {}).get("dash", {})
        audio_list = dash.get("audio", [])
        if not audio_list:
            logger.warning(f"[Bili取链] 无DASH音频 bvid={bvid} cid={cid}")
            return "", None
        audio_url = audio_list[0].get("baseUrl", "") or audio_list[0].get("base_url", "")
        if not audio_url and audio_list[0].get("backup_url"):
            backup = audio_list[0]["backup_url"]
            if isinstance(backup, list) and backup:
                audio_url = backup[0]
            else:
                audio_url = backup
        expires_at = _derive_bili_expiry(audio_url)
        logger.info(f"[Bili取链] bvid={bvid} cid={cid} {'成功' if audio_url else '失败'}"
                    f"{' expires=' + str(expires_at) if expires_at else ''}")
        return audio_url, expires_at
    except Exception as e:
        logger.error("[Bili取链] 异常 bvid=%s cid=%s: %s", bvid, cid, type(e).__name__)
        return "", None


def _derive_bili_expiry(audio_url):
    """从B站音频URL参数推导过期时间"""
    if not audio_url:
        return None
    import urllib.parse
    from datetime import datetime, timezone, timedelta
    try:
        parsed = urllib.parse.urlparse(audio_url)
        qs = urllib.parse.parse_qs(parsed.query)
        for key in ("expire", "expires", "deadline", "e"):
            val = qs.get(key, [None])[0]
            if val:
                ts = int(val)
                if ts > 1e12:
                    ts //= 1000
                tz_utc8 = timezone(timedelta(hours=8))
                return datetime.fromtimestamp(ts, tz=tz_utc8).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass
    return "未知"


def get_bili_play_url(bvid, page=1):
    """获取B站视频指定分P的播放信息，返回 {raw_url, title, duration, cover, author}"""
    bvid = _normalize_bvid(bvid)
    page = _bounded_int(page, 1, MAX_BILI_VIDEO_PAGES)
    if not bvid or page is None:
        return None
    pages = _get_bili_pagelist(bvid)
    if not pages:
        return None
    idx = min(page - 1, len(pages) - 1)
    target = pages[idx]
    if not isinstance(target, dict):
        return None
    cid = target.get("cid")
    if not cid:
        return None
    audio_url, expires_at = _get_bili_audio_url(bvid, cid)
    if not audio_url:
        return None
    return {
        "raw_url": audio_url,
        "expires_at": expires_at,
        "title": _safe_text(target.get("part", "")),
        "duration": target.get("duration", 0),
        "page": target.get("page", page),
    }


def get_bili_video_info(bvid):
    """获取B站视频基本信息 {title, cover, duration, author}"""
    bvid = _normalize_bvid(bvid)
    if not bvid:
        return None
    url = f"{BILI_API}/x/web-interface/view"
    try:
        resp = requests.get(
            url,
            params={"bvid": bvid},
            headers=_bili_headers(),
            timeout=10,
            allow_redirects=False,
        )
        data = resp.json()
        if data.get("code") != 0:
            return None
        inner = data["data"]
        if not isinstance(inner, dict):
            return None
        staff = inner.get("staff", [])
        if not isinstance(staff, list):
            staff = []
        authors = [
            _safe_text(s.get("name", ""))
            for s in staff
            if isinstance(s, dict) and s.get("name")
        ]
        if not authors:
            owner = inner.get("owner", {})
            authors = [
                _safe_text(owner.get("name", ""))
            ] if isinstance(owner, dict) else []
        return {
            "title": _safe_text(inner.get("title", "")),
            "cover": _normalize_bili_pic(inner.get("pic", "")),
            "duration": inner.get("duration", 0),
            "author": _safe_text("; ".join(filter(None, authors))),
        }
    except Exception as e:
        logger.error("[Bili视频信息] 异常 bvid=%s: %s", bvid, type(e).__name__)
        return None


def get_bili_complete_video_info(bvid):
    """获取B站视频完整信息（含所有分P）"""
    bvid = _normalize_bvid(bvid)
    if not bvid:
        return None
    info = get_bili_video_info(bvid)
    if not info:
        return None
    pages = _get_bili_pagelist(bvid)
    return {
        "bvid": bvid,
        "title": info["title"],
        "cover": info["cover"],
        "author": info["author"],
        "duration": info["duration"],
        "pages": [{
            "page": p.get("page", 1),
            "cid": p.get("cid", 0),
            "part": _safe_text(p.get("part", "")),
            "duration": p.get("duration", 0),
        } for p in pages],
    }


def _normalize_bili_pic(url):
    """规一化B站封面URL"""
    if not isinstance(url, str):
        return ""
    url = url.strip()
    if (
        not url
        or len(url) > 8192
        or any(ord(char) < 32 or ord(char) == 127 for char in url)
    ):
        return ""
    if url.startswith("//"):
        url = "https:" + url
    if url.startswith("http://"):
        url = "https://" + url[7:]
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme.lower() != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            return ""
        _ = parsed.port
    except ValueError:
        return ""
    return url


def _format_bili_song_name(video_title, page_number, page_title, total_pages):
    """格式化多P歌曲名: 主标题P序号 分P标题"""
    if total_pages <= 1:
        return video_title
    if not page_title:
        return f"{video_title}P{page_number}"
    return f"{video_title}P{page_number} {page_title}"


# ====== 收藏夹相关 ======

def get_bili_favorite_collections():
    """获取当前登录用户的收藏夹列表，返回 [{id, title, count, cover}]"""
    user = get_bili_user_info()
    if not user:
        logger.warning("[Bili收藏夹] 未登录，无法获取")
        return []
    uid = _normalize_numeric_id(user.get("uid"), "用户ID")
    if not uid:
        return []
    url = f"{BILI_API}/x/v3/fav/folder/created/list"
    logger.info(f"[Bili收藏夹] 请求: GET {url}")
    try:
        resp = requests.get(
            url,
            params={"up_mid": uid, "pn": 1, "ps": MAX_BILI_COLLECTIONS},
            headers=_bili_headers(),
            timeout=15,
            allow_redirects=False,
        )
        data = resp.json()
        if data.get("code") != 0:
            logger.error("[Bili收藏夹] API错误 code=%s", data.get("code", "?"))
            return []
        inner = data.get("data") or {}
        inner_list = inner.get("list", []) if isinstance(inner, dict) else []
        if not isinstance(inner_list, list):
            return []
        result = []
        for item in inner_list[:MAX_BILI_COLLECTIONS]:
            if not isinstance(item, dict):
                continue
            collection_id = _normalize_numeric_id(item.get("id"), "收藏夹ID")
            if not collection_id:
                continue
            result.append({
                "id": collection_id,
                "title": _safe_text(item.get("title", "")),
                "count": item.get("media_count", 0),
                "cover": _normalize_bili_pic(item.get("cover", "")),
            })
        logger.info(f"[Bili收藏夹] 共 {len(result)} 个")
        return result
    except Exception as e:
        logger.error("[Bili收藏夹] 异常: %s", type(e).__name__)
        return []


def get_bili_favorite_bvids(media_id):
    """获取指定收藏夹中所有视频BVID，返回 [{bvid, title}]"""
    media_id = _normalize_numeric_id(media_id, "收藏夹ID")
    if not media_id:
        return []
    url = f"{BILI_API}/x/v3/fav/resource/ids"
    logger.info(f"[Bili收藏夹内容] 请求: GET {url}")
    try:
        resp = requests.get(
            url,
            params={"media_id": media_id, "platform": "web"},
            headers=_bili_headers(),
            timeout=15,
            allow_redirects=False,
        )
        data = resp.json()
        if data.get("code") != 0:
            logger.error("[Bili收藏夹内容] API错误 code=%s", data.get("code", "?"))
            return []
        raw_items = data.get("data", [])
        if not isinstance(raw_items, list):
            return []
        items = raw_items[:MAX_PLAYLIST_IMPORT_TRACKS]
        result = []
        seen = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("type") != 2:  # 仅视频
                continue
            bvid = _normalize_bvid(item.get("bvid") or item.get("bv_id", ""))
            if bvid and bvid not in seen:
                seen.add(bvid)
                result.append({"bvid": bvid, "title": ""})
        logger.info(f"[Bili收藏夹内容] 共 {len(result)} 个视频")
        return result
    except Exception as e:
        logger.error("[Bili收藏夹内容] 异常: %s", type(e).__name__)
        return []


def get_bili_favorite_all_tracks(media_id):
    """获取收藏夹中所有歌曲信息，生成 BILI_PLAYLIST_SONG: 标记"""
    bvids = get_bili_favorite_bvids(media_id)
    result = []
    logger.info(f"[Bili歌单处理] 处理 {len(bvids)} 个视频...")
    for item in bvids:
        bvid = item["bvid"]
        info = get_bili_complete_video_info(bvid)
        if not info:
            continue
        for page in info["pages"]:
            if len(result) >= MAX_PLAYLIST_IMPORT_TRACKS:
                logger.warning("[Bili歌单处理] 达到安全上限 %d，停止导入", MAX_PLAYLIST_IMPORT_TRACKS)
                return result
            song_name = _format_bili_song_name(
                info["title"], page["page"], page.get("part", ""), len(info["pages"])
            )
            marker = f"BILI_PLAYLIST_SONG:{bvid}:{page['page']}:{song_name}:{info.get('author', '')}"
            result.append({
                "id": bvid,
                "bvid": bvid,
                "page": page["page"],
                "name": song_name,
                "artist": info.get("author", ""),
                "marker": marker,
            })
    logger.info(f"[Bili歌单处理] 完成 {len(result)} 首")
    return result


# ====== 批量取链 ======

def resolve_bili_marker_batch(markers, count=5):
    """批量解析 BILI_PLAYLIST_SONG: 标记为实际播放URL
    返回 {marker: url} dict"""
    safe_count = _bounded_int(count, 1, 20)
    if safe_count is None or not isinstance(markers, (list, tuple)):
        return {}
    resolved = {}
    to_resolve = []
    for m in markers:
        if not isinstance(m, str):
            continue
        parts = m.split(":", 3)
        if (
            len(parts) >= 3
            and parts[0] == "BILI_PLAYLIST_SONG"
            and _normalize_bvid(parts[1])
            and _bounded_int(parts[2], 1, MAX_BILI_VIDEO_PAGES) is not None
            and m not in resolved
        ):
            to_resolve.append(m)
            if len(to_resolve) >= safe_count:
                break
    if not to_resolve:
        return resolved

    logger.info(f"[Bili批量取链] 解析 {len(to_resolve)} 个标记")

    def fetch_one(marker):
        parts = marker.split(":", 3)
        if len(parts) >= 3:
            bvid = _normalize_bvid(parts[1])
            page = _bounded_int(parts[2], 1, MAX_BILI_VIDEO_PAGES)
            if not bvid or page is None:
                return marker, ""
            info = get_bili_play_url(bvid, page)
            if info:
                return marker, info["raw_url"]
        return marker, ""

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(fetch_one, m): m for m in to_resolve}
        for future in as_completed(futures):
            try:
                marker, url = future.result()
                if url:
                    resolved[marker] = url
            except Exception as e:
                logger.error("[Bili批量取链] 并发异常: %s", type(e).__name__)

    logger.info(f"[Bili批量取链] 成功 {len(resolved)}/{len(to_resolve)}")
    return resolved


def refill_bili_playlist_queue(channel_id, play_list_dict, count=5, lock=None):
    """检查播放队列并将前 count 个 BILI_PLAYLIST_SONG 标记替换为真实URL"""
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
            and item.get("file", "").startswith("BILI_PLAYLIST_SONG:")
        ]

    if lock is not None:
        with lock:
            markers = collect_markers()
    else:
        markers = collect_markers()
    if not markers:
        return 0

    resolved = resolve_bili_marker_batch(markers, safe_count)
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
        logger.info(f"[Bili批量取链] 已替换 {replaced} 个标记为真实URL")
    return replaced
