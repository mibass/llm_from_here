"""Gemini TTS inline tags and narrator text preparation.

Two prompt schemas are supported:
- ``legacy`` (Gemini 3.1 / 2.5): Audio Profile / Director's Notes header blocks
  plus square-bracket emotion tags ([positive], [curiosity], ...).
- ``gemini38`` (Gemini 3.8 Flash TTS): text is a verbatim transcript; sustained
  delivery moves into structured ``speech_metadata.style`` and momentary vocal
  events may appear inline as angle-bracket tags (<laugh>, <sigh>, ...).
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Curated subset of Google-documented inline audio tags (Gemini supports 200+).
GEMINI_TTS_TAGS = frozenset(
    {
        "positive",
        "neutral",
        "negative",
        "enthusiasm",
        "excitement",
        "curiosity",
        "interest",
        "hope",
        "amusement",
        "awe",
        "determination",
        "nervousness",
        "frustration",
        "annoyance",
        "agitation",
        "tension",
        "confusion",
        "anger",
        "whispers",
        "laughs",
        "adoration",
        "admiration",
        "aggression",
    }
)

_PRODUCTION_BRACKET_RE = re.compile(
    r"\[(?:APPLAUSE|MUSIC|BACKGROUND\s+MUSIC)[^\]]*\]",
    re.IGNORECASE,
)
_ANY_BRACKET_RE = re.compile(r"\[([^\]]+)\]")

# Gemini 3.8 angle-bracket vocal events (point-in-time, performed inline).
GEMINI38_VOCAL_EVENTS = frozenset(
    {
        "laugh",
        "laughs",
        "sigh",
        "breath",
        "cough",
        "gasp",
        "short pause",
        "medium pause",
        "long pause",
    }
)
_ANY_ANGLE_RE = re.compile(r"<([^\n<>]{1,40})>")

# Sustained style strings for Gemini 3.8 speech_metadata (structured schema).
GEMINI38_DEFAULT_STYLE = (
    "Warm, witty NPR radio host; relaxed storytelling with natural breath "
    "and phrasing, like Live From There."
)
_GEMINI38_SECTION_STYLES: dict[str, str] = {
    "intro": (
        "Warm, witty host opening a live radio show; energetic but unhurried, "
        "direct address to an intimate studio audience."
    ),
    "story": (
        "Warm, intimate first-person narrator; relaxed storytelling with "
        "natural pauses and emotionally present delivery."
    ),
    "outro": (
        "Grateful, lightly humorous host signing off; unhurried warmth with "
        "satisfied end-of-show energy."
    ),
}
_GEMINI38_MAX_STYLE_CHARS = 480


def is_gemini38_tts_slug(slug: str | None) -> bool:
    """True when the TTS model slug is a Gemini 3.8 TTS model (structured schema)."""
    if not slug:
        return False
    lowered = slug.lower()
    return "gemini" in lowered and "tts" in lowered and "3.8" in lowered


def gemini_tag_prompt_block() -> str:
    """Prompt snippet for script LLMs — keep configs/configv3.yaml narrator prompts in sync."""
    tags = ", ".join(f"[{t}]" for t in sorted(GEMINI_TTS_TAGS))
    return (
        "For narrator dialog only (Dris Thile / first-person story paragraphs): optionally "
        "prefix at most ONE Gemini TTS emotion tag at the start of each line or paragraph. "
        f"Allowed tags: {tags}. "
        "Default to [neutral] or [positive] for most lines; use stronger tags such as "
        "[enthusiasm], [excitement], or [laughs] only when the content warrants it. "
        "Never add emotion tags to Music or Audience lines or to [APPLAUSE] / [MUSIC] cues."
    )


def prepare_narrator_tts_text(text: str, *, schema: str = "legacy") -> str:
    """
    Prepare narrator dialog for TTS.

    Strips show-production bracket cues and unknown [tags]; preserves allowlisted
    Gemini emotion tags. Also removes parenthetical asides and double quotes.

    ``schema`` selects tag handling:
    - ``legacy``: angle-bracket tags pass through untouched (3.1 behavior).
    - ``gemini38``: allowlisted angle-bracket vocal events (<laugh>, <sigh>, ...)
      are preserved; unknown angle tags are stripped.
    """
    filtered = _PRODUCTION_BRACKET_RE.sub("", text)

    def _replace_bracket(match: re.Match[str]) -> str:
        inner = match.group(1).strip().lower()
        if inner in GEMINI_TTS_TAGS:
            return match.group(0)
        logger.warning("Stripping unknown bracket tag [%s]", match.group(1))
        return ""

    filtered = _ANY_BRACKET_RE.sub(_replace_bracket, filtered)
    if schema == "gemini38":
        filtered = _ANY_ANGLE_RE.sub(_replace_angle, filtered)
    filtered = re.sub(r"\(.*?\)", "", filtered)
    filtered = filtered.replace('"', "")
    return re.sub(r"\s+", " ", filtered).strip()


def _replace_angle(match: re.Match[str]) -> str:
    inner = match.group(1).strip().lower()
    if inner in GEMINI38_VOCAL_EVENTS:
        return f"<{inner}>"
    logger.warning("Stripping unknown angle-bracket vocal event <%s>", match.group(1))
    return ""


def build_gemini38_tts_request(
    transcript: str,
    *,
    style: str | None = None,
    section: str | None = None,
) -> dict[str, object]:
    """
    Build a Gemini 3.8 TTS request body fragment for OpenRouter's /audio/speech.

    Gemini 3.8 treats ``input`` as a verbatim transcript; sustained delivery
    moves to ``speech_metadata.style``. Returns a dict suitable for merging
    into the request body (via the OpenAI SDK's ``extra_body``).
    """
    prepared = prepare_narrator_tts_text(transcript, schema="gemini38")
    if not prepared:
        raise ValueError("transcript is empty after narrator text preparation")

    preset = _GEMINI38_SECTION_STYLES.get((section or "").strip().lower())
    style_text = (style or preset or GEMINI38_DEFAULT_STYLE).strip()
    if len(style_text) > _GEMINI38_MAX_STYLE_CHARS:
        style_text = style_text[:_GEMINI38_MAX_STYLE_CHARS].rstrip()
    metadata: dict[str, str] = {"style": style_text}
    return {"input": prepared, "speech_metadata": metadata}


_DEFAULT_AUDIO_PROFILE = (
    "Dris Thile — warm, witty, musicianly NPR host; conversational storytelling "
    "with natural breath and phrasing, like Live From There."
)
_DEFAULT_SCENE = (
    "Live From There stage — intimate live audience, Dris at the mic telling a "
    "first-person story with a light instrumental underscore."
)
_DEFAULT_DIRECTOR_NOTES = (
    "Pacing: relaxed storytelling with natural pauses between beats.\n"
    "Tone: nostalgic, gently humorous, emotionally present without melodrama.\n"
    "Delivery: first-person memoir; vary energy subtly across the arc.\n"
    "Tags: honor inline Gemini emotion tags such as [positive] or [curiosity] "
    "only at clause openings; do not speak tag names literally.\n"
    "Do NOT read section headers, director notes, or sample context aloud — "
    "narrate only the Transcript section."
)
_DEFAULT_SAMPLE_CONTEXT = (
    "Dris is mid-show, between guest segments, sharing a personal anecdote that "
    "feels both specific and universal."
)
_SECTION_PRESETS: dict[str, dict[str, str]] = {
    "intro": {
        "scene": (
            "Live From There show opening — warm house lights, the band vamping "
            "underneath, Dris welcoming the audience before guest introductions."
        ),
        "sample_context": (
            "Top of the show; Dris sets the tone, shares a beat of banter, and builds "
            "toward announcing tonight's guests."
        ),
        "director_notes": (
            "Pacing: energetic but unhurried show-opening rhythm with room for laughs.\n"
            "Tone: warm, witty, hostly — musicianly NPR banter, not announcer-flat.\n"
            "Delivery: direct address to the live audience; vary energy across beats.\n"
            "Tags: honor inline Gemini emotion tags at clause openings only.\n"
            "Do NOT read section headers, director notes, or sample context aloud — "
            "narrate only the Transcript section."
        ),
    },
    "story": {},
    "outro": {
        "scene": (
            "Live From There closing — Dris at the mic thanking guests and the audience "
            "with a light instrumental bed."
        ),
        "sample_context": (
            "End of the show; Dris wraps the evening with gratitude and a call to action."
        ),
        "director_notes": (
            "Pacing: unhurried sign-off with natural warmth.\n"
            "Tone: grateful, lightly humorous, satisfied end-of-show energy.\n"
            "Delivery: first-person host voice; sincere without being saccharine.\n"
            "Tags: honor inline Gemini emotion tags at clause openings only.\n"
            "Do NOT read section headers, director notes, or sample context aloud — "
            "narrate only the Transcript section."
        ),
    },
}
# Gemini TTS output truncates well before the documented 655s cap on long inputs;
# keep each request short enough for ~60–90s of speech.
LONGFORM_TTS_MAX_CHUNK_CHARS = 750
LONGFORM_TTS_CHUNK_PAUSE_MS = 350
_CONTINUATION_TAIL_CHARS = 120
_SENTENCE_SPLIT_RE = re.compile(r"(?<!\w\.\w.)(?<![A-Z][a-z]\.)(?<=\.|\?|\!)\s+")
_DIALOGUE_LINE_RE = re.compile(r'^\s*"', re.MULTILINE)


def _paragraph_has_dialogue(paragraph: str) -> bool:
    return bool(_DIALOGUE_LINE_RE.search(paragraph)) or paragraph.count('"') >= 2


def _split_on_sentences(paragraph: str, max_chars: int) -> list[str]:
    """Split a long paragraph on sentence boundaries."""
    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(paragraph) if s.strip()]
    if not sentences:
        return [paragraph]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for sentence in sentences:
        prepared_len = len(prepare_narrator_tts_text(sentence))
        if prepared_len > max_chars:
            if current:
                chunks.append(" ".join(current))
                current = []
                current_len = 0
            chunks.append(sentence)
            continue
        if current and current_len + prepared_len + 1 > max_chars:
            chunks.append(" ".join(current))
            current = [sentence]
            current_len = prepared_len
        else:
            current.append(sentence)
            current_len += prepared_len + (1 if current_len else 0)
    if current:
        chunks.append(" ".join(current))
    return chunks


def _split_dialogue_paragraph(paragraph: str, max_chars: int) -> list[str]:
    """Split dialogue-heavy paragraphs on blank lines, keeping exchanges intact."""
    blocks = [b.strip() for b in re.split(r"\n\s*\n", paragraph) if b.strip()]
    if len(blocks) <= 1:
        prepared_len = len(prepare_narrator_tts_text(paragraph))
        if prepared_len <= int(max_chars * 1.25):
            return [paragraph]
        return _split_on_sentences(paragraph, max_chars)

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for block in blocks:
        prepared_len = len(prepare_narrator_tts_text(block))
        extra = 2 if current else 0
        if current and current_len + extra + prepared_len > max_chars:
            chunks.append("\n\n".join(current))
            current = [block]
            current_len = prepared_len
        else:
            current.append(block)
            current_len += prepared_len + extra
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def _split_oversized_paragraph(paragraph: str, max_chars: int) -> list[str]:
    """Split a long paragraph without breaking quoted dialogue exchanges."""
    if _paragraph_has_dialogue(paragraph):
        return _split_dialogue_paragraph(paragraph, max_chars)
    return _split_on_sentences(paragraph, max_chars)


def split_longform_transcript(
    transcript: str,
    *,
    max_chars: int = LONGFORM_TTS_MAX_CHUNK_CHARS,
) -> list[str]:
    """
    Split a story transcript into act-sized chunks at paragraph/sentence boundaries.

    Uses prepared (spoken) character counts so prompts stay within Gemini TTS limits.
    """
    transcript = transcript.strip()
    if not transcript:
        return []

    prepared_full = prepare_narrator_tts_text(transcript)
    if len(prepared_full) <= max_chars:
        return [transcript]

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", transcript) if p.strip()]
    if not paragraphs:
        paragraphs = [transcript]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for paragraph in paragraphs:
        prepared_len = len(prepare_narrator_tts_text(paragraph))
        if prepared_len > max_chars:
            if current:
                chunks.append("\n\n".join(current))
                current = []
                current_len = 0
            chunks.extend(_split_oversized_paragraph(paragraph, max_chars))
            continue

        extra = 2 if current else 0
        if current and current_len + extra + prepared_len > max_chars:
            chunks.append("\n\n".join(current))
            current = [paragraph]
            current_len = prepared_len
        else:
            current.append(paragraph)
            current_len += prepared_len + extra

    if current:
        chunks.append("\n\n".join(current))

    logger.info(
        "Split long-form transcript into %s chunk(s) (max_chars=%s, total_prepared=%s)",
        len(chunks),
        max_chars,
        len(prepared_full),
    )
    for i, chunk in enumerate(chunks):
        prepared = prepare_narrator_tts_text(chunk)
        logger.info(
            "Long-form chunk %s/%s (%s chars): %s ... %s",
            i + 1,
            len(chunks),
            len(prepared),
            prepared[:80],
            prepared[-80:] if len(prepared) > 80 else "",
        )
    return chunks


def build_longform_tts_prompt(
    transcript: str,
    *,
    audio_profile: str = _DEFAULT_AUDIO_PROFILE,
    scene: str | None = None,
    director_notes: str | None = None,
    sample_context: str | None = None,
    section: str | None = None,
    chunk_index: int = 0,
    chunk_total: int = 1,
    previous_tail: str | None = None,
) -> str:
    """
    Build a Gemini advanced speech-generation prompt for one coherent narration block.

    See https://ai.google.dev/gemini-api/docs/speech-generation
    """
    prepared = prepare_narrator_tts_text(transcript)
    if not prepared:
        raise ValueError("transcript is empty after narrator text preparation")

    section_preset = _SECTION_PRESETS.get((section or "").strip().lower(), {})
    profile = audio_profile.strip()
    scene_text = (scene or section_preset.get("scene") or _DEFAULT_SCENE).strip()

    if chunk_total > 1 and chunk_index > 0:
        notes = (
            director_notes
            or (
                "Continue seamlessly from the previous beat with the same voice, tone, "
                "and pacing. Do NOT read section headers aloud — narrate only the "
                "Transcript section."
            )
        ).strip()
        context = (
            sample_context
            or section_preset.get("sample_context")
            or "Continuing narration on the Live From There stage."
        ).strip()
        if previous_tail:
            context += f' Pick up immediately after: "...{previous_tail.strip()}"'
        part_label = f"Part {chunk_index + 1} of {chunk_total}"
        return (
            f"Audio Profile: {profile}\n\n"
            f"The Scene: {scene_text} ({part_label}, continuing)\n\n"
            f"Director's Notes:\n{notes}\n\n"
            f"Sample Context: {context}\n\n"
            f"Transcript:\n{prepared}"
        )

    notes = (
        director_notes
        or section_preset.get("director_notes")
        or _DEFAULT_DIRECTOR_NOTES
    ).strip()
    if chunk_total > 1:
        notes += (
            f"\nThis narration is part {chunk_index + 1} of {chunk_total}; "
            "read the full transcript through a natural pause at the end."
        )
    context = (
        sample_context
        or section_preset.get("sample_context")
        or _DEFAULT_SAMPLE_CONTEXT
    ).strip()

    return (
        f"Audio Profile: {profile}\n\n"
        f"The Scene: {scene_text}\n\n"
        f"Director's Notes:\n{notes}\n\n"
        f"Sample Context: {context}\n\n"
        f"Transcript:\n{prepared}"
    )
