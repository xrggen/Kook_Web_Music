import hashlib
import json
import logging
import os
import re
import sys
import threading
import time
from typing import Any, Dict, Optional

import requests

try:
    from .config import QQ_COOKIE_TXT_PATH, QQ_CREDENTIAL_PATH
    from .secure_storage import secure_read_text, secure_write_text
except ImportError:
    from config import QQ_COOKIE_TXT_PATH, QQ_CREDENTIAL_PATH
    from secure_storage import secure_read_text, secure_write_text

logger = logging.getLogger(__name__)
MAX_COOKIE_CHARS = 64 * 1024
MAX_CREDENTIAL_JSON_CHARS = 256 * 1024
COOKIE_KEY_RE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")

_STATE_LOCK = threading.RLock()
_REFRESH_LOCK = threading.Lock()
_MAINTENANCE_LOCK = threading.Lock()
_maintenance_thread = None


def _env_int(name: str, default: int, minimum: int) -> int:
    try:
        return max(minimum, int(os.getenv(name, default)))
    except (TypeError, ValueError):
        logger.warning("[QQ凭证] %s 配置无效，使用默认值 %s", name, default)
        return default


def _check_interval() -> int:
    return _env_int("QQ_CREDENTIAL_CHECK_INTERVAL", 10800, 900)


def _proactive_refresh_interval() -> int:
    return _env_int("QQ_CREDENTIAL_REFRESH_INTERVAL", 64800, 3600)


def _refresh_window() -> int:
    return _env_int("QQ_CREDENTIAL_REFRESH_WINDOW", 86400, 3600)


def _validate_cookie_string(cookie_str: str, allow_empty: bool = False) -> str:
    if not isinstance(cookie_str, str):
        raise ValueError("QQ音乐Cookie必须是字符串")
    cookie_str = cookie_str.strip()
    if not cookie_str and not allow_empty:
        raise ValueError("QQ音乐Cookie不能为空")
    if len(cookie_str) > MAX_COOKIE_CHARS:
        raise ValueError("QQ音乐Cookie过长")
    if any(char in cookie_str for char in ("\r", "\n", "\0")):
        raise ValueError("QQ音乐Cookie包含非法控制字符")
    return cookie_str


def parse_cookie_string(cookie_str: str) -> Dict[str, str]:
    cookies: Dict[str, str] = {}
    try:
        cookie_str = _validate_cookie_string(cookie_str, allow_empty=True)
    except ValueError:
        return cookies
    for part in cookie_str.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip()
        if key and COOKIE_KEY_RE.fullmatch(key):
            cookies[key] = value.strip()
    return cookies


def serialize_cookie(cookies: Dict[str, str]) -> str:
    parts = []
    for key, value in cookies.items():
        key = str(key).strip()
        value = str(value).strip()
        if not COOKIE_KEY_RE.fullmatch(key):
            raise ValueError("QQ音乐Cookie键名无效")
        if ";" in value or any(char in value for char in ("\r", "\n", "\0")):
            raise ValueError("QQ音乐Cookie值包含非法字符")
        parts.append(f"{key}={value}")
    return _validate_cookie_string("; ".join(parts), allow_empty=True)


def _first(cookies: Dict[str, str], *keys: str) -> str:
    for key in keys:
        value = cookies.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _normalize_uin(value: Any) -> str:
    match = re.search(r"(\d+)", str(value or ""))
    return match.group(1) if match else ""


def _epoch_seconds(value: Any) -> int:
    try:
        ts = int(float(value))
    except (TypeError, ValueError):
        return 0
    if ts > 10_000_000_000:
        ts //= 1000
    return ts


def _read_text(path: str) -> str:
    try:
        return _validate_cookie_string(
            secure_read_text(path, max_chars=MAX_COOKIE_CHARS + 1),
            allow_empty=True,
        )
    except (OSError, UnicodeError, ValueError):
        return ""


