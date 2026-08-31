import logging
import time

import requests
from flask import jsonify, request

try:
    from .config import QQ_MUSIC_API_BASE
    from .qq_credential import (
        clear_qq_credential,
        ensure_qq_credential,
        load_qq_cookie,
        parse_cookie_string,
        refresh_qq_credential,
        save_qq_cookie,
        serialize_cookie,
        start_qq_credential_maintenance,
    )
except ImportError:
    from config import QQ_MUSIC_API_BASE
    from qq_credential import (
        clear_qq_credential,
        ensure_qq_credential,
        load_qq_cookie,
        parse_cookie_string,
        refresh_qq_credential,
        save_qq_cookie,
        serialize_cookie,
        start_qq_credential_maintenance,
    )

logger = logging.getLogger(__name__)

MAX_ACCOUNT_PAGE_LIMIT = 100
MAX_ACCOUNT_PAGE_OFFSET = 1_000_000


def _single_query_value(name):
    values = request.args.getlist(name)
    if len(values) > 1:
        raise ValueError(f"{name}不允许重复")
    return values[0] if values else None


def _parse_page_arg(name, default, minimum, maximum):
    value = _single_query_value(name)
    if value is None:
        return default
    if not value or len(value) > 12 or not value.isascii() or not value.isdigit():
        raise ValueError(f"{name}参数格式无效")
    parsed = int(value)
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{name}参数超出允许范围")
    return parsed


def _load_qq_cookie():
    return load_qq_cookie()


def _enrich_cookie_from_session(cookie_str, session):
    """把扫码响应里可能独立返回的 refresh/access 字段并入持久化 Cookie。"""
    cookies = parse_cookie_string(cookie_str)
    candidates = []
    if isinstance(session, dict):
        candidates.append(session)
        for key in ("credential", "data", "user", "loginData"):
            value = session.get(key)
            if isinstance(value, dict):
                candidates.append(value)

    def first(*keys):
        for candidate in candidates:
            for key in keys:
                value = candidate.get(key)
                if value not in (None, ""):
                    return value
        return None

    uin = first("musicid", "uin")
    musickey = first("musickey", "qqmusic_key", "qm_keyst")
    refresh_token = first("refresh_token", "refreshToken")
    refresh_key = first("refresh_key", "refreshKey")
    access_token = first("access_token", "accessToken")
    openid = first("openid", "openId")
    unionid = first("unionid", "unionId")
    login_type = first("login_type", "loginType")

    if uin and not cookies.get("uin"):
        cookies["uin"] = str(uin)
    if musickey:
        cookies["qqmusic_key"] = str(musickey)
        cookies["qm_keyst"] = str(musickey)
    if refresh_token:
        cookies["psrf_qqrefresh_token"] = str(refresh_token)
    if refresh_key:
        cookies["psrf_qqrefresh_key"] = str(refresh_key)
    if access_token:
        cookies["psrf_qqaccess_token"] = str(access_token)
    if openid:
        cookies["psrf_qqopenid"] = str(openid)
    if unionid:
        cookies["psrf_qqunionid"] = str(unionid)
    if login_type not in (None, ""):
        cookies["login_type"] = str(login_type)

    try:
        create_time = int(first("musickeyCreateTime", "musickey_create_time") or 0)
        key_expires_in = int(first("keyExpiresIn", "key_expires_in") or 0)
    except (TypeError, ValueError):
        create_time = 0
        key_expires_in = 0
    if create_time and key_expires_in:
        expires_at = create_time + key_expires_in
        cookies["musickeyCreateTime"] = str(create_time)
        cookies["qqmusic_key_expiresAt"] = str(expires_at)
        cookies["musickey_expiresAt"] = str(expires_at)

    return serialize_cookie(cookies)


def _save_qq_cookie(cookie_str, session=None, source="login"):
    cookie_str = _enrich_cookie_from_session(cookie_str, session or {})
    credential = save_qq_cookie(cookie_str, source=source)
    logger.info(
        "[QQ账号] 登录凭证已保存 uin=%s refresh_supported=%s",
        credential.get("uin"),
        bool(
            (credential.get("refresh_token") and credential.get("refresh_key"))
            or str(credential.get("musickey") or "").startswith(("Q_H_L", "W_X"))
        ),
    )
    return credential


def _clear_qq_cookie():
    clear_qq_credential()


