"""网易云账号管理 API 路由 — 代理请求到本地 Node.js API"""
import os
import json
import logging
import requests
from flask import jsonify, request, render_template

try:
    from .config import MUSIC_API_BASE
    from .secure_storage import secure_read_text, secure_write_text
except ImportError:
    from config import MUSIC_API_BASE
    from secure_storage import secure_read_text, secure_write_text

logger = logging.getLogger(__name__)

COOKIE_TXT_PATH = os.path.join(os.path.dirname(__file__), "Cookie", "cookie.txt")
COOKIE_JSON_PATH = os.path.join(os.path.dirname(__file__), "Cookie", "cookies.json")
MAX_COOKIE_CHARS = 64 * 1024
_SENSITIVE_RESPONSE_KEYS = frozenset({
    "cookie",
    "cookies",
    "set_cookie",
    "token",
    "access_token",
    "accesstoken",
    "access_key",
    "accesskey",
    "refresh_token",
    "refreshtoken",
    "refresh_key",
    "refreshkey",
    "session",
    "session_id",
    "sessionid",
    "sessdata",
    "csrf",
    "csrf_token",
    "csrftoken",
    "__csrf",
    "music_u",
    "music_a",
    "musickey",
    "music_key",
    "qqmusic_key",
    "qm_keyst",
    "authorization",
    "password",
    "secret",
    "client_secret",
    "api_key",
    "apikey",
    "credential",
    "credentials",
    "login_cookie",
    "user_cookie",
    "oauth_token",
    "nmtid",
    "jessionid",
    "jct",
})
MAX_ACCOUNT_UID_LENGTH = 32
MAX_ACCOUNT_PAGE_LIMIT = 100
MAX_ACCOUNT_PAGE_OFFSET = 1_000_000


def _single_query_value(name):
    values = request.args.getlist(name)
    if len(values) > 1:
        raise ValueError(f"{name}不允许重复")
    return values[0] if values else None


def _parse_account_uid():
    value = _single_query_value("uid")
    if value in (None, ""):
        raise ValueError("缺少uid参数")
    if (
        len(value) > MAX_ACCOUNT_UID_LENGTH
        or not value.isascii()
        or not value.isdigit()
        or int(value) <= 0
    ):
        raise ValueError("uid参数格式无效")
    return value


def _parse_account_page_arg(name, default, minimum, maximum):
    value = _single_query_value(name)
    if value is None:
        return default
    if not value or len(value) > 12 or not value.isascii() or not value.isdigit():
        raise ValueError(f"{name}参数格式无效")
    parsed = int(value)
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{name}参数超出允许范围")
    return parsed


def _sanitize_external_payload(value):
    """Remove login credentials from data returned by the local Node API."""
    if isinstance(value, dict):
        clean = {}
        for key, item in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if normalized in _SENSITIVE_RESPONSE_KEYS:
                continue
            clean[key] = _sanitize_external_payload(item)
        return clean
    if isinstance(value, list):
        return [_sanitize_external_payload(item) for item in value]
    return value


def _capture_response_cookie(result):
    if not isinstance(result, dict):
        return
    cookie = result.get("cookie")
    if isinstance(cookie, str) and cookie.strip():
        _save_cookie(cookie.strip())


def _normalize_cookie(cookie_str):
    if not isinstance(cookie_str, str):
        raise ValueError("Cookie必须是字符串")
    cookie_str = cookie_str.strip()
    if not cookie_str:
        raise ValueError("Cookie内容为空")
    if len(cookie_str) > MAX_COOKIE_CHARS:
        raise ValueError("Cookie内容过长")
    if any(char in cookie_str for char in ("\r", "\n", "\0")):
        raise ValueError("Cookie包含非法控制字符")
    return cookie_str


def _load_cookie():
    """从cookie.txt加载Cookie字符串"""
    try:
        if os.path.exists(COOKIE_TXT_PATH):
            return _normalize_cookie(
                secure_read_text(COOKIE_TXT_PATH, max_chars=MAX_COOKIE_CHARS + 1)
            )
    except Exception:
        pass
    return ""


def _save_cookie(cookie_str):
    """保存Cookie字符串到文件"""
    secure_write_text(COOKIE_TXT_PATH, _normalize_cookie(cookie_str))


def _clear_cookie():
    """清除Cookie文件"""
    failures = 0
    for path in (COOKIE_TXT_PATH, COOKIE_JSON_PATH):
        try:
            os.remove(path)
        except FileNotFoundError:
            continue
        except OSError as exc:
            failures += 1
            logger.error("[账号API] 删除登录凭据失败: %s", type(exc).__name__)
    if failures:
        raise OSError("未能完整删除网易云登录凭据")


def _merge_save_cookies(resp_cookies):
    """合并响应中的cookie到本地存储"""
    if not resp_cookies:
        return
    new_parts = [f"{k}={v}" for k, v in resp_cookies.items()]
    if not new_parts:
        return
    new_cookie = "; ".join(new_parts)
    existing = _load_cookie()
    if existing:
        # 合并：新值覆盖旧值
        existing_map = {}
        for part in existing.split(";"):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                existing_map[k.strip()] = v.strip()
        for part in new_parts:
            k, v = part.split("=", 1)
            existing_map[k.strip()] = v.strip()
        merged = "; ".join(f"{k}={v}" for k, v in existing_map.items())
        _save_cookie(merged)
    else:
        _save_cookie(new_cookie)


