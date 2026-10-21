"""Public long-lived audit Goal controller.

This is the non-policy part of the production architecture: pin a source tree,
keep one resumable investigation Goal, checkpoint every model turn, and stop
only at the deployment's time boundary. Target selection, Wordfence rules,
prompts, and submission qualification are deliberately injected by a private
adapter and are not part of this public module.
"""
from __future__ import annotations

import argparse
import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Protocol

from .providers import Result, run_claude, run_codex
from .util import now, write_json


class PromptAdapter(Protocol):
    def __call__(self, state: Mapping[str, object]) -> tuple[str, dict]: ...


@dataclass(frozen=True)
class GoalConfig:
    target: str
    source_dir: Path
    work_dir: Path
    provider: str = "codex"
    model: str = "gpt-6-sol"
    effort: str = "high"
    budget_seconds: float = 6 * 3600
    turn_timeout: int = 1800


class AuditGoal:
    """Checkpointed investigation loop with no target-selection or policy logic."""

    def __init__(self, config: GoalConfig, prompt_adapter: PromptAdapter):
        self.config = config
        self.prompt_adapter = prompt_adapter
        self.config.work_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.config.work_dir / "goal-state.json"
        self.turns_dir = self.config.work_dir / "turns"
        self.turns_dir.mkdir(exist_ok=True)

    def _load(self) -> dict:
        if self.state_path.exists():
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                return value
        return {
            "schema": "whitebox-audit-goal/1",
            "goal_id": uuid.uuid4().hex,
            "target": self.config.target,
            "source_dir": str(self.config.source_dir),
            "provider": self.config.provider,
            "model": self.config.model,
            "effort": self.config.effort,
            "started_at": now(),
            "updated_at": now(),
            "turn": 0,
            "status": "OPEN",
            "session_id": None,
            "observations": [],
        }

    def _save(self, state: dict) -> None:
        state["updated_at"] = now()
        write_json(self.state_path, state)

    def run(self) -> dict:
        state = self._load()
        deadline = time.monotonic() + max(1.0, self.config.budget_seconds)
        state["status"] = "RUNNING"
        self._save(state)
        while time.monotonic() < deadline:
            prompt, schema = self.prompt_adapter(state)
            run_root = self.turns_dir / f"turn-{int(state['turn']) + 1:04d}"
            try:
                if self.config.provider == "claude":
                    result: Result = run_claude(
                        prompt, schema, self.config.source_dir, run_root,
                        model=self.config.model, effort=self.config.effort,
                        timeout=self.config.turn_timeout, source_dir=self.config.source_dir)
                else:
                    result = run_codex(
                        prompt, schema, self.config.source_dir, run_root,
                        model=self.config.model, effort=self.config.effort,
                        timeout=self.config.turn_timeout,
                        goal_objective=("Investigate the pinned source deeply and checkpoint "
                                        "the next evidence-backed direction"),
                        require_daybreak=False)
            except Exception as exc:  # checkpoint the failure; the next invocation resumes
                state["status"] = "ERROR"
                state["last_error"] = f"{type(exc).__name__}: {exc}"
                self._save(state)
                return state
            state["turn"] = int(state.get("turn", 0)) + 1
            state["session_id"] = result.manifest.get("session_id")
            state["last_manifest"] = str(result.directory / "manifest.json")
            state["observations"].append(result.data)
            self._save(state)
            # The model's structured result decides whether this Goal is still active.
            if result.data.get("goal_status") in {"complete", "no_further_direction"}:
                state["status"] = "COMPLETE"
                self._save(state)
                return state
        state["status"] = "TIME_BOUNDARY"
        self._save(state)
        return state


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a deployment-supplied audit Goal")
    parser.add_argument("--target", required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--prompt-file", type=Path, required=True,
                        help="deployment-owned prompt/schema JSON; not shipped publicly")
    parser.add_argument("--seconds", type=float, default=6 * 3600)
    args = parser.parse_args(argv)
    prompt_doc = json.loads(args.prompt_file.read_text(encoding="utf-8"))

    def adapter(_state: Mapping[str, object]) -> tuple[str, dict]:
        return str(prompt_doc["prompt"]), dict(prompt_doc["schema"])

    result = AuditGoal(GoalConfig(args.target, args.source, args.work,
                                  budget_seconds=args.seconds), adapter).run()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") in {"COMPLETE", "TIME_BOUNDARY"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
