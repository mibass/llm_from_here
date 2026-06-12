from llm_from_here.schemas.llm_outputs import intro_lines_to_longform_segments

_VALID_MUSIC = (
    "[MUSIC Create a 180-second instrumental track at 110 BPM. Live acoustic bluegrass intro. "
    "Banjo, mandolin, upright bass, brushed drums, warm and energetic. Instrumental only, no vocals.]"
)


def test_intro_lines_to_longform_segments_merges_dris():
    lines = [
        {"speaker": "Music", "dialog": _VALID_MUSIC},
        {"speaker": "Dris Thile", "dialog": "[positive] Welcome back."},
        {"speaker": "Dris Thile", "dialog": "Tonight we have great guests."},
        {"speaker": "Audience", "dialog": "[APPLAUSE duration 5]"},
        {"speaker": "Dris Thile", "dialog": "[enthusiasm] Let's meet them."},
    ]
    segments = intro_lines_to_longform_segments(lines)
    assert [s["speaker"] for s in segments] == [
        "music",
        "dris thile",
        "audience",
        "dris thile",
    ]
    assert "Welcome back." in segments[1]["dialog"]
    assert "Tonight we have great guests." in segments[1]["dialog"]
    assert segments[3]["dialog"] == "[enthusiasm] Let's meet them."
