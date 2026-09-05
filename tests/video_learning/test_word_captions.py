from deeptutor.video_learning.service import normalize_cues, parse_webvtt


def test_preserves_source_word_timing_and_entities():
    cues = normalize_cues(
        parse_webvtt(
            "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nHello <00:00:02.000><c>world &amp; friends</c>\n"
        )
    )
    assert cues[0]["text"] == "Hello world & friends"
    assert cues[0]["words"] == [
        {"start": 1.0, "end": 2.0, "text": "Hello "},
        {"start": 2.0, "end": 3.0, "text": "world & friends"},
    ]


def test_sentence_only_and_multiline_remain_compatible():
    cue = normalize_cues(parse_webvtt("00:00:01.000 --> 00:00:03.000\n第一行\nsecond line\n"))[0]
    assert "words" not in cue
    assert cue["lines"] == ["第一行", "second line"]
    assert cue["text"] == "第一行 second line"


def test_invalid_inline_times_fall_back_without_inventing_timing():
    cue = normalize_cues(
        parse_webvtt("00:00:01.000 --> 00:00:03.000\nHello <00:00:04.000>world\n")
    )[0]
    assert "words" not in cue
    assert cue["text"] == "Hello world"


def test_rejects_unordered_word_times_and_nonfinite_cues():
    assert normalize_cues([{"start": float("inf"), "end": float("inf"), "text": "bad"}]) == []
    cue = normalize_cues(
        [
            {
                "start": 1,
                "end": 4,
                "text": "a b",
                "words": [{"start": 2, "end": 3, "text": "a"}, {"start": 1, "end": 2, "text": "b"}],
            }
        ]
    )[0]
    assert "words" not in cue