def _atomic_write_text(path: str, content: str) -> None:
    secure_write_text(path, content)


def _load_json(path: str) -> Dict[str, Any]:
    try:
        raw = secure_read_text(path, max_chars=MAX_CREDENTIAL_JSON_CHARS + 1)
        if len(raw) > MAX_CREDENTIAL_JSON_CHARS:
            return {}
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, UnicodeError):
        return {}


def _key_expiry_from_cookie(cookies: Dict[str, str]) -> int:
    """只使用 musickey 自身过期时间，不能拿短寿命 access token 判定整套登录失效。"""
    candidates = []
    for key in (
        "qqmusic_key_expiresAt",
        "musickey_expiresAt",
        "qm_keyst_expiresAt",
    ):
        value = _epoch_seconds(cookies.get(key))
        if value > 0:
            candidates.append(value)
    return min(candidates) if candidates else 0


def _credential_from_cookie(
    cookie_str: str,
    previous: Optional[Dict[str, Any]] = None,
    source: str = "cookie",
    mark_refreshed: bool = False,
) -> Dict[str, Any]:
    previous = dict(previous or {})
    cookies = parse_cookie_string(cookie_str)
    now = int(time.time())

    uin = _normalize_uin(_first(cookies, "uin", "musicid", "wxuin"))
    previous_uin = _normalize_uin(previous.get("uin"))
    same_account = bool(uin and previous_uin and uin == previous_uin)
    carry = previous if same_account else {}

    musickey = _first(cookies, "qqmusic_key", "qm_keyst", "musickey") or str(carry.get("musickey") or "")
    refresh_token = _first(
        cookies,
        "psrf_qqrefresh_token",
        "refresh_token",
        "qqmusic_refresh_token",
    ) or str(carry.get("refresh_token") or "")
    refresh_key = _first(
        cookies,
        "psrf_qqrefresh_key",
        "refresh_key",
        "qqmusic_refresh_key",
    ) or str(carry.get("refresh_key") or "")
    access_token = _first(
        cookies,
        "psrf_qqaccess_token",
        "access_token",
        "qqmusic_access_token",
    ) or str(carry.get("access_token") or "")
    openid = _first(cookies, "psrf_qqopenid", "openid") or str(carry.get("openid") or "")
    unionid = _first(cookies, "psrf_qqunionid", "unionid") or str(carry.get("unionid") or "")

    try:
        login_type = int(_first(cookies, "login_type", "loginType") or carry.get("login_type") or 0)
    except (TypeError, ValueError):
        login_type = 0
    if not login_type and musickey:
        login_type = 1 if musickey.startswith("W_X") else 2

    key_expires_at = _key_expiry_from_cookie(cookies)
    if not key_expires_at:
        key_expires_at = _epoch_seconds(carry.get("key_expires_at"))
    key_expires_in = max(0, key_expires_at - now) if key_expires_at else int(carry.get("key_expires_in") or 0)
    create_time = _epoch_seconds(
        _first(cookies, "musickeyCreateTime", "musickey_create_time")
        or carry.get("musickey_create_time")
    )
    if not create_time and key_expires_at and key_expires_in:
        create_time = max(0, key_expires_at - key_expires_in)

    access_expires_at = _epoch_seconds(
        _first(cookies, "psrf_access_token_expiresAt", "access_token_expiresAt")
        or carry.get("access_expires_at")
    )

    refreshed_at = int(carry.get("refreshed_at") or 0)
    if mark_refreshed:
        refreshed_at = now

    return {
        "version": 1,
        "source": source,
        "uin": uin or previous_uin,
        "str_musicid": _first(cookies, "str_musicid") or str(carry.get("str_musicid") or uin or previous_uin),
        "musickey": musickey,
        "refresh_token": refresh_token,
        "refresh_key": refresh_key,
        "access_token": access_token,
        "access_expires_at": access_expires_at,
        "openid": openid,
        "unionid": unionid,
        "login_type": login_type,
        "musickey_create_time": create_time,
        "key_expires_in": key_expires_in,
        "key_expires_at": key_expires_at,
        "cookie": cookie_str,
        "updated_at": now,
        "refreshed_at": refreshed_at,
        "last_refresh_attempt": int(carry.get("last_refresh_attempt") or 0),
        "last_refresh_error": str(carry.get("last_refresh_error") or ""),
        "refresh_failures": int(carry.get("refresh_failures") or 0),
    }


