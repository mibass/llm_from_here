"""SFX/foley agent: an LLM-in-the-loop decisor over sound providers.

The agent takes an SFX intent (an improv cue) and negotiates with whatever sound
libraries are available, instead of firing one blind keyword search:

1. Search each provider with the current query (bounded duration).
2. Ask an LLM judge whether one candidate matches the intent, or to propose a
   sharper concrete query, or to give up.
3. Repeat up to ``max_attempts`` with a mechanical give-up guard (no result,
   repeated query, unknown candidate ref, or LLM failure all terminate).
4. On success, download once and persist in a local cache keyed by intent so
   recurring palette sounds never pay for a fetch again.

Providers implement :class:`SoundProvider`; the only shipped provider talks to
the Freesound REST API directly (with timeouts/retries and the higher-quality
HQ preview MP3), so it does not depend on the legacy ``freesound`` client.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import appdirs
import requests

from llm_from_here.llm_env import is_openrouter_free_mode
from llm_from_here.llm_session import LlmSession
from llm_from_here.schemas.foley_outputs import FoleyStep

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "openrouter:deepseek/deepseek-v4-flash"
_DEFAULT_MAX_ATTEMPTS = 3
_DEFAULT_NUM_CANDIDATES = 5
_SEARCH_TIMEOUT_S = 15
_DOWNLOAD_TIMEOUT_S = 60
# Bump to invalidate previously chosen sounds when the judge behavior changes
# (e.g. importing short-clip/sustained duration guidance).
_CACHE_VERSION = "2"
_MAX_IMPACT_CLIP_SEC = 8

_SQUASH_RE = re.compile(r"\s+")


def normalize_cue(cue: str) -> str:
    """Normalize an SFX cue into a compact, stable cache/query key."""
    s = _SQUASH_RE.sub(" ", (cue or "").strip())
    return s.strip(" .!?,;:\"'")


class FoleyProviderError(RuntimeError):
    """A provider could not be reached or could not satisfy a request."""


@dataclass(frozen=True)
class FoleyCandidate:
    """One searchable/downloadable sound from any provider."""

    provider: str
    candidate_id: str
    name: str
    duration_sec: float | None = None
    preview_url: str | None = None
    author: str = ""
    page_url: str = ""

    @property
    def ref(self) -> str:
        return f"{self.provider}:{self.candidate_id}"


class SoundProvider(Protocol):
    name: str

    def search(
        self,
        query: str,
        duration_min_sec: int,
        duration_max_sec: int,
        num_results: int = 5,
    ) -> list[FoleyCandidate]:
        """Return up to ``num_results`` candidates, best-matching first."""
        ...

    def download(self, candidate: FoleyCandidate, dest_dir: Path) -> Path:
        """Fetch the candidate's audio into ``dest_dir`` and return the local path."""
        ...


