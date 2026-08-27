#!/usr/bin/env python3
"""Fail when Windows/Ubuntu shared runtime files drift apart.

Windows is the authoritative implementation. OS-specific behavior belongs inside shared
code behind platform checks; platform directories may differ only in documentation and
explicitly platform-only packaging/deployment assets.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT / "windows"
UBUNTU = ROOT / "Ubuntu"

SHARED_FILES = (
    ".env.example",
    "account_api.py",
    "api.py",
    "app.py",
    "bili_account_api.py",
    "bili_utils.py",
    "config.py",
    "cookie_login.py",
    "cookie_login_captcha.py",
    "create_env.py",
    "kookvoice/__init__.py",
    "kookvoice/kookvoice.py",
    "kookvoice/requestor.py",
    "qq_account_api.py",
    "qq_utils.py",
    "requirements.txt",
    "routes.py",
    "run.py",
    "runtime_health.py",
    "save_cookie.py",
    "service_watchdog.py",
    "static/css/dashboard.css",
    "static/css/style.css",
    "static/js/account.js",
    "static/js/bili_account.js",
    "static/js/dashboard.js",
    "static/js/main.js",
    "static/js/qq_account.js",
    "templates/account.html",
    "templates/dashboard.html",
    "templates/index.html",
    "templates/test.html",
    "tests/test_stability.py",
    "tests/test_watchdog.py",
    "utils.py",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    failures: list[str] = []
    for relative in SHARED_FILES:
        win = WINDOWS / relative
        ubuntu = UBUNTU / relative
        if not win.is_file():
            failures.append(f"Windows 主线缺少共享文件: {relative}")
            continue
        if not ubuntu.is_file():
            failures.append(f"Ubuntu 缺少共享文件: {relative}")
            continue
        if win.read_bytes() != ubuntu.read_bytes():
            failures.append(
                f"共享文件发生分叉: {relative} "
                f"(windows={digest(win)[:12]}, Ubuntu={digest(ubuntu)[:12]})"
            )

    if failures:
        print("FAILED: Windows / Ubuntu shared runtime drift detected")
        for failure in failures:
            print(f"- {failure}")
        print("\nWindows 是主线；请同步修改 Ubuntu 对应文件，或把 OS 差异收敛到共享代码内部。")
        return 1

    print(f"PASS: {len(SHARED_FILES)} shared runtime files are byte-for-byte identical")
    return 0


if __name__ == "__main__":
    sys.exit(main())
