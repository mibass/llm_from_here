"""Tests for yt-dlp environment overrides (GitHub Actions tuning)."""

from __future__ import annotations

import json

import pytest

from llm_from_here.plugins.ytfetch import (
    build_yt_dlp_download_attempt_opts,
    merge_yt_dlp_env_into,
    _yt_dlp_fallback_overlays,
)

_YT_DLP_ENV_KEYS = (
    "YT_DLP_COOKIE_FILE",
    "YT_DLP_PLAYER_CLIENT",
    "YT_DLP_EXTRACTOR_ARGS_JSON",
    "YT_DLP_COMPAT_OPTIONS",
    "YT_DLP_IMPERSONATE",
    "YT_DLP_USER_AGENT",
    "YT_DLP_SOCKET_TIMEOUT",
    "YT_DLP_VERBOSE",
    "YT_DLP_DISABLE_FALLBACK",
)


@pytest.fixture(autouse=True)
def _clear_yt_dlp_env(monkeypatch):
    for key in _YT_DLP_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_merge_empty(monkeypatch):
    opts = {"quiet": True}
    merge_yt_dlp_env_into(opts)
    assert "cookiefile" not in opts
    assert "extractor_args" not in opts


def test_merge_player_client(monkeypatch):
    monkeypatch.setenv("YT_DLP_PLAYER_CLIENT", "tv, android")
    opts: dict = {"quiet": True}
    merge_yt_dlp_env_into(opts)
    assert opts["extractor_args"]["youtube"]["player_client"] == ["tv", "android"]


def test_extractor_args_json_overrides_player_client(monkeypatch):
    monkeypatch.setenv("YT_DLP_PLAYER_CLIENT", "tv")
    monkeypatch.setenv(
        "YT_DLP_EXTRACTOR_ARGS_JSON",
        json.dumps({"youtube": {"player_client": ["web"]}}),
    )
    opts: dict = {}
    merge_yt_dlp_env_into(opts)
    assert opts["extractor_args"]["youtube"]["player_client"] == ["web"]


def test_compat_opts(monkeypatch):
    monkeypatch.setenv("YT_DLP_COMPAT_OPTIONS", "2025, 2024")
    opts: dict = {}
    merge_yt_dlp_env_into(opts)
    assert opts["compat_opts"] == {"2025", "2024"}


def test_verbose(monkeypatch):
    monkeypatch.setenv("YT_DLP_VERBOSE", "1")
    opts: dict = {"quiet": True, "noprogress": True}
    merge_yt_dlp_env_into(opts)
    assert opts["quiet"] is False
    assert opts["noprogress"] is False
    assert opts["verbose"] is True


def test_impersonate_parsed(monkeypatch):
    monkeypatch.setenv("YT_DLP_IMPERSONATE", "chrome-136")
    opts: dict = {}
    merge_yt_dlp_env_into(opts)
    imp = opts.get("impersonate")
    assert imp is not None
    assert str(imp) == "chrome-136"


def test_user_agent_skipped_when_impersonate(monkeypatch):
    monkeypatch.setenv("YT_DLP_IMPERSONATE", "chrome-136")
    monkeypatch.setenv("YT_DLP_USER_AGENT", "Custom/1.0")
    opts: dict = {}
    merge_yt_dlp_env_into(opts)
    assert "http_headers" not in opts


def test_build_attempts_single_when_disable_fallback(monkeypatch):
    monkeypatch.setenv("YT_DLP_DISABLE_FALLBACK", "1")
    base = {"quiet": True}
    attempts = build_yt_dlp_download_attempt_opts(base)
    assert len(attempts) == 1
    assert attempts[0]["quiet"] is True


def test_build_attempts_single_when_explicit_impersonate(monkeypatch):
    monkeypatch.setenv("YT_DLP_IMPERSONATE", "chrome-136")
    base = {"quiet": True}
    merge_yt_dlp_env_into(base)
    attempts = build_yt_dlp_download_attempt_opts(base)
    assert len(attempts) == 1


def test_build_attempts_fallback_chain_length(monkeypatch):
    base = {"quiet": True}
    attempts = build_yt_dlp_download_attempt_opts(base)
    assert len(attempts) == len(_yt_dlp_fallback_overlays())
    assert "impersonate" in attempts[0]


def test_build_attempts_fallback_keeps_base_keys(monkeypatch):
    base = {"quiet": True, "format": "bestaudio"}
    attempts = build_yt_dlp_download_attempt_opts(base)
    assert attempts[-1]["quiet"] is True
    assert attempts[-1]["format"] == "bestaudio"
