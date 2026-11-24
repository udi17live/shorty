"""Ask an LLM for the best clips, then snap them to sentence boundaries and validate."""

from __future__ import annotations

import logging
import re
from string import Template
from typing import Any

from shortyy.config import PACKAGE_DIR
from shortyy.llm import LLM, LLMError

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "clips": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "rank": {"type": "integer"},
                    "start_seconds": {"type": "number"},
                    "end_seconds": {"type": "number"},
                    "title": {"type": "string"},
                    "post_title": {"type": "string"},
                    "caption": {"type": "string"},
                    "hashtags": {"type": "array", "items": {"type": "string"}},
                    "broll_queries": {"type": "array", "items": {"type": "string"}},
                    "rationale": {"type": "string"},
                    "hook_score": {"type": "number"},
                    "value_score": {"type": "number"},
                    "clarity_score": {"type": "number"},
                    "overall_score": {"type": "number"},
                },
                "required": [
                    "rank",
                    "start_seconds",
                    "end_seconds",
                    "title",
                    "post_title",
                    "caption",
                    "hashtags",
                    "broll_queries",
                    "rationale",
                    "hook_score",
                    "value_score",
                    "clarity_score",
                    "overall_score",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["clips"],
    "additionalProperties": False,
}


def parse_seconds(value: Any) -> float | None:
    """Parse a timestamp into seconds from float, int, or 'MM:SS' / 'HH:MM:SS' strings."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    val_str = str(value).strip().rstrip("s").strip()
    try:
        return float(val_str)
    except ValueError:
        pass
    if ":" in val_str:
        parts = val_str.split(":")
        try:
            if len(parts) == 2:
                return float(parts[0]) * 60 + float(parts[1])
            if len(parts) == 3:
                return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        except ValueError:
            return None
    return None


def build_prompt(source: dict, transcript: dict, options: dict) -> tuple[str, str]:
    instructions = (options.get("instructions") or "").strip()
    sentences = transcript.get("sentences", [])
    t_start = sentences[0]["start"] if sentences else 0.0
    t_end = sentences[-1]["end"] if sentences else 0.0
    template = Template((PACKAGE_DIR / "prompts" / "clip_selection.md").read_text(encoding="utf-8"))
    system = template.substitute(
        clip_count=options["clip_count"],
        min_seconds=_fmt(options["min_seconds"]),
        max_seconds=_fmt(options["max_seconds"]),
        transcript_start=f"{t_start:.1f}",
        transcript_end=f"{t_end:.1f}",
        instructions=f"\nInstructions from the user:\n{instructions}\n" if instructions else "",
    )
    lines = "\n".join(f"[{s['start']:.1f}-{s['end']:.1f}] {s['text']}" for s in sentences)
    min_str, max_str = _fmt(options["min_seconds"]), _fmt(options["max_seconds"])
    user = (
        f"Video: {source.get('title') or 'Untitled'}"
        + (f" by {source['uploader']}" if source.get("uploader") else "")
        + f" ({source.get('duration_seconds', 0):.0f}s, language: {transcript.get('language')})\n\n"
        f"Transcript duration: {t_start:.1f}s to {t_end:.1f}s.\n"
        f"Clip duration constraint: each clip MUST have end_seconds - start_seconds "
        f"between {min_str}s and {max_str}s.\n\n"
        f"Transcript (one sentence per line, [start-end] in seconds):\n{lines}\n\n"
        f"Return up to {options['clip_count']} clips as a single JSON object with a \"clips\" array "
        f"containing \"start_seconds\" and \"end_seconds\"."
    )
    return system, user


def select_clips(llm: LLM, source: dict, transcript: dict, options: dict) -> dict:
    if not transcript.get("sentences"):
        raise ValueError("No speech found in the video, so there is nothing to clip")
    system, user = build_prompt(source, transcript, options)
    min_s, max_s = float(options["min_seconds"]), float(options["max_seconds"])
    sentences = sorted(transcript["sentences"], key=lambda s: (s["start"], s["end"]))
    t_start, t_end = sentences[0]["start"], sentences[-1]["end"]
    last_error = "no clips returned"
    current_user = user
    provider_name = getattr(llm, "name", "LLM")
    model_name = getattr(llm, "model", "unknown")

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            raw_response = llm.complete_json(system, current_user, SCHEMA, "clip_selection")
            raw = raw_response.get("clips", []) if isinstance(raw_response, dict) else []
        except LLMError as exc:
            if attempt == MAX_ATTEMPTS:
                raise
            last_error = str(exc)
            logger.warning(
                "clip selection attempt %d (provider=%s, model=%s) failed: %s",
                attempt,
                provider_name,
                model_name,
                exc,
            )
            current_user = (
                f"{user}\n\n"
                f"CORRECTION REQUIRED (Previous attempt #{attempt} returned invalid JSON):\n"
                f"The previous output caused this parsing error: {exc}\n\n"
                f"CRITICAL FORMATTING INSTRUCTIONS:\n"
                f"- Return EXACTLY ONE JSON object matching the required schema: "
                f"{{\"clips\": [...]}} and absolutely nothing else.\n"
                f"- Do NOT return markdown code fences (no ```json or ```).\n"
                f"- Do NOT return explanations, commentary, or text before or after the JSON.\n"
                f"- Do NOT return multiple JSON objects or multiple arrays."
            )
            continue

        rejections: list[str] = []
        clips = validate_clips(raw, transcript, options, rejections=rejections)
        if clips:
            return {"model": llm.model, "clips": clips}

        rejection_summary = (
            "\n".join(f"- {r}" for r in rejections)
            if rejections
            else f"Model returned {len(raw)} empty or malformed suggestions."
        )
        last_error = f"none of the {len(raw)} suggested clips were valid:\n{rejection_summary}"
        logger.warning(
            "clip selection attempt %d (provider=%s, model=%s): %s",
            attempt,
            provider_name,
            model_name,
            last_error,
        )

        if attempt < MAX_ATTEMPTS:
            current_user = (
                f"{user}\n\n"
                f"CORRECTION REQUIRED (Previous attempt #{attempt} produced clips "
                f"violating constraints):\n"
                f"{rejection_summary}\n\n"
                f"STRICT TIMESTAMP & DURATION CONSTRAINTS:\n"
                f"- Return a single JSON object with a \"clips\" array.\n"
                f"- Each clip MUST have numeric 'start_seconds' and 'end_seconds' "
                f"directly from the transcript.\n"
                f"- 'start_seconds' must be >= {t_start:.1f} and < 'end_seconds'.\n"
                f"- 'end_seconds' must be <= {t_end:.1f}.\n"
                f"- Duration (end_seconds - start_seconds) MUST be between {min_s:.0f}s and {max_s:.0f}s.\n"
                f"- Clips must not overlap.\n"
            )

    raise ValueError(f"Clip selection failed after {MAX_ATTEMPTS} attempts: {last_error}")


def validate_clips(
    raw_clips: list[dict],
    transcript: dict,
    options: dict,
    rejections: list[str] | None = None,
) -> list[dict]:
    """Validate clip candidates, snapping to sentence boundaries and filtering invalid clips."""
    min_s, max_s = float(options["min_seconds"]), float(options["max_seconds"])
    sentences = sorted(transcript.get("sentences", []), key=lambda s: (s["start"], s["end"]))
    t_start = sentences[0]["start"] if sentences else 0.0
    t_end = sentences[-1]["end"] if sentences else 0.0
    accepted: list[dict] = []

    for item in sorted(raw_clips, key=lambda c: _num(c.get("rank"), 999)):
        rank = item.get("rank", len(accepted) + 1)
        raw_start = (
            item.get("start_seconds")
            if "start_seconds" in item
            else item.get("start")
            if "start" in item
            else item.get("start_time")
        )
        raw_end = (
            item.get("end_seconds")
            if "end_seconds" in item
            else item.get("end")
            if "end" in item
            else item.get("end_time")
        )

        start = parse_seconds(raw_start)
        end = parse_seconds(raw_end)

        # 1. Missing or unparseable timestamps
        if start is None or end is None:
            reason = f"missing or unparseable timestamps (start={raw_start!r}, end={raw_end!r})"
            _log_rejection(rank, start, end, min_s, max_s, reason, rejections)
            continue

        # 2. Negative start timestamp
        if start < 0:
            reason = f"start timestamp ({start:.1f}s) is negative"
            _log_rejection(rank, start, end, min_s, max_s, reason, rejections)
            continue

        # 3. End timestamp not strictly greater than start
        if end <= start:
            reason = f"end ({end:.1f}s) <= start ({start:.1f}s)"
            _log_rejection(rank, start, end, min_s, max_s, reason, rejections)
            continue

        # Check model-reported duration against end - start (end - start is authoritative)
        raw_dur = item.get("duration_seconds") if "duration_seconds" in item else item.get("duration")
        model_dur = parse_seconds(raw_dur)
        calculated_dur = end - start
        if model_dur is not None and abs(model_dur - calculated_dur) > 1.5:
            logger.info(
                "Candidate %s: model duration_seconds (%.1fs) disagrees with end - start (%.1fs); "
                "using end - start as authoritative",
                rank,
                model_dur,
                calculated_dur,
            )

        # 4. Out of transcript bounds
        if sentences and (start < t_start - 0.5 or end > t_end + 0.5):
            reason = (
                f"timestamps ({start:.1f}s-{end:.1f}s) outside transcript range "
                f"({t_start:.1f}s-{t_end:.1f}s)"
            )
            _log_rejection(rank, start, end, min_s, max_s, reason, rejections)
            continue

        # 5. Raw duration limits check
        raw_duration = calculated_dur
        if raw_duration < min_s - 0.5:
            reason = f"duration ({raw_duration:.1f}s) < minimum ({min_s:.1f}s)"
            _log_rejection(rank, start, end, min_s, max_s, reason, rejections)
            continue
        if raw_duration > max_s + 0.5:
            reason = f"duration ({raw_duration:.1f}s) > maximum ({max_s:.1f}s)"
            _log_rejection(rank, start, end, min_s, max_s, reason, rejections)
            continue

        # 6. Snap to sentence boundaries
        snapped_start, snapped_end = snap(start, end, sentences, min_s, max_s)
        snapped_duration = snapped_end - snapped_start

        if not (min_s - 0.5 <= snapped_duration <= max_s + 0.5):
            reason = f"snapped duration ({snapped_duration:.1f}s) outside limits [{min_s:.1f}s, {max_s:.1f}s]"
            _log_rejection(rank, snapped_start, snapped_end, min_s, max_s, reason, rejections)
            continue

        # 7. Overlap check with already accepted clips
        if any(snapped_start < c["end_seconds"] and c["start_seconds"] < snapped_end for c in accepted):
            reason = "overlaps with a higher-ranked clip"
            _log_rejection(rank, snapped_start, snapped_end, min_s, max_s, reason, rejections)
            continue

        hashtags, caption = clean_hashtags(item.get("hashtags"), str(item.get("caption", "")))
        score = _num(item.get("overall_score") if "overall_score" in item else item.get("score"), 0.0)
        rationale = str(item.get("rationale") or item.get("reasoning") or "").strip()

        accepted.append(
            {
                "start_seconds": round(snapped_start, 3),
                "end_seconds": round(snapped_end, 3),
                "title": str(item.get("title", "")).strip() or f"Clip {len(accepted) + 1}",
                "post_title": str(item.get("post_title", "")).strip()[:100],
                "caption": clean_caption(caption),
                "hashtags": hashtags,
                "broll_queries": [
                    str(q).strip() for q in (item.get("broll_queries") or []) if str(q).strip()
                ][:8],
                "rationale": rationale,
                "score": score,
                "transcript": excerpt(snapped_start, snapped_end, sentences),
            }
        )
        if len(accepted) == options["clip_count"]:
            break

    for rank_idx, clip in enumerate(accepted, start=1):
        clip["rank"] = rank_idx
    return accepted


def _log_rejection(
    rank: Any,
    start: float | None,
    end: float | None,
    min_s: float,
    max_s: float,
    reason: str,
    rejections: list[str] | None = None,
) -> None:
    has_dur = start is not None and end is not None and end > start
    dur_str = f"{(end - start):.1f}" if has_dur else "unknown"
    start_str = f"{start:.1f}" if start is not None else "unknown"
    end_str = f"{end:.1f}" if end is not None else "unknown"
    msg = (
        f"candidate {rank} rejected:\n"
        f"start={start_str}\n"
        f"end={end_str}\n"
        f"duration={dur_str}\n"
        f"allowed={min_s:.0f}-{max_s:.0f}\n"
        f"reason={reason}"
    )
    logger.warning("%s", msg)
    if rejections is not None:
        rejections.append(
            f"candidate {rank} (start={start_str}, end={end_str}, duration={dur_str}, "
            f"allowed={min_s:.0f}-{max_s:.0f}): {reason}"
        )


def snap(start: float, end: float, sentences: list[dict], min_s: float, max_s: float) -> tuple[float, float]:
    """Move start/end to the nearest sentence boundaries, then grow or trim into range."""
    if not sentences:
        return start, min(max(end, start + min_s), start + max_s)
    start = min(sentences, key=lambda s: abs(s["start"] - start))["start"]
    end = min(sentences, key=lambda s: abs(s["end"] - end))["end"]
    if end <= start:
        later = [s["end"] for s in sentences if s["end"] > start]
        end = later[0] if later else start + min_s
    if end - start < min_s:
        longer = [s["end"] for s in sentences if s["end"] >= start + min_s]
        if longer:
            end = min(longer)
        else:
            earlier = [s["start"] for s in sentences if s["start"] <= end - min_s]
            if earlier:
                start = max(earlier)
    if end - start > max_s:
        fitting = [s["end"] for s in sentences if start < s["end"] <= start + max_s]
        end = max(fitting) if fitting and max(fitting) - start >= min_s else start + max_s
    return start, end


def excerpt(start: float, end: float, sentences: list[dict]) -> str:
    return " ".join(s["text"] for s in sentences if s["start"] >= start - 0.01 and s["end"] <= end + 0.01)


_LENGTH_MARKER = re.compile(r"\s*\(\d+\s*(?:chars?|characters?|s|secs?|seconds?)\)\s*$", re.IGNORECASE)
_TRAILING_TAGS = re.compile(r"(?:\s*#[\w\u00C0-\uFFFF]+)+\s*$")


def clean_caption(caption: str) -> str:
    value = caption.strip()
    while (updated := _LENGTH_MARKER.sub("", value).strip()) != value:
        value = updated
    return re.sub(r"\s{2,}", " ", value)


def clean_hashtags(tags: Any, caption: str) -> tuple[list[str], str]:
    """Normalise hashtags and move any trailing hashtags out of the caption."""
    found = _TRAILING_TAGS.search(caption)
    extra = found.group(0).split() if found else []
    caption = caption[: found.start()].strip() if found else caption
    result: list[str] = []
    for tag in [*(tags if isinstance(tags, list) else []), *extra]:
        cleaned = "#" + re.sub(r"[^\w\u00C0-\uFFFF]", "", str(tag))
        if len(cleaned) > 1 and cleaned.lower() not in {t.lower() for t in result}:
            result.append(cleaned)
    return result[:10], caption


def _num(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _fmt(value: float) -> str:
    return f"{float(value):g}"
