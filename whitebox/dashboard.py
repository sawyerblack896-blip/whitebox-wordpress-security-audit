"""Read-only, local-only view of saved white-box audit progress."""

from __future__ import annotations

import fcntl
import json
import re
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def _read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _running(lock_path: Path) -> bool:
    if not lock_path.is_file():
        return False
    try:
        with lock_path.open("r+") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(handle, fcntl.LOCK_UN)
    except OSError:
        return False
    return False


def _timestamp(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None
    except ValueError:
        return None


def _runs(directory: Path) -> dict:
    counts = {"opus": 0, "sol": 0, "failed": 0}
    minutes = {"opus": 0.0, "sol": 0.0}
    latest = None
    last_activity = 0.0
    for run in (directory / "runs").glob("*/run-manifest.json"):
        item = _read(run)
        provider = item.get("provider")
        key = "opus" if provider == "anthropic" else "sol" if provider == "openai" else None
        if key:
            counts[key] += 1
            start, end = _timestamp(item.get("started_at")), _timestamp(item.get("ended_at"))
            if start and end:
                minutes[key] += max(0.0, (end - start).total_seconds() / 60)
        if item.get("exit_code") != 0:
            counts["failed"] += 1
        ended = _timestamp(item.get("ended_at"))
        if ended and (latest is None or ended > latest):
            latest = ended
    # A running CLI call may have events before its manifest is finalized.
    for events in (directory / "runs").glob("*/events.jsonl"):
        try:
            last_activity = max(last_activity, events.stat().st_mtime)
        except OSError:
            continue
    return {"counts": counts, "minutes": {k: round(v, 1) for k, v in minutes.items()},
            "last_run_at": latest.isoformat() if latest else None,
            "last_event_at": datetime.fromtimestamp(last_activity, timezone.utc).isoformat()
            if last_activity else None}


_SOURCE_PATH = re.compile(r"(?<![\w])(?:[\w./-]+/)?[\w.-]+\.(?:php|py|c|h|cpp|hpp|js|ts|go|rs|java|rb|sol)\b")


def _last_tool(directory: Path) -> dict | None:
    """Only report tool kind and source filenames; never expose command arguments."""
    logs = sorted((directory / "runs").glob("*/events.jsonl"),
                  key=lambda path: path.stat().st_mtime, reverse=True)
    for log in logs[:2]:
        try:
            with log.open("rb") as handle:
                handle.seek(0, 2)
                size = handle.tell()
                handle.seek(max(0, size - 262144))
                lines = handle.read().decode("utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            try:
                event = json.loads(line)
            except ValueError:
                continue
            command = ""
            when = None
            if event.get("method") in {"item/started", "item/completed"}:
                item = event.get("params", {}).get("item", {})
                if item.get("type") == "commandExecution":
                    command = str(item.get("command") or "")
                    millis = event.get("emittedAtMs")
                    if isinstance(millis, (int, float)):
                        when = datetime.fromtimestamp(millis / 1000, timezone.utc).isoformat()
            elif event.get("type") == "assistant":
                for block in reversed(event.get("message", {}).get("content", [])):
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        tool = block.get("name")
                        if tool in {"Read", "Grep", "Glob", "Bash"}:
                            data = block.get("input") or {}
                            command = str(data.get("file_path") or data.get("path") or
                                          data.get("pattern") or data.get("command") or "")
                            when = event.get("timestamp")
                            break
            if command:
                paths = _SOURCE_PATH.findall(command)
                title = ("最近检查 " + "、".join(Path(path).name for path in paths[:3])
                         if paths else "运行过本地命令，未形成审查结论")
                return {"kind": "tool", "when": when, "title": title,
                        "detail": "来自模型工具事件；只显示文件名，不显示命令内容。",
                        "files": []}
    return None


def _candidate_counts(directory: Path) -> dict:
    counts = {}
    for path in (directory / "candidates").glob("*/outcome.json"):
        status = _read(path).get("status", "UNKNOWN")
        counts[status] = counts.get(status, 0) + 1
    return counts


def _candidates(directory: Path, checklist: dict) -> list[dict]:
    stages = checklist.get("candidates", {})
    if not isinstance(stages, dict):
        return []
    candidates = []
    for candidate_id, candidate_stages in stages.items():
        base = directory / "candidates" / candidate_id
        outcome, lead, assessment = (_read(base / name) for name in
                                     ("outcome.json", "lead.json", "assessment.json"))
        candidates.append({"id": candidate_id, "status": outcome.get("status", "PENDING"),
                           "location": (f"{Path(str(lead.get('file'))).name}:{lead.get('line')}"
                                        if lead.get("file") and lead.get("line") else ""),
                           "claim": str(lead.get("claim") or "")[:500],
                           "limitations": str(outcome.get("limitations") or "")[:700],
                           "reproduced": assessment.get("reproduced"),
                           "negative_control": str(assessment.get("negative_control") or "")[:300],
                           "stages": candidate_stages if isinstance(candidate_stages, dict) else {}})
    return candidates


def _history(directory: Path) -> list[dict]:
    """Summarize persisted evidence, never model prose from the live stream."""
    entries = []
    for manifest_path in (directory / "runs").glob("*/run-manifest.json"):
        manifest = _read(manifest_path)
        output = _read(manifest_path.with_name("output.json"))
        focus = output.get("focus_boundary_id")
        if focus:
            covered = output.get("coverage") or []
            files = covered[0].get("files", []) if isinstance(covered, list) and covered and isinstance(covered[0], dict) else []
            leads = output.get("leads") or []
            reads = manifest.get("observed_source_reads") or []
            read_count = len(reads) if isinstance(reads, list) else 0
            subject = "、".join(Path(file).name for file in files[:2]) if focus == "unmapped-gap" else str(focus).replace("-", " ")
            title = f"源码审查：{subject}；{len(leads)} 条新线索"
            note = str(output.get("next_boundary") or "").splitlines()[0][:350]
            read_note = (f"实际打开 {read_count} 个源码文件" if read_count else
                         f"模型记录覆盖 {len(files)} 个文件")
            detail = read_note + ("；本轮未提出新线索。" if not leads else
                                  f"；提出 {len(leads)} 条待验证线索。")
            entries.append({"kind": "source_review", "when": manifest.get("ended_at"),
                            "title": title, "detail": detail, "model_note": note,
                            "files": [str(file) for file in files[:8]]})
    for outcome_path in (directory / "candidates").glob("*/outcome.json"):
        outcome = _read(outcome_path)
        candidate_id = outcome_path.parent.name
        status = str(outcome.get("status") or "UNKNOWN")
        result = {"NEEDS_MORE_TEST": "证据不足", "QUALIFIED_FINDING": "内部合格",
                  "REJECTED": "已否定"}.get(status, status)
        entries.append({"kind": "candidate_assessment",
                        "when": datetime.fromtimestamp(outcome_path.stat().st_mtime, timezone.utc).isoformat(),
                        "title": f"评估候选 {candidate_id}：{result}",
                        "detail": str(outcome.get("limitations") or outcome.get("claim") or "")[:700],
                        "files": []})
    for plan_path in (directory / "candidates").glob("*/plan.json"):
        if plan_path.with_name("outcome.json").exists():
            continue
        plan = _read(plan_path)
        entries.append({"kind": "candidate_plan",
                        "when": datetime.fromtimestamp(plan_path.stat().st_mtime, timezone.utc).isoformat(),
                        "title": f"制定候选 {plan_path.parent.name} 的隔离实验计划",
                        "detail": str(plan.get("claim") or plan.get("reason") or "")[:700],
                        "files": []})
    entries.sort(key=lambda entry: entry.get("when") or "", reverse=True)
    return entries[:6]


def _job(directory: Path) -> dict:
    job = _read(directory / "job.json")
    checklist = _read(directory / "checklist.json")
    running = _running(directory / ".lock")
    raw_status = str(job.get("status", "UNKNOWN"))
    detail = str(job.get("status_detail") or "")[:500]
    if running:
        state = "RUNNING"
    elif raw_status == "REPORT_DRAFT":
        state = "REPORT_READY"
    elif raw_status in {"OPEN_FRONTIER", "NO_TESTABLE_FRONTIER"}:
        state = "STOPPED_WITH_GAPS" if raw_status == "OPEN_FRONTIER" else "STOPPED"
    elif raw_status in {"NEW", "SNAPSHOT", "SNAPSHOT_VERIFIED"}:
        state = "NOT_RUNNING"
    else:
        state = "ERROR_OR_PAUSED"
    runs = _runs(directory)
    updated = _timestamp(job.get("updated_at"))
    event_time = _timestamp(runs["last_event_at"])
    recent = max((t for t in (updated, event_time) if t), default=None)
    if running and recent and (datetime.now(timezone.utc) - recent).total_seconds() > 600:
        state = "RUNNING_NO_RECENT_OUTPUT"
    history = _history(directory)
    tool = _last_tool(directory) if running or not history else None
    if tool:
        history = [tool, *history][:6]
    if raw_status == "CLI_FAILED":
        activity = {"kind": "error", "when": job.get("updated_at"),
                    "title": "Codex 授权被拒绝（401）" if "401" in detail else "模型调用失败",
                    "detail": "本轮调用中断，候选验证未继续。原始错误见任务详情。",
                    "files": []}
    else:
        activity = history[0] if history else {"kind": "none", "when": None,
                                               "title": "还没有源码或实验记录", "detail": "", "files": []}
    return {"id": directory.name, "source": str(job.get("source_input", "")),
            "profile": str(job.get("profile", "")), "state": state,
            "revision": str((job.get("snapshot") or {}).get("revision") or ""),
            "stage": raw_status, "detail": detail, "round": job.get("round", 0),
            "running": running, "updated_at": job.get("updated_at"),
            "last_activity_at": recent.isoformat() if recent else None,
            "stages": checklist.get("stages", {}), "candidate_stages": checklist.get("candidates", {}),
            "candidates": _candidates(directory, checklist),
            "candidate_counts": _candidate_counts(directory),
            "candidate_total": len(job.get("candidate_ids", [])),
            "processed_leads": len(job.get("processed_leads", [])),
            "findings": len(job.get("findings", [])),
            "unreviewed_code_count": checklist.get("unreviewed_code_count"),
            "activity": activity, "history": history,
            **runs}


def _live(directory: Path) -> dict:
    item = _read(directory / "live.json")
    feedback = _read(directory / "work" / "codex-feedback.json")
    phase = str(item.get("phase", "UNKNOWN"))
    running = _running(directory / ".run.lock")
    state = "RUNNING" if running else "REPORT_READY" if phase == "DONE" else "NOT_RUNNING"
    handoff = _read(directory / "work" / "claude-handoff.json")
    leads = handoff.get("leads") if isinstance(handoff.get("leads"), list) else []
    gaps = handoff.get("remaining_gaps") if isinstance(handoff.get("remaining_gaps"), list) else []
    if leads:
        activity = {"kind": "handoff", "when": item.get("updated_at"),
                    "title": f"Claude 交接了 {len(leads)} 条线索、{len(gaps)} 个待查缺口",
                    "detail": str(leads[0].get("title") or "")[:400] if isinstance(leads[0], dict) else "",
                    "files": []}
    else:
        activity = {"kind": "none", "when": item.get("updated_at"),
                    "title": "尚无实际审查交接", "detail": "", "files": []}
    return {"id": directory.name, "source": str(item.get("source_input", "")),
            "profile": str(item.get("profile", "")), "stage": phase, "state": state,
            "revision": str(item.get("requested_revision") or ""),
            "cycle": item.get("cycle", 1), "running": running,
            "updated_at": item.get("updated_at"),
            "feedback_status": feedback.get("status"),
            "activity": activity,
            "history": [activity] if activity["kind"] != "none" else [],
            "blocker": str(feedback.get("blocker") or "")[:500] if phase == "NEEDS_DIRECTION" else "",
            "resume_when": str(feedback.get("resume_when") or "")[:500]
            if phase == "NEEDS_DIRECTION" else ""}


def snapshot(root: Path) -> dict:
    jobs = [_job(path.parent) for path in sorted((root / "jobs").glob("*/job.json"))]
    live = [_live(path.parent) for path in sorted((root / "live").glob("*/live.json"))]
    jobs.sort(key=lambda x: x.get("updated_at") or "", reverse=True)
    live.sort(key=lambda x: x.get("updated_at") or "", reverse=True)
    return {"generated_at": datetime.now(timezone.utc).isoformat(), "jobs": jobs,
            "interactive": live,
            "summary": {"running": sum(x["running"] for x in [*jobs, *live]),
                        "errors": sum(x["state"] == "ERROR_OR_PAUSED" for x in jobs),
                        "open_frontier": sum(x["state"] == "STOPPED_WITH_GAPS" for x in jobs),
                        "reports": sum(x["state"] == "REPORT_READY" for x in [*jobs, *live])}}


HTML_PATH = Path(__file__).with_name("dashboard.html")


def serve(root: Path, host: str = "127.0.0.1", port: int = 8765) -> None:
    if host not in {"127.0.0.1", "::1"}:
        raise ValueError("dashboard may only bind to loopback")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path in {"/", "/index.html"}:
                data, kind = HTML_PATH.read_bytes(), "text/html; charset=utf-8"
            elif self.path == "/api/jobs":
                data = json.dumps(snapshot(root), ensure_ascii=False).encode()
                kind = "application/json; charset=utf-8"
            elif self.path == "/health":
                data, kind = b"ok\n", "text/plain; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; connect-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer((host, port), Handler)
    server.serve_forever()
