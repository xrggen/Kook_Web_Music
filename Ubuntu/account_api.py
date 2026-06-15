"""网易云账号管理 API 路由 — 代理请求到本地 Node.js API"""
import os
import json
import logging
import requests
from flask import jsonify, request

logger = logging.getLogger(__name__)

MUSIC_API_BASE = "http://localhost:3000"
COOKIE_TXT_PATH = os.path.join(os.path.dirname(__file__), "Cookie", "cookie.txt")
COOKIE_JSON_PATH = os.path.join(os.path.dirname(__file__), "Cookie", "cookies.json")


def _load_cookie():
    """从cookie.txt加载Cookie字符串"""
    try:
        if os.path.exists(COOKIE_TXT_PATH):
            with open(COOKIE_TXT_PATH, "r", encoding="utf-8") as f:
                return f.read().strip()
    except Exception:
        pass
    return ""


def _save_cookie(cookie_str):
    """保存Cookie字符串到文件"""
    os.makedirs(os.path.dirname(COOKIE_TXT_PATH), exist_ok=True)
    with open(COOKIE_TXT_PATH, "w", encoding="utf-8") as f:
        f.write(cookie_str)


def _clear_cookie():
    """清除Cookie文件"""
    try:
        if os.path.exists(COOKIE_TXT_PATH):
            os.remove(COOKIE_TXT_PATH)
        if os.path.exists(COOKIE_JSON_PATH):
            os.remove(COOKIE_JSON_PATH)
    except Exception:
        pass


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
        r = requests.get(url, params=params, headers=headers, timeout=15)
        result = r.json()
        result["_http_status"] = r.status_code
        code = result.get("code", "?")
        logger.info(f"[账号API] 状态={r.status_code} code={code}")
        if r.cookies:
            _merge_save_cookies(r.cookies)
        return result
    except Exception as e:
        logger.error(f"[账号API] GET {path} 失败: {e}")
        return {"code": -1, "message": str(e)}


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
        r = requests.post(url, data=data or {}, headers=headers, timeout=20)
        result = r.json()
        result["_http_status"] = r.status_code
        code = result.get("code", "?")
        logger.info(f"[账号API] 状态={r.status_code} code={code}")
        if r.cookies:
            _merge_save_cookies(r.cookies)
        return result
    except Exception as e:
        logger.error(f"[账号API] POST {path} 失败: {e}")
        return {"code": -1, "message": str(e)}


def register_account_routes(app):
    """注册账号管理相关路由"""

    @app.route("/account")
    def account_page():
        """账号管理页面"""
        from flask import render_template
        return render_template("account.html")

    @app.route("/api/account/status")
    def account_status():
        """获取登录状态"""
        result = _api_get("/login/status")
        # login_status 返回 code:200 且包含 account/profile 信息时表示已登录
        return jsonify(result)

    @app.route("/api/account/detail")
    def account_detail():
        """获取用户详情"""
        uid = request.args.get("uid", "")
        if not uid:
            return jsonify({"code": -1, "message": "缺少uid参数"})
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
        uid = request.args.get("uid", "")
        limit = request.args.get("limit", 30)
        offset = request.args.get("offset", 0)
        if not uid:
            return jsonify({"code": -1, "message": "缺少uid参数"})
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
        # 803 = 登录成功，body中可能带cookie字段
        if result.get("code") == 803:
            cookie_str = result.get("cookie", "")
            if cookie_str:
                _save_cookie(cookie_str)
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
        _clear_cookie()
        return jsonify(result)

    @app.route("/api/account/cookie", methods=["POST"])
    def account_save_cookie():
        """手动保存Cookie"""
        data = request.json or {}
        cookie_str = data.get("cookie", "")
        if cookie_str:
            _save_cookie(cookie_str)
            return jsonify({"code": 200, "message": "Cookie已保存"})
        return jsonify({"code": -1, "message": "Cookie内容为空"})
