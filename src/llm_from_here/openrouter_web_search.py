"""OpenRouter web search via the ``openrouter:web_search`` server tool."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, cast

from llm_from_here.llm_env import (
    build_openrouter_client,
    get_openrouter_chat_model,
    get_web_search_engine,
    get_web_search_max_results,
    get_web_search_max_total_results,
)

logger = logging.getLogger(__name__)


@dataclass
class UrlCitation:
    url: str
    title: str = ""
    content: str = ""

    @classmethod
    def from_annotation(cls, ann: dict[str, Any]) -> UrlCitation | None:
        if ann.get("type") != "url_citation":
            return None
        cite = ann.get("url_citation") or {}
        url = (cite.get("url") or "").strip()
        if not url:
            return None
        return cls(
            url=url,
            title=(cite.get("title") or "").strip(),
            content=(cite.get("content") or "").strip(),
        )


@dataclass
class WebSearchResult:
    content: str
    citations: list[UrlCitation] = field(default_factory=list)
    web_search_requests: int = 0

    def format_sources(self) -> str:
        if not self.citations:
            return "(no citations returned)"
        lines: list[str] = []
        for i, cite in enumerate(self.citations, start=1):
            title = cite.title or cite.url
            snippet = cite.content[:500] + ("..." if len(cite.content) > 500 else "")
            lines.append(f"{i}. [{title}]({cite.url})")
            if snippet:
                lines.append(f"   {snippet}")
        return "\n".join(lines)


def _parse_annotations(message: Any) -> list[UrlCitation]:
    raw = getattr(message, "annotations", None)
    if raw is None and isinstance(message, dict):
        raw = message.get("annotations")
    if not raw:
        return []
    citations: list[UrlCitation] = []
    for ann in raw:
        if isinstance(ann, dict):
            parsed = UrlCitation.from_annotation(ann)
        else:
            dumped = ann.model_dump() if hasattr(ann, "model_dump") else {}
            parsed = UrlCitation.from_annotation(dumped)
        if parsed:
            citations.append(parsed)
    return citations


def _parse_usage(response: Any) -> int:
    usage = getattr(response, "usage", None)
    if usage is None:
        return 0
    server_tool = getattr(usage, "server_tool_use", None)
    if server_tool is None and isinstance(usage, dict):
        server_tool = usage.get("server_tool_use")
    if server_tool is None:
        return 0
    if isinstance(server_tool, dict):
        return int(server_tool.get("web_search_requests") or 0)
    return int(getattr(server_tool, "web_search_requests", 0) or 0)


def build_web_search_tool(
    *,
    engine: str | None = None,
    max_results: int | None = None,
    max_total_results: int | None = None,
    search_context_size: str | None = "medium",
    allowed_domains: list[str] | None = None,
    excluded_domains: list[str] | None = None,
) -> dict[str, Any]:
    """Build the OpenRouter web search server tool payload."""
    parameters: dict[str, Any] = {
        "engine": engine or get_web_search_engine(),
        "max_results": max_results if max_results is not None else get_web_search_max_results(),
    }
    total = max_total_results if max_total_results is not None else get_web_search_max_total_results()
    if total is not None:
        parameters["max_total_results"] = total
    if search_context_size:
        parameters["search_context_size"] = search_context_size
    if allowed_domains:
        parameters["allowed_domains"] = allowed_domains
    if excluded_domains:
        parameters["excluded_domains"] = excluded_domains
    return {"type": "openrouter:web_search", "parameters": parameters}


def run_web_search(
    prompt: str,
    *,
    model: str | None = None,
    engine: str | None = None,
    max_results: int | None = None,
    max_total_results: int | None = None,
    search_context_size: str | None = "medium",
    allowed_domains: list[str] | None = None,
    excluded_domains: list[str] | None = None,
) -> WebSearchResult:
    """Run OpenRouter web search and return prose plus citation annotations."""
    client = build_openrouter_client()
    slug = (model or get_openrouter_chat_model()).strip()
    tool = build_web_search_tool(
        engine=engine,
        max_results=max_results,
        max_total_results=max_total_results,
        search_context_size=search_context_size,
        allowed_domains=allowed_domains,
        excluded_domains=excluded_domains,
    )
    logger.info(
        "OpenRouter web search model=%s engine=%s max_results=%s",
        slug,
        tool["parameters"].get("engine"),
        tool["parameters"].get("max_results"),
    )
    response = client.chat.completions.create(
        model=slug,
        messages=[{"role": "user", "content": prompt}],
        tools=[cast(Any, tool)],
    )
    choice = response.choices[0]
    message = choice.message
    content = (message.content or "").strip()
    citations = _parse_annotations(message)
    requests = _parse_usage(response)
    logger.info(
        "Web search complete: citations=%s web_search_requests=%s content_len=%s",
        len(citations),
        requests,
        len(content),
    )
    return WebSearchResult(
        content=content,
        citations=citations,
        web_search_requests=requests,
    )
