from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path


class EdgeSecretStore:
    def __init__(self, platform_dir: Path):
        self.platform_dir = Path(platform_dir).resolve()
        self.data_dir = self.platform_dir / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        configured = os.environ.get("EDGE_AGENT_SECRET_PATH", "").strip()
        if configured:
            path = Path(configured).expanduser()
            if not path.is_absolute():
                path = self.platform_dir / path
            self.path = path.resolve()
        else:
            self.path = (self.data_dir / "edge-agent.secret").resolve()
        self._bootstrap_from_env()

    def _bootstrap_from_env(self) -> None:
        if self.path.exists():
            return
        token = os.environ.get("EDGE_AGENT_TOKEN", "").strip()
        if token:
            self.write(token)

    def read(self) -> str:
        try:
            return self.path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return ""

    def configured(self) -> bool:
        return len(self.read()) >= 32

    def write(self, token: str) -> None:
        token = str(token or "").strip()
        if len(token) < 32 or len(token) > 512 or any(ch.isspace() for ch in token):
            raise ValueError("Agent Token 必须为 32-512 个非空白字符")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            os.chmod(self.data_dir, stat.S_IRWXU)
        fd, temp_name = tempfile.mkstemp(prefix=".edge-agent-", dir=str(self.data_dir), text=True)
        try:
            if os.name != "nt":
                os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(token)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.path)
            if os.name != "nt":
                os.chmod(self.path, stat.S_IRUSR | stat.S_IWUSR)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
