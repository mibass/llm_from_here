"""Tests for Deno binary resolution used by yt-dlp."""

from __future__ import annotations

import os

import pytest

from llm_from_here.plugins.ytfetch import _resolved_deno_executable


@pytest.fixture
def fake_deno(tmp_path):
    p = tmp_path / "deno"
    p.write_text("#!/bin/sh\necho deno\n")
    p.chmod(0o755)
    return p


def test_resolved_deno_prefers_yt_dlp_deno(monkeypatch, fake_deno):
    monkeypatch.setenv("YT_DLP_DENO", str(fake_deno))
    monkeypatch.delenv("PATH", raising=False)
    assert _resolved_deno_executable() == str(fake_deno)


def test_resolved_deno_which(monkeypatch, fake_deno):
    monkeypatch.delenv("YT_DLP_DENO", raising=False)
    monkeypatch.setenv("PATH", str(fake_deno.parent))
    assert _resolved_deno_executable() == str(fake_deno)


def test_resolved_deno_default_home(monkeypatch, fake_deno, tmp_path):
    monkeypatch.delenv("YT_DLP_DENO", raising=False)
    monkeypatch.setenv("PATH", "")
    home = tmp_path / "h"
    bin_dir = home / ".deno" / "bin"
    bin_dir.mkdir(parents=True)
    target = bin_dir / "deno"
    target.write_bytes(fake_deno.read_bytes())
    target.chmod(0o755)
    monkeypatch.setenv("HOME", str(home))
    assert _resolved_deno_executable() == str(target)


def test_resolved_deno_none_when_missing(monkeypatch, tmp_path):
    monkeypatch.delenv("YT_DLP_DENO", raising=False)
    monkeypatch.setenv("PATH", "")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert _resolved_deno_executable() is None
