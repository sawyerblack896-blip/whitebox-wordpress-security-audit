"""Read subscription limits without reading or printing provider credentials."""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .util import digest_file


def _window(value: dict | None) -> dict | None:
    if not isinstance(value, dict) or value.get("usedPercent") is None:
        return None
    return {"used": value["usedPercent"], "minutes": value.get("windowDurationMins"),
            "resets_at": value.get("resetsAt")}


def codex_limits(timeout: float = 15) -> dict:
    """Use the documented local app-server account/rateLimits/read method."""
    binary = os.environ.get("CODEX_BIN") or shutil.which("codex")
    if not binary or not Path(binary).exists():
        return {"error": "Codex CLI unavailable"}
    env = dict(os.environ)
    env.pop("OPENAI_API_KEY", None)
    env.pop("CODEX_API_KEY", None)
    process = subprocess.Popen([binary, "app-server", "--stdio"], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               text=True, bufsize=1, env=env)
    events: queue.Queue[dict] = queue.Queue()

    def read() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            try:
                events.put(json.loads(line))
            except json.JSONDecodeError:
                continue

    threading.Thread(target=read, daemon=True).start()
    deadline = time.monotonic() + timeout

    def send(request: dict) -> None:
        assert process.stdin is not None
        process.stdin.write(json.dumps(request, separators=(",", ":")) + "\n")
        process.stdin.flush()

    def response(number: int) -> dict:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Codex quota request timed out")
            event = events.get(timeout=remaining)
            if event.get("id") == number:
                return event

    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "clientInfo": {"name": "whitebox_quota", "title": "Whitebox Quota", "version": "1.0"},
            "capabilities": {}}})
        init = response(1)
        if init.get("error"):
            raise ValueError("Codex app-server initialization failed")
        send({"jsonrpc": "2.0", "method": "initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "account/rateLimits/read"})
        event = response(2)
        if event.get("error"):
            detail = json.dumps(event["error"], ensure_ascii=False).lower()
            if "token_invalidated" in detail or "unauthorized" in detail or "401" in detail:
                raise ValueError("Codex login expired; sign in again on the server")
            raise ValueError("Codex rate limits unavailable")
        result = event.get("result") or {}
        buckets = result.get("rateLimitsByLimitId") or {}
        if not buckets and result.get("rateLimits"):
            one = result["rateLimits"]
            buckets = {one.get("limitId") or "codex": one}
        return {"buckets": {name: {"name": value.get("limitName") or name,
                                    "primary": _window(value.get("primary")),
                                    "secondary": _window(value.get("secondary"))}
                            for name, value in buckets.items()},
                "checked_at": time.time()}
    except (OSError, ValueError, TimeoutError, queue.Empty) as exc:
        return {"error": str(exc)}
    finally:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)


def claude_limits(live_dir: Path) -> dict:
    path = live_dir / "claude-quota.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {"error": "waiting for Claude's first response"}
    if not isinstance(data, dict):
        return {"error": "invalid Claude status"}
    return data


def _percent(window: dict | None) -> str:
    if not window or window.get("used") is None:
        return "—"
    used = float(window["used"])
    return f"{max(0, 100 - used):.0f}% left"


def _reset(window: dict | None) -> str:
    stamp = window.get("resets_at") if window else None
    try:
        if isinstance(stamp, (int, float)):
            when = datetime.fromtimestamp(stamp, ZoneInfo("Asia/Taipei"))
        elif isinstance(stamp, str):
            when = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(
                ZoneInfo("Asia/Taipei"))
        else:
            return ""
    except (ValueError, OverflowError):
        return ""
    return when.strftime(" %m-%d %H:%M Taipei")


def codex_identity(live_dir: Path, *, not_before: float | None = None) -> dict | None:
    """Read the TUI's own rollout; never infer Daybreak from the requested model."""
    work = str((live_dir / "work").resolve())
    sessions = Path.home() / ".codex" / "sessions"
    if not sessions.is_dir():
        return None
    for path in sorted(sessions.glob("**/*.jsonl"), key=lambda p: p.stat().st_mtime,
                       reverse=True):
        try:
            if not_before is not None and path.stat().st_mtime < not_before - 1:
                continue
            with path.open() as stream:
                first = json.loads(stream.readline())
                if first.get("type") != "session_meta" or first.get("payload", {}).get("cwd") != work:
                    continue
                meta = first["payload"]
                size = path.stat().st_size
                stream.seek(max(0, size - 1024 * 1024))
                if size > 1024 * 1024:
                    stream.readline()
                seen = None
                for line in stream:
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if event.get("type") == "turn_context":
                        payload = event.get("payload") or {}
                        seen = {"model": payload.get("model"),
                                "program": payload.get("cyber_access_program"),
                                "effort": (payload.get("collaboration_mode") or {}).get("reasoning_effort")
                                          or ((payload.get("collaboration_mode") or {}).get("settings") or {}).get("reasoning_effort")
                                          or payload.get("effort")
                                          or (payload.get("reasoning") or {}).get("effort"),
                                "provider": meta.get("model_provider"),
                                "session_id": meta.get("id"),
                                "rollout_sha256": digest_file(path)}
                return seen or {"model": None, "program": None, "effort": None,
                                "provider": meta.get("model_provider"),
                                "session_id": meta.get("id"),
                                "rollout_sha256": digest_file(path)}
        except (OSError, ValueError, TypeError):
            continue
    return None


def render(live_dir: Path, codex: dict | None = None) -> str:
    claude = claude_limits(live_dir)
    codex = codex if codex is not None else codex_limits()
    lines = ["SUBSCRIPTION LIMITS — remaining", ""]
    if claude.get("error"):
        lines.append("Claude  " + claude["error"])
    else:
        windows = claude.get("rate_limits") or {}
        for key, label in (("five_hour", "5h"), ("seven_day", "7d")):
            window = windows.get(key)
            lines.append(f"Claude {label:2}  {_percent(window):>9}{_reset(window)}")
        age = time.time() - claude.get("checked_at", 0)
        if age > 180:
            lines.append(f"Claude data {int(age // 60)}m old")
    if codex.get("error"):
        lines.append("Codex   " + codex["error"])
    else:
        buckets = codex.get("buckets") or {}
        if not buckets:
            lines.append("Codex   no limit data returned")
        for name, bucket in buckets.items():
            label = bucket.get("name") or name
            for key in ("primary", "secondary"):
                window = bucket.get(key)
                if window:
                    mins = window.get("minutes")
                    horizon = "7d" if mins == 10080 else "5h" if mins == 300 else f"{mins}m"
                    lines.append(f"Codex {label} {horizon}  {_percent(window):>9}{_reset(window)}")
    try:
        stage = json.loads((live_dir / "live.json").read_text()).get("phase")
    except (OSError, json.JSONDecodeError):
        stage = None
    if stage and stage.startswith("CODEX"):
        identity = codex_identity(live_dir)
        if identity:
            lines.append("TUI: " + str(identity.get("model") or "unknown") + " / "
                         + str(identity.get("effort") or "effort unknown") + " / "
                         + str(identity.get("program") or "Daybreak unverified"))
        else:
            lines.append("TUI: waiting for first Codex turn")
    lines.append("Refresh: Claude on replies; Codex every 45s")
    return "\n".join(lines)


def watch(live_dir: Path, interval: int = 45) -> None:
    while True:
        print("\033[2J\033[H" + render(live_dir), flush=True)
        time.sleep(max(30, interval))