def _invalidate_legacy_verify_cache() -> None:
    """旧 Bot 命令仍经 qq_utils.verify_qq_cookie；凭证变化后立即清掉它的短期缓存。"""
    candidates = ["qq_utils"]
    if __package__:
        candidates.append(f"{__package__}.qq_utils")
    for name in candidates:
        module = sys.modules.get(name)
        cache = getattr(module, "_verify_cache", None) if module is not None else None
        if isinstance(cache, dict):
            cache["ts"] = 0
            cache["result"] = None


def _persist(credential: Dict[str, Any]) -> Dict[str, Any]:
    """原子保存 Credential 与兼容 Cookie。

    psrf_access_token_expiresAt 只是 access token 的寿命，不代表 qqmusic_key/musickey
    已失效。旧 verify_qq_cookie 会把它误当作整套登录态的最早过期时间，因此兼容
    Cookie 中移除这个客户端时间戳；真实值单独保存在 credential JSON 里。
    """
    stored = dict(credential)
    cookies = parse_cookie_string(str(stored.get("cookie") or ""))
    if not stored.get("access_expires_at"):
        stored["access_expires_at"] = _epoch_seconds(cookies.get("psrf_access_token_expiresAt"))
    cookies.pop("psrf_access_token_expiresAt", None)
    cookies.pop("access_token_expiresAt", None)
    cookie_str = serialize_cookie(cookies)
    stored["cookie"] = cookie_str

    _atomic_write_text(QQ_COOKIE_TXT_PATH, cookie_str)
    _atomic_write_text(
        QQ_CREDENTIAL_PATH,
        json.dumps(stored, ensure_ascii=False, indent=2, sort_keys=True),
    )
    _invalidate_legacy_verify_cache()
    return stored


def save_qq_cookie(cookie_str: str, source: str = "login") -> Dict[str, Any]:
    """保存 Cookie 并提取可续期 Credential。兼容旧 cookie.txt 存储。"""
    cookie_str = _validate_cookie_string(cookie_str)
    with _STATE_LOCK:
        previous = _load_json(QQ_CREDENTIAL_PATH)
        mark_refreshed = source in {"login", "manual", "refresh"}
        credential = _credential_from_cookie(
            cookie_str,
            previous=previous,
            source=source,
            mark_refreshed=mark_refreshed,
        )
        return _persist(credential)


def load_qq_credential() -> Dict[str, Any]:
    """加载 Credential；首次运行时自动从旧 qq_cookie.txt 迁移。"""
    with _STATE_LOCK:
        credential = _load_json(QQ_CREDENTIAL_PATH)
        cookie_str = _read_text(QQ_COOKIE_TXT_PATH)

        if not cookie_str and credential.get("cookie"):
            try:
                cookie_str = _validate_cookie_string(credential.get("cookie"))
            except ValueError:
                cookie_str = ""
                credential["cookie"] = ""
            if cookie_str:
                _atomic_write_text(QQ_COOKIE_TXT_PATH, cookie_str)

        if cookie_str:
            if not credential:
                credential = _credential_from_cookie(
                    cookie_str,
                    source="migration",
                    mark_refreshed=False,
                )
                credential = _persist(credential)
            elif cookie_str != str(credential.get("cookie") or ""):
                credential = _credential_from_cookie(
                    cookie_str,
                    previous=credential,
                    source="external-update",
                    mark_refreshed=False,
                )
                credential = _persist(credential)
        return credential