class FreesoundProvider:
    """Freesound REST (APiv2) provider with timeouts, retries, and HQ previews."""

    name = "freesound"

    def __init__(self, api_key: str | None = None, timeout_s: int = _SEARCH_TIMEOUT_S):
        self.api_key = api_key if api_key is not None else os.getenv("FREESOUND_API_KEY")
        self.timeout_s = timeout_s

    def _get(
        self, url: str, params: dict[str, Any] | None = None, timeout_s: int | None = None
    ) -> dict[str, Any]:
        if not self.api_key:
            raise FoleyProviderError("FREESOUND_API_KEY is not set")
        headers = {"Authorization": f"Token {self.api_key}"}
        last: Exception | None = None
        for attempt in (1, 2):
            try:
                resp = requests.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=timeout_s or self.timeout_s,
                )
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException as e:
                last = e
                logger.warning("Freesound request failed (attempt %s): %s", attempt, e)
        raise FoleyProviderError(f"Freesound request failed: {last}")

    def search(
        self,
        query: str,
        duration_min_sec: int,
        duration_max_sec: int,
        num_results: int = _DEFAULT_NUM_CANDIDATES,
    ) -> list[FoleyCandidate]:
        """Text search. Freesound's keyword search returns nothing for long
        object+action phrases, so when a query has no hits we retry with trailing
        tokens trimmed off until results appear or a single token remains."""
        if not normalize_cue(query):
            raise FoleyProviderError("Empty search query")
        tried: list[str] = []
        candidate_query = normalize_cue(query)
        while True:
            tried.append(candidate_query)
            payload = self._search_once(
                candidate_query, duration_min_sec, duration_max_sec, num_results
            )
            out = self._candidates_from(payload)
            if out:
                if len(tried) > 1:
                    logger.info(
                        "Freesound trimmed query %r -> %r (%s results)",
                        query,
                        candidate_query,
                        len(out),
                    )
                return out
            tokens = candidate_query.split()
            if len(tokens) <= 1:
                break
            candidate_query = " ".join(tokens[:-1])
        logger.info("Freesound search for %r returned no results (tried %s)", query, tried)
        return []

    def _search_once(
        self,
        query: str,
        duration_min_sec: int,
        duration_max_sec: int,
        num_results: int,
    ) -> dict[str, Any]:
        return self._get(
            "https://freesound.org/apiv2/search/text/",
            {
                "query": query,
                "filter": f"duration:[{duration_min_sec} TO {duration_max_sec}]",
                "fields": "id,name,duration,previews,author,url",
                "page_size": str(num_results),
                "sort": "rating_desc",
            },
        )

    def _candidates_from(self, payload: dict[str, Any]) -> list[FoleyCandidate]:
        out: list[FoleyCandidate] = []
        for item in payload.get("results") or []:
            previews = item.get("previews") or {}
            author = (item.get("author") or {}).get("username", "")
            out.append(
                FoleyCandidate(
                    provider=self.name,
                    candidate_id=str(item.get("id", "")),
                    name=str(item.get("name") or ""),
                    duration_sec=item.get("duration"),
                    preview_url=previews.get("preview-hq-mp3")
                    or previews.get("preview-lq-mp3"),
                    author=author,
                    page_url=str(item.get("url") or ""),
                )
            )
        return out

    def download(self, candidate: FoleyCandidate, dest_dir: Path) -> Path:
        if not candidate.preview_url:
            raise FoleyProviderError(f"No preview URL for {candidate.ref}")
        dest_dir.mkdir(parents=True, exist_ok=True)
        ext = os.path.splitext(candidate.preview_url)[1] or ".mp3"
        dest = dest_dir / f"freesound_id-{candidate.candidate_id}{ext}"
        if dest.exists() and dest.stat().st_size > 0:
            return dest
        resp = requests.get(candidate.preview_url, timeout=_DOWNLOAD_TIMEOUT_S)
        resp.raise_for_status()
        resp.raw.decode_content = True
        with open(dest, "wb") as f:
            f.write(resp.content)
        return dest


class FoleyCache:
    """Persistent intent -> chosen sound store (recurring palette reuse)."""

    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "index.json"
        self._index: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._index = data
        except (OSError, ValueError):
            self._index = {}

    def _save(self) -> None:
        try:
            self.index_path.write_text(
                json.dumps(self._index, indent=2), encoding="utf-8"
            )
        except OSError as e:
            logger.error("Could not write foley cache index: %s", e)

    @staticmethod
    def _key(intent: str) -> str:
        payload = f"{normalize_cue(intent).lower()}|v{_CACHE_VERSION}"
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
        return f"{digest}"

    def get(self, intent: str) -> dict[str, Any] | None:
        entry = self._index.get(self._key(intent))
        if not entry:
            return None
        path = self.root / entry.get("file", "")
        if not path.is_file() or path.stat().st_size == 0:
            self._index.pop(self._key(intent), None)
            self._save()
            return None
        return {**entry, "path": str(path)}

    def put(
        self,
        intent: str,
        provider: str,
        candidate: FoleyCandidate,
        source_path: Path,
    ) -> None:
        key = self._key(intent)
        if not (source_path.is_file() and source_path.stat().st_size > 0):
            logger.warning("Not caching empty foley file for %r", intent)
            return
        ext = source_path.suffix or ".mp3"
        name = f"{key}_{provider}_{candidate.candidate_id}{ext}"
        dest = self.root / name
        if not dest.exists():
            shutil.copyfile(source_path, dest)
        self._index[key] = {
            "intent": normalize_cue(intent),
            "provider": provider,
            "source_id": candidate.candidate_id,
            "source_name": candidate.name,
            "author": candidate.author,
            "page_url": candidate.page_url,
            "file": name,
        }
        self._save()


