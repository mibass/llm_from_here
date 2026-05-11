"""Live guest_agent smoke tests (OPENROUTER_API_KEY + YT_API_KEY required)."""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv

from llm_from_here.agents.guest_agent import (
    GuestAgentDeps,
    clear_guest_agent_cache_for_tests,
    get_guest_agent,
    strip_guest_queue_prefix,
)
from llm_from_here.plugins.ytfetch import YtFetch

pytestmark = pytest.mark.integration

load_dotenv()


@pytest.fixture(autouse=True)
def _fresh_agent_cache():
    clear_guest_agent_cache_for_tests()
    yield
    clear_guest_agent_cache_for_tests()


requires_keys = pytest.mark.skipif(
    not os.getenv("OPENROUTER_API_KEY") or not os.getenv("YT_API_KEY"),
    reason="OPENROUTER_API_KEY and YT_API_KEY required for guest_agent e2e",
)


@requires_keys
def test_guest_agent_finds_segment_for_musician():
    yt = YtFetch(video_ids_supaset_autoexpire_days=90)
    deps = GuestAgentDeps(
        yt_fetch=yt,
        duration_min_sec=180,
        duration_max_sec=600,
        guest_category="music",
        guest_name="Yo-Yo Ma",
        guest_match_name=strip_guest_queue_prefix("Yo-Yo Ma"),
    )
    agent = get_guest_agent()
    result = agent.run_sync(
        'Guest category: music. Guest name: "Yo-Yo Ma". Find one appropriate clip.',
        deps=deps,
    )
    seg = result.output
    assert seg.video_id
    assert seg.intro_sentence.strip()
    yt.finalize()


@requires_keys
def test_guest_agent_finds_segment_for_comedian():
    yt = YtFetch(video_ids_supaset_autoexpire_days=90)
    deps = GuestAgentDeps(
        yt_fetch=yt,
        duration_min_sec=300,
        duration_max_sec=660,
        guest_category="comedy",
        guest_name="Tig Notaro",
        guest_match_name=strip_guest_queue_prefix("Tig Notaro"),
    )
    agent = get_guest_agent()
    result = agent.run_sync(
        'Guest category: comedy. Guest name: "Tig Notaro". Find one appropriate clip.',
        deps=deps,
    )
    seg = result.output
    assert seg.video_id
    assert seg.intro_sentence.strip()
    yt.finalize()