def load_qq_cookie() -> str:
    credential = load_qq_credential()
    try:
        return _validate_cookie_string(
            credential.get("cookie") or _read_text(QQ_COOKIE_TXT_PATH),
            allow_empty=True,
        )
    except ValueError:
        return ""


def clear_qq_credential() -> None:
    with _STATE_LOCK:
        failures = 0
        for path in (QQ_COOKIE_TXT_PATH, QQ_CREDENTIAL_PATH):
            try:
                os.remove(path)
            except FileNotFoundError:
                continue
            except OSError as exc:
                failures += 1
                logger.warning("[QQ凭证] 删除凭据失败: %s", type(exc).__name__)
        _invalidate_legacy_verify_cache()
        if failures:
            raise OSError("未能完整删除QQ音乐登录凭据")


def _qqmusic_sign(param_str: str) -> str:
    k1 = {str(i): i for i in range(10)}
    k1.update({"A": 10, "B": 11, "C": 12, "D": 13, "E": 14, "F": 15})
    l1 = [212, 45, 80, 68, 195, 163, 163, 203, 157, 220, 254, 91, 204, 79, 104, 6]
    table = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/="

    md5_str = hashlib.md5(param_str.encode("utf-8")).hexdigest().upper()
    t1 = "".join(md5_str[i] for i in [21, 4, 9, 26, 16, 20, 27, 30])
    t3 = "".join(md5_str[i] for i in [18, 11, 3, 2, 1, 7, 6, 25])

    values = []
    for i in range(16):
        x1 = k1[md5_str[i * 2]]
        x2 = k1[md5_str[i * 2 + 1]]
        values.append((x1 * 16 ^ x2) ^ l1[i])

    encoded = []
    for i in range(6):
        if i == 5:
            encoded.append(table[values[-1] >> 2])
            encoded.append(table[(values[-1] & 3) << 4])
        else:
            encoded.append(table[values[i * 3] >> 2])
            encoded.append(table[(values[i * 3 + 1] >> 4) ^ ((values[i * 3] & 3) << 4)])
            encoded.append(table[(values[i * 3 + 2] >> 6) ^ ((values[i * 3 + 1] & 15) << 2)])
            encoded.append(table[63 & values[i * 3 + 2]])

    middle = re.sub(r"[\\/+]+", "", "".join(encoded))
    return "zzb" + (t1 + middle + t3).lower()


def _signed_request(host: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    sign = _qqmusic_sign(body)
    response = requests.post(
        f"{host}?sign={sign}&_={int(time.time() * 1000)}",
        data=body.encode("utf-8"),
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Content-Type": "application/json",
            "Referer": "https://y.qq.com/",
        },
        timeout=(5, 15),
        allow_redirects=False,
    )
    response.raise_for_status()
    data = response.json()
    req = data.get("req1") or data.get("req_0") or {}
    code = req.get("code")
    if code not in (0, "0"):
        raise RuntimeError(f"QQ音乐刷新接口返回 code={code}")
    result = req.get("data")
    if not isinstance(result, dict):
        raise RuntimeError("QQ音乐刷新接口未返回凭证数据")
    return result