class FoleyAgent:
    """LLM-in-the-loop sound picker with a bounded, mechanical give-up guard."""

    def __init__(
        self,
        cache_dir: Path | str | None = None,
        model_slug: str | None = None,
        max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
        num_candidates: int = _DEFAULT_NUM_CANDIDATES,
        providers: list[SoundProvider] | None = None,
        free_mode: bool | None = None,
    ):
        if cache_dir is None:
            root = Path(appdirs.user_cache_dir(appname="llm_from_here")) / "foley"
        else:
            root = Path(cache_dir)
        self.cache = FoleyCache(root)
        self.model_slug = model_slug or _DEFAULT_MODEL
        self.max_attempts = max(int(max_attempts), 1)
        self.num_candidates = num_candidates
        self.providers: list[SoundProvider] = providers or [FreesoundProvider()]
        self._free_mode = is_openrouter_free_mode() if free_mode is None else free_mode
        self._session: LlmSession | None = None

    def __getstate__(self) -> dict[str, Any]:
        state = self.__dict__.copy()
        state["_session"] = None
        return state

    def __setstate__(self, state: dict[str, Any]) -> None:
        self.__dict__.update(state)

    def _session_for(self, model_slug: str | None) -> LlmSession:
        if model_slug:
            return LlmSession(_SYSTEM_MESSAGE, model_slug=model_slug)
        if self._session is None:
            self._session = LlmSession(_SYSTEM_MESSAGE, model_slug=self.model_slug)
        return self._session

    def _provider_by_name(self) -> dict[str, SoundProvider]:
        return {p.name: p for p in self.providers}

    @staticmethod
    def _mechanical_give_up(reason: str) -> bool:
        """True when the judge didn't meaningfully reject the candidates."""
        return "no accept/refine" in reason or "repeated or empty refined query" in reason

    def _search_once(
        self,
        query: str,
        duration_min_sec: int,
        duration_max_sec: int,
    ) -> tuple[list[FoleyCandidate], list[str]]:
        candidates: list[FoleyCandidate] = []
        errors: list[str] = []
        for prov in self.providers:
            try:
                candidates.extend(
                    prov.search(
                        query,
                        duration_min_sec,
                        duration_max_sec,
                        num_results=self.num_candidates,
                    )
                )
            except Exception as e:  # noqa: BLE001 - provider failures are non-fatal
                logger.warning("Foley provider %s failed for %r: %s", prov.name, query, e)
                errors.append(f"{prov.name} unavailable: {e}")
        return candidates, errors

    def resolve(
        self,
        intent: str,
        duration_min_sec: int = 1,
        duration_max_sec: int = 60,
        model_slug: str | None = None,
        download_dir: Path | str | None = None,
        sustained: bool = False,
    ) -> dict[str, Any]:
        """Resolve an SFX intent to a downloaded audio file (or a miss).

        ``sustained=True`` frames the cue as a background/ambience bed and biases
        the judge toward full-length clips (as opposed to short impact sounds).

        Returns ``{"status": "hit"|"cached"|"miss", "file": Path|None,
        "audit": {...}}``. Files land in ``download_dir`` (or the cache root).
        """
        initial = normalize_cue(intent)
        audit: dict[str, Any] = {
            "intent": initial,
            "status": "miss",
            "attempts": [],
            "selected": None,
        }
        if not initial:
            audit["attempts"].append({"query": "", "decision": "empty intent"})
            return audit

        cached = self.cache.get(initial)
        if cached:
            audit["status"] = "cached"
            audit["selected"] = {
                "provider": cached.get("provider"),
                "id": cached.get("source_id"),
                "name": cached.get("source_name"),
            }
            audit["attempts"].append({"query": initial, "decision": "cached"})
            audit["file"] = cached.get("path")
            return audit

        dest_dir = Path(download_dir) if download_dir else self.cache.root
        dest_dir.mkdir(parents=True, exist_ok=True)
        providers = self._provider_by_name()

        query = initial
        seen_queries = {initial.lower()}
        last_candidates: list[FoleyCandidate] = []
        for attempt in range(1, self.max_attempts + 1):
            candidates, errors = self._search_once(query, duration_min_sec, duration_max_sec)
            last_candidates = candidates
            if not candidates:
                logger.info(
                    "Foley search for %r returned no candidates (attempt %s/%s)",
                    query,
                    attempt,
                    self.max_attempts,
                )
            attempt_row: dict[str, Any] = {
                "attempt": attempt,
                "query": query,
                "candidates": [
                    {
                        "provider": c.provider,
                        "id": c.candidate_id,
                        "ref": c.ref,
                        "name": c.name,
                        "duration_sec": c.duration_sec,
                    }
                    for c in candidates
                ],
                "provider_errors": errors,
                "decision": "",
            }
            audit["attempts"].append(attempt_row)

            if not candidates:
                step = self._decide(
                    initial, query, [], errors, attempt, intent, sustained=sustained
                )
                outcome, detail = self._apply_step(step, [], query, seen_queries)
            elif self._free_mode:
                # No LLM budget in free mode: take the top-ranked candidate blindly.
                outcome, detail = "accept", candidates[0]
            else:
                step = self._decide(
                    initial,
                    query,
                    candidates,
                    errors,
                    attempt,
                    intent,
                    sustained=sustained,
                )
                outcome, detail = self._apply_step(step, candidates, query, seen_queries)

            if outcome == "accept":
                res = self._accept_and_download(
                    audit, attempt_row, providers, dest_dir, detail, initial
                )
                return res

            if outcome == "retry":
                query = detail
                seen_queries.add(query.lower())
                attempt_row["decision"] = f"retry with {query!r}"
                continue

            attempt_row["decision"] = f"give_up: {detail}"
            if candidates and self._mechanical_give_up(detail):
                return self._best_effort_accept(
                    audit, attempt_row, providers, dest_dir, candidates[0], initial
                )
            return self._finalize_miss(audit, detail)

        last_decision = audit["attempts"][-1].get("decision") or "max attempts"
        if last_candidates:
            return self._best_effort_accept(
                audit,
                audit["attempts"][-1],
                providers,
                dest_dir,
                last_candidates[0],
                initial,
            )
        return self._finalize_miss(audit, last_decision)

    def _accept_and_download(
        self,
        audit: dict[str, Any],
        attempt_row: dict[str, Any],
        providers: dict[str, SoundProvider],
        dest_dir: Path,
        cand: FoleyCandidate,
        intent: str,
    ) -> dict[str, Any]:
        """Download, cache, and record an accepted candidate as a hit. On download
        failure marks the miss reason and returns a miss dict."""
        try:
            path = providers[cand.provider].download(cand, dest_dir)
        except Exception as e:  # noqa: BLE001 - download failure -> miss
            logger.warning("Foley download failed for %s: %s", cand.ref, e)
            audit["attempts"] = [
                {**row, "decision": row.get("decision") or "download failed"}
                for row in audit["attempts"]
            ]
            return self._finalize_miss(audit, f"download failed for {cand.ref}")
        self.cache.put(intent, cand.provider, cand, path)
        audit["status"] = "hit"
        audit["selected"] = {
            "provider": cand.provider,
            "id": cand.candidate_id,
            "name": cand.name,
        }
        attempt_row["decision"] = f"accept {cand.ref}"
        logger.info(
            "Foley %r -> %s (%s, %.1fs)",
            intent,
            cand.name,
            cand.ref,
            cand.duration_sec or 0,
        )
        return {**audit, "file": str(path)}

    def _best_effort_accept(
        self,
        audit: dict[str, Any],
        attempt_row: dict[str, Any],
        providers: dict[str, SoundProvider],
        dest_dir: Path,
        cand: FoleyCandidate,
        intent: str,
    ) -> dict[str, Any]:
        """Keep the top candidate instead of dropping the SFX on a mechanical
        give-up (no-decision, repeated refine, or exhausted attempts)."""
        if attempt_row and attempt_row.get("decision"):
            attempt_row["decision"] = (
                f"best-effort accept {cand.ref} ({attempt_row['decision']})"
            )
        else:
            attempt_row["decision"] = f"best-effort accept {cand.ref}"
        logger.info(
            "Best-effort accept %s for %r (%s)",
            cand.ref,
            intent,
            attempt_row["decision"],
        )
        return self._accept_and_download(
            audit, attempt_row, providers, dest_dir, cand, intent
        )

    def _finalize_miss(self, audit: dict[str, Any], reason: str) -> dict[str, Any]:
        audit["status"] = "miss"
        audit["reason"] = reason
        logger.warning("Foley miss for %r: %s", audit.get("intent"), reason)
        return {**audit, "file": None}

    def _decide(
        self,
        intent: str,
        query: str,
        candidates: list[FoleyCandidate],
        errors: list[str],
        attempt: int,
        raw_intent: str,
        sustained: bool = False,
    ) -> FoleyStep:
        lines = [
            f"SFX intent: {intent}",
            f"Attempt {attempt}/{self.max_attempts} for query {query!r}:",
        ]
        if sustained:
            lines.append(
                "This is a sustained background/ambience bed: prefer a clip long enough "
                "to underlie the whole scene over a short one-shot loop."
            )
        else:
            lines.append(
                f"For a momentary impact sound, prefer the shortest clearly-matching "
                f"candidate (ideally under ~{_MAX_IMPACT_CLIP_SEC}s). Accept a longer "
                f"clip only if it is the only credible match or the intent is itself "
                f"sustained."
            )
        if candidates:
            lines.append("Candidate sounds (pick ONLY by exact ref):")
            for c in candidates:
                dur = f", duration={c.duration_sec:.1f}s" if c.duration_sec else ""
                lines.append(f"  - ref: {c.ref}  name: {c.name!r}{dur}  provider: {c.provider}")
        else:
            lines.append("No matching sounds found in this library.")
        if errors:
            lines.append("Provider errors: " + " | ".join(errors))
        lines.append(
            "- To accept, set accept=true and candidate_ref to an EXACT ref from the list "
            "above. Never invent a ref.\n"
            "- Otherwise set refined_query to a more concrete, library-searchable query "
            "(physical object + action, e.g. 'door creak' not 'tense orchestral sting').\n"
            "- Only set give_up=true if this attempt is the last chance or every candidate "
            "is clearly wrong and no better query comes to mind."
        )
        prompt = "\n".join(lines)
        try:
            raw = self._session_for(None).run_structured(prompt, FoleyStep)
            return FoleyStep.model_validate(raw)
        except Exception as e:  # noqa: BLE001 - LLM failure degrades to give-up
            logger.warning("Foley judge failed for %r: %s", intent, e)
            return FoleyStep(give_up=True, give_up_reason=f"judge error: {e}")

    def _apply_step(
        self,
        step: FoleyStep,
        candidates: list[FoleyCandidate],
        query: str,
        seen_queries: set[str],
    ) -> tuple[str, Any]:
        refs = {c.ref for c in candidates}
        if step.accept and step.candidate_ref in refs:
            return "accept", next(c for c in candidates if c.ref == step.candidate_ref)
        if (step.refined_query or "").strip():
            rq = normalize_cue(step.refined_query)
            if rq and rq.lower() not in seen_queries and rq.lower() != query.lower():
                return "retry", rq
            return "give_up", f"repeated or empty refined query {rq!r}"
        if step.give_up:
            return "give_up", step.give_up_reason or "no acceptable sound found"
        return "give_up", "judge returned no accept/refine decision"


_SYSTEM_MESSAGE = (
    "You are a sound-design librarian for an improv podcast. Given an SFX intent and a "
    "short list of candidate sounds found in a library, pick the single best candidate by "
    "its exact ref, or propose a sharper, concrete, library-searchable query to retry. "
    "Prefer accepting a plausible match over endless searching. Duration matters: for "
    "momentary impact sounds pick the shortest clearly-matching clip; for sustained "
    "ambience pick a clip long enough to underlie the scene. Physical object + action "
    "queries (e.g. 'door creak', 'cafe espresso machine hiss') beat abstract adjectives. "
    "Give up only when nothing is acceptable and no better query comes to mind."
)