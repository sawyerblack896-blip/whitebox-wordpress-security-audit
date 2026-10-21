"""Small deterministic helpers shared by the controller and validators."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False).encode() + b"\n"
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"JSON root is not an object: {path}")
    return value


def tree_digest(root: Path) -> str:
    """Hash relative paths, file bytes, and in-tree symlink targets."""
    h = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            target = os.readlink(path).encode()
            rel = path.relative_to(root).as_posix().encode()
            h.update(len(rel).to_bytes(4, "big") + rel)
            h.update(len(target).to_bytes(8, "big"))
            h.update(hashlib.sha256(b"SYMLINK\0" + target).digest())
            continue
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError(f"source tree contains special file: {path}")
        rel = path.relative_to(root).as_posix().encode()
        h.update(len(rel).to_bytes(4, "big") + rel)
        h.update(path.stat().st_size.to_bytes(8, "big"))
        h.update(bytes.fromhex(digest_file(path)))
    return h.hexdigest()

def init_run_root(root: Path) -> None:
    """Create the generic directories used by a deployment-owned run."""
    (root / "source").mkdir(parents=True, exist_ok=True)
    (root / "runs").mkdir(parents=True, exist_ok=True)
