import base64
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from llm_from_here.openrouter_music import (
    LyriaContentFilterError,
    LyriaEmptyStreamError,
    _collect_streamed_mp3,
    _collect_streamed_mp3_with_retry,
    _looks_like_codebook_tokens,
    _lyria_retry_delay_for_attempt,
    _lyria_retry_delays_sec,
    generate_instrumental,
    normalize_music_prompt,
    simplified_music_prompt,
    youtube_fallback_query,
)
from llm_from_here.schemas.llm_outputs import IntroLine


class TestNormalizeMusicPrompt(unittest.TestCase):
    def test_strips_music_wrapper(self):
        cue = "[MUSIC Create an approximately 3 minute bluegrass intro. Instrumental only, no vocals.]"
        out = normalize_music_prompt(cue)
        self.assertTrue(out.startswith("Create an approximately 3 minute"))
        self.assertIn("Instrumental only, no vocals", out)

    def test_strips_background_wrapper(self):
        cue = "[background: Acoustic folk underscore, ~88 BPM. Instrumental only, no vocals.]"
        out = normalize_music_prompt(cue)
        self.assertTrue(out.startswith("Acoustic folk underscore"))

    def test_appends_no_vocals_guard(self):
        out = normalize_music_prompt("[MUSIC Warm jazz piano, ~90 BPM.]")
        self.assertIn("Instrumental only, no vocals.", out)


class TestYoutubeFallbackQuery(unittest.TestCase):
    def test_truncates_long_prompt(self):
        cue = (
            "[MUSIC Create an approximately 3 minute live acoustic bluegrass intro. "
            "Banjo, mandolin, upright bass, brushed drums, ~110 BPM, warm and energetic. "
            "Instrumental only, no vocals.]"
        )
        query = youtube_fallback_query(cue)
        self.assertLessEqual(len(query), 80)
        self.assertIn("bluegrass", query.lower())


class TestIntroLineMusicCue(unittest.TestCase):
    def test_accepts_full_music_prompt(self):
        line = IntroLine(
            speaker="Music",
            dialog=(
                "[MUSIC Create an approximately 3 minute live acoustic bluegrass intro. "
                "Banjo, mandolin, upright bass, brushed drums, ~110 BPM, warm and energetic. "
                "Instrumental only, no vocals.]"
            ),
        )
        self.assertEqual(line.speaker, "Music")

    def test_rejects_short_music_tag_only(self):
        with self.assertRaises(ValueError):
            IntroLine(speaker="Music", dialog="[MUSIC bluegrass]")

    def test_chris_thile_alias_normalizes_to_dris(self):
        line = IntroLine(speaker="Chris Thile", dialog="Good evening, folks.")
        self.assertEqual(line.speaker, "Dris Thile")


class TestGenerateInstrumental(unittest.TestCase):
    @patch("llm_from_here.openrouter_music._segment_from_openrouter_speech_file")
    @patch("llm_from_here.openrouter_music._collect_streamed_mp3_with_retry")
    def test_writes_wav_from_stream(self, mock_collect, mock_decode):
        mock_collect.return_value = b"\xff\xfb" + b"\x00" * 128
        mock_audio = MagicMock()
        mock_decode.return_value = mock_audio

        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "track.wav")
            meta = generate_instrumental(
                "[MUSIC Short folk cue. Instrumental only, no vocals.]",
                out,
                client=MagicMock(),
            )
            mock_collect.assert_called_once()
            mock_audio.export.assert_called_once_with(out, format="wav")
            self.assertEqual(meta["source"], "openrouter_lyria")


