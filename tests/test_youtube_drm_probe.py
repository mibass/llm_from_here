"""Unit tests for YouTube DRM / extractability probing (ytfetch metadata)."""

from llm_from_here.plugins.ytfetch import info_has_playable_youtube_audio


def test_info_has_playable_youtube_audio_empty():
    assert info_has_playable_youtube_audio({}) is False


def test_info_has_playable_youtube_audio_no_formats_key():
    assert info_has_playable_youtube_audio({"title": "x"}) is False


def test_info_has_playable_youtube_audio_drm_only():
    info = {
        "formats": [
            {"acodec": "mp4a.40.2", "has_drm": True},
            {"acodec": "opus", "has_drm": True},
        ]
    }
    assert info_has_playable_youtube_audio(info) is False


def test_info_has_playable_youtube_audio_clean_audio():
    info = {"formats": [{"acodec": "opus", "has_drm": False}]}
    assert info_has_playable_youtube_audio(info) is True


def test_info_has_playable_youtube_audio_missing_has_drm_treated_ok():
    """Unset ``has_drm`` means not explicitly flagged DRM-only."""
    info = {"formats": [{"acodec": "opus"}]}
    assert info_has_playable_youtube_audio(info) is True


def test_info_has_playable_youtube_audio_maybedrm_rejected():
    """Match yt-dlp ``has_drm == \"maybe\"`` bucket (ambiguous DRM)."""
    info = {"formats": [{"acodec": "opus", "has_drm": "maybe"}]}
    assert info_has_playable_youtube_audio(info) is False


def test_info_has_playable_youtube_audio_video_only_streams_skipped():
    info = {"formats": [{"acodec": "none", "vcodec": "avc1"}]}
    assert info_has_playable_youtube_audio(info) is False


def test_info_has_playable_youtube_audio_mixed_drm_and_clean():
    info = {
        "formats": [
            {"acodec": "opus", "has_drm": True},
            {"acodec": "mp4a.40.2"},
        ]
    }
    assert info_has_playable_youtube_audio(info) is True
