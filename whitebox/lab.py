"""Execute bounded model plans only inside disposable, offline WordPress cases."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from .util import digest_file, now, write_json


class LabError(RuntimeError):
    pass


def case_record_complete(record: dict, setup: list[dict], actions: list[dict],
                         oracle: list[dict]) -> bool:
    """Check raw case evidence, including a successful cleanup and exact plan binding."""
    if not record.get("ended_at") or record.get("cleanup_error"):
        return False
    for section, expected in (("setup", setup), ("actions", actions), ("oracle", oracle)):
        actual = record.get(section)
        if (not isinstance(actual, list) or len(actual) != len(expected)
                or any(not isinstance(item, dict) or item.get("action") != step
                       or not isinstance(item.get("result"), dict)
                       or type(item["result"].get("exit_code")) is not int
                       or (section == "setup" and item["result"]["exit_code"] != 0)
                       for item, step in zip(actual, expected))):
            return False
    return True


def _run(args: list[str], *, cwd: Path | None = None, input_text: str | None = None,
         timeout: int = 90) -> dict:
    try:
        result = subprocess.run(args, input=input_text, text=True, capture_output=True,
                                cwd=cwd, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise LabError(f"local lab command timed out: {args[:3]}") from exc
    return {"exit_code": result.returncode, "stdout": result.stdout[:1048576],
            "stderr": result.stderr[:65536]}


class WordPressFarm:
    def __init__(self, farm: Path, dependencies: list[Path] | None = None):
        self.farm = farm
        self.dependencies = dependencies or []
        self.script = farm / "farm.py"
        if not self.script.is_file():
            raise LabError(f"WordPress farm missing: {self.script}")

    def _farm(self, *args: str, timeout: int = 180) -> dict:
        return _run(["python3", str(self.script), *args], cwd=self.farm, timeout=timeout)

    def create(self, package: Path) -> str:
        args = ["create", "auto", "--plugin-zip", str(package), "--wait-seconds", "60"]
        for dependency in self.dependencies:
            args.extend(["--dependency-zip", str(dependency)])
        result = self._farm(*args, timeout=300)
        if result["exit_code"] != 0:
            raise LabError(f"case creation failed: {result['stderr'][-800:]}")
        try:
            details = json.loads(result["stdout"].splitlines()[-1])
            case = details["case"]
        except (ValueError, KeyError, IndexError) as exc:
            raise LabError("farm returned no case ID") from exc
        if not re.fullmatch(r"case-[a-f0-9]{12}", case):
            raise LabError("farm returned an invalid case ID")
        return case

    def action(self, case: str, action: dict) -> dict:
        kind = action.get("kind")
        if kind == "wp":
            args = action.get("args")
            if not isinstance(args, list) or not args or len(args) > 30 or any(
                    not isinstance(x, str) or len(x) > 8192 for x in args):
                raise LabError("invalid WP-CLI action")
            return self._farm("wp", case, *args, timeout=90)
        compose = ["docker", "compose", "-p", f"wff-{case}", "-f",
                   str(self.farm / "runs" / case / "compose.yaml"), "exec", "-T", "web"]
        if kind == "http":
            method, path = action.get("method", "GET"), action.get("path", "")
            if method not in {"GET", "POST", "PUT", "DELETE"} or not isinstance(path, str) or not path.startswith("/"):
                raise LabError("HTTP action must use a local absolute path")
            if any(x in path for x in ("\n", "\r", "\x00")) or path.startswith("//") or len(path) > 4096:
                raise LabError("unsafe HTTP path")
            headers = action.get("headers", [])
            if not isinstance(headers, list) or len(headers) > 20:
                raise LabError("invalid headers")
            cmd = compose + ["curl", "-i", "-sS", "--max-time", "20", "--path-as-is",
                             "--request", method]
            for header in headers:
                if not isinstance(header, dict) or set(header) != {"name", "value"}:
                    raise LabError("invalid HTTP header item")
                key, value = header["name"], header["value"]
                if not re.fullmatch(r"[A-Za-z0-9-]{1,60}", key) or key.lower() == "host":
                    raise LabError("invalid HTTP header name")
                if not isinstance(value, str) or any(x in value for x in "\r\n\x00") or len(value) > 4096:
                    raise LabError("invalid HTTP header value")
                cmd += ["--header", f"{key}: {value}"]
            body = action.get("body", "")
            if not isinstance(body, str) or len(body.encode()) > 65536:
                raise LabError("HTTP request body exceeds limit")
            if body:
                cmd += ["--data-binary", "@-"]
            cmd.append("http://localhost" + path)
            return _run(cmd, cwd=self.farm, input_text=body or None, timeout=30)
        if kind == "php":
            code = action.get("code")
            if not isinstance(code, str) or not code or len(code.encode()) > 32768:
                raise LabError("PHP test code exceeds limit")
            return _run(compose + ["php", "-r", code], cwd=self.farm, timeout=30)
        raise LabError(f"unsupported local action: {kind}")

    def destroy(self, case: str) -> dict:
        return self._farm("destroy", case, "--confirm", timeout=180)

    def execute_case(self, package: Path, setup: list[dict], actions: list[dict],
                     oracle: list[dict], out: Path) -> Path:
        if not all(isinstance(x, list) and len(x) <= 20 for x in (setup, actions, oracle)):
            raise LabError("plan has too many actions")
        case = self.create(package)
        record = {"case": case, "started_at": now(), "package_sha256": digest_file(package),
                  "setup": [], "actions": [], "oracle": []}
        try:
            for section, steps in (("setup", setup), ("actions", actions), ("oracle", oracle)):
                for action in steps:
                    result = self.action(case, action)
                    record[section].append({"action": action, "result": result})
                    write_json(out, record)
                    if result["exit_code"] != 0 and section == "setup":
                        raise LabError(f"setup action failed in {case}; see {out}")
            record["ended_at"] = now()
        finally:
            # Export the record before destroying the disposable lab.
            write_json(out, record)
            clean = self.destroy(case)
            if clean["exit_code"] != 0:
                record["cleanup_error"] = clean["stderr"][-800:]
                write_json(out, record)
        return out


def run_plan(farm: WordPressFarm, package: Path, plan: dict, out: Path) -> list[Path]:
    if plan.get("decision") != "TEST" or not plan.get("positive") or not plan.get("negative"):
        raise LabError("candidate lacks positive and negative test sequences")
    out.mkdir(parents=True, exist_ok=True)
    setup, oracle = plan.get("setup", []), plan.get("oracle", [])
    records = []
    for label in ("positive", "negative", "pristine-replay"):
        steps = plan["positive"] if label != "negative" else plan["negative"]
        record = out / f"{label}.json"
        if record.exists():
            try:
                saved = json.loads(record.read_text())
                if (saved.get("package_sha256") == digest_file(package)
                        and case_record_complete(saved, setup, steps, oracle)):
                    records.append(record)
                    continue
            except (ValueError, OSError):
                pass
        created = farm.execute_case(package, setup, steps, oracle, record)
        saved = json.loads(created.read_text())
        if saved.get("package_sha256") != digest_file(package) or not case_record_complete(
                saved, setup, steps, oracle):
            raise LabError(f"local case has incomplete raw evidence or cleanup: {created}")
        records.append(created)
    return records
