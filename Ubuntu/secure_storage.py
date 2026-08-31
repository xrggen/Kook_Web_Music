"""原子写入本地凭据文件，并尽量限制为当前用户可读写。"""

import os
import tempfile


def secure_read_text(path, encoding="utf-8", max_chars=None):
    """读取凭据文本；在 POSIX 上先把已有文件权限收紧到 0600。"""
    target = os.path.realpath(os.path.abspath(path))
    if os.name == "posix":
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
    with open(target, "r", encoding=encoding) as handle:
        if max_chars is None:
            return handle.read()
        return handle.read(max_chars)


def secure_write_bytes(path, payload):
    target = os.path.realpath(os.path.abspath(path))
    directory = os.path.dirname(target)
    os.makedirs(directory, exist_ok=True)
    if os.name == "posix":
        try:
            os.chmod(directory, 0o700)
        except OSError:
            pass
    descriptor = None
    temporary_path = None
    try:
        descriptor, temporary_path = tempfile.mkstemp(prefix=".credential-", dir=directory)
        try:
            os.fchmod(descriptor, 0o600)
        except (AttributeError, OSError):
            pass
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, target)
        temporary_path = None
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)


def secure_write_text(path, text, encoding="utf-8"):
    secure_write_bytes(path, str(text).encode(encoding))
