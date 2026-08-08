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

    def test_T_Tier2_retry_on_ssl_error_syscall(self):
        """T-Tier2-pattern: Tier 1 fails with SSL_ERROR_SYSCALL → Tier 2 with proxy."""
        from unittest.mock import patch as _patch, MagicMock

        with self._td() as td:
            _, work = _make_local_remote(Path(td))
            # Two mocked subprocess.run results: T1 fail, T2 success.
            t1_result = MagicMock(returncode=1, stdout="", stderr="fatal: unable to access 'https://github.com/x/y.git/': OpenSSL SSL_connect: SSL_ERROR_SYSCALL in connection to github.com:443")
            t2_result = MagicMock(returncode=0, stdout="Everything up-to-date\n", stderr="")
            side_effects = [t1_result, t2_result]
            with _patch("subprocess.run", side_effect=side_effects) as mock_run:
                r = auto_run.cmd_git_push(str(work), remote="origin", branch="main")

            # T1 called, T2 called → exactly 2 invocations
            self.assertEqual(mock_run.call_count, 2,
                             f"expected 2 subprocess calls (Tier 1 + Tier 2), got {mock_run.call_count}")

            # Tier 1 call should have -c http.proxy= (empty override)
            t1_call = mock_run.call_args_list[0]
            t1_argv = t1_call.args[0]
            self.assertIn("-c", t1_argv)
            self.assertIn("http.proxy=", t1_argv)
            # Last two args should be push + remote + branch
            self.assertEqual(t1_argv[-3:], ["push", "origin", "main"])

            # Tier 2 call should set mihomo proxy
            t2_call = mock_run.call_args_list[1]
            t2_argv = t2_call.args[0]
            joined = " ".join(t2_argv)
            self.assertIn("http.proxy=http://127.0.0.1:7897", joined)
            self.assertIn("http.https://github.com.proxy=http://127.0.0.1:7897", joined)
            self.assertEqual(t2_argv[-3:], ["push", "origin", "main"])

            # Result: exit 0, tier_used=2, retried=True
            self.assertEqual(r["exit"], 0, f"stderr: {r.get('stderr')}")
            self.assertEqual(r["tier_used"], 2)
            self.assertTrue(r["retried"])
            self.assertIn("SSL_ERROR_SYSCALL", r["tier1_stderr"])

    def test_T_Tier1_no_retry_on_non_network_failure(self):
        """T-Tier1-no-retry: Tier 1 fails with non-retryable stderr → no Tier 2."""
        from unittest.mock import patch as _patch, MagicMock

        with self._td() as td:
            _, work = _make_local_remote(Path(td))
            t1_result = MagicMock(returncode=128, stdout="", stderr="error: src refspec main does not match any")
            with _patch("subprocess.run", return_value=t1_result) as mock_run:
                r = auto_run.cmd_git_push(str(work), remote="origin", branch="main")

            self.assertEqual(mock_run.call_count, 1,
                             "should NOT retry on non-network failure")
            self.assertEqual(r["exit"], 128)
            self.assertEqual(r["tier_used"], 1)
            self.assertFalse(r["retried"])

    def test_T_pattern_regex_matches_three_signals(self):
        """T-pattern: _PUSH_RETRY_PATTERN matches the three documented signals."""
        signals = [
            "SSL_ERROR_SYSCALL in connection to github.com:443",
            "fatal: unable to access ... connect to github.com 443 timeout",
            "Connection reset by peer",
        ]
        for s in signals:
            self.assertIsNotNone(
                auto_run._PUSH_RETRY_PATTERN.search(s),
                f"pattern should match: {s!r}",
            )
        # Negative: should NOT match non-retryable errors
        non_signals = [
            "error: src refspec main does not match any",
            "Permission denied (publickey).",
        ]
        for s in non_signals:
            self.assertIsNone(
                auto_run._PUSH_RETRY_PATTERN.search(s),
                f"pattern should NOT match: {s!r}",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
