import pytest

from shortyy.llm import LLMError
from shortyy.selection import build_prompt, clean_caption, clean_hashtags, select_clips, snap, validate_clips

OPTIONS = {"clip_count": 3, "min_seconds": 15, "max_seconds": 30, "instructions": ""}


def raw(start, end, rank=1, **extra):
    return {
        "rank": rank,
        "start_seconds": start,
        "end_seconds": end,
        "title": f"t{rank}",
        "post_title": "p",
        "caption": "c",
        "hashtags": ["a"],
        "rationale": "r",
        "overall_score": 8,
        **extra,
    }


def test_snap_moves_to_sentence_boundaries(transcript):
    start, end = snap(6.3, 23.0, transcript["sentences"], 15, 30)
    assert start == 6.0
    assert end == pytest.approx(transcript["sentences"][3]["end"])


def test_snap_extends_short_clip_to_minimum(transcript):
    start, end = snap(0.1, 5.0, transcript["sentences"], 15, 30)
    assert end - start >= 15


def test_snap_trims_long_clip_at_sentence_end(transcript):
    start, end = snap(0.0, 59.0, transcript["sentences"], 15, 30)
    assert end - start <= 30
    assert end in {s["end"] for s in transcript["sentences"]}


def test_validate_drops_overlaps_and_renumbers(transcript):
    clips = validate_clips([raw(0, 20, 1), raw(5, 25, 2), raw(36, 55, 3)], transcript, OPTIONS)
    assert [c["rank"] for c in clips] == [1, 2]
    assert clips[1]["start_seconds"] == 36.0
    assert clips[0]["transcript"].startswith("sentence 0")


def test_validate_respects_clip_count(transcript):
    options = {**OPTIONS, "clip_count": 1}
    assert len(validate_clips([raw(0, 20, 1), raw(36, 55, 2)], transcript, options)) == 1


def test_validate_skips_garbage(transcript):
    assert validate_clips([{"rank": 1, "start_seconds": "x"}], transcript, OPTIONS) == []


def test_caption_and_hashtag_cleanup():
    assert clean_caption("Great point (87 chars)") == "Great point"
    tags, caption = clean_hashtags(["growth", "#Startups", "#growth"], "Build things #founders #Startups")
    assert caption == "Build things"
    assert tags == ["#growth", "#Startups", "#founders"]


def test_prompt_includes_options_and_instructions(transcript):
    system, user = build_prompt(
        {"title": "Talk", "uploader": "Ann", "duration_seconds": 60},
        transcript,
        {**OPTIONS, "instructions": "End captions with 'Follow for more'"},
    )
    assert "up to 3" in system and "between 15 and 30 seconds" in system
    assert "Follow for more" in system
    assert "[0.0-" in user and "Talk by Ann" in user


class FakeLLM:
    model = "fake"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def complete_json(self, system, user, schema, name):
        self.calls += 1
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_select_clips_retries_until_valid(transcript):
    llm = FakeLLM([LLMError("boom"), {"clips": [{"rank": 1}]}, {"clips": [raw(0, 20)]}])
    result = select_clips(llm, {"title": "x"}, transcript, OPTIONS)
    assert llm.calls == 3
    assert result["model"] == "fake" and len(result["clips"]) == 1


def test_select_clips_without_speech_fails():
    with pytest.raises(ValueError, match="No speech"):
        select_clips(FakeLLM([]), {}, {"sentences": []}, OPTIONS)


def test_clip_selection_constraints_and_validation():
    # 120s transcript with 10s sentences
    sentences = [{"start": float(i * 10), "end": float((i + 1) * 10), "text": f"s{i}"} for i in range(12)]
    tr = {"language": "en", "sentences": sentences}
    opts = {"clip_count": 5, "min_seconds": 20.0, "max_seconds": 60.0}

    # 1. valid 20s clip -> accepted
    res_20 = validate_clips([raw(0.0, 20.0, 1)], tr, opts)
    assert len(res_20) == 1
    assert res_20[0]["start_seconds"] == 0.0
    assert res_20[0]["end_seconds"] == 20.0

    # 2. 19s clip -> rejected
    rejections_19 = []
    res_19 = validate_clips([raw(0.0, 19.0, 1)], tr, opts, rejections=rejections_19)
    assert len(res_19) == 0
    assert any("< minimum" in r for r in rejections_19)

    # 3. 60s clip -> accepted
    res_60 = validate_clips([raw(10.0, 70.0, 1)], tr, opts)
    assert len(res_60) == 1
    assert res_60[0]["start_seconds"] == 10.0
    assert res_60[0]["end_seconds"] == 70.0

    # 4. 61s clip -> rejected
    rejections_61 = []
    res_61 = validate_clips([raw(10.0, 71.0, 1)], tr, opts, rejections=rejections_61)
    assert len(res_61) == 0
    assert any("> maximum" in r for r in rejections_61)

    # 5. negative start -> rejected
    rejections_neg = []
    res_neg = validate_clips([raw(-5.0, 20.0, 1)], tr, opts, rejections=rejections_neg)
    assert len(res_neg) == 0
    assert any("negative" in r for r in rejections_neg)

    # 6. end <= start -> rejected
    rejections_le = []
    res_le = validate_clips([raw(30.0, 20.0, 1)], tr, opts, rejections=rejections_le)
    assert len(res_le) == 0
    assert any("<= start" in r for r in rejections_le)

    # 7. timestamp outside transcript -> rejected
    rejections_out = []
    res_out = validate_clips([raw(0.0, 150.0, 1)], tr, opts, rejections=rejections_out)
    assert len(res_out) == 0
    assert any("outside transcript" in r for r in rejections_out)


