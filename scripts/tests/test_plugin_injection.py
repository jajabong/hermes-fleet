"""Tests for on-demand plugin injection (P1) in dispatcher.py."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dispatcher import _match_plugins, PLUGIN_KEYWORD_MAP  # noqa: E402

PLUGS = ["dsh-ppt", "dsh-excel-chat", "dsh-browser", "dsh-docker",
         "dsh-email", "dsh-mneme", "dsh-data-agent", "dsh-vision-router"]


def test_map_has_minimum_plugins():
    for name in ("dsh-excel-chat", "dsh-ppt", "dsh-browser", "dsh-doc",
                 "dsh-doc-share", "dsh-vision-router", "dsh-email",
                 "dsh-docker", "dsh-data-agent", "dsh-mneme"):
        assert name in PLUGIN_KEYWORD_MAP


def test_match_ppt():
    assert _match_plugins("make a PPT for the quarterly review", PLUGS) == ["dsh-ppt"]


def test_match_excel():
    assert _match_plugins("analyze xlsx sales data", PLUGS) == ["dsh-excel-chat"]


def test_match_email():
    assert _match_plugins("send an email report", PLUGS) == ["dsh-email"]


def test_match_multiple():
    got = _match_plugins("screenshot the browser and email it", PLUGS)
    assert "dsh-browser" in got
    assert "dsh-email" in got


def test_no_match_returns_empty():
    assert _match_plugins("hello there", PLUGS) == []


def test_case_insensitive():
    assert _match_plugins("MAKE A SLIDES DECK", PLUGS) == ["dsh-ppt"]


def test_unknown_plugin_not_matched_by_default():
    got = _match_plugins("make a ppt", ["dsh-mystery-plugin", "dsh-ppt"])
    assert got == ["dsh-ppt"]


def test_result_is_subset_and_shorter_than_all():
    matched = _match_plugins("make a ppt", PLUGS)
    assert matched == ["dsh-ppt"]
    assert len(matched) < len(PLUGS)
