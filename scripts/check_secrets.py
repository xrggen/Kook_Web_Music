#!/usr/bin/env python3
"""Scan tracked files and reachable Git history without printing secret values."""
from __future__ import annotations
import re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_EMAIL_SUFFIXES = ("@users.noreply.github.com", "@example.invalid")
SENSITIVE_PATH = re.compile(r"(?ix)(^|/)(?:\.env(?:\..*)?|(?:cookie|cookies|qq_cookie|bili_cookie)\.(?:txt|json)|qr\.png|[^/]*(?:credential|secret)[^/]*\.json|[^/]*\.(?:pem|key|pfx|p12|jks|keystore|session|session-journal))$")
ALLOWED_SENSITIVE_PATHS = {"Ubuntu/.env.example", "Ubuntu/Cookie/README.md", "windows/.env.example", "windows/Cookie/README.md"}
LOCKFILE_SUFFIXES = ("/package-lock.json", "/yarn.lock")
CONTENT_RULES = {
    "private-key": re.compile(rb"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----"),
    "kook-token": re.compile(rb"(?<![A-Za-z0-9+/])\d{1,4}/[A-Za-z0-9+/=]{6,}/[A-Za-z0-9+/=]{16,}(?![A-Za-z0-9+/=])"),
    "github-token": re.compile(rb"(?:gh[pousr]_[A-Za-z0-9]{30,255}|github_pat_[A-Za-z0-9_]{40,255})"),
    "aws-access-key": re.compile(rb"(?:AKIA|ASIA)[A-Z0-9]{16}"),
    "google-api-key": re.compile(rb"AIza[0-9A-Za-z_-]{35}"),
    "slack-token": re.compile(rb"xox[baprs]-[0-9A-Za-z-]{10,}"),
    "jwt": re.compile(rb"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    "authorization-value": re.compile(rb"(?i)authorization[ \t]*[:=][ \t]*[\"']?(?:bearer|bot|basic)[ \t]+[A-Za-z0-9._~+/=-]{12,}"),
    "credential-url": re.compile(rb"(?i)https?://[^\s/:@]+:[^\s/@]+@[^\s/\"']+"),
    "personal-cloud-endpoint": re.compile(rb"(?i)https://[A-Za-z0-9-]+\.[A-Za-z0-9-]+\.tencentscf\.com"),
}
SECRET_ASSIGNMENT = re.compile(rb"(?im)^(BOT_TOKEN|SECRET_KEY|INITIAL_ADMIN_PASSWORD|CREDENTIAL_MASTER_KEY)[ \t]*=[ \t]*(.*)$")
EMAIL = re.compile(rb"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
PLACEHOLDER_WORDS = (b"example", b"placeholder", b"replace", b"change_me", b"changeme", b"your_", b"your-", b"random", b"secret_key", b"token_here")
DYNAMIC_MARKERS = (b"os.environ", b"os.getenv", b"getenv(", b"getpass(", b"input(", b"token_urlsafe(", b"token_hex(", b"secrets.", b"environ[")

def git(*args: str, input_data: bytes | None = None) -> bytes:
    return subprocess.run(["git", "-c", "core.quotepath=false", "-C", str(ROOT), *args], input=input_data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout

def line_number(content: bytes, start: int) -> int: return content.count(b"\n", 0, start) + 1
def norm(label: str) -> str: return label.replace("\\", "/")
def is_lockfile(label: str) -> bool: return norm(label).endswith(LOCKFILE_SUFFIXES)

def looks_placeholder(raw: bytes) -> bool:
    value = raw.strip().strip(b"'\"")
    if not value: return True
    lowered = value.lower()
    if any(x in value for x in (b"{", b"}", b"<", b">", b"${")): return True
    if any(x in lowered for x in PLACEHOLDER_WORDS): return True
    if any(x in lowered for x in DYNAMIC_MARKERS): return True
    return False

def scan(label: str, content: bytes, secrets: set[str], warnings: set[str]) -> None:
    if b"\0" in content: return
    for name, pattern in CONTENT_RULES.items():
        for m in pattern.finditer(content):
            loc = f"{label}:{line_number(content, m.start())}"
            if name == "kook-token" and is_lockfile(label): warnings.add(f"lockfile-entropy: {loc}")
            else: secrets.add(f"{name}: {loc}")
    for m in SECRET_ASSIGNMENT.finditer(content):
        value = m.group(2).strip().strip(b"'\"")
        if looks_placeholder(value) or len(value) < 12: continue
        loc = f"{label}:{line_number(content, m.start())}"
        secrets.add(f"env-secret-assignment: {loc}")
    for m in EMAIL.finditer(content):
        email = m.group(0).decode("ascii", errors="ignore").lower()
        if not email.endswith(ALLOWED_EMAIL_SUFFIXES): warnings.add(f"email-address: {label}:{line_number(content, m.start())}")

def main() -> int:
    secrets, warnings = set(), set()
    tracked = [x.decode("utf-8") for x in git("ls-files", "-z").split(b"\0") if x]
    for relative in tracked:
        n = norm(relative)
        if SENSITIVE_PATH.search(n) and n not in ALLOWED_SENSITIVE_PATHS: secrets.add(f"sensitive-path: worktree/{n}")
        path = ROOT / Path(relative)
        if path.is_file(): scan(f"worktree/{n}", path.read_bytes(), secrets, warnings)
    seen = set()
    for row in git("rev-list", "--objects", "--all").decode("utf-8", errors="replace").splitlines():
        oid, sep, relative = row.partition(" ")
        if not sep or oid in seen: continue
        seen.add(oid); n = norm(relative)
        if SENSITIVE_PATH.search(n) and n not in ALLOWED_SENSITIVE_PATHS: secrets.add(f"sensitive-path: history/{oid[:10]}/{n}")
        if git("cat-file", "-t", oid).strip() == b"blob": scan(f"history/{oid[:10]}/{n}", git("cat-file", "blob", oid), secrets, warnings)
    rows = git("log", "--all", "--format=%H%x00%ae%x00%ce%x00%B%x00").split(b"\0")
    for i in range(0, len(rows)-3, 4):
        commit = rows[i].decode("ascii", errors="ignore").strip()[:10]
        for role, value in (("author", rows[i+1]), ("committer", rows[i+2])):
            email = value.decode("utf-8", errors="replace").lower()
            if email and not email.endswith(ALLOWED_EMAIL_SUFFIXES): warnings.add(f"personal-{role}-email: commit/{commit}")
        scan(f"commit-message/{commit}", rows[i+3], secrets, warnings)
    if warnings:
        print(f"WARN: {len(warnings)} privacy/heuristic finding(s); no values printed")
        for f in sorted(warnings): print(f"- {f}")
    if secrets:
        print(f"FAILED: {len(secrets)} potential secret finding(s)")
        for f in sorted(secrets): print(f"- {f}")
        return 1
    print(f"PASS: scanned {len(tracked)} tracked files and {len(seen)} reachable Git objects; no token/cookie/key/private-secret patterns found")
    return 0

if __name__ == "__main__": sys.exit(main())