class TestLyriaHelpers(unittest.TestCase):
    def test_looks_like_codebook_tokens(self):
        self.assertTrue(_looks_like_codebook_tokens(["[[A0]] [[B1]] [[C2]]"]))
        self.assertFalse(_looks_like_codebook_tokens(["sorry, no audio"]))

    def test_simplified_music_prompt_is_safe_generic(self):
        original = (
            "Create a 180-second instrumental track at 95 BPM. Live acoustic folk-rock intro. "
            "Mandolin, acoustic guitar, upright bass, light percussion."
        )
        fallback = simplified_music_prompt(original)
        self.assertIn("180-second", fallback)
        self.assertIn("folk instrumental", fallback.lower())
        self.assertIn("no vocals", fallback.lower())
        self.assertNotIn("rock", fallback.lower())

    def test_default_retry_delays(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LLMFH_LYRIA_RETRY_DELAYS_SEC", None)
            self.assertEqual(_lyria_retry_delays_sec(), (2.0, 8.0, 20.0))
        self.assertEqual(_lyria_retry_delay_for_attempt(1), 2.0)
        self.assertEqual(_lyria_retry_delay_for_attempt(2), 8.0)
        self.assertEqual(_lyria_retry_delay_for_attempt(3), 20.0)


class TestCollectStreamedMp3(unittest.TestCase):
    def test_parses_delta_audio_chunks(self):
        payload = base64.b64encode(b"fake-mp3-bytes").decode("ascii")
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta = MagicMock()
        chunk.choices[0].delta.audio = {"data": payload}

        client = MagicMock()
        client.chat.completions.create.return_value = [chunk]

        data = _collect_streamed_mp3(client, "google/lyria-3-pro-preview", "prompt")
        self.assertEqual(data, b"fake-mp3-bytes")

    def test_empty_stream_raises_lyria_empty_stream_error(self):
        text_chunk = MagicMock()
        text_chunk.choices = [MagicMock()]
        text_chunk.choices[0].delta = MagicMock()
        text_chunk.choices[0].delta.audio = None
        text_chunk.choices[0].delta.content = "sorry, no audio"

        client = MagicMock()
        client.chat.completions.create.return_value = [text_chunk]

        with self.assertRaises(LyriaEmptyStreamError):
            _collect_streamed_mp3(client, "google/lyria-3-pro-preview", "prompt")

    def test_codebook_tokens_raise_content_filter_error(self):
        text_chunk = MagicMock()
        text_chunk.choices = [MagicMock()]
        text_chunk.choices[0].delta = MagicMock()
        text_chunk.choices[0].delta.audio = None
        text_chunk.choices[0].delta.content = "[[A0]] [[B1]] [[C2]]"

        client = MagicMock()
        client.chat.completions.create.return_value = [text_chunk]

        with self.assertRaises(LyriaContentFilterError):
            _collect_streamed_mp3(client, "google/lyria-3-pro-preview", "folk-rock intro")

    @patch("llm_from_here.openrouter_music.time.sleep")
    def test_content_filter_retries_with_simplified_prompt(self, mock_sleep):
        payload = base64.b64encode(b"fallback-mp3").decode("ascii")
        ok_chunk = MagicMock()
        ok_chunk.choices = [MagicMock()]
        ok_chunk.choices[0].delta = MagicMock()
        ok_chunk.choices[0].delta.audio = {"data": payload}

        filter_chunk = MagicMock()
        filter_chunk.choices = [MagicMock()]
        filter_chunk.choices[0].delta = MagicMock()
        filter_chunk.choices[0].delta.audio = None
        filter_chunk.choices[0].delta.content = "[[A0]] [[A1]]"

        client = MagicMock()
        client.chat.completions.create.side_effect = [
            [filter_chunk],
            [ok_chunk],
        ]

        data = _collect_streamed_mp3_with_retry(
            client,
            "google/lyria-3-pro-preview",
            "folk-rock intro prompt",
            max_attempts=3,
            retry_delay_sec=0,
        )
        self.assertEqual(data, b"fallback-mp3")
        self.assertEqual(client.chat.completions.create.call_count, 2)
        fallback_prompt = client.chat.completions.create.call_args_list[1].kwargs["messages"][0][
            "content"
        ]
        self.assertIn("folk instrumental", fallback_prompt.lower())
        self.assertIn("180-second", fallback_prompt)
        mock_sleep.assert_not_called()

    @patch("llm_from_here.openrouter_music.time.sleep")
    def test_exponential_backoff_between_empty_stream_retries(self, mock_sleep):
        payload = base64.b64encode(b"retry-mp3").decode("ascii")
        ok_chunk = MagicMock()
        ok_chunk.choices = [MagicMock()]
        ok_chunk.choices[0].delta = MagicMock()
        ok_chunk.choices[0].delta.audio = {"data": payload}

        empty_chunk = MagicMock()
        empty_chunk.choices = [MagicMock()]
        empty_chunk.choices[0].delta = MagicMock()
        empty_chunk.choices[0].delta.audio = None

        client = MagicMock()
        client.chat.completions.create.side_effect = [
            [empty_chunk],
            [ok_chunk],
        ]

        data = _collect_streamed_mp3_with_retry(
            client,
            "google/lyria-3-pro-preview",
            "prompt",
            max_attempts=2,
        )
        self.assertEqual(data, b"retry-mp3")
        self.assertEqual(client.chat.completions.create.call_count, 2)
        mock_sleep.assert_called_once_with(2.0)

    @patch("llm_from_here.openrouter_music.time.sleep")
    def test_retry_succeeds_on_second_attempt(self, mock_sleep):
        payload = base64.b64encode(b"retry-mp3").decode("ascii")
        ok_chunk = MagicMock()
        ok_chunk.choices = [MagicMock()]
        ok_chunk.choices[0].delta = MagicMock()
        ok_chunk.choices[0].delta.audio = {"data": payload}

        empty_chunk = MagicMock()
        empty_chunk.choices = [MagicMock()]
        empty_chunk.choices[0].delta = MagicMock()
        empty_chunk.choices[0].delta.audio = None

        client = MagicMock()
        client.chat.completions.create.side_effect = [
            [empty_chunk],
            [ok_chunk],
        ]

        data = _collect_streamed_mp3_with_retry(
            client,
            "google/lyria-3-pro-preview",
            "prompt",
            max_attempts=2,
            retry_delay_sec=0,
        )
        self.assertEqual(data, b"retry-mp3")
        self.assertEqual(client.chat.completions.create.call_count, 2)
        mock_sleep.assert_not_called()

    def test_collect_uses_audio_only_modality(self):
        payload = base64.b64encode(b"fake-mp3-bytes").decode("ascii")
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta = MagicMock()
        chunk.choices[0].delta.audio = {"data": payload}

        client = MagicMock()
        client.chat.completions.create.return_value = [chunk]

        _collect_streamed_mp3(client, "google/lyria-3-pro-preview", "prompt")

        kwargs = client.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs["extra_body"]["modalities"], ["audio"])
        self.assertEqual(kwargs["extra_body"]["audio"], {"format": "mp3"})

    def test_retry_exhausted_raises(self):
        empty_chunk = MagicMock()
        empty_chunk.choices = [MagicMock()]
        empty_chunk.choices[0].delta = MagicMock()
        empty_chunk.choices[0].delta.audio = None

        client = MagicMock()
        client.chat.completions.create.return_value = [empty_chunk]

        with self.assertRaises(LyriaEmptyStreamError):
            _collect_streamed_mp3_with_retry(
                client,
                "google/lyria-3-pro-preview",
                "prompt",
                max_attempts=2,
                retry_delay_sec=0,
            )
        self.assertEqual(client.chat.completions.create.call_count, 2)


if __name__ == "__main__":
    unittest.main()
