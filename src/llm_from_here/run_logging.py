"""Per-show-run logging: main log under ``output_folder``; agent traces in ``agent_trace.log``."""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import sys
from typing import Any

AGENT_TRACE_LOGGER_NAME = "llm_from_here.agent_trace"
MAIN_RUN_LOG_BASENAME = "show_runner.log"
LEGACY_ROOT_LOG_BASENAME = "showRunner.log"
AGENT_TRACE_LOG_BASENAME = "agent_trace.log"


def bootstrap_showrunner_logging() -> None:
    """Configure root level/formatters without a repo-root shared log file."""
    root = logging.getLogger()
    if getattr(root, "_llmfh_logging_bootstrapped", False):
        return
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s:%(name)s:%(levelname)s:%(message)s")
    if os.getenv("LLMFH_SHOWRUNNER_LOG_STDOUT", "").strip().lower() in ("1", "true", "yes", "on"):
        if not any(
            isinstance(h, logging.StreamHandler) and getattr(h, "stream", None) is sys.stderr
            for h in root.handlers
        ):
            sh = logging.StreamHandler(sys.stderr)
            sh.setFormatter(fmt)
            root.addHandler(sh)
    setattr(root, "_llmfh_logging_bootstrapped", True)


def _detach_file_handlers_by_basename(logger: logging.Logger, basenames: frozenset[str]) -> None:
    for h in list(logger.handlers):
        if not isinstance(h, logging.FileHandler):
            continue
        base = os.path.basename(getattr(h, "baseFilename", "") or "")
        if base in basenames:
            logger.removeHandler(h)
            try:
                h.close()
            except OSError:
                pass


def configure_show_run_logging(output_folder: str) -> None:
    """Attach ``show_runner.log`` and ``agent_trace.log`` under ``output_folder``."""
    bootstrap_showrunner_logging()
    root = logging.getLogger()
    fmt = logging.Formatter("%(asctime)s:%(name)s:%(levelname)s:%(message)s")

    _detach_file_handlers_by_basename(
        root, frozenset({MAIN_RUN_LOG_BASENAME, LEGACY_ROOT_LOG_BASENAME})
    )

    main_path = os.path.join(output_folder, MAIN_RUN_LOG_BASENAME)
    fh = logging.FileHandler(main_path, encoding="utf-8")
    fh.setFormatter(fmt)
    fh.setLevel(logging.INFO)
    root.addHandler(fh)

    agent_logger = logging.getLogger(AGENT_TRACE_LOGGER_NAME)
    agent_logger.setLevel(logging.INFO)
    agent_logger.propagate = False
    _detach_file_handlers_by_basename(agent_logger, frozenset({AGENT_TRACE_LOG_BASENAME}))
    ah = logging.FileHandler(
        os.path.join(output_folder, AGENT_TRACE_LOG_BASENAME), encoding="utf-8"
    )
    ah.setFormatter(fmt)
    ah.setLevel(logging.INFO)
    agent_logger.addHandler(ah)


def log_pydantic_agent_trace(
    scope: str,
    run_result: Any,
    *,
    context: dict[str, Any] | None = None,
    output_extra: Any = None,
) -> None:
    """Append one pydantic-ai run trace (messages + usage) to ``agent_trace.log``."""
    log = logging.getLogger(AGENT_TRACE_LOGGER_NAME)
    if not log.handlers:
        return
    try:
        usage = getattr(run_result, "usage", None)
        usage_obj = (
            dataclasses.asdict(usage)
            if usage is not None and dataclasses.is_dataclass(usage)
            else usage
        )
        raw_json = run_result.new_messages_json()
        msgs = json.loads(raw_json.decode("utf-8"))
        out_val = output_extra if output_extra is not None else getattr(run_result, "output", None)
        model_dump = getattr(out_val, "model_dump", None)
        out_payload = model_dump() if callable(model_dump) else out_val
        payload = {
            "kind": "pydantic_ai_run",
            "scope": scope,
            "run_id": getattr(run_result, "run_id", None),
            "context": context or {},
            "usage": usage_obj,
            "output": out_payload,
            "new_messages": msgs,
        }
        log.info("%s\n%s", scope, json.dumps(payload, indent=2, default=str))
    except Exception as exc:  # noqa: BLE001 — tracing must not break the pipeline
        log.warning("agent trace serialization failed: %s", exc)


def log_filter_llm_trace(
    *,
    title: str,
    channel_title: str,
    guest_name: str,
    structured_response: Any,
    kept: bool,
) -> None:
    """Append filter-model structured output to ``agent_trace.log``."""
    log = logging.getLogger(AGENT_TRACE_LOGGER_NAME)
    if not log.handlers:
        return
    sr = structured_response
    sr_dump = getattr(sr, "model_dump", None)
    if callable(sr_dump):
        sr_payload = sr_dump()
    elif isinstance(sr, dict):
        sr_payload = sr
    else:
        sr_payload = dict(sr) if hasattr(sr, "keys") else sr
    payload = {
        "kind": "filter_llm",
        "guest_name": guest_name,
        "title": title,
        "channel_title": channel_title,
        "structured_response": sr_payload,
        "kept": kept,
    }
    log.info("guest_agent.filter_video\n%s", json.dumps(payload, indent=2, default=str))
