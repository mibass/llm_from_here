"""Tests for yt-dlp environment overrides (GitHub Actions tuning)."""

from __future__ import annotations

import json

import pytest

from llm_from_here.plugins.ytfetch import (
    YOUTUBE_AUDIO_FORMAT_SPEC,
    DEFAULT_YT_DLP_SOCKET_TIMEOUT,
    build_yt_dlp_download_attempt_opts,
    merge_yt_dlp_env_into,
    strip_guest_query_prefix,
    _filtered_yt_dlp_fallback_overlays,
)
from llm_from_here.plugins import ytfetch as ytfetch_mod

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
    "YT_DLP_FORMAT",
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


def test_format_override(monkeypatch):
    monkeypatch.setenv("YT_DLP_FORMAT", "bestaudio/worstaudio")
    opts: dict = {"format": YOUTUBE_AUDIO_FORMAT_SPEC}
    merge_yt_dlp_env_into(opts)
    assert opts["format"] == "bestaudio/worstaudio"


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
    assert len(attempts) == len(_filtered_yt_dlp_fallback_overlays())
    assert attempts[-1] == {"quiet": True}
    if len(attempts) > 1:
        assert "impersonate" in attempts[0]


def test_build_attempts_skips_unsupported_impersonate(monkeypatch):
    monkeypatch.setattr(ytfetch_mod, "_curlcffi_handler_available", lambda: False)
    ytfetch_mod._impersonation_filter_logged = False
    overlays = _filtered_yt_dlp_fallback_overlays()
    assert overlays == ({},)
    attempts = build_yt_dlp_download_attempt_opts({"quiet": True})
    assert len(attempts) == 1
    assert "impersonate" not in attempts[0]


def test_strip_guest_query_prefix():
    assert strip_guest_query_prefix("Band Name: The Avett Brothers") == "The Avett Brothers"
    assert strip_guest_query_prefix("Comedian: Roy Wood Jr.") == "Roy Wood Jr."
    assert strip_guest_query_prefix("folk instrumental live") == "folk instrumental live"


def test_build_youtube_audio_ydl_opts_default_socket_timeout():
    fetch = ytfetch_mod.YtFetch.__new__(ytfetch_mod.YtFetch)
    opts = fetch._build_youtube_audio_ydl_opts("/tmp/test", for_download=True)
    assert opts["socket_timeout"] == DEFAULT_YT_DLP_SOCKET_TIMEOUT


def test_build_attempts_fallback_keeps_base_keys(monkeypatch):
    base = {"quiet": True, "format": YOUTUBE_AUDIO_FORMAT_SPEC}
    attempts = build_yt_dlp_download_attempt_opts(base)
    assert attempts[-1]["quiet"] is True
    assert attempts[-1]["format"] == YOUTUBE_AUDIO_FORMAT_SPEC


def test_build_attempts_single_when_explicit_format(monkeypatch):
    monkeypatch.setenv("YT_DLP_FORMAT", "bestaudio")
    base = {"quiet": True}
    merge_yt_dlp_env_into(base)
    attempts = build_yt_dlp_download_attempt_opts(base)
    assert len(attempts) == 1