def _api_get(path, **params):
    """调用本地API GET请求，附带Cookie"""
    cookie = _load_cookie()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    if cookie:
        headers["Cookie"] = cookie
    url = f"{MUSIC_API_BASE}{path}"
    logger.info(f"[账号API] GET {url}")
    try:
        r = requests.get(url, params=params, headers=headers, timeout=15, allow_redirects=False)
        result = r.json()
        if not isinstance(result, dict):
            raise ValueError("unexpected local API response")
        code = result.get("code", "?")
        logger.info(f"[账号API] 状态={r.status_code} code={code}")
        if r.cookies:
            _merge_save_cookies(r.cookies)
        _capture_response_cookie(result)
        return _sanitize_external_payload(result)
    except Exception as e:
        logger.error("[账号API] GET %s 失败: %s", path, type(e).__name__)
        return {"code": -1, "message": "本地音乐API请求失败"}


def _api_post(path, data=None):
    """调用本地API POST请求，附带Cookie"""
    cookie = _load_cookie()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    if cookie:
        headers["Cookie"] = cookie
    url = f"{MUSIC_API_BASE}{path}"
    logger.info(f"[账号API] POST {url}")
    try:
        r = requests.post(url, data=data or {}, headers=headers, timeout=20, allow_redirects=False)
        result = r.json()
        if not isinstance(result, dict):
            raise ValueError("unexpected local API response")
        code = result.get("code", "?")
        logger.info(f"[账号API] 状态={r.status_code} code={code}")
        if r.cookies:
            _merge_save_cookies(r.cookies)
        _capture_response_cookie(result)
        return _sanitize_external_payload(result)
    except Exception as e:
        logger.error("[账号API] POST %s 失败: %s", path, type(e).__name__)
        return {"code": -1, "message": "本地音乐API请求失败"}


