#!/usr/bin/env python3
"""Scan tracked files and reachable Git history without printing secret values."""
from __future__ import annotations
import argparse, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_EMAIL_SUFFIXES = ("@users.noreply.github.com", "@example.invalid")
SENSITIVE_PATH = re.compile(r"(?ix)(^|/)(?:\.env(?:\..*)?|(?:cookie|cookies|qq_cookie|bili_cookie)\.(?:txt|json)|qr\.png|[^/]*(?:credential|secret)[^/]*\.json|[^/]*\.(?:pem|key|pfx|p12|jks|keystore|session|session-journal|db|db-wal|db-shm|sqlite|sqlite3|secret|ppk|log|sddl|clixml)|(?:project\.private\.config\.json|appsecret\.txt|appid\.txt|bootstrap-admin\.json))$")
ALLOWED_SENSITIVE_PATHS = {"Ubuntu/.env.example", "Ubuntu/Cookie/README.md", "windows/.env.example", "windows/Cookie/README.md", "cloud/.env.example", "edge/.env.example"}
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
SECRET_ASSIGNMENT = re.compile(rb"(?im)^(BOT_TOKEN|SECRET_KEY|INITIAL_ADMIN_PASSWORD|CREDENTIAL_MASTER_KEY|EDGE_AGENT_TOKEN|WECHAT_MINIAPP_APP_SECRET)[ \t]*=[ \t]*(.*)$")
EMAIL = re.compile(rb"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
PLACEHOLDER_WORDS = (b"example", b"placeholder", b"replace", b"change_me", b"changeme", b"your_", b"your-", b"random", b"secret_key", b"token_here")
DYNAMIC_MARKERS = (b"os.environ", b"os.getenv", b"getenv(", b"getpass(", b"input(", b"token_urlsafe(", b"token_hex(", b"secrets.", b"environ[")

def git(*args: str, input_data: bytes | None = None) -> bytes:
    return subprocess.run(["git", "-c", "core.quotepath=false", "-C", str(ROOT), *args], input=input_data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout

def scan_git_objects(entries, secrets, warnings):
    command = ["git", "-C", str(ROOT), "cat-file", "--batch"]
    with subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE) as reader:
        for oid, label in entries:
            reader.stdin.write(oid.encode("utf-8") + b"\n")
            reader.stdin.flush()
            header = reader.stdout.readline().split()
            if len(header) != 3:
                raise RuntimeError(f"Cannot read Git object for {label}")
            size = int(header[2])
            content = reader.stdout.read(size)
            if len(content) != size or reader.stdout.read(1) != b"\n":
                raise RuntimeError(f"Incomplete Git object for {label}")
            if header[1] == b"blob":
                scan(label, content, secrets, warnings)
        reader.stdin.close()
        if reader.wait() != 0:
            raise RuntimeError("Git object scan failed")


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

def documented_placeholder(label, value):
    if not label.lower().endswith(".md"):
        return False
    text = value.decode("utf-8", errors="replace")
    return text in {"你的KOOK机器人Token", "已经配置", "请使用足够长的随机字符串"} or bool(
        re.fullmatch(r"这里填(?:写)?第[0-9]+步生成的AgentToken", text)
    )


def scan(label: str, content: bytes, secrets: set[str], warnings: set[str]) -> None:
    if b"\0" in content: return
    for name, pattern in CONTENT_RULES.items():
        for m in pattern.finditer(content):
            if (name == "credential-url" and label.endswith(("/windows/tests/test_stability.py", "/Ubuntu/tests/test_stability.py"))
                    and m.group(0) == b"https://" + b"user:password@example.invalid"):
                continue
            if (name == "authorization-value" and label.lower().endswith(".md")
                    and m.group(0).split()[-1].lower() == b"edge_agent_token"):
                continue
            loc = f"{label}:{line_number(content, m.start())}"
            if name == "kook-token" and is_lockfile(label): warnings.add(f"lockfile-entropy: {loc}")
            else: secrets.add(f"{name}: {loc}")
    for m in SECRET_ASSIGNMENT.finditer(content):
        value = m.group(2).strip().strip(b"'\"")
        if looks_placeholder(value) or documented_placeholder(label, value) or len(value) < 12: continue
        loc = f"{label}:{line_number(content, m.start())}"
        secrets.add(f"env-secret-assignment: {loc}")
    for m in EMAIL.finditer(content):
        email = m.group(0).decode("ascii", errors="ignore").lower()
        if not email.endswith(ALLOWED_EMAIL_SUFFIXES): warnings.add(f"email-address: {label}:{line_number(content, m.start())}")

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--staged', action='store_true', help='scan the prospective commit from the Git index')
    parser.add_argument('--outgoing', action='store_true', help='scan HEAD objects and commits not on origin')
    args = parser.parse_args()
    secrets, warnings = set(), set()
    tracked = [x.decode("utf-8") for x in git("ls-files", "-z").split(b"\0") if x]
    entries = []
    scope = "index" if args.staged else "worktree"
    for relative in tracked:
        n = norm(relative)
        if SENSITIVE_PATH.search(n) and n not in ALLOWED_SENSITIVE_PATHS:
            secrets.add(f"sensitive-path: {scope}/{n}")
            continue
        if args.staged:
            entries.append((f":{relative}", f"{scope}/{n}"))
        else:
            path = ROOT / Path(relative)
            if path.is_file() and path.resolve() == path:
                scan(f"{scope}/{n}", path.read_bytes(), secrets, warnings)
    seen = set()
    revision_scope = ("HEAD", "--not", "--remotes=origin") if args.outgoing else ("--all",)
    for row in git("rev-list", "--objects", *revision_scope).decode("utf-8", errors="replace").splitlines():
        oid, sep, relative = row.partition(" ")
        if not sep or oid in seen: continue
        seen.add(oid); n = norm(relative)
        if SENSITIVE_PATH.search(n) and n not in ALLOWED_SENSITIVE_PATHS:
            secrets.add(f"sensitive-path: history/{oid[:10]}/{n}")
            continue
        entries.append((oid, f"history/{oid[:10]}/{n}"))
    scan_git_objects(entries, secrets, warnings)
    rows = git("log", "--format=%H%x00%ae%x00%ce%x00%B%x00", *revision_scope).split(b"\0")
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
