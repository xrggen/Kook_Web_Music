import os
import json
import logging
import requests
from flask import jsonify, request

from config import QQ_MUSIC_API_BASE, QQ_COOKIE_TXT_PATH

logger = logging.getLogger(__name__)


def _load_qq_cookie():
    try:
        if os.path.exists(QQ_COOKIE_TXT_PATH):
            with open(QQ_COOKIE_TXT_PATH, "r", encoding="utf-8") as f:
                return f.read().strip()
    except Exception:
        pass
    return ""


def _save_qq_cookie(cookie_str):
    os.makedirs(os.path.dirname(QQ_COOKIE_TXT_PATH), exist_ok=True)
    with open(QQ_COOKIE_TXT_PATH, "w", encoding="utf-8") as f:
        f.write(cookie_str)
    # 同步到 qq-music-api 的全局 cookie 配置
    try:
        import re
        uin_match = re.search(r'uin=o?(\d+)', cookie_str)
        uin = uin_match.group(1) if uin_match else ""
        info_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "qq-music-api", "config", "user-info.json"
        )
        if os.path.exists(os.path.dirname(info_path)):
            with open(info_path, "w", encoding="utf-8") as f:
                json.dump({"loginUin": uin, "cookie": cookie_str}, f, ensure_ascii=False)
            logger.info("[QQ账号] 已同步cookie到 user-info.json")
    except Exception as e:
        logger.warning(f"[QQ账号] 同步user-info.json失败: {e}")


def _clear_qq_cookie():
    try:
        if os.path.exists(QQ_COOKIE_TXT_PATH):
            os.remove(QQ_COOKIE_TXT_PATH)
    except Exception as e:
        logger.warning(f"[QQ账号] 删除cookie文件失败: {e}")


def _qq_api_get(path, **params):
    cookie = _load_qq_cookie()
    if cookie:
        params["cookie"] = cookie
    url = f"{QQ_MUSIC_API_BASE}{path}"
    try:
        res = requests.get(url, params=params, timeout=15)
        return res.json()
    except Exception as e:
        logger.error(f"[QQ账号API] GET {path} 异常: {e}")
        return {"error": str(e)}


def _qq_api_post(path, data=None):
    cookie = _load_qq_cookie()
    params = {}
    if cookie:
        params["cookie"] = cookie
    url = f"{QQ_MUSIC_API_BASE}{path}"
    try:
        res = requests.post(url, params=params, json=data, timeout=15)
        return res.json()
    except Exception as e:
        logger.error(f"[QQ账号API] POST {path} 异常: {e}")
        return {"error": str(e)}


def register_qq_account_routes(app):
    """注册QQ音乐账号管理路由"""

    @app.route('/api/qq/account/status', methods=['GET'])
    def qq_account_status():
        """获取QQ音乐登录状态（含Cookie存活验证）"""
        try:
            from qq_utils import verify_qq_cookie
            result = verify_qq_cookie()
            return jsonify({
                "code": 200,
                "logged_in": result["valid"],
                "uin": result["uin"],
                "message": result["message"],
                "need_relogin": result["need_relogin"],
                "expires_in": result.get("expires_in", -1),
            })
        except Exception as e:
            logger.error(f"[QQ账号] 状态查询异常: {e}")
            return jsonify({"code": 500, "error": str(e)})

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
            logger.error(f"[QQ账号] 创建二维码异常: {e}")
            return jsonify({"code": 500, "error": str(e)})

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
                cookie_str = session.get("cookie", "")
                if cookie_str:
                    _save_qq_cookie(cookie_str)
                    logger.info("[QQ账号] 扫码登录成功，cookie已保存")
                return jsonify({"code": 200, "status": "success", "message": "登录成功"})
            elif "已扫码" in str(message) or "授权" in str(message):
                return jsonify({"code": 200, "status": "scanned", "message": "已扫码，请在手机上确认"})
            elif "过期" in str(message):
                return jsonify({"code": 200, "status": "expired", "message": "二维码已过期，请刷新"})
            else:
                return jsonify({"code": 200, "status": "waiting", "message": "等待扫码"})
        except Exception as e:
            logger.error(f"[QQ账号] 检查扫码状态异常: {e}")
            return jsonify({"code": 500, "error": str(e)})

    @app.route('/api/qq/account/profile', methods=['GET'])
    def qq_account_profile():
        """获取QQ音乐用户详情"""
        try:
            from qq_utils import verify_qq_cookie, get_qq_user_avatar
            vr = verify_qq_cookie()
            if not vr["valid"]:
                return jsonify({"code": 401, "error": "未登录或Cookie已失效"})
            uin = vr["uin"]
            avatar = get_qq_user_avatar(uin)
            return jsonify({
                "code": 200, "uin": uin, "avatar": avatar,
                "nickname": f"QQ用户{uin[-4:]}",
            })
        except Exception as e:
            logger.error(f"[QQ账号] 获取详情异常: {e}")
            return jsonify({"code": 500, "error": str(e)})

    @app.route('/api/qq/account/playlists', methods=['GET'])
    def qq_account_playlists():
        """获取QQ音乐用户歌单"""
        try:
            from qq_utils import verify_qq_cookie, get_qq_user_playlists
            vr = verify_qq_cookie()
            if not vr["valid"]:
                return jsonify({"code": 401, "error": "未登录或Cookie已失效"})
            uin = vr["uin"]
            offset = request.args.get("offset", 0, type=int)
            limit = request.args.get("limit", 30, type=int)
            pl = get_qq_user_playlists(uin, offset, limit)
            return jsonify({"code": 200, "playlists": pl, "total": len(pl)})
        except Exception as e:
            logger.error(f"[QQ账号] 获取歌单异常: {e}")
            return jsonify({"code": 500, "error": str(e)})

    @app.route('/api/qq/account/cookie', methods=['POST'])
    def qq_account_save_cookie():
        """手动保存QQ音乐Cookie"""
        try:
            data = request.json or {}
            cookie = data.get("cookie", "").strip()
            if not cookie:
                return jsonify({"code": 400, "error": "Cookie不能为空"})
            _save_qq_cookie(cookie)
            logger.info("[QQ账号] 手动保存cookie成功")
            return jsonify({"code": 200, "message": "Cookie保存成功"})
        except Exception as e:
            logger.error(f"[QQ账号] 保存cookie异常: {e}")
            return jsonify({"code": 500, "error": str(e)})

    @app.route('/api/qq/account/logout', methods=['POST'])
    def qq_account_logout():
        """退出QQ音乐登录"""
        try:
            _clear_qq_cookie()
            logger.info("[QQ账号] 已退出登录")
            return jsonify({"code": 200, "message": "已退出QQ音乐登录"})
        except Exception as e:
            logger.error(f"[QQ账号] 退出异常: {e}")
            return jsonify({"code": 500, "error": str(e)})