def register_account_routes(app):
    """注册账号管理与桌面应用页面路由"""

    @app.route("/account")
    def account_page():
        """账号管理页面"""
        return render_template("account.html")

    @app.route("/library")
    def library_page():
        """跨平台音乐库页面"""
        return render_template("library.html")

    @app.route("/status")
    def status_page():
        """运行时健康状态页面"""
        return render_template("status.html")

    @app.route("/settings")
    def settings_page():
        """浏览器端界面设置页面"""
        return render_template("settings.html")

    @app.route("/api/playlist/promote", methods=["POST"])
    def promote_playlist_item():
        """把指定待播歌曲提升到队首，作为当前歌曲之后的下一首。"""
        data = request.get_json(silent=True) or {}
        channel_id = str(data.get("channel_id") or "")
        index = data.get("index")
        if not channel_id or index is None:
            return jsonify({"success": False, "error": "缺少必要参数"})

        try:
            index = int(index)
        except (TypeError, ValueError):
            return jsonify({"success": False, "error": "无效的歌曲索引"})

        try:
            try:
                from . import kookvoice
            except ImportError:
                import kookvoice

            with kookvoice.state_lock:
                state = kookvoice.play_list.get(channel_id)
                if state is None:
                    return jsonify({"success": False, "error": "播放列表不存在"})

                queue = state.get("play_list", [])
                if index < 0 or index >= len(queue):
                    return jsonify({"success": False, "error": "索引超出范围"})

                item = queue[index]
                extra = item.get("extra", {}) if isinstance(item, dict) else {}
                if not isinstance(extra, dict):
                    extra = {}
                song_name = extra.get("title") or extra.get("音乐名字") or "未知歌曲"

                if index == 0:
                    return jsonify({
                        "success": True,
                        "already_top": True,
                        "name": song_name,
                    })

                item = queue.pop(index)
                queue.insert(0, item)

                # 随机播放开启时 _queue_backup 保存原顺序。同步本次“顶歌”意图，
                # 避免之后关闭随机播放时把被顶歌曲重新放回旧位置。
                backup = state.get("_queue_backup")
                if isinstance(backup, list):
                    backup_index = next(
                        (i for i, candidate in enumerate(backup) if candidate is item),
                        None,
                    )
                    if backup_index is not None and backup_index > 0:
                        backup.insert(0, backup.pop(backup_index))

            logger.info(
                "[顶歌] channel=%s index=%s song=%s",
                channel_id,
                index,
                song_name,
            )
            return jsonify({
                "success": True,
                "already_top": False,
                "name": song_name,
            })
        except Exception as e:
            logger.error("顶歌失败: %s", type(e).__name__)
            return jsonify({"success": False, "error": "调整播放队列失败"}), 500

    @app.route("/api/account/status")
    def account_status():
        """获取登录状态"""
        result = _api_get("/login/status")
        # login_status 返回 code:200 且包含 account/profile 信息时表示已登录
        return jsonify(result)

    @app.route("/api/account/detail")
    def account_detail():
        """获取用户详情"""
        try:
            uid = _parse_account_uid()
        except ValueError as exc:
            return jsonify({"code": 400, "message": str(exc)}), 400
        result = _api_get(f"/user/detail", uid=uid)
        return jsonify(result)

    @app.route("/api/account/level")
    def account_level():
        """获取用户等级"""
        result = _api_get("/user/level")
        return jsonify(result)

    @app.route("/api/account/subcount")
    def account_subcount():
        """获取收藏计数"""
        result = _api_get("/user/subcount")
        return jsonify(result)

    @app.route("/api/account/playlists")
    def account_playlists():
        """获取用户歌单"""
        try:
            uid = _parse_account_uid()
            limit = _parse_account_page_arg(
                "limit", 30, 1, MAX_ACCOUNT_PAGE_LIMIT
            )
            offset = _parse_account_page_arg(
                "offset", 0, 0, MAX_ACCOUNT_PAGE_OFFSET
            )
        except ValueError as exc:
            return jsonify({"code": 400, "message": str(exc)}), 400
        result = _api_get(f"/user/playlist", uid=uid, limit=limit, offset=offset)
        return jsonify(result)

    @app.route("/api/account/qr/key", methods=["POST"])
    def account_qr_key():
        """获取二维码登录key"""
        import time
        result = _api_get("/login/qr/key", timestamp=int(time.time() * 1000))
        return jsonify(result)

    @app.route("/api/account/qr/create", methods=["POST"])
    def account_qr_create():
        """创建二维码"""
        import time
        data = request.json or {}
        key = data.get("key", "")
        if not key:
            return jsonify({"code": -1, "message": "缺少key参数"})
        result = _api_get("/login/qr/create", key=key, qrimg="true", type=1,
                          timestamp=int(time.time() * 1000))
        return jsonify(result)

    @app.route("/api/account/qr/check", methods=["POST"])
    def account_qr_check():
        """检查二维码扫码状态"""
        import time
        data = request.json or {}
        key = data.get("key", "")
        if not key:
            return jsonify({"code": -1, "message": "缺少key参数"})
        result = _api_get("/login/qr/check", key=key,
                          timestamp=int(time.time() * 1000))
        return jsonify(result)

    @app.route("/api/account/cellphone/captcha", methods=["POST"])
    def account_captcha_send():
        """发送手机验证码"""
        data = request.json or {}
        phone = data.get("phone", "")
        ct = data.get("countrycode", "86")
        if not phone:
            return jsonify({"code": -1, "message": "缺少phone参数"})
        import time
        result = _api_get("/captcha/sent", phone=phone, countrycode=ct,
                          timestamp=int(time.time() * 1000))
        return jsonify(result)

    @app.route("/api/account/cellphone/verify", methods=["POST"])
    def account_captcha_verify():
        """校验验证码"""
        data = request.json or {}
        phone = data.get("phone", "")
        code = data.get("captcha", "")
        ct = data.get("countrycode", "86")
        if not phone or not code:
            return jsonify({"code": -1, "message": "缺少参数"})
        import time
        result = _api_get("/captcha/verify", phone=phone, captcha=code,
                          countrycode=ct, timestamp=int(time.time() * 1000))
        return jsonify(result)

    @app.route("/api/account/cellphone/login", methods=["POST"])
    def account_cellphone_login():
        """手机验证码登录"""
        data = request.json or {}
        phone = data.get("phone", "")
        code = data.get("captcha", "")
        ct = data.get("countrycode", "86")
        if not phone or not code:
            return jsonify({"code": -1, "message": "缺少手机号或验证码"})
        import time
        ts = int(time.time() * 1000)
        result = _api_post(f"/login/cellphone?timestamp={ts}", {
            "phone": phone,
            "captcha": code,
            "countrycode": ct,
            "rememberLogin": "true",
        })
        return jsonify(result)

    @app.route("/api/account/signin", methods=["POST"])
    def account_signin():
        """每日签到"""
        data = request.json or {}
        sign_type = data.get("type", 0)  # 0=android(3点经验), 1=web(2点经验)
        result = _api_get("/daily_signin", type=sign_type)
        return jsonify(result)

    @app.route("/api/account/logout", methods=["POST"])
    def account_logout():
        """退出登录"""
        result = _api_get("/logout")
        try:
            _clear_cookie()
        except OSError:
            return jsonify({"code": 500, "message": "本地登录凭据清理失败"}), 500
        return jsonify(result)

    @app.route("/api/account/cookie", methods=["POST"])
    def account_save_cookie():
        """手动保存Cookie"""
        data = request.json or {}
        try:
            cookie_str = _normalize_cookie(data.get("cookie"))
            _save_cookie(cookie_str)
            return jsonify({"code": 200, "message": "Cookie已保存"})
        except ValueError as exc:
            return jsonify({"code": 400, "message": str(exc)}), 400
        except OSError:
            return jsonify({"code": 500, "message": "Cookie保存失败"}), 500
