#!/usr/bin/env python3
"""Tests for auto_run.py cmd_git_push (v29.8 git-push helper, P1 #9 fix)."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

import auto_run  # noqa: E402


def _make_local_remote(tmp_path):
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    subprocess.run(["git", "init", "--bare", "-q", "-b", "main", str(remote)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(work)], check=True)
    subprocess.run(["git", "-C", str(work), "config", "user.email", "t@l"], check=True)
    subprocess.run(["git", "-C", str(work), "config", "user.name", "t"], check=True)
    (work / "README.md").write_text("test\n")
    subprocess.run(["git", "-C", str(work), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(work), "commit", "-q", "-m", "init"], check=True)
    subprocess.run(["git", "-C", str(work), "remote", "add", "origin", str(remote)], check=True)
    subprocess.run(["git", "-C", str(work), "push", "-q", "origin", "main"], check=True)
    return remote, work


class CmdGitPushTests(unittest.TestCase):

    @contextmanager
    def _td(self):
        with tempfile.TemporaryDirectory() as t:
            yield t

    def test_T3_nonexistent_path(self):
        bogus = "/tmp/auto_run_test_nonexistent_xyz123"
        r = auto_run.cmd_git_push(bogus)
        self.assertEqual(r["exit"], 1)
        self.assertIn("not a directory", r.get("error", ""))
        self.assertIn(bogus, r["error"])

    def test_T4_existing_dir_no_dot_git(self):
        with self._td() as td:
            r = auto_run.cmd_git_push(td)
            self.assertEqual(r["exit"], 1)
            self.assertIn("not a git repo", r.get("error", ""))

    def test_T6_tilde_expansion(self):
        with self._td() as td:
            orig = os.path.expanduser
            try:
                os.path.expanduser = lambda p: p.replace("~", td)
                r = auto_run.cmd_git_push("~/nope_xyz")
                self.assertEqual(r["exit"], 1)
                self.assertNotIn("~/", r["error"])
                self.assertIn("nope_xyz", r["error"])
            finally:
                os.path.expanduser = orig

    def test_T5_local_push_succeeds(self):
        with self._td() as td:
            remote, work = _make_local_remote(Path(td))
            (work / "new.txt").write_text("hi\n")
            subprocess.run(["git", "-C", str(work), "add", "new.txt"], check=True)
            subprocess.run(["git", "-C", str(work), "commit", "-q", "-m", "second"], check=True)
            r = auto_run.cmd_git_push(str(work), remote="origin", branch="main")
            self.assertEqual(r["exit"], 0, f"stderr: {r.get('stderr')}")
            self.assertEqual(r["task"], "git-push")
            self.assertEqual(r["repo_dir"], str(work))

    def test_T5b_subprocess_env_unsets_proxy(self):
        with self._td() as td:
            remote, work = _make_local_remote(Path(td))
            saved = {}
            for k in ("http_proxy", "https_proxy", "all_proxy"):
                saved[k] = os.environ.get(k)
                os.environ[k] = "http://evil-proxy:9999"
            try:
                r = auto_run.cmd_git_push(str(work), remote="origin", branch="main")
                self.assertEqual(r["exit"], 0, f"stderr: {r.get('stderr')}")
            finally:
                for k, v in saved.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v


if __name__ == "__main__":
    unittest.main(verbosity=2)
