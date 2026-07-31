#!/usr/bin/env python3
"""Unit tests for review-gate risk routing and schema validation."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SCRIPT = SCRIPT_DIR / "review_gate.py"
sys.path.insert(0, str(SCRIPT_DIR))

from l2_from_opencode import explicit_verdict as l2_explicit_verdict
from l3_from_pi import explicit_verdict as l3_explicit_verdict


def run(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True,
    )


class ReviewGateTests(unittest.TestCase):
    def test_low_route(self):
        with tempfile.TemporaryDirectory() as td:
            m = Path(td) / "manifest.json"
            m.write_text(json.dumps({
                "run_id": "t-low",
                "project_root": "/tmp",
                "goal": "docs",
                "acceptance_criteria": ["docs ok"],
                "base_ref": "HEAD",
                "head_ref": "WORKTREE",
                "changed_files": ["README.md"],
                "risk_level": "MEDIUM",
                "risk_reasons": ["documentation only", "no behaviour change"],
                "started_at": "x",
                "completed_at": None,
                "status": "in_progress",
            }))
            r = run("classify", "--manifest", str(m))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(m.read_text())["risk_level"], "LOW")
            r = run("route", "--manifest", str(m))
            self.assertEqual(r.returncode, 0, r.stderr)
            data = json.loads(r.stdout)
            self.assertEqual(data["layers"], ["L1", "L2-light"])
            self.assertFalse(data["l3_required"])

    def test_high_route(self):
        with tempfile.TemporaryDirectory() as td:
            m = Path(td) / "manifest.json"
            m.write_text(json.dumps({
                "run_id": "t-high",
                "project_root": "/tmp",
                "goal": "auth",
                "acceptance_criteria": ["secure"],
                "base_ref": "HEAD",
                "head_ref": "WORKTREE",
                "changed_files": ["auth.py"],
                "risk_level": "MEDIUM",
                "risk_reasons": ["auth change", "public api"],
                "started_at": "x",
                "completed_at": None,
                "status": "in_progress",
            }))
            r = run("classify", "--manifest", str(m))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(m.read_text())["risk_level"], "HIGH")
            r = run("route", "--manifest", str(m))
            data = json.loads(r.stdout)
            self.assertEqual(data["layers"], ["L1", "L2", "L3"])
            self.assertTrue(data["l3_required"])

    def test_markdown_bold_verdicts(self):
        samples = {
            "**Verdict: PASS** (standalone)": "PASS",
            "### Verdict\n**PASS**": "PASS",
            "**PASS_WITH_NOTES**": "PASS_WITH_NOTES",
            "**Recommendation: CHANGES_REQUIRED**": "CHANGES_REQUIRED",
        }
        for raw, expected in samples.items():
            with self.subTest(raw=raw):
                self.assertEqual(l2_explicit_verdict(raw), expected)
                self.assertEqual(l3_explicit_verdict(raw), expected)

    def test_verdict_does_not_match_mid_sentence(self):
        raw = "This is not a verdict PASS in prose."
        self.assertIsNone(l2_explicit_verdict(raw))
        self.assertIsNone(l3_explicit_verdict(raw))

    def test_l2_schema_requires_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "l2.json"
            f.write_text(json.dumps({
                "verdict": "CHANGES_REQUIRED",
                "findings": [{
                    "severity": "high",
                    "category": "security",
                    "title": "missing authz",
                    "evidence": [],
                    "impact": "privilege",
                    "recommendation": "add check",
                    "confidence": 0.9,
                }],
                "commands_reviewed": [],
                "tests_missing": [],
                "escalation_required": True,
                "escalation_reasons": ["high finding"],
            }))
            r = run("validate", "--kind", "l2", "--file", str(f))
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("path:line", r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
