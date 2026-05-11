"""Unit tests for yt-dlp download preset ordering (no network)."""

from __future__ import annotations

import pytest

from llm_from_here.plugins.ytfetch import build_yt_dlp_download_attempt_opts


def _clear_yt_dlp_strategy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("YT_DLP_DISABLE_FALLBACK", raising=False)
    monkeypatch.delenv("YT_DLP_VANILLA_FIRST", raising=False)
    for key in (
        "YT_DLP_COOKIE_FILE",
        "YT_DLP_IMPERSONATE",
        "YT_DLP_PLAYER_CLIENT",
        "YT_DLP_EXTRACTOR_ARGS_JSON",
        "YT_DLP_COMPAT_OPTIONS",
        "YT_DLP_USER_AGENT",
        "YT_DLP_FORMAT",
    ):
        monkeypatch.delenv(key, raising=False)


def test_build_yt_dlp_download_attempt_opts_rotation_length(monkeypatch: pytest.MonkeyPatch):
    _clear_yt_dlp_strategy_env(monkeypatch)
    opts = build_yt_dlp_download_attempt_opts({"quiet": True})
    assert len(opts) >= 2
    assert "impersonate" in opts[1]


def test_yt_dlp_vanilla_first_plain_attempt_first(monkeypatch: pytest.MonkeyPatch):
    _clear_yt_dlp_strategy_env(monkeypatch)
    monkeypatch.setenv("YT_DLP_VANILLA_FIRST", "1")
    opts = build_yt_dlp_download_attempt_opts({"quiet": True})
    assert "impersonate" not in opts[0]
    assert any(o.get("impersonate") is not None for o in opts[1:])
