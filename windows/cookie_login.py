import os
import sys
import json
import time
import webbrowser
from typing import Dict, Any

import requests

try:
    from .config import MUSIC_API_PORT
    from .secure_storage import secure_write_bytes, secure_write_text
except ImportError:
    from config import MUSIC_API_PORT
    from secure_storage import secure_write_bytes, secure_write_text


API_BASE = f"http://127.0.0.1:{MUSIC_API_PORT}"
COOKIE_DIR = os.path.join(os.path.dirname(__file__), "Cookie")
COOKIE_JSON_PATH = os.path.join(COOKIE_DIR, "cookies.json")
COOKIE_TXT_PATH = os.path.join(COOKIE_DIR, "cookie.txt")


def ensure_cookie_dir():
    if not os.path.exists(COOKIE_DIR):
        os.makedirs(COOKIE_DIR, exist_ok=True)


def save_cookies(cookies: Dict[str, Any]):
    ensure_cookie_dir()
    secure_write_text(
        COOKIE_JSON_PATH,
        json.dumps(cookies, ensure_ascii=False, indent=2),
    )

    # 同时生成常见的 header Cookie 文本
    cookie_str = "; ".join([f"{k}={v}" for k, v in cookies.items()])
    secure_write_text(COOKIE_TXT_PATH, cookie_str)

    print(f"已保存 Cookie 到: {COOKIE_JSON_PATH} 和 {COOKIE_TXT_PATH}")


