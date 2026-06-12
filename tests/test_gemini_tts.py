import os
from unittest.mock import MagicMock

from llm_from_here.gemini_tts import (
    GEMINI_TTS_TAGS,
    build_longform_tts_prompt,
    gemini_tag_prompt_block,
    prepare_narrator_tts_text,
    split_longform_transcript,
)


def test_prepare_narrator_preserves_gemini_tag():
    assert prepare_narrator_tts_text("[positive] Hello there.") == "[positive] Hello there."


def test_prepare_narrator_strips_production_cues():
    assert (
        prepare_narrator_tts_text("[positive] Welcome [APPLAUSE duration 5] folks")
        == "[positive] Welcome folks"
    )


def test_prepare_narrator_strips_unknown_brackets():
    assert prepare_narrator_tts_text("[Hello] world") == "world"


def test_prepare_narrator_strips_parens_and_quotes():
    assert prepare_narrator_tts_text('[positive] Say "hi" (quietly)') == "[positive] Say hi"


def test_gemini_tag_prompt_block_lists_tags():
    block = gemini_tag_prompt_block()
    assert "[positive]" in block
    assert "[neutral]" in block


def test_segments_to_timeline_tts_passes_gemini_tags():
    import tempfile

    from llm_from_here.plugins.segmentsToTimeline import SegmentsToTimeline

    params = {
        "segments_object": "intro_intro",
        "segment_type_key": "speaker",
        "segment_value_key": "dialog",
        "segment_type_map": {},
        "segment_transition_map": [],
    }
    with tempfile.TemporaryDirectory() as temp_dir:
        stt = SegmentsToTimeline(
            params,
            {"output_folder": temp_dir},
            "test_instance",
        )
        stt.show_tts = MagicMock()
        out = os.path.join(temp_dir, "line.wav")
        stt.tts("[positive] Hello world", out, fast_tts=False)
        stt.show_tts.speak.assert_called_once_with(
            "[positive] Hello world", out, fast=False
        )


def test_allowlist_nonempty():
    assert "positive" in GEMINI_TTS_TAGS
    assert "whispers" in GEMINI_TTS_TAGS


def test_build_longform_tts_prompt_structure():
    transcript = "[positive] Hello from the stage."
    prompt = build_longform_tts_prompt(transcript)
    assert "Audio Profile:" in prompt
    assert "The Scene:" in prompt
    assert "Director's Notes:" in prompt
    assert "Sample Context:" in prompt
    assert "Transcript:" in prompt
    assert "[positive] Hello from the stage." in prompt
    assert "Do NOT read section headers" in prompt


def test_split_longform_transcript_keeps_short_text():
    text = "[positive] Short story beat."
    assert split_longform_transcript(text) == [text]


def test_split_longform_transcript_splits_paragraphs():
    paragraphs = [
        "[positive] " + ("Word " * 80).strip() + ".",
        "[neutral] " + ("Another " * 80).strip() + ".",
        "[curiosity] " + ("Final " * 80).strip() + ".",
    ]
    text = "\n\n".join(paragraphs)
    chunks = split_longform_transcript(text, max_chars=300)
    assert len(chunks) >= 2
    joined = " ".join(prepare_narrator_tts_text(c) for c in chunks)
    assert len(joined) >= len(prepare_narrator_tts_text(text)) - 10


def test_split_longform_transcript_keeps_dialogue_together():
    avocado_para = (
        "Lost in reverie, I turned a corner and literally bumped into a pyramid of avocados. "
        "That was a metaphor for something, though pinpointing what exactly escaped me as "
        "the ensuing conversation with the store clerk took an unexpected turn:\n\n"
        '"Sorry about that," I chuckled, bending to assist. "Looks like they were ripe for the picking."\n\n'
        '"No worries," replied the clerk, eyes as wise as a moonlit owl. '
        '"Gravity and avocados have a way of finding each other."\n\n'
        '"True enough," I said, setting the last avocado in place. '
        '"Only they can turn a stumble into guacamole."'
    )
    chunks = split_longform_transcript(avocado_para, max_chars=400)
    joined = " ".join(prepare_narrator_tts_text(c) for c in chunks)
    assert "Sorry about that" in joined
    assert "No worries" in joined
    assert "True enough" in joined
    for chunk in chunks:
        text = prepare_narrator_tts_text(chunk)
        if "No worries" in text and "Sorry about that" not in text:
            assert "unexpected turn" not in text or "Sorry" in text