def test_validation_supports_start_end_keys_and_string_timestamps():
    sentences = [{"start": float(i * 10), "end": float((i + 1) * 10), "text": f"s{i}"} for i in range(10)]
    tr = {"language": "en", "sentences": sentences}
    opts = {"clip_count": 3, "min_seconds": 20.0, "max_seconds": 60.0}

    # "start" / "end" and "score" / "reasoning"
    raw_deepseek = {
        "rank": 1,
        "start": 10.0,
        "end": 40.0,
        "score": 8.5,
        "reasoning": "Great moment",
        "title": "Clip A",
        "post_title": "Short A",
        "caption": "Check this",
        "hashtags": ["#viral"],
        "broll_queries": ["nature"],
    }
    res = validate_clips([raw_deepseek], tr, opts)
    assert len(res) == 1
    assert res[0]["start_seconds"] == 10.0
    assert res[0]["end_seconds"] == 40.0
    assert res[0]["score"] == 8.5
    assert res[0]["rationale"] == "Great moment"

    # String format timestamps: "00:10" to "00:40"
    raw_str = {
        "rank": 1,
        "start_time": "00:10",
        "end_time": "00:40",
        "title": "Clip B",
    }
    res_str = validate_clips([raw_str], tr, opts)
    assert len(res_str) == 1
    assert res_str[0]["start_seconds"] == 10.0
    assert res_str[0]["end_seconds"] == 40.0


def test_select_clips_retries_with_rejection_reasons_in_prompt(transcript):
    recorded_users = []

    class MockLLM:
        model = "mock"

        def complete_json(self, system, user, schema, name):
            recorded_users.append(user)
            if len(recorded_users) == 1:
                # Return clip outside duration
                return {"clips": [{"rank": 1, "start_seconds": 0.0, "end_seconds": 10.0}]}
            # Second attempt returns valid clip
            return {"clips": [{"rank": 1, "start_seconds": 0.0, "end_seconds": 20.0}]}

    result = select_clips(MockLLM(), {"title": "Test"}, transcript, OPTIONS)
    assert len(result["clips"]) == 1
    assert len(recorded_users) == 2
    assert "attempt #1" in recorded_users[1].lower()
    assert "< minimum" in recorded_users[1]
    assert "CORRECTION REQUIRED" in recorded_users[1]


def test_validation_model_duration_discrepancy_uses_end_minus_start():
    sentences = [{"start": float(i * 10), "end": float((i + 1) * 10), "text": f"s{i}"} for i in range(10)]
    tr = {"language": "en", "sentences": sentences}
    opts = {"clip_count": 3, "min_seconds": 20.0, "max_seconds": 60.0}

    # Model returned duration_seconds=99.0, but end - start is 30.0 (which is within limits)
    raw_clip = {
        "rank": 1,
        "start": 10.0,
        "end": 40.0,
        "duration_seconds": 99.0,
        "title": "Clip With Bad Model Duration",
    }
    res = validate_clips([raw_clip], tr, opts)
    assert len(res) == 1
    assert res[0]["start_seconds"] == 10.0
    assert res[0]["end_seconds"] == 40.0


def test_validation_rejects_missing_timestamps():
    sentences = [{"start": 0.0, "end": 60.0, "text": "hello"}]
    tr = {"language": "en", "sentences": sentences}
    opts = {"clip_count": 3, "min_seconds": 20.0, "max_seconds": 60.0}

    rejections = []
    res = validate_clips([{"rank": 1, "start": None, "end": 30.0}], tr, opts, rejections=rejections)
    assert len(res) == 0
    assert any("missing or unparseable" in r for r in rejections)


def test_select_clips_retries_on_invalid_json_with_specific_prompt(transcript):
    recorded_users = []

    class MockLLM:
        model = "mock"

        def complete_json(self, system, user, schema, name):
            from shortyy.providers.base import LLMStructuredOutputError
            recorded_users.append(user)
            if len(recorded_users) == 1:
                raise LLMStructuredOutputError("Model returned multiple JSON values")
            return {"clips": [{"rank": 1, "start_seconds": 0.0, "end_seconds": 20.0}]}

    result = select_clips(MockLLM(), {"title": "Test"}, transcript, OPTIONS)
    assert len(result["clips"]) == 1
    assert len(recorded_users) == 2
    assert "returned invalid JSON" in recorded_users[1]
    assert "CRITICAL FORMATTING INSTRUCTIONS" in recorded_users[1]
    assert "EXACTLY ONE JSON object" in recorded_users[1]
