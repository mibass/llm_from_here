"""Tool-calling agent for guest clip discovery (replaces category YAML maps)."""

from __future__ import annotations

import concurrent.futures
import logging
from dataclasses import dataclass
from typing import Any

from googleapiclient.errors import HttpError
from pydantic_ai import Agent, ModelRetry, RunContext
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from llm_from_here.llm_env import get_filter_model, get_structured_model
from llm_from_here.llm_session import LlmSession
from llm_from_here.models.guest_models import GuestSegment, VideoResult
from llm_from_here.run_logging import log_filter_llm_trace
from llm_from_here.schemas.llm_outputs import LlmFilterResponse

logger = logging.getLogger(__name__)

_GUEST_QUEUE_PREFIXES = (
    "band name:",
    "comedian:",
    "author:",
    "actor:",
)


def strip_guest_queue_prefix(name: str) -> str:
    """Strip Supabase queue role prefixes so metadata matching uses the person's/band's real name."""
    s = (name or "").strip()
    low = s.lower()
    for p in _GUEST_QUEUE_PREFIXES:
        if low.startswith(p):
            return s[len(p) :].strip()
    return s


# Mirrors legacy ``llm_filter_prompt`` in configv3 / ``includes/llm_filter_vars.yml``.
LLM_FILTER_TOOL_PROMPT = """Can you tell me if this video would be appropriate for a variety show that is meant to be
uplifting and simulate nostalgic feelings? I want to avoid controversial, misogynistic, and political content.
You should be more lenient with channels from well known sources like NPR, PBS, and the BBC as well as late night
talk shows.

The booked guest for this segment is "{guest_match_name}".

Respond **yes** only if BOTH:
1) The clip fits the uplifting variety-show guidelines above.
2) The video primarily features or is clearly about "{guest_match_name}"—not a different person who happens to appear
   (for example another author on the same channel). Accept reasonable spelling or nickname variants.

Respond **no** if either condition fails.

Make your best guess and respond only with yes or no.

The title is "{title}" and the channel title is "{channel_title}"
and the description is:
```
{description}
```
"""


GUEST_AGENT_SYSTEM = """You are a show producer for a nostalgic uplifting variety show like Live From Here.

Tools:
- search_youtube: search YouTube with a concise query (guest name + category cues such as live performance,
  interview, stand-up, book reading). Respect duration_min_sec / duration_max_sec from the tool defaults unless you pass overrides.
- filter_video: True means the clip **matches the booked guest** and is appropriate for broadcast; False means reject.

Workflow:
1) Search with a strong query for the given guest and category.
2) For promising candidates, call filter_video with their metadata.
3) Pick exactly ONE video_id that is appropriate and matches the guest.
4) Respond with GuestSegment: guest_name, video_id, intro_sentence (one short host intro), duration_seconds (from search results).
"""


@dataclass
class GuestAgentDeps:
    """Per-run deps wired from ``SegmentsToTimeline.agent_search``."""

    yt_fetch: Any
    duration_min_sec: int
    duration_max_sec: int
    guest_category: str
    guest_name: str = ""
    """Raw queue label (may include ``Band Name:`` prefix)."""
    guest_match_name: str = ""
    """Normalized name for filter/metadata (falls back to stripped ``guest_name``)."""


_guest_agents: dict[str, Agent[GuestAgentDeps, GuestSegment]] = {}


def video_metadata_features_guest(
    guest_name: str,
    title: str,
    description: str,
    *,
    fuzzy_threshold: int = 88,
) -> bool:
    """True when title/description strongly associate this clip with ``guest_name``."""
    from fuzzywuzzy import fuzz

    g = strip_guest_queue_prefix(guest_name or "").strip().lower()
    if not g:
        return False
    hay = f"{title or ''} {(description or '')[:12000]}".lower()
    variants = [g]
    if "&" in g:
        variants.append(g.replace("&", "and"))
    for v in variants:
        if v in hay:
            return True
        if fuzz.token_set_ratio(v, hay) >= fuzzy_threshold:
            return True
    return False


def _run_filter_llm(
    title: str,
    channel_title: str,
    description: str,
    guest_name: str = "",
) -> bool:
    """Return True if the clip should be **kept** (appropriate).

    Note: ``YtFetch.llm_filter_title`` uses inverted booleans for rejection;
    this tool uses positive semantics so the model reads naturally.
    """
    prompt = LLM_FILTER_TOOL_PROMPT.format(
        guest_match_name=guest_name or "(unknown)",
        title=title,
        channel_title=channel_title,
        description=description[:8000],
    )
    session = LlmSession(system_message="", model_slug=get_filter_model())
    resp = session.run_structured(prompt, LlmFilterResponse, log_prompt=False)
    kept = resp.get("answer", "").lower() == "yes"
    log_filter_llm_trace(
        title=title,
        channel_title=channel_title,
        guest_name=guest_name,
        structured_response=resp,
        kept=kept,
    )
    return kept


def _make_guest_agent(model: str) -> Agent[GuestAgentDeps, GuestSegment]:
    agent = Agent(
        model,
        deps_type=GuestAgentDeps,
        output_type=GuestSegment,
        system_prompt=(GUEST_AGENT_SYSTEM,),
        retries=2,
        output_retries=5,
        defer_model_check=True,
    )

    @agent.tool
    @retry(
        wait=wait_exponential(multiplier=1, min=1, max=30),
        stop=stop_after_attempt(5),
        retry=retry_if_exception_type((HttpError, ConnectionError, OSError)),
    )
    def search_youtube(
        ctx: RunContext[GuestAgentDeps],
        query: str,
        duration_min_sec: int | None = None,
        duration_max_sec: int | None = None,
    ) -> list[VideoResult]:
        deps = ctx.deps
        dmin = int(duration_min_sec if duration_min_sec is not None else deps.duration_min_sec)
        dmax = int(duration_max_sec if duration_max_sec is not None else deps.duration_max_sec)
        rows = deps.yt_fetch.search_videos_for_agent(
            query,
            duration_search_filter="medium",
            duration_min_sec=dmin,
            duration_max_sec=dmax,
            max_results=15,
        )
        if not rows:
            raise ModelRetry(
                "No videos matched the duration window; broaden the query or try alternate keywords."
            )
        keys = ("video_id", "title", "channel_title", "description", "duration_seconds")
        return [VideoResult(**{k: r[k] for k in keys}) for r in rows]

    @agent.tool
    def filter_video(
        ctx: RunContext[GuestAgentDeps],
        title: str,
        channel_title: str,
        description: str,
    ) -> bool:
        """True = clip is appropriate to air (keep). False = reject."""
        gn = (ctx.deps.guest_match_name or strip_guest_queue_prefix(ctx.deps.guest_name)).strip()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(_run_filter_llm, title, channel_title, description, gn)
            return fut.result()

    return agent


def get_guest_agent() -> Agent[GuestAgentDeps, GuestSegment]:
    """Agent singleton keyed by ``get_structured_model()``."""
    model = get_structured_model()
    if model not in _guest_agents:
        logger.info("Building guest_agent with structured model=%s", model)
        _guest_agents[model] = _make_guest_agent(model)
    return _guest_agents[model]


def clear_guest_agent_cache_for_tests() -> None:
    """Test helper: drop cached agents after env/model routing changes."""
    _guest_agents.clear()