def test_build_longform_tts_prompt_continuation_includes_tail():
    prompt = build_longform_tts_prompt(
        "[neutral] The clerk smiled.",
        chunk_index=1,
        chunk_total=2,
        previous_tail="bumped into a pyramid of avocados.",
    )
    assert "Pick up immediately after" in prompt
    assert "pyramid of avocados" in prompt


def test_build_longform_tts_prompt_continuation_chunk():
    prompt = build_longform_tts_prompt(
        "[neutral] Picking up the thread.",
        chunk_index=1,
        chunk_total=3,
    )
    assert "Part 2 of 3" in prompt
    assert "Continue seamlessly" in prompt


def test_build_longform_tts_prompt_intro_section():
    prompt = build_longform_tts_prompt("[positive] Good evening.", section="intro")
    assert "show opening" in prompt
    assert "announcing tonight's guests" in prompt


def test_build_longform_tts_prompt_custom_profile():
    prompt = build_longform_tts_prompt(
        "[neutral] Test line.",
        audio_profile="Custom Host",
        scene="Custom stage",
    )
    assert "Audio Profile: Custom Host" in prompt
    assert "The Scene: Custom stage" in prompt


def test_gemini_longform_tts_uses_speak_longform():
    import tempfile

    from pydub import AudioSegment

    from llm_from_here.plugins.segmentsToTimeline import SegmentsToTimeline

    params = {
        "segments_object": "story_segments",
        "segment_type_key": "speaker",
        "segment_value_key": "dialog",
        "segment_type_map": {},
        "segment_transition_map": [],
    }
    with tempfile.TemporaryDirectory() as temp_dir:
        stt = SegmentsToTimeline(
            params,
            {"output_folder": temp_dir},
            "test_instance",
        )
        stt.show_tts = MagicMock()

        def _write_silent_wav(prompt, path, **kwargs):
            AudioSegment.silent(duration=50).export(path, format="wav")

        stt.show_tts.speak_longform.side_effect = _write_silent_wav
        out = os.path.join(temp_dir, "story.wav")
        stt.gemini_longform_TTS("[positive] Story block text here.", out)
        stt.show_tts.speak_longform.assert_called_once()
        prompt = stt.show_tts.speak_longform.call_args[0][0]
        assert "Transcript:" in prompt
        assert "[positive] Story block text here." in prompt


def test_gemini_longform_tts_chunks_long_transcript():
    import tempfile

    from pydub import AudioSegment

    from llm_from_here.plugins.segmentsToTimeline import SegmentsToTimeline

    paragraphs = [
        "[positive] " + ("Word " * 80).strip() + ".",
        "[neutral] " + ("Another " * 80).strip() + ".",
        "[curiosity] " + ("Final " * 80).strip() + ".",
    ]
    text = "\n\n".join(paragraphs)

    params = {
        "segments_object": "story_segments",
        "segment_type_key": "speaker",
        "segment_value_key": "dialog",
        "segment_type_map": {},
        "segment_transition_map": [],
    }
    with tempfile.TemporaryDirectory() as temp_dir:
        stt = SegmentsToTimeline(
            params,
            {"output_folder": temp_dir},
            "test_instance",
        )
        stt.show_tts = MagicMock()

        def _write_silent_wav(prompt, path, **kwargs):
            AudioSegment.silent(duration=50).export(path, format="wav")

        stt.show_tts.speak_longform.side_effect = _write_silent_wav
        out = os.path.join(temp_dir, "story.wav")
        stt.gemini_longform_TTS(text, out, max_chunk_chars=300)
        assert stt.show_tts.speak_longform.call_count >= 2
        assert os.path.exists(out)
