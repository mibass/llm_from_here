"""Unit tests for narrator reverb (pedalboard)."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from pydub import AudioSegment, generators

from llm_from_here.plugins import audioEffects
from llm_from_here.plugins.audioTimeline import AudioTimeline


class AudioEffectsTest(unittest.TestCase):
    def test_apply_narrator_reverb_disabled_returns_unchanged(self):
        tone = generators.Sine(440).to_audio_segment(duration=500)
        out = audioEffects.apply_narrator_reverb(tone, {"enabled": False})
        self.assertEqual(len(out), len(tone))
        self.assertEqual(out.raw_data, tone.raw_data)

    def test_apply_narrator_reverb_none_config(self):
        tone = generators.Sine(440).to_audio_segment(duration=500)
        out = audioEffects.apply_narrator_reverb(tone, None)
        self.assertEqual(out.raw_data, tone.raw_data)

    def test_convolution_reverb_changes_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            ir_path = os.path.join(tmp, "test_ir.wav")
            audioEffects.ensure_default_impulse_response(ir_path)
            tone = generators.Sine(440).to_audio_segment(duration=800).set_frame_rate(44100)
            config = {
                "enabled": True,
                "mode": "convolution",
                "impulse_response": ir_path,
                "wet_db": -8,
                "high_cut_hz": 8000,
            }
            out = audioEffects.apply_narrator_reverb(tone, config)
        self.assertGreaterEqual(len(out), len(tone))
        self.assertNotEqual(out.raw_data[: len(tone.raw_data)], tone.raw_data)

    def test_algorithmic_reverb_changes_audio(self):
        tone = generators.Sine(440).to_audio_segment(duration=800).set_frame_rate(44100)
        out = audioEffects.apply_narrator_reverb(
            tone,
            {
                "enabled": True,
                "mode": "reverb",
                "room_size": 0.5,
                "wet_level": 0.4,
                "dry_level": 0.85,
            },
        )
        self.assertNotEqual(out.raw_data, tone.raw_data)

    def test_timeline_without_reverb_unchanged(self):
        timeline = AudioTimeline()
        tone = generators.Sine(440).to_audio_segment(duration=400)
        timeline.add_to_timeline(tone, start_time=0)
        stored = timeline.timeline[0]["audio"]
        self.assertEqual(stored.raw_data, tone.raw_data)

    def test_render_applies_narrator_reverb(self):
        tone = generators.Sine(440).to_audio_segment(duration=800).set_frame_rate(44100)
        timeline = AudioTimeline(
            params={
                "narrator_reverb": {
                    "enabled": True,
                    "mode": "reverb",
                    "room_size": 0.7,
                    "wet_level": 0.55,
                    "dry_level": 0.7,
                },
                "narrator_segment_types": ["dris thile"],
            }
        )
        timeline.add_to_timeline(
            tone, start_time=0, type="dris thile", name="narrator"
        )
        with tempfile.TemporaryDirectory() as tmp:
            out_path = os.path.join(tmp, "rendered.wav")
            timeline.render(out_path, "wav")
            rendered = AudioSegment.from_wav(out_path)
        self.assertNotEqual(rendered.raw_data, tone.raw_data)

    def test_reverb_failure_returns_dry_audio(self):
        tone = generators.Sine(440).to_audio_segment(duration=400)
        with patch(
            "llm_from_here.plugins.audioEffects._apply_convolution_reverb",
            side_effect=RuntimeError("boom"),
        ):
            out = audioEffects.apply_narrator_reverb(
                tone,
                {"enabled": True, "mode": "convolution", "impulse_response": "missing.wav"},
            )
        self.assertEqual(out.raw_data, tone.raw_data)


if __name__ == "__main__":
    unittest.main()
