#!/usr/bin/env python3
"""Scan tracked files and reachable Git history without printing secret values.

Secret findings fail the scan. Privacy-only findings (for example upstream author
emails) are reported as warnings so vendored/open-source history does not mask real
credential failures.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ALLOWED_EMAIL_SUFFIXES = ("@users.noreply.github.com", "@example.invalid")
SENSITIVE_PATH = re.compile(
    r"(?ix)"
    r"(^|/)(?:"
    r"\.env(?:\..*)?|"
    r"(?:cookie|cookies|qq_cookie|bili_cookie)\.(?:txt|json)|"
    r"qr\.png|"
    r"[^/]*(?:credential|secret)[^/]*\.json|"
    r"[^/]*\.(?:pem|key|pfx|p12|jks|keystore|session|session-journal)"
    r")$"
)
ALLOWED_SENSITIVE_PATHS = {
    "Ubuntu/.env.example",
    "Ubuntu/Cookie/README.md",
    "windows/.env.example",
    "windows/Cookie/README.md",
}
LOCKFILE_SUFFIXES = ("/package-lock.json", "/yarn.lock")
CONTENT_RULES = {
    "private-key": re.compile(rb"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----"),
    "kook-token": re.compile(
        rb"(?<![A-Za-z0-9+/])\d{1,4}/[A-Za-z0-9+/=]{6,}/"
        rb"[A-Za-z0-9+/=]{16,}(?![A-Za-z0-9+/=])"
    ),
    "github-token": re.compile(
        rb"(?:gh[pousr]_[A-Za-z0-9]{30,255}|github_pat_[A-Za-z0-9_]{40,255})"
    ),
    "aws-access-key": re.compile(rb"(?:AKIA|ASIA)[A-Z0-9]{16}"),
    "google-api-key": re.compile(rb"AIza[0-9A-Za-z_-]{35}"),
    "slack-token": re.compile(rb"xox[baprs]-[0-9A-Za-z-]{10,}"),
    "jwt": re.compile(
        rb"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
    ),
    "authorization-value": re.compile(
        rb"(?i)authorization[ \t]*[:=][ \t]*[\"']?(?:bearer|bot|basic)[ \t]+"
        rb"[A-Za-z0-9._~+/=-]{12,}"
    ),
    "env-secret-assignment": re.compile(
        rb"(?im)^(?:BOT_TOKEN|SECRET_KEY|INITIAL_ADMIN_PASSWORD|CREDENTIAL_MASTER_KEY)"
        rb"[ \t]*=[ \t]*[^\s#]{12,}[ \t]*$"
    ),
    "credential-url": re.compile(
        rb"(?i)https?://[^\s/:@]+:[^\s/@]+@[^\s/\"']+"
    ),
    "personal-cloud-endpoint": re.compile(
        rb"(?i)https://[A-Za-z0-9-]+\.[A-Za-z0-9-]+\.tencentscf\.com"
    ),
}
EMAIL = re.compile(rb"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")


def git(*args: str, input_data: bytes | None = None) -> bytes:
    return subprocess.run(
        ["git", "-c", "core.quotepath=false", "-C", str(ROOT), *args],
        input=input_data,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    ).stdout


def line_number(content: bytes, start: int) -> int:
    return content.count(b"\n", 0, start) + 1


def _is_lockfile_label(label: str) -> bool:
    normalized = label.replace("\\", "/")
    return normalized.endswith(LOCKFILE_SUFFIXES)


def scan_content(
    label: str,
    content: bytes,
    secret_findings: set[str],
    privacy_warnings: set[str],
) -> None:
    if b"\0" in content:
        return
    for rule_name, pattern in CONTENT_RULES.items():
        for match in pattern.finditer(content):
            finding = f"{rule_name}: {label}:{line_number(content, match.start())}"
            # npm/yarn integrity material can accidentally match the legacy KOOK token
            # shape. Keep it visible, but do not treat third-party lockfile entropy as a
            # credential unless it appears in source/config/documentation as well.
            if rule_name == "kook-token" and _is_lockfile_label(label):
                privacy_warnings.add(f"lockfile-entropy: {label}:{line_number(content, match.start())}")
            else:
                secret_findings.add(finding)
    for match in EMAIL.finditer(content):
        email = match.group(0).decode("ascii", errors="ignore").lower()
        if not email.endswith(ALLOWED_EMAIL_SUFFIXES):
            privacy_warnings.add(
                f"email-address: {label}:{line_number(content, match.start())}"
            )


def main() -> int:
    secret_findings: set[str] = set()
    privacy_warnings: set[str] = set()

    tracked = [
        item.decode("utf-8")
        for item in git("ls-files", "-z").split(b"\0")
        if item
    ]
    for relative in tracked:
        normalized = relative.replace("\\", "/")
        if SENSITIVE_PATH.search(normalized) and normalized not in ALLOWED_SENSITIVE_PATHS:
            secret_findings.add(f"sensitive-path: worktree/{normalized}")
        path = ROOT / Path(relative)
        if path.is_file():
            scan_content(
                f"worktree/{normalized}",
                path.read_bytes(),
                secret_findings,
                privacy_warnings,
            )

    seen: set[str] = set()
    for raw_line in git("rev-list", "--objects", "--all").decode(
        "utf-8", errors="replace"
    ).splitlines():
        object_id, separator, relative = raw_line.partition(" ")
        if not separator or object_id in seen:
            continue
        seen.add(object_id)
        normalized = relative.replace("\\", "/")
        if SENSITIVE_PATH.search(normalized) and normalized not in ALLOWED_SENSITIVE_PATHS:
            secret_findings.add(f"sensitive-path: history/{object_id[:10]}/{normalized}")
        if git("cat-file", "-t", object_id).strip() != b"blob":
            continue
        scan_content(
            f"history/{object_id[:10]}/{normalized}",
            git("cat-file", "blob", object_id),
            secret_findings,
            privacy_warnings,
        )

    identity_rows = git("log", "--all", "--format=%H%x00%ae%x00%ce%x00%B%x00").split(b"\0")
    for index in range(0, len(identity_rows) - 3, 4):
        commit = identity_rows[index].decode("ascii", errors="ignore").strip()[:10]
        for role, value in (
            ("author", identity_rows[index + 1]),
            ("committer", identity_rows[index + 2]),
        ):
            email = value.decode("utf-8", errors="replace").lower()
            if email and not email.endswith(ALLOWED_EMAIL_SUFFIXES):
                privacy_warnings.add(f"personal-{role}-email: commit/{commit}")
        scan_content(
            f"commit-message/{commit}",
            identity_rows[index + 3],
            secret_findings,
            privacy_warnings,
        )

    if privacy_warnings:
        print(f"WARN: {len(privacy_warnings)} privacy/heuristic finding(s); no values printed")
        for finding in sorted(privacy_warnings):
            print(f"- {finding}")

    if secret_findings:
        print(f"FAILED: {len(secret_findings)} potential secret finding(s)")
        for finding in sorted(secret_findings):
            print(f"- {finding}")
        return 1

    print(
        f"PASS: scanned {len(tracked)} tracked files and {len(seen)} reachable Git objects; "
        "no token/cookie/key/private-secret patterns found"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