def _full_refresh_payload(credential: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not credential.get("refresh_token") or not credential.get("refresh_key"):
        return None
    uin = _normalize_uin(credential.get("uin"))
    if not uin:
        return None
    login_type = int(credential.get("login_type") or 2)
    param = {
        "openid": str(credential.get("openid") or ""),
        "access_token": str(credential.get("access_token") or ""),
        "refresh_token": str(credential.get("refresh_token") or ""),
        "expired_in": int(credential.get("access_expires_at") or credential.get("key_expires_at") or 0),
        "str_musicid": str(credential.get("str_musicid") or uin),
        "musicid": int(uin),
        "musickey": str(credential.get("musickey") or ""),
        "unionid": str(credential.get("unionid") or ""),
        "refresh_key": str(credential.get("refresh_key") or ""),
        "loginMode": 2,
    }
    return {
        "comm": {
            "fPersonality": "0",
            "tmeLoginType": str(login_type),
            "tmeLoginMethod": "1",
            "qq": "",
            "authst": "",
            "ct": "11",
            "cv": "12080008",
            "v": "12080008",
            "tmeAppID": "qqmusic",
        },
        "req1": {
            "module": "music.login.LoginServer",
            "method": "Login",
            "param": param,
        },
    }


def _legacy_refresh(credential: Dict[str, Any]) -> Dict[str, Any]:
    uin = _normalize_uin(credential.get("uin"))
    musickey = str(credential.get("musickey") or "")
    if not uin or not musickey:
        raise RuntimeError("QQ音乐凭证缺少 uin 或 musickey")

    if musickey.startswith("Q_H_L"):
        payload = {
            "req1": {
                "module": "QQConnectLogin.LoginServer",
                "method": "QQLogin",
                "param": {
                    "expired_in": 7776000,
                    "musicid": int(uin),
                    "musickey": musickey,
                },
            }
        }
        return _signed_request("https://u6.y.qq.com/cgi-bin/musics.fcg", payload)

    if musickey.startswith("W_X"):
        payload = {
            "comm": {
                "fPersonality": "0",
                "tmeLoginType": "1",
                "tmeLoginMethod": "1",
                "qq": "",
                "authst": "",
                "ct": "11",
                "cv": "12080008",
                "v": "12080008",
                "tmeAppID": "qqmusic",
            },
            "req1": {
                "module": "music.login.LoginServer",
                "method": "Login",
                "param": {
                    "code": "",
                    "openid": str(credential.get("openid") or ""),
                    "refresh_token": str(credential.get("refresh_token") or ""),
                    "str_musicid": str(credential.get("str_musicid") or uin),
                    "musickey": musickey,
                    "unionid": str(credential.get("unionid") or ""),
                    "refresh_key": str(credential.get("refresh_key") or ""),
                    "loginMode": 2,
                },
            },
        }
        return _signed_request("https://u.y.qq.com/cgi-bin/musics.fcg", payload)

    raise RuntimeError("未知的 QQ音乐 musickey 格式")


def _response_value(data: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return None


def _apply_refresh_result(
    credential: Dict[str, Any],
    result: Dict[str, Any],
    reason: str,
) -> Dict[str, Any]:
    now = int(time.time())
    musickey = str(_response_value(result, "musickey", "qqmusic_key") or credential.get("musickey") or "")
    if not musickey:
        raise RuntimeError("刷新成功响应中缺少 musickey")

    uin = _normalize_uin(_response_value(result, "musicid", "uin") or credential.get("uin"))
    key_expires_in = int(_response_value(result, "keyExpiresIn", "key_expires_in") or 7776000)
    create_time = _epoch_seconds(_response_value(result, "musickeyCreateTime", "musickey_create_time")) or now
    key_expires_at = create_time + max(3600, key_expires_in)

    cookies = parse_cookie_string(str(credential.get("cookie") or ""))
    old_uin = cookies.get("uin", "")
    cookies["uin"] = f"o{uin}" if old_uin.startswith("o") else uin
    cookies["qqmusic_key"] = musickey
    cookies["qm_keyst"] = musickey
    if "musickey" in cookies:
        cookies["musickey"] = musickey
    cookies["qqmusic_key_expiresAt"] = str(key_expires_at)
    cookies["musickey_expiresAt"] = str(key_expires_at)

    field_map = {
        "refresh_token": ("refresh_token", "psrf_qqrefresh_token"),
        "refresh_key": ("refresh_key", "psrf_qqrefresh_key"),
        "access_token": ("access_token", "psrf_qqaccess_token"),
        "openid": ("openid", "psrf_qqopenid"),
        "unionid": ("unionid", "psrf_qqunionid"),
    }
    updated = dict(credential)
    for target, (response_key, cookie_key) in field_map.items():
        value = _response_value(result, response_key, target)
        if value not in (None, ""):
            updated[target] = str(value)
            cookies[cookie_key] = str(value)

    access_expires_at = _epoch_seconds(
        _response_value(result, "expired_at", "expiredAt", "accessTokenExpiresAt", "access_token_expires_at")
    ) or int(credential.get("access_expires_at") or 0)

    try:
        login_type = int(_response_value(result, "loginType", "login_type") or credential.get("login_type") or 0)
    except (TypeError, ValueError):
        login_type = int(credential.get("login_type") or 0)

    updated.update({
        "version": 1,
        "source": "refresh",
        "uin": uin,
        "str_musicid": str(_response_value(result, "str_musicid", "strMusicid") or credential.get("str_musicid") or uin),
        "musickey": musickey,
        "access_expires_at": access_expires_at,
        "login_type": login_type or (1 if musickey.startswith("W_X") else 2),
        "musickey_create_time": create_time,
        "key_expires_in": key_expires_in,
        "key_expires_at": key_expires_at,
        "cookie": serialize_cookie(cookies),
        "updated_at": now,
        "refreshed_at": now,
        "last_refresh_attempt": now,
        "last_refresh_error": "",
        "refresh_failures": 0,
        "last_refresh_reason": reason,
    })
    return _persist(updated)


def refresh_qq_credential(reason: str = "manual") -> Dict[str, Any]:
    """刷新 QQ 音乐登录凭证。优先完整 refresh_token，失败后回退 musickey 续期。"""
    with _REFRESH_LOCK:
        credential = load_qq_credential()
        if not credential.get("uin") or not credential.get("musickey"):
            raise RuntimeError("未找到可刷新的QQ音乐登录凭证")

        errors = []
        full_payload = _full_refresh_payload(credential)
        if full_payload is not None:
            try:
                result = _signed_request("https://u.y.qq.com/cgi-bin/musics.fcg", full_payload)
                refreshed = _apply_refresh_result(credential, result, reason)
                logger.info("[QQ凭证] 完整 Credential 刷新成功，uin=%s reason=%s", refreshed.get("uin"), reason)
                return refreshed
            except Exception as exc:
                errors.append(f"credential refresh: {type(exc).__name__}")
                logger.warning(
                    "[QQ凭证] 完整 Credential 刷新失败，尝试 musickey fallback: %s",
                    type(exc).__name__,
                )

        try:
            result = _legacy_refresh(credential)
            refreshed = _apply_refresh_result(credential, result, reason)
            logger.info("[QQ凭证] musickey 刷新成功，uin=%s reason=%s", refreshed.get("uin"), reason)
            return refreshed
        except Exception as exc:
            errors.append(f"musickey refresh: {type(exc).__name__}")

        now = int(time.time())
        failed = dict(credential)
        failed["last_refresh_attempt"] = now
        failed["last_refresh_error"] = "; ".join(errors)
        failed["refresh_failures"] = int(failed.get("refresh_failures") or 0) + 1
        failed["updated_at"] = now
        _persist(failed)
        raise RuntimeError(failed["last_refresh_error"] or "QQ音乐凭证刷新失败")


def _credential_status(credential: Dict[str, Any]) -> Dict[str, Any]:
    now = int(time.time())
    uin = _normalize_uin(credential.get("uin"))
    musickey = str(credential.get("musickey") or "")
    expires_at = _epoch_seconds(credential.get("key_expires_at"))
    expires_in = expires_at - now if expires_at else -1
    has_auth = bool(uin and musickey)
    expired = bool(expires_at and expires_in <= 0)
    refresh_supported = bool(
        has_auth
        and (
            (credential.get("refresh_token") and credential.get("refresh_key"))
            or musickey.startswith(("Q_H_L", "W_X"))
        )
    )
    return {
        "valid": bool(has_auth and not expired),
        "uin": uin,
        "expires_in": int(expires_in),
        "expires_at": expires_at,
        "expired": expired,
        "refresh_supported": refresh_supported,
        "auto_refresh": True,
        "refreshed_at": int(credential.get("refreshed_at") or 0),
        "last_refresh_attempt": int(credential.get("last_refresh_attempt") or 0),
        "last_refresh_error": str(credential.get("last_refresh_error") or ""),
        "refresh_failures": int(credential.get("refresh_failures") or 0),
    }


def ensure_qq_credential(force_refresh: bool = False, reason: str = "request") -> Dict[str, Any]:
    """确保凭证可用；接近过期或长时间未轮换时自动刷新。"""
    credential = load_qq_credential()
    status = _credential_status(credential)
    if not status["uin"] or not credential.get("musickey"):
        status.update({"valid": False, "need_relogin": True, "message": "未设置QQ音乐登录凭证"})
        return status

    now = int(time.time())
    refreshed_at = int(credential.get("refreshed_at") or 0)
    due_by_age = refreshed_at <= 0 or now - refreshed_at >= _proactive_refresh_interval()
    due_by_expiry = status["expires_in"] >= 0 and status["expires_in"] <= _refresh_window()
    should_refresh = bool(force_refresh or due_by_age or due_by_expiry or status["expired"])

    if should_refresh and status["refresh_supported"]:
        try:
            credential = refresh_qq_credential(reason=reason)
            status = _credential_status(credential)
            status.update({"need_relogin": False, "message": "QQ音乐凭证已自动续期"})
            return status
        except Exception as exc:
            logger.warning(
                "[QQ凭证] 自动续期失败 reason=%s: %s",
                reason,
                type(exc).__name__,
            )
            credential = load_qq_credential()
            status = _credential_status(credential)
            # 刷新失败不立即注销仍未到期的旧凭证；网络抖动不能触发误登出。
            if status["valid"] or not status["expired"]:
                status["valid"] = True
                status.update({
                    "need_relogin": False,
                    "message": "QQ音乐凭证续期暂时失败，继续使用现有登录态",
                })
                return status

    status["need_relogin"] = bool(status["expired"] or not status["valid"])
    if status["valid"]:
        status["message"] = "QQ音乐登录凭证有效，自动续期已启用"
    elif status["refresh_supported"]:
        status["message"] = "QQ音乐凭证已过期且自动续期失败，请重新登录"
    else:
        status["message"] = "QQ音乐凭证不可续期，请重新登录"
    return status


def qq_credential_status() -> Dict[str, Any]:
    return ensure_qq_credential(force_refresh=False, reason="status")


def _maintenance_worker() -> None:
    logger.info(
        "[QQ凭证] 自动续期线程启动 check=%ss refresh_interval=%ss refresh_window=%ss",
        _check_interval(),
        _proactive_refresh_interval(),
        _refresh_window(),
    )
    try:
        ensure_qq_credential(force_refresh=False, reason="startup")
    except Exception:
        logger.exception("[QQ凭证] 启动健康检查失败")

    while True:
        time.sleep(_check_interval())
        try:
            ensure_qq_credential(force_refresh=False, reason="background")
        except Exception:
            logger.exception("[QQ凭证] 后台续期检查失败")


def start_qq_credential_maintenance():
    """只启动一个守护线程；不会改变现有 run.py 启动方式。"""
    global _maintenance_thread
    with _MAINTENANCE_LOCK:
        if _maintenance_thread is not None and _maintenance_thread.is_alive():
            return _maintenance_thread
        _maintenance_thread = threading.Thread(
            target=_maintenance_worker,
            name="qq-credential-maintenance",
            daemon=True,
        )
        _maintenance_thread.start()
        return _maintenance_thread
