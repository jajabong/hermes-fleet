"""Tests for hermes_subagent.py (P0 + P4). Stdlib only, no network."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hermes_subagent as h


def test_provider_defaults():
    assert h.PROVIDER_DEFAULTS["deepseek-official"] == (
        "https://api.deepseek.com/v1", "deepseek-v4-flash")
    assert h.PROVIDER_DEFAULTS["minimax"] == (
        "https://api.minimaxi.com/v1", "MiniMax-M3")


def test_estimate_tokens():
    assert h._estimate_tokens("") == 1
    assert h._estimate_tokens("hello world") == 3


def test_load_settings_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(h, "DSH_SETTINGS", tmp_path / "settings.yaml")
    assert h._load_settings() == {}


def test_load_settings_parses_providers(tmp_path, monkeypatch):
    settings = tmp_path / "settings.yaml"
    settings.write_text(
        "llm-pi-ai:\n"
        "  providers:\n"
        "    deepseek-official:\n"
        "      apiKey: sk-a\n"
        "    minimax:\n"
        "      apiKey: sk-b\n"
        "      baseURL: https://api.minimaxi.com/v1\n"
    )
    monkeypatch.setattr(h, "DSH_SETTINGS", settings)
    assert h._api_key("deepseek-official") == "sk-a"
    assert h._api_key("minimax") == "sk-b"
    assert h._provider_cfg("minimax")["baseURL"] == "https://api.minimaxi.com/v1"
    assert h._api_key("nope") is None


def test_missing_key_returns_error(tmp_path, monkeypatch):
    monkeypatch.setattr(h, "DSH_SETTINGS", tmp_path / "settings.yaml")
    r = h.run_subagent("hi")
    assert r == {"error": "missing-api-key"}


def test_unknown_provider_returns_error(tmp_path, monkeypatch):
    monkeypatch.setattr(h, "DSH_SETTINGS", tmp_path / "settings.yaml")
    r = h.run_subagent("hi", provider="does-not-exist")
    assert r["error"] == "api-error"
    assert "unknown provider" in r["message"]


def test_tool_whitelist():
    assert {"web_search", "web_fetch", "read_file", "write_file",
            "bash", "list_dir", "search_files"} <= h.TOOL_WHITELIST


def test_execute_tool_blocked():
    r = h._execute_tool("evil", {})
    assert "not allowed" in r


def test_execute_tool_read_file(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("hello")
    assert h._execute_tool("read_file", {"path": str(f)}) == "hello"


def test_execute_tool_read_file_missing():
    assert h._execute_tool("read_file", {"path": "/nonexistent/x"}).startswith("error")


def test_execute_tool_write_file(tmp_path):
    f = tmp_path / "out.txt"
    r = h._execute_tool("write_file", {"path": str(f), "content": "data"})
    assert f.read_text() == "data"
    assert "wrote 4 bytes" in r


def test_execute_tool_bash():
    r = h._execute_tool("bash", {"cmd": "echo hi"})
    assert r.strip() == "hi"


def test_execute_tool_list_dir(tmp_path):
    (tmp_path / "one").write_text("x")
    r = h._execute_tool("list_dir", {"path": str(tmp_path)})
    assert "one" in r


def test_execute_tool_bad_args():
    r = h._execute_tool("read_file", {})
    assert "bad arguments" in r


def test_run_subagent_with_tools_missing_key(tmp_path, monkeypatch):
    monkeypatch.setattr(h, "DSH_SETTINGS", tmp_path / "settings.yaml")
    assert h.run_subagent_with_tools("hi") == {"error": "missing-api-key"}


def test_main_help_caps_stdout(capsys):
    with pytest.raises(SystemExit):
        h.main(["--help"])
    out = capsys.readouterr().out
    assert "--tools" in out
