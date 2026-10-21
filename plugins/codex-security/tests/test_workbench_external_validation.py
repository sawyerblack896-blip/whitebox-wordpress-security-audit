from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from workbench_test_support import run_workbench, write_completed_contract


def test_external_validation_binds_host_owned_finding_ids_before_indexing(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    target = tmp_path / "target"
    scan_dir = tmp_path / "scan"
    target.mkdir()
    scan_dir.mkdir(mode=0o700)
    registered = run_workbench(
        state_dir,
        "register-cli-scan",
        "--scan-dir",
        str(scan_dir),
        "--repository",
        str(target),
        "--recipe-json",
        json.dumps(
            {
                "config": {},
                "mode": "standard",
                "repository": str(target),
                "target": {"kind": "repository", "paths": []},
                "validationMode": "external",
            }
        ),
    )
    scan_id = str(registered["scanId"])
    write_completed_contract(scan_dir, scan_id, target)

    draft = json.loads((scan_dir / "findings.json").read_text())
    assert "findingId" not in draft["findings"][0]

    completed = run_workbench(
        state_dir, "complete-external-validation", "--scan-id", scan_id
    )

    persisted = json.loads((scan_dir / "findings.json").read_text())
    finding = persisted["findings"][0]
    assert finding["findingId"].startswith("csf_")
    assert finding["occurrenceId"].startswith("occ_")
    assert finding["fingerprints"]["algorithm"] == "codex-security/v1"
    assert completed["scan"]["progress"]["status"] == "complete"
    with sqlite3.connect(state_dir / "workbench.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM findings").fetchone() == (1,)
        assert connection.execute("SELECT COUNT(*) FROM finding_occurrences").fetchone() == (1,)
