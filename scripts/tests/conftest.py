import sys
from pathlib import Path

sys.path.insert(0, "/Users/henry/scratch/hermes-fleet/scripts")

ARTIFACT_ROOT = Path.home() / ".hermes" / "artifacts" / "queen"


def make_plan(tasks, run_id_prefix="test"):
    import uuid

    return {
        "version": "1",
        "run_id": run_id_prefix + uuid.uuid4().hex[:8],
        "project_root": "/tmp",
        "risk_level": "LOW",
        "sandbox": "fs:loose",
        "tasks": tasks,
    }
