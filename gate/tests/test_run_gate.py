from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gate import run_gate


class TestGateDecisions(unittest.TestCase):
    def test_baseline_failure_rejects(self):
        verdict, _ = run_gate.decide(
            [{"status": "FAIL"}],
            [{"status": "PASS"}],
            {"block_on_baseline_fail": True, "block_on_any_golden_fail": True},
        )
        self.assertEqual(verdict, "REJECTED")

    def test_golden_failure_blocks(self):
        verdict, _ = run_gate.decide(
            [{"status": "PASS"}],
            [{"status": "FAIL"}],
            {"block_on_baseline_fail": True, "block_on_any_golden_fail": True},
        )
        self.assertEqual(verdict, "BLOCKED")

    def test_all_golden_skipped_is_not_ready(self):
        verdict, _ = run_gate.decide(
            [{"status": "PASS"}],
            [{"status": "SKIP"}],
            {"require_enabled_golden": True},
        )
        self.assertEqual(verdict, "NOT_READY")

    def test_enabled_golden_pass_reaches_l2(self):
        verdict, _ = run_gate.decide(
            [{"status": "PASS"}],
            [{"status": "PASS"}],
            {
                "block_on_baseline_fail": True,
                "block_on_any_golden_fail": True,
                "require_enabled_golden": True,
            },
        )
        self.assertEqual(verdict, "READY_FOR_L2")


class TestSafeExecution(unittest.TestCase):
    def test_shell_string_is_rejected(self):
        result = run_gate.run_group(
            [{"id": "BAD", "enabled": True, "cmd": "echo unsafe"}],
            {"workdir": ".", "timeout_sec": 1},
        )
        self.assertEqual(result[0]["status"], "FAIL")
        self.assertEqual(result[0]["exit"], 125)

    def test_workdir_escape_is_rejected(self):
        result = run_gate.run_group(
            [{"id": "BAD", "enabled": True, "cmd": ["python3", "-V"], "workdir": "../"}],
            {"workdir": ".", "timeout_sec": 1},
        )
        self.assertEqual(result[0]["status"], "FAIL")

    def test_job_id_validation(self):
        self.assertIsNotNone(run_gate.JOB_RE.fullmatch("JOB-0001"))
        self.assertIsNone(run_gate.JOB_RE.fullmatch("job-1"))

    def test_requirements_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "requirements.md"
            path.write_text("Objective: test\n", encoding="utf-8")
            result = run_gate.validate_requirements(path)
            self.assertEqual(result["status"], "present")
            self.assertEqual(len(result["sha256"]), 64)


class TestStatusParser(unittest.TestCase):
    def test_paths_include_ordinary_and_untracked(self):
        raw = " M file.py\0?? new.txt\0"
        self.assertEqual(run_gate.parse_porcelain_paths(raw), {"file.py", "new.txt"})

    def test_paths_include_both_rename_sides(self):
        raw = "R  new.py\0old.py\0"
        self.assertEqual(run_gate.parse_porcelain_paths(raw), {"new.py", "old.py"})


if __name__ == "__main__":
    unittest.main()
