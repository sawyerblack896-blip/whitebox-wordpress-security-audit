"""One disposable Docker container per generic-source experiment.

The source is mounted read-only. Setup may use a network only when the trusted
profile explicitly enables it; test actions run after network removal.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from .lab import LabError, _run, case_record_complete
from .util import now, tree_digest, write_json


DEFAULT_IMAGES = (
    "python:3.12-slim", "node:22-bookworm-slim", "php:8.3-cli",
    "golang:1.25", "rust:1.90", "ubuntu:24.04",
)


def _action(container: str, value: dict, *, setup: bool) -> dict:
    if value.get("kind") != "exec":
        raise LabError("generic Docker plans only support exec actions")
    args = value.get("args")
    if (not isinstance(args, list) or not args or len(args) > 40
            or any(not isinstance(x, str) or not x or len(x) > 8192 for x in args)):
        raise LabError("generic Docker action needs a bounded argv list")
    command = ["docker", "exec", "-w", "/work", container, *args]
    return _run(command, timeout=180)


class DockerLab:
    def __init__(self, source: Path, allowed_images: list[str], *, setup_network: bool = False):
        if not source.is_dir():
            raise LabError("source snapshot is not a directory")
        self.source = source
        self.allowed_images = set(allowed_images)
        self.setup_network = setup_network

    def execute_case(self, image: str, setup: list[dict], actions: list[dict],
                     oracle: list[dict], out: Path) -> Path:
        if image not in self.allowed_images:
            raise LabError(f"runtime image is not in the trusted profile: {image}")
        if not all(isinstance(x, list) and len(x) <= 30 for x in (setup, actions, oracle)):
            raise LabError("generic Docker plan has too many actions")
        container = "wb-" + uuid.uuid4().hex[:16]
        network = "bridge" if self.setup_network else "none"
        command = ["docker", "run", "-d", "--pull", "missing", "--name", container,
                   "--network", network, "--pids-limit", "1024", "--cap-drop", "ALL",
                   "--security-opt", "no-new-privileges", "--user", "1000:1000",
                   "--tmpfs", "/work:rw,exec,uid=1000,gid=1000",
                   "--tmpfs", "/tmp:rw,exec,uid=1000,gid=1000", "--mount",
                   f"type=bind,src={self.source.resolve()},dst=/source,readonly",
                   "--entrypoint", "sh", image, "-c",
                   "cp -R /source/. /work/ && touch /work/.wb-ready && sleep infinity"]
        record = {"container": container, "started_at": now(), "source_tree_sha256": tree_digest(self.source),
                  "image": image, "setup_network": self.setup_network,
                  "setup": [], "actions": [], "oracle": []}
        created = False
        try:
            started = _run(command, timeout=300)
            if started["exit_code"] != 0:
                raise LabError(f"Docker case did not start: {started['stderr'][-800:]}")
            created = True
            deadline = time.monotonic() + 180
            while True:
                ready = _run(["docker", "exec", container, "test", "-f", "/work/.wb-ready"], timeout=15)
                if ready["exit_code"] == 0:
                    break
                running = _run(["docker", "inspect", container, "--format",
                                "{{.State.Running}}"], timeout=15)
                if running["exit_code"] or running["stdout"].strip() != "true":
                    logs = _run(["docker", "logs", container], timeout=15)
                    raise LabError(f"Docker source copy failed: {logs['stderr'][-800:] or logs['stdout'][-800:]}")
                if time.monotonic() >= deadline:
                    raise LabError("Docker source copy did not finish within 180 seconds")
                time.sleep(0.25)
            inspected = _run(["docker", "inspect", container, "--format", "{{.Image}}"], timeout=30)
            if inspected["exit_code"] or not inspected["stdout"].strip():
                raise LabError("could not identify the exact Docker image used by the case")
            record["image_id"] = inspected["stdout"].strip()
            for step in setup:
                result = _action(container, step, setup=True)
                record["setup"].append({"action": step, "result": result})
                write_json(out, record)
                if result["exit_code"]:
                    raise LabError(f"generic Docker setup failed; see {out}")
            if self.setup_network:
                detached = _run(["docker", "network", "disconnect", "bridge", container], timeout=30)
                if detached["exit_code"]:
                    raise LabError("could not remove Docker setup network before tests")
            record["test_network"] = "none"
            for section, steps in (("actions", actions), ("oracle", oracle)):
                for step in steps:
                    result = _action(container, step, setup=False)
                    record[section].append({"action": step, "result": result})
                    write_json(out, record)
            record["ended_at"] = now()
            return out
        finally:
            if created:
                cleaned = _run(["docker", "rm", "-f", container], timeout=120)
                if cleaned["exit_code"]:
                    record["cleanup_error"] = cleaned["stderr"][-800:]
            write_json(out, record)


def run_docker_plan(lab: DockerLab, plan: dict, out: Path) -> list[Path]:
    if plan.get("decision") != "TEST" or not plan.get("positive") or not plan.get("negative"):
        raise LabError("candidate lacks positive and negative Docker actions")
    image = plan.get("runtime_image", "")
    if not isinstance(image, str) or image not in lab.allowed_images:
        raise LabError("plan did not choose an allowed Docker image")
    out.mkdir(parents=True, exist_ok=True)
    records = []
    for label in ("positive", "negative", "pristine-replay"):
        path = out / f"{label}.json"
        if path.exists():
            try:
                saved = json.loads(path.read_text())
                actions = plan["negative"] if label == "negative" else plan["positive"]
                if (saved.get("source_tree_sha256") == tree_digest(lab.source)
                        and saved.get("image") == image and saved.get("image_id")
                        and saved.get("test_network") == "none"
                        and case_record_complete(saved, plan.get("setup", []), actions,
                                                 plan.get("oracle", []))):
                    records.append(path)
                    continue
            except (ValueError, OSError):
                pass
        actions = plan["negative"] if label == "negative" else plan["positive"]
        created = lab.execute_case(image, plan.get("setup", []), actions,
                                  plan.get("oracle", []), path)
        saved = json.loads(created.read_text())
        if (saved.get("source_tree_sha256") != tree_digest(lab.source)
                or saved.get("image") != image or not saved.get("image_id")
                or saved.get("test_network") != "none"
                or not case_record_complete(saved, plan.get("setup", []), actions,
                                            plan.get("oracle", []))):
            raise LabError(f"generic Docker case has incomplete raw evidence or cleanup: {created}")
        records.append(created)
    image_ids = {json.loads(path.read_text()).get("image_id") for path in records}
    if len(image_ids) != 1 or None in image_ids:
        raise LabError("generic Docker controls used different image IDs")
    return records