def get_qr_key() -> str:
    url = f"{API_BASE}/login/qr/key"
    r = requests.get(
        url,
        params={"timestamp": int(time.time() * 1000)},
        timeout=10,
        allow_redirects=False,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 200:
        raise RuntimeError(f"获取key失败 code={data.get('code', '?')}")
    return data["data"]["unikey"]


def get_qr_payload(key: str) -> Dict[str, Any]:
    # 返回包含 qrimg(base64) 与 qrurl 的数据
    url = f"{API_BASE}/login/qr/create"
    r = requests.get(
        url,
        params={"key": key, "qrimg": "true", "type": 1, "timestamp": int(time.time() * 1000)},
        timeout=10,
        allow_redirects=False,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 200:
        raise RuntimeError(f"获取二维码失败 code={data.get('code', '?')}")
    return data.get("data", {})


def check_qr_status(key: str) -> Dict[str, Any]:
    url = f"{API_BASE}/login/qr/check"
    r = requests.get(
        url,
        params={"key": key, "timestamp": int(time.time() * 1000)},
        timeout=10,
        allow_redirects=False,
    )
    r.raise_for_status()
    return r.json()


def get_login_status() -> Dict[str, Any]:
    url = f"{API_BASE}/login/status"
    r = requests.get(url, timeout=10, allow_redirects=False)
    r.raise_for_status()
    return r.json()


def extract_cookies_from_response(resp: requests.Response) -> Dict[str, str]:
    cookies = {}
    for k, v in resp.cookies.items():
        cookies[k] = v
    return cookies


def main():
    print(f"使用 API: {API_BASE}")
    ensure_cookie_dir()
    qr_path = os.path.join(COOKIE_DIR, "qr.png")

    def cleanup_qr_file():
        try:
            if os.path.isfile(qr_path):
                os.remove(qr_path)
        except OSError:
            pass

    import atexit
    atexit.register(cleanup_qr_file)

    try:
        key = get_qr_key()
    except Exception as e:
        print(f"获取二维码key失败: {type(e).__name__}")
        sys.exit(1)

    try:
        qr_data = get_qr_payload(key)
        print("请使用网易云音乐App扫码登录...")

        # 优先使用 base64 图片，落地为本地文件并打开，避免跳转到官网
        qrimg = qr_data.get("qrimg")  # 可能是 data:image/png;base64,XXXX
        opened = False
        if (
            isinstance(qrimg, str)
            and qrimg.startswith("data:image/png;base64,")
            and len(qrimg) <= 2 * 1024 * 1024
        ):
            import base64
            _, b64 = qrimg.split(",", 1)
            img_bytes = base64.b64decode(b64, validate=True)
            if len(img_bytes) > 1024 * 1024:
                raise ValueError("二维码图片过大")
            ensure_cookie_dir()
            secure_write_bytes(qr_path, img_bytes)
            try:
                webbrowser.open(f"file:///{qr_path}")
                opened = True
                print(f"已在本地打开二维码图片: {qr_path}")
            except Exception:
                pass

        if not opened:
            # 兜底：服务只返回 qrurl 时也在本机生成图片，避免泄露登录链接。
            qrurl = qr_data.get("qrurl")
            if isinstance(qrurl, str) and 0 < len(qrurl) <= 4096:
                try:
                    import io
                    import qrcode

                    image = qrcode.make(qrurl, border=2)
                    buffer = io.BytesIO()
                    image.save(buffer, format="PNG")
                    secure_write_bytes(qr_path, buffer.getvalue())
                    webbrowser.open(f"file:///{qr_path}")
                    opened = True
                    print(f"已在本地打开二维码图片: {qr_path}")
                except Exception:
                    pass
        if not opened:
            raise RuntimeError("本机API未返回可用二维码")
    except Exception as e:
        print(f"获取二维码失败: {type(e).__name__}")
        sys.exit(1)

    # 轮询登录状态
    login_cookies: Dict[str, str] = {}
    start = time.time()
    while True:
        try:
            status = check_qr_status(key)
        except Exception as e:
            print(f"检查二维码状态失败: {type(e).__name__}")
            time.sleep(2)
            continue

        code = status.get("code")
        if code == 802:
            print("已扫码，等待确认...")
        elif code == 801:
            print("等待扫码...")
        elif code == 803:
            print("登录成功！正在获取 Cookie...")
            # 803 通常会在响应中包含 cookie 或者需要再调 login/status
            try:
                # 尝试从 login/status 获取 Cookie（若服务实现支持）
                resp = requests.get(f"{API_BASE}/login/status", timeout=10, allow_redirects=False)
                resp.raise_for_status()
                login_cookies = extract_cookies_from_response(resp)
            except Exception:
                pass

            # 兜底：从当前会话或 qr/check 响应中提取（若 Set-Cookie 在其中）
            if not login_cookies:
                # 使用一个会话再请求一次，以捕获 Set-Cookie
                with requests.Session() as s:
                    s.get(f"{API_BASE}/login/status", timeout=10, allow_redirects=False)
                    login_cookies = {k: v for k, v in s.cookies.items()}

            # 再兜底：部分服务会把 cookie 放在 803 的返回体中
            if not login_cookies:
                # 尝试读取 status 中的 cookie 字段
                if isinstance(status, dict):
                    cookie_str = status.get("cookie") or (status.get("data") or {}).get("cookie")
                    if isinstance(cookie_str, str) and cookie_str:
                        # 解析为字典
                        parts = [p.strip() for p in cookie_str.split(";") if p.strip()]
                        for p in parts:
                            if "=" in p:
                                k, v = p.split("=", 1)
                                login_cookies[k.strip()] = v.strip()

            if not login_cookies:
                print("未能自动提取 Cookie，请检查 API 服务是否返回 Set-Cookie。")
                sys.exit(2)

            save_cookies(login_cookies)
            break
        else:
            # 其他状态或二维码过期
            msg = status.get("message") or status.get("msg") or "状态更新"
            msg = str(msg).replace("\r", " ").replace("\n", " ")[:160]
            print(f"状态: {code} - {msg}")
            if code in (800,):  # 二维码过期
                print("二维码已过期，请重试。")
                sys.exit(3)

        # 超时控制
        if time.time() - start > 180:
            print("登录超时，请重试。")
            sys.exit(4)
        time.sleep(2)


if __name__ == "__main__":
    main()