def _qq_api_get(path, **params):
    cookie = _load_qq_cookie()
    headers = {"Cookie": cookie} if cookie else {}
    url = f"{QQ_MUSIC_API_BASE}{path}"
    try:
        res = requests.get(url, params=params, headers=headers, timeout=15, allow_redirects=False)
        return res.json()
    except Exception as e:
        logger.error("[QQ账号API] GET %s 异常: %s", path, type(e).__name__)
        return {"error": "QQ音乐API请求失败"}


def _qq_api_post(path, data=None):
    cookie = _load_qq_cookie()
    headers = {"Cookie": cookie} if cookie else {}
    url = f"{QQ_MUSIC_API_BASE}{path}"
    try:
        res = requests.post(url, json=data, headers=headers, timeout=15, allow_redirects=False)
        return res.json()
    except Exception as e:
        logger.error("[QQ账号API] POST %s 异常: %s", path, type(e).__name__)
        return {"error": "QQ音乐API请求失败"}


def register_qq_account_routes(app, start_maintenance=True):
    """注册QQ音乐账号管理路由，并启动单例凭证续期守护线程。"""
    if start_maintenance:
        start_qq_credential_maintenance()

    @app.route('/api/qq/account/status', methods=['GET'])
    def qq_account_status():
        """获取QQ音乐登录状态，并在需要时主动续期。"""
        try:
            result = ensure_qq_credential(force_refresh=False, reason="account-status")
            return jsonify({
                "code": 200,
                "logged_in": bool(result.get("valid")),
                "uin": result.get("uin", ""),
                "message": result.get("message", ""),
                "need_relogin": bool(result.get("need_relogin")),
                "expires_in": result.get("expires_in", -1),
                "expires_at": result.get("expires_at", 0),
                "auto_refresh": bool(result.get("auto_refresh", True)),
                "refresh_supported": bool(result.get("refresh_supported")),
                "last_refresh_at": result.get("refreshed_at", 0),
                "last_refresh_attempt": result.get("last_refresh_attempt", 0),
                "last_refresh_error": result.get("last_refresh_error", ""),
                "refresh_failures": result.get("refresh_failures", 0),
            })
        except Exception as e:
            logger.error("[QQ账号] 状态查询异常: %s", type(e).__name__)
            return jsonify({"code": 500, "error": "QQ音乐账号操作失败"}), 500

    @app.route('/api/qq/account/refresh', methods=['POST'])
    def qq_account_refresh():
        """人工触发一次凭证续期，供故障排查和账号页手动恢复使用。"""
        try:
            credential = refresh_qq_credential(reason="manual-api")
            expires_at = int(credential.get("key_expires_at") or 0)
            return jsonify({
                "code": 200,
                "success": True,
                "uin": credential.get("uin", ""),
                "expires_at": expires_at,
                "expires_in": max(-1, expires_at - int(time.time())) if expires_at else -1,
                "message": "QQ音乐登录凭证续期成功",
            })
        except Exception as e:
            logger.warning("[QQ账号] 手动续期失败: %s", type(e).__name__)
            return jsonify({"code": 409, "success": False, "error": "QQ音乐凭据更新冲突"}), 409

    @app.route('/api/qq/account/qr/create', methods=['POST'])
    def qq_account_qr_create():
        """创建QQ音乐二维码登录"""
        try:
            result = _qq_api_get("/getQQLoginQr")
            response = result.get("response", result)
            if response.get("img"):
                return jsonify({
                    "code": 200,
                    "qrcode": response.get("img", ""),
                    "ptqrtoken": response.get("ptqrtoken", ""),
                    "qrsig": response.get("qrsig", ""),
                })
            return jsonify({"code": 500, "error": "获取二维码失败"})
        except Exception as e:
            logger.error("[QQ账号] 创建二维码异常: %s", type(e).__name__)
            return jsonify({"code": 500, "error": "QQ音乐账号操作失败"}), 500

    @app.route('/api/qq/account/qr/check', methods=['POST'])
    def qq_account_qr_check():
        """检查QQ音乐扫码状态"""
        try:
            data = request.json or {}
            ptqrtoken = data.get("ptqrtoken", "")
            qrsig = data.get("qrsig", "")
            if not ptqrtoken or not qrsig:
                return jsonify({"code": 400, "error": "缺少参数"})

            result = _qq_api_post("/checkQQLoginQr", {"ptqrtoken": ptqrtoken, "qrsig": qrsig})
            response = result.get("response", result)
            is_ok = response.get("isOk", False)
            message = response.get("message", "")

            if is_ok:
                session = response.get("session", {})
                cookie_str = session.get("cookie", "") if isinstance(session, dict) else ""
                if cookie_str:
                    _save_qq_cookie(cookie_str, session=session, source="login")
                    logger.info("[QQ账号] 扫码登录成功，Credential已保存并启用自动续期")
                else:
                    logger.warning("[QQ账号] 扫码登录响应未包含Cookie")
                return jsonify({"code": 200, "status": "success", "message": "登录成功"})
            elif "已扫码" in str(message) or "授权" in str(message):
                return jsonify({"code": 200, "status": "scanned", "message": "已扫码，请在手机上确认"})
            elif "过期" in str(message):
                return jsonify({"code": 200, "status": "expired", "message": "二维码已过期，请刷新"})
            else:
                return jsonify({"code": 200, "status": "waiting", "message": "等待扫码"})
        except Exception as e:
            logger.error("[QQ账号] 检查扫码状态异常: %s", type(e).__name__)
            return jsonify({"code": 500, "error": "QQ音乐账号操作失败"}), 500

    @app.route('/api/qq/account/profile', methods=['GET'])
    def qq_account_profile():
        """获取QQ音乐用户详情"""
        try:
            status = ensure_qq_credential(force_refresh=False, reason="account-profile")
            if not status.get("valid"):
                return jsonify({"code": 401, "error": "未登录或登录凭证已失效"})
            try:
                from .qq_utils import get_qq_user_avatar
            except ImportError:
                from qq_utils import get_qq_user_avatar
            uin = status.get("uin", "")
            avatar = get_qq_user_avatar(uin)
            return jsonify({
                "code": 200,
                "uin": uin,
                "avatar": avatar,
                "nickname": f"QQ用户{uin[-4:]}" if uin else "QQ用户",
            })
        except Exception as e:
            logger.error("[QQ账号] 获取详情异常: %s", type(e).__name__)
            return jsonify({"code": 500, "error": "QQ音乐账号操作失败"}), 500

    @app.route('/api/qq/account/playlists', methods=['GET'])
    def qq_account_playlists():
        """获取QQ音乐用户歌单"""
        try:
            offset = _parse_page_arg(
                "offset", 0, 0, MAX_ACCOUNT_PAGE_OFFSET
            )
            limit = _parse_page_arg(
                "limit", 30, 1, MAX_ACCOUNT_PAGE_LIMIT
            )
            status = ensure_qq_credential(force_refresh=False, reason="account-playlists")
            if not status.get("valid"):
                return jsonify({"code": 401, "error": "未登录或登录凭证已失效"})
            try:
                from .qq_utils import get_qq_user_playlists
            except ImportError:
                from qq_utils import get_qq_user_playlists
            uin = status.get("uin", "")
            playlists = get_qq_user_playlists(uin, offset, limit)
            return jsonify({"code": 200, "playlists": playlists, "total": len(playlists)})
        except ValueError:
            return jsonify({"code": 400, "error": "分页参数无效"}), 400
        except Exception as e:
            logger.error("[QQ账号] 获取歌单异常: %s", type(e).__name__)
            return jsonify({"code": 500, "error": "QQ音乐账号操作失败"}), 500

    @app.route('/api/qq/account/cookie', methods=['POST'])
    def qq_account_save_cookie():
        """手动保存QQ音乐Cookie，同时构建可续期Credential。"""
        try:
            data = request.json or {}
            cookie = data.get("cookie")
            credential = _save_qq_cookie(cookie, source="manual")
            return jsonify({
                "code": 200,
                "message": "Cookie保存成功，自动续期已启用",
                "refresh_supported": bool(
                    (credential.get("refresh_token") and credential.get("refresh_key"))
                    or str(credential.get("musickey") or "").startswith(("Q_H_L", "W_X"))
                ),
            })
        except ValueError as e:
            return jsonify({"code": 400, "error": str(e)}), 400
        except Exception as e:
            logger.error("[QQ账号] 保存cookie异常: %s", type(e).__name__)
            return jsonify({"code": 500, "error": "QQ音乐账号操作失败"}), 500

    @app.route('/api/qq/account/logout', methods=['POST'])
    def qq_account_logout():
        """退出QQ音乐登录并清除Cookie/Credential。"""
        try:
            _clear_qq_cookie()
            logger.info("[QQ账号] 已退出登录并清理本地Credential")
            return jsonify({"code": 200, "message": "已退出QQ音乐登录"})
        except Exception as e:
            logger.error("[QQ账号] 退出异常: %s", type(e).__name__)
            return jsonify({"code": 500, "error": "QQ音乐账号操作失败"}), 500
