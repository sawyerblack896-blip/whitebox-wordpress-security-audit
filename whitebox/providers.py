"""Fresh, recorded CLI sessions. No model may self-attest its own identity."""

from __future__ import annotations

import json
import os
import pwd
import queue
import shutil
import stat
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from .util import digest_file, now, write_json


class ProviderError(RuntimeError):
    def __init__(self, state: str, detail: str):
        super().__init__(detail)
        self.state = state


@dataclass(frozen=True)
class Result:
    data: dict
    manifest: dict
    directory: Path


def _runuser() -> str:
    """Absolute path to runuser. It lives in /usr/sbin, which a restricted PATH omits; by bare
    name the claude provider then dies with an opaque Errno 2 on every turn."""
    import shutil as _sh
    if os.path.exists("/usr/sbin/runuser"):
        return "/usr/sbin/runuser"
    return _sh.which("runuser") or "/usr/sbin/runuser"

def _parse_json_text(value: str) -> dict:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ProviderError("INVALID_OUTPUT", "model did not produce valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ProviderError("INVALID_OUTPUT", "model output root must be an object")
    return parsed


def _event_from_thread(event: dict, thread_id: str) -> bool:
    """True only for notifications emitted by the requested parent thread.

    App-server forwards child-agent notifications on the same stream.  In particular, a
    child's ``turn/completed`` must not terminate the parent's structured turn.
    """
    return event.get("params", {}).get("threadId") == thread_id


def _codex_rollout(session_id: str, codex_home: Path) -> tuple[str | None, str | None, str | None, Path | None]:
    if not session_id or not codex_home.exists():
        return None, None, None, None
    matches = list((codex_home / "sessions").glob(f"**/*{session_id}*.jsonl"))
    if len(matches) != 1:
        return None, None, None, None
    model = effort = provider = cyber_program = None
    with matches[0].open() as stream:
        for line in stream:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = event.get("payload", {})
            if event.get("type") == "session_meta":
                provider = payload.get("model_provider")
            elif event.get("type") == "turn_context":
                model = payload.get("model")
                cyber_program = payload.get("cyber_access_program")
                effort = (payload.get("collaboration_mode") or {}).get("reasoning_effort")
                if not effort:
                    effort = ((payload.get("collaboration_mode") or {}).get("settings") or {}).get("reasoning_effort")
                if not effort:
                    effort = (payload.get("effort") or
                              (payload.get("reasoning") or {}).get("effort"))
    if provider != "openai":
        return None, None, None, matches[0]
    return model, effort, cyber_program, matches[0]


def _run_codex_once(prompt: str, schema: dict, trusted_cwd: Path, run_root: Path,
                    *, model: str, effort: str, timeout: int,
                    executable: str, codex_home: Path | None,
                    goal_objective: str, require_daybreak: bool = True) -> Result:
    """Run a fresh Sol 6 turn with an explicit Daybreak Blue request.

    The CLI's exec surface has no cyber-program selector. App-server has a
    per-turn selector; its rollout also records the treatment actually used.
    """
    if not shutil.which(executable) and not Path(executable).exists():
        raise ProviderError("MISSING_CLI", "Codex CLI is not installed")
    if model not in ("gpt-6-sol", "gpt-5.6-sol"):
        raise ProviderError("MODEL_UNSUPPORTED",
                            "this harness supports gpt-6-sol or gpt-5.6-sol, got %r" % model)
    run_dir = run_root / uuid.uuid4().hex
    run_dir.mkdir(parents=True, mode=0o700)
    schema_path, output_path, raw_path = (run_dir / "schema.json", run_dir / "output.json",
                                         run_dir / "events.jsonl")
    write_json(schema_path, schema)
    started = now()
    env = dict(os.environ)
    env.pop("OPENAI_API_KEY", None)
    env.pop("CODEX_API_KEY", None)
    if codex_home:
        env["CODEX_HOME"] = str(codex_home)
    session = final_text = None
    turn_status = None
    protocol_error = None
    app_exit = None
    goal_requested = goal_active = goal_complete = goal_cleared_after_failure = False
    stage_error: ProviderError | None = None
    data: dict | None = None
    actual_model = actual_effort = actual_program = rollout = None
    with (run_dir / "stderr.txt").open("w") as stderr, raw_path.open("w") as raw:
        proc = subprocess.Popen([executable, "app-server", "--stdio"],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr,
                                text=True, bufsize=1, cwd=trusted_cwd, env=env)
        events: queue.Queue[dict] = queue.Queue()

        def record_events() -> None:
            for line in proc.stdout:
                raw.write(line)
                raw.flush()
                try:
                    events.put(json.loads(line))
                except json.JSONDecodeError:
                    continue

        threading.Thread(target=record_events, daemon=True).start()
        deadline = time.monotonic() + timeout
        pending: list[dict] = []

        def next_event() -> dict:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProviderError("TIMEOUT", f"Codex timed out; events: {raw_path}")
            try:
                return events.get(timeout=remaining)
            except queue.Empty as exc:
                raise ProviderError("TIMEOUT", f"Codex timed out; events: {raw_path}") from exc

        def send(id_: int, method: str, params: dict | None = None) -> None:
            request = {"jsonrpc": "2.0", "id": id_, "method": method}
            if params is not None:
                request["params"] = params
            proc.stdin.write(json.dumps(request, separators=(",", ":")) + "\n")
            proc.stdin.flush()

        def response(id_: int) -> dict:
            while True:
                event = next_event()
                if event.get("id") == id_:
                    if "error" in event:
                        raise ProviderError("CLI_FAILED", f"Codex app-server {id_}: {event['error']}")
                    return event["result"]
                pending.append(event)

        try:
            send(1, "initialize", {
                "clientInfo": {"name": "whitebox_harness", "title": "Whitebox Harness", "version": "0.1.0"},
                "capabilities": {"experimentalApi": True},
            })
            response(1)
            proc.stdin.write('{"jsonrpc":"2.0","method":"initialized"}\n')
            proc.stdin.flush()
            send(2, "thread/start", {
                "model": model, "cwd": str(trusted_cwd), "sandbox": "danger-full-access",
                "approvalPolicy": "never", "ephemeral": False, "daybreakEnabled": False,
            })
            thread = response(2)
            session = thread["thread"]["id"]
            if thread.get("model") != model or thread.get("modelProvider") != "openai":
                raise ProviderError("MODEL_FALLBACK", f"Codex thread model/provider mismatch: {run_dir}")
            send(3, "turn/start", {
                "threadId": session, "input": [{"type": "text", "text": prompt}],
                "model": model, "effort": effort,
                "approvalPolicy": "never", "sandboxPolicy": {"type": "dangerFullAccess"},
                "outputSchema": schema,
            })
            response(3)
            # Setting an active Goal on an idle thread makes the app-server
            # schedule its own turn. Attach it only after this structured turn
            # has been accepted so the Goal and output schema refer to one turn.
            send(4, "thread/goal/set", {"threadId": session, "objective": goal_objective,
                                         "status": "active"})
            goal_requested = True
            active = response(4).get("goal", {})
            if active.get("status") != "active" or active.get("objective") != goal_objective:
                raise ProviderError("GOAL_INCOMPLETE", f"Codex did not activate the stage Goal: {run_dir}")
            goal_active = True
            while True:
                event = pending.pop(0) if pending else next_event()
                method = event.get("method")
                # Subagents share this app-server event stream.  Without binding terminal and
                # final-answer events to the parent thread, an interrupted reviewer turn is
                # mistaken for the audit turn and surfaces as the opaque
                # ``Codex turn failed: None`` while the parent is still working.
                if method in {"item/completed", "turn/completed", "turn/failed"} \
                        and not _event_from_thread(event, session):
                    continue
                if method == "item/completed":
                    item = event.get("params", {}).get("item", {})
                    if item.get("type") == "agentMessage" and item.get("phase") == "final_answer":
                        final_text = item.get("text")
                elif method in {"turn/completed", "turn/failed"}:
                    turn_status = event.get("params", {}).get("turn", {}).get("status")
                    protocol_error = event.get("params", {}).get("turn", {}).get("error")
                    break
            if turn_status == "completed":
                home = codex_home or Path(env.get("CODEX_HOME", Path.home() / ".codex"))
                actual_model, actual_effort, actual_program, rollout = _codex_rollout(session or "", home)
                if (actual_model != model or actual_effort != effort or
                        (require_daybreak and actual_program != "daybreak_blue")):
                    raise ProviderError("PROVENANCE_UNVERIFIED", f"Codex model/effort identity missing or changed: {run_dir}")
                if not final_text:
                    raise ProviderError("INVALID_OUTPUT", f"Codex final output is missing: {run_dir}")
                data = _parse_json_text(final_text)
                write_json(output_path, data)
                send(5, "thread/goal/set", {"threadId": session, "status": "complete"})
                completed = response(5).get("goal", {})
                if completed.get("status") != "complete":
                    raise ProviderError("GOAL_INCOMPLETE", f"Codex did not complete the stage Goal: {run_dir}")
                goal_complete = True
        except ProviderError as exc:
            stage_error = exc
        except (OSError, KeyError, TypeError) as exc:
            stage_error = ProviderError("CLI_FAILED", f"Codex app-server protocol failed: {exc}; events: {raw_path}")
        finally:
            if goal_requested and not goal_complete and session and proc.poll() is None:
                try:
                    send(6, "thread/goal/clear", {"threadId": session})
                    deadline = min(deadline, time.monotonic() + 5)
                    response(6)
                    goal_cleared_after_failure = True
                except (ProviderError, OSError, KeyError, TypeError):
                    pass
            proc.terminate()
            try:
                app_exit = proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                app_exit = proc.wait(timeout=5)
    if rollout is None:
        home = codex_home or Path(env.get("CODEX_HOME", Path.home() / ".codex"))
        actual_model, actual_effort, actual_program, rollout = _codex_rollout(session or "", home)
    manifest = {
        "provider": "openai", "requested_model": model, "requested_effort": effort,
        "requested_cyber_access_program": "daybreak_blue",
        "actual_model": actual_model, "actual_effort": actual_effort,
        "actual_cyber_access_program": actual_program,
        "session_id": session, "execution_kind": "codex_app_server_daybreak_fresh_session",
        "started_at": started, "ended_at": now(),
        "exit_code": 0 if turn_status == "completed" and goal_complete and stage_error is None else 1,
        "app_server_exit_code": app_exit, "turn_status": turn_status,
        "turn_error": protocol_error,
        "goal_objective": goal_objective, "goal_active": goal_active,
        "goal_complete": goal_complete,
        "goal_cleared_after_failure": goal_cleared_after_failure,
        "events_sha256": digest_file(raw_path),
        "rollout_sha256": digest_file(rollout) if rollout else None,
        "run_dir": str(run_dir),
    }
    if output_path.is_file():
        manifest["output_sha256"] = digest_file(output_path)
    write_json(run_dir / "run-manifest.json", manifest)
    if stage_error is not None:
        raise stage_error
    if turn_status != "completed":
        retryable = isinstance(protocol_error, dict) and protocol_error.get("codexErrorInfo") == "serverOverloaded"
        state = "CAPACITY_RETRY" if retryable else "CLI_FAILED"
        raise ProviderError(state, f"Codex turn failed: {protocol_error}; events: {raw_path}")
    if not goal_complete or data is None:
        raise ProviderError("GOAL_INCOMPLETE", f"Codex stage goal was not completed: {run_dir}")
    return Result(data, manifest, run_dir)


def run_codex(prompt: str, schema: dict, trusted_cwd: Path, run_root: Path,
              *, model: str = "gpt-6-sol", effort: str = "high", timeout: int = 1800,
              executable: str = "codex", codex_home: Path | None = None,
              require_daybreak: bool = True,
              goal_objective: str = "Return the requested structured source-security analysis") -> Result:
    for attempt in range(3):
        try:
            return _run_codex_once(prompt, schema, trusted_cwd, run_root, model=model,
                                   effort=effort, timeout=timeout, executable=executable,
                                   codex_home=codex_home, goal_objective=goal_objective,
                                   require_daybreak=require_daybreak)
        except ProviderError as exc:
            if exc.state != "CAPACITY_RETRY" or attempt == 2:
                raise
            time.sleep(5 * (attempt + 1))
    raise AssertionError("unreachable")


def run_claude(prompt: str, schema: dict, trusted_cwd: Path, run_root: Path,
               *, model: str = "claude-opus-5", effort: str = "high", timeout: int = 1800,
               executable: str = "claude", source_dir: Path | None = None) -> Result:
    if not shutil.which(executable) and not Path(executable).exists():
        raise ProviderError("MISSING_CLI", "Claude Code CLI is not installed")
    run_dir = run_root / uuid.uuid4().hex
    run_dir.mkdir(parents=True, mode=0o700)
    started = now()
    raw_path = run_dir / "events.jsonl"
    command = [executable, "-p", prompt, "--model", model, "--effort", effort,
               "--output-format", "stream-json", "--verbose", "--json-schema", json.dumps(schema),
               "--safe-mode", "--no-session-persistence",
               "--permission-mode", "bypassPermissions", "--tools", "default"]
    if source_dir:
        command += ["--add-dir", str(source_dir)]
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)
    if os.geteuid() == 0:
        # Claude Code refuses bypassPermissions under root. Run its full built-in
        # toolset as a dedicated user; the orchestrator still owns the evidence.
        try:
            account = pwd.getpwnam("whitebox")
        except KeyError as exc:
            raise ProviderError("RUNTIME_USER_MISSING", "whitebox runtime user is missing") from exc
        # A deployment may provide its own live root; never assume a private
        # server path in the public runtime.
        root = Path(os.environ.get("WHITEBOX_ROOT", Path.cwd())).resolve()
        if not trusted_cwd.resolve().is_relative_to(root):
            raise ProviderError("RUNTIME_PATH", "Claude workspace is outside the whitebox root")
        for path in (trusted_cwd, *trusted_cwd.parents):
            if path == root.parent:
                break
            os.chmod(path, stat.S_IMODE(path.stat().st_mode) | stat.S_IXOTH)
        os.chown(trusted_cwd, account.pw_uid, account.pw_gid)
        os.chmod(trusted_cwd, 0o700)
        # Evidence inputs are created by the root orchestrator with a restrictive
        # umask. Claude needs to read its stage workspace, not just enter it.
        for base, dirs, files in os.walk(trusted_cwd, followlinks=False):
            for name in dirs:
                path = Path(base) / name
                if not path.is_symlink():
                    os.chown(path, account.pw_uid, account.pw_gid)
            for name in files:
                path = Path(base) / name
                if not path.is_symlink():
                    os.chown(path, account.pw_uid, account.pw_gid)
        if source_dir:
            source_dir = source_dir.resolve()
            if not source_dir.is_relative_to(root / "source"):
                raise ProviderError("RUNTIME_PATH", "Claude source is outside the source cache")
            for path in (source_dir, *source_dir.parents):
                if path == root.parent:
                    break
                access = stat.S_IXOTH | (stat.S_IROTH if path == source_dir else 0)
                os.chmod(path, stat.S_IMODE(path.stat().st_mode) | access)
            for base, dirs, files in os.walk(source_dir, followlinks=False):
                for name in dirs:
                    path = Path(base) / name
                    if not path.is_symlink():
                        os.chmod(path, stat.S_IMODE(path.stat().st_mode) | stat.S_IROTH | stat.S_IXOTH)
                for name in files:
                    path = Path(base) / name
                    if not path.is_symlink():
                        os.chmod(path, stat.S_IMODE(path.stat().st_mode) | stat.S_IROTH)
        env.update({"HOME": account.pw_dir, "USER": account.pw_name,
                    "LOGNAME": account.pw_name})
        command[0] = "/usr/local/bin/claude"
        command = [_runuser(), "-u", account.pw_name, "--", *command]
    state = {"session": None, "selected_model": None, "actual_model": None,
             "observed_models": set(), "output": None}
    read_calls: dict[str, str] = {}
    successful_reads: set[str] = set()
    with raw_path.open("w") as raw, (run_dir / "stderr.txt").open("w") as stderr:
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=stderr,
                                text=True, cwd=trusted_cwd, env=env)

        def record_events() -> None:
            for line in proc.stdout:
                raw.write(line)
                raw.flush()
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                kind = event.get("type")
                if kind == "system" and event.get("subtype") == "init":
                    state["session"] = event.get("session_id")
                    state["selected_model"] = event.get("model")
                elif kind == "assistant":
                    message = event.get("message") or {}
                    if message.get("model"):
                        state["actual_model"] = message["model"]
                        state["observed_models"].add(message["model"])
                    for block in message.get("content") or []:
                        if block.get("type") == "tool_use" and block.get("name") == "Read":
                            path = (block.get("input") or {}).get("file_path")
                            if isinstance(path, str) and block.get("id"):
                                read_calls[block["id"]] = path
                elif kind == "user":
                    for block in (event.get("message") or {}).get("content") or []:
                        if block.get("type") == "tool_result" and not block.get("is_error"):
                            path = read_calls.get(block.get("tool_use_id"))
                            if path and not str(block.get("content", "")).startswith("Error:"):
                                successful_reads.add(path)
                elif kind == "result":
                    state["output"] = event.get("structured_output") or event.get("result")
                    state["session"] = state["session"] or event.get("session_id")

        reader = threading.Thread(target=record_events, daemon=True)
        reader.start()
        try:
            exit_code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            proc.kill()
            proc.wait(timeout=5)
            reader.join(timeout=5)
            raise ProviderError("TIMEOUT", f"Claude timed out; events: {raw_path}") from exc
        reader.join(timeout=5)
    session, selected_model = state["session"], state["selected_model"]
    actual_model, output = state["actual_model"], state["output"]
    if isinstance(output, str):
        try:
            output = json.loads(output)
        except json.JSONDecodeError:
            output = None
    manifest = {
        "provider": "anthropic", "requested_model": model, "requested_effort": effort,
        "selected_model": selected_model, "actual_model": actual_model,
        "observed_models": sorted(state["observed_models"]),
        "actual_effort": None,  # Claude stream confirms the model, not the selected effort.
        "session_id": session, "execution_kind": "claude_cli_fresh_session",
        "observed_source_reads": sorted(successful_reads),
        "started_at": started, "ended_at": now(), "exit_code": exit_code,
        "events_sha256": digest_file(raw_path), "run_dir": str(run_dir),
    }
    write_json(run_dir / "run-manifest.json", manifest)
    if exit_code != 0:
        stderr_text = (run_dir / "stderr.txt").read_text().lower()
        failure = "AUTH_EXPIRED" if "auth" in stderr_text or "login" in stderr_text else "CLI_FAILED"
        raise ProviderError(failure, f"Claude exited {exit_code}; local diagnostic record: {run_dir}")
    if actual_model != model or not session or any(
            observed != model for observed in state["observed_models"]):
        raise ProviderError("MODEL_FALLBACK", f"Claude actual model missing or changed: {run_dir}")
    if not isinstance(output, dict):
        raise ProviderError("INVALID_OUTPUT", f"Claude structured result missing: {run_dir}")
    write_json(run_dir / "output.json", output)
    manifest["output_sha256"] = digest_file(run_dir / "output.json")
    write_json(run_dir / "run-manifest.json", manifest)
    return Result(output, manifest, run_dir)
