import os
import tempfile
from unittest.mock import MagicMock

import numpy as np

from llm_from_here.gemini_tts import (
    GEMINI38_DEFAULT_STYLE,
    GEMINI38_VOCAL_EVENTS,
    build_gemini38_tts_request,
    is_gemini38_tts_slug,
    prepare_narrator_tts_text,
)


def test_is_gemini38_slug_detection():
    assert is_gemini38_tts_slug("google/gemini-3.8-flash-tts")
    assert is_gemini38_tts_slug("google/gemini-3.8-flash-lite-tts")
    assert not is_gemini38_tts_slug("google/gemini-3.1-flash-tts-preview")
    assert not is_gemini38_tts_slug(None)
    assert not is_gemini38_tts_slug("openai/gpt-4o-mini-tts")


def test_vocal_event_allowlist_nonempty():
    assert "laugh" in GEMINI38_VOCAL_EVENTS
    assert "sigh" in GEMINI38_VOCAL_EVENTS
    assert "short pause" in GEMINI38_VOCAL_EVENTS


def test_prepare_narrator_gemini38_preserves_vocal_events():
    text = "<laugh> That show! <sigh> Then a <short pause> and <laughs>"
    out = prepare_narrator_tts_text(text, schema="gemini38")
    assert "<laugh>" in out
    assert "<sigh>" in out
    assert "<short pause>" in out
    assert "<laughs>" in out


def test_prepare_narrator_gemini38_strips_unknown_angle():
    out = prepare_narrator_tts_text("<whistle> And then.", schema="gemini38")
    assert "<whistle>" not in out
    assert out == "And then."


def test_prepare_narrator_legacy_leaves_angle_untouched():
    text = "<laugh> Hello there."
    assert prepare_narrator_tts_text(text, schema="legacy") == "<laugh> Hello there."


def test_build_gemini38_request_transcript_and_metadata():
    request = build_gemini38_tts_request("[positive] Hello from the stage.")
    assert request["input"] == "[positive] Hello from the stage."
    assert request["speech_metadata"] == {"style": GEMINI38_DEFAULT_STYLE}


def test_build_gemini38_request_strips_production_cues():
    request = build_gemini38_tts_request("[positive] Hello [APPLAUSE duration 5] folks")
    assert request["input"] == "[positive] Hello folks"


def test_build_gemini38_request_section_style():
    request = build_gemini38_tts_request("Good evening.", section="intro")
    style = request["speech_metadata"]["style"]
    assert "host opening" in style


def test_build_gemini38_request_custom_style_overrides_section():
    request = build_gemini38_tts_request(
        "Good evening.", style="Whispered urgently", section="intro"
    )
    assert request["speech_metadata"]["style"] == "Whispered urgently"


def test_build_gemini38_request_empty_raises():
    try:
        build_gemini38_tts_request("[APPLAUSE duration 5]")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_gemini_longform_tts_uses_structured_schema_for_38():
    import wave
    import numpy as np
    import pydub

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
            seg = pydub.AudioSegment(
                data=np.zeros(1200, dtype=np.int16),
                frame_rate=24000,
                sample_width=2,
                channels=1,
            )
            seg.export(path, format="wav")

        stt.show_tts.speak_longform.side_effect = _write_silent_wav
        out = os.path.join(temp_dir, "story.wav")
        stt.gemini_longform_TTS(
            "[positive] Story block text here.",
            out,
            tts_model="google/gemini-3.8-flash-tts",
        )
        stt.show_tts.speak_longform.assert_called_once()
        kwargs = stt.show_tts.speak_longform.call_args[1]
        assert kwargs["speech_metadata"]["style"] == GEMINI38_DEFAULT_STYLE
        text = stt.show_tts.speak_longform.call_args[0][0]
        assert "Audio Profile:" not in text
        assert "[positive] Story block text here." in text
        wave.open(out, "rb").close()


def test_gemini_longform_tts_legacy_schema_unchanged_for_31():
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
        kwargs = stt.show_tts.speak_longform.call_args[1]
        assert "speech_metadata" not in kwargs or kwargs["speech_metadata"] is None
        prompt = stt.show_tts.speak_longform.call_args[0][0]
        assert "Transcript:" in prompt


def test_showtts_speak_longform_passes_speech_metadata():
    from llm_from_here.plugins import showTTS as showtts_mod

    tts = showtts_mod.ShowTextToSpeech()
    fake_client = MagicMock()
    tts._openrouter_client = fake_client

    import pydub

    with tempfile.TemporaryDirectory() as temp_dir:
        out = os.path.join(temp_dir, "line.wav")

        silence = pydub.AudioSegment.silent(duration=50)
        silence.export(out, format="wav")
        import io

        import io

        mp3_buf = io.BytesIO()
        silence.export(mp3_buf, format="mp3")
        # gemini-3.8 slug routes to pcm decode: use raw 24kHz mono 16-bit bytes.
        pcm_bytes = (np.zeros(1200, dtype=np.int16)).tobytes()
        fake_resp = MagicMock()

        def _stream_to_file(path):
            with open(path, "wb") as f:
                f.write(pcm_bytes)

        fake_resp.stream_to_file.side_effect = _stream_to_file
        fake_client.audio.speech.create.return_value = fake_resp

        tts.speak_longform(
            "[positive] Hello.",
            out,
            model="google/gemini-3.8-flash-tts",
            speech_metadata={"style": "warm"},
        )
        call = fake_client.audio.speech.create.call_args
        assert call.kwargs.get("extra_body") == {"speech_metadata": {"style": "warm"}}
        assert call.kwargs.get("model") == "google/gemini-3.8-flash-tts"
