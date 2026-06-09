import logging
from flask import jsonify, request

from bili_utils import (
    load_bili_cookie, save_bili_cookie, clear_bili_cookie,
    generate_bili_qr, poll_bili_qr, verify_bili_cookie,
    get_bili_user_info, get_bili_favorite_collections,
)

logger = logging.getLogger(__name__)


def register_bili_account_routes(app):
    """注册B站账号管理路由"""

    @app.route('/api/bili/account/status', methods=['GET'])
    def bili_account_status():
        """获取B站登录状态"""
        try:
            result = verify_bili_cookie()
            return jsonify({
                "code": 200,
                "logged_in": result.get("valid", False),
                "uid": result.get("uid", 0),
                "uname": result.get("uname", ""),
                "face": result.get("face", ""),
                "message": result.get("message", ""),
            })
        except Exception as e:
            logger.error(f"[Bili账号] 状态查询异常: {e}")
            return jsonify({"code": 500, "error": str(e)})

    @app.route('/api/bili/account/qr/create', methods=['POST'])
    def bili_account_qr_create():
        """生成B站登录二维码"""
        try:
            result = generate_bili_qr()
            if not result:
                return jsonify({"code": 500, "error": "生成二维码失败"})
            return jsonify({
                "code": 200,
                "qrcode": result["qrcode_b64"],
                "qrcode_key": result["qrcode_key"],
            })
        except Exception as e:
            logger.error(f"[Bili账号] 创建二维码异常: {e}")
            return jsonify({"code": 500, "error": str(e)})

    @app.route('/api/bili/account/qr/check', methods=['POST'])
    def bili_account_qr_check():
        """检查B站扫码状态"""
        try:
            data = request.json or {}
            qrcode_key = data.get("qrcode_key", "")
            if not qrcode_key:
                return jsonify({"code": 400, "error": "缺少qrcode_key"})
            result = poll_bili_qr(qrcode_key)
            return jsonify({
                "code": 200,
                "status": result.get("status", "waiting"),
                "message": result.get("message", ""),
            })
        except Exception as e:
            logger.error(f"[Bili账号] 检查扫码状态异常: {e}")
            return jsonify({"code": 500, "error": str(e)})

    @app.route('/api/bili/account/profile', methods=['GET'])
    def bili_account_profile():
        """获取B站用户详情"""
        try:
            user = get_bili_user_info()
            if not user:
                vr = verify_bili_cookie()
                if not vr["valid"]:
                    return jsonify({"code": 401, "error": "未登录或Cookie已失效"})
                return jsonify({"code": 200, "uid": vr["uid"], "uname": vr["uname"], "face": vr["face"]})
            return jsonify({
                "code": 200,
                "uid": user["uid"],
                "uname": user["uname"],
                "face": user["face"],
                "level": user.get("level", 0),
                "vip_type": user.get("vip_type", 0),
            })
        except Exception as e:
            logger.error(f"[Bili账号] 获取详情异常: {e}")
            return jsonify({"code": 500, "error": str(e)})

    @app.route('/api/bili/account/playlists', methods=['GET'])
    def bili_account_playlists():
        """获取B站收藏夹列表"""
        try:
            vr = verify_bili_cookie()
            if not vr["valid"]:
                return jsonify({"code": 401, "error": "未登录或Cookie已失效"})
            playlists = get_bili_favorite_collections()
            return jsonify({
                "code": 200,
                "playlists": [{
                    "id": str(pl["id"]),
                    "name": pl["title"],
                    "cover": pl.get("cover", ""),
                    "trackCount": pl.get("count", 0),
                    "playCount": 0,
                } for pl in playlists],
                "total": len(playlists),
            })
        except Exception as e:
            logger.error(f"[Bili账号] 获取收藏夹异常: {e}")
            return jsonify({"code": 500, "error": str(e)})

    @app.route('/api/bili/account/cookie', methods=['POST'])
    def bili_account_save_cookie():
        """手动保存B站Cookie (SESSDATA)"""
        try:
            data = request.json or {}
            cookie = data.get("cookie", "").strip()
            if not cookie:
                return jsonify({"code": 400, "error": "Cookie不能为空"})
            # 支持直接传入 SESSDATA 或完整 Cookie 串
            if not cookie.startswith("SESSDATA="):
                cookie = f"SESSDATA={cookie}"
            save_bili_cookie(cookie)
            logger.info("[Bili账号] 手动保存cookie成功")
            return jsonify({"code": 200, "message": "Cookie保存成功"})
        except Exception as e:
            logger.error(f"[Bili账号] 保存cookie异常: {e}")
            return jsonify({"code": 500, "error": str(e)})

    @app.route('/api/bili/account/logout', methods=['POST'])
    def bili_account_logout():
        """退出B站登录"""
        try:
            clear_bili_cookie()
            logger.info("[Bili账号] 已退出登录")
            return jsonify({"code": 200, "message": "已退出B站登录"})
        except Exception as e:
            logger.error(f"[Bili账号] 退出异常: {e}")
            return jsonify({"code": 500, "error": str(e)})
