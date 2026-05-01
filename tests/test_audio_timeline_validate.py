"""Regression: timeline loads files by path so pydub/ffmpeg can sniff container."""

from pydub import AudioSegment

from llm_from_here.plugins.audioTimeline import AudioTimeline


def test_validate_audio_loads_wav_by_path(tmp_path):
    wav_path = tmp_path / "clip.wav"
    AudioSegment.silent(duration=50).export(wav_path, format="wav")

    tl = AudioTimeline()
    seg = tl._validate_audio(str(wav_path))
    assert isinstance(seg, AudioSegment)
    assert len(seg) == 50
