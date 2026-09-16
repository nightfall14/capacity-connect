"""Trainer-facing insights derived from video confusion telemetry."""

from __future__ import annotations

from collections import defaultdict


def build_curriculum_insights(heatmap: list[dict], doubts: list[dict] | None = None) -> list[str]:
    """Turn red/amber buckets and clustered doubts into actionable messages."""
    insights: list[str] = []
    red = [bucket for bucket in heatmap if bucket["score"] > 3]
    amber = [bucket for bucket in heatmap if 0 < bucket["score"] <= 3]
    if red:
        start = red[0]["start_seconds"]
        end = red[-1]["end_seconds"]
        pauses = sum(bucket["pause_count"] for bucket in red)
        rewinds = sum(bucket["rewind_count"] for bucket in red)
        insights.append(
            f"{pauses + rewinds} repeated interactions occurred between "
            f"{_clock(start)} and {_clock(end)}. Consider adding a worked example."
        )
    elif amber:
        start = amber[0]["start_seconds"]
        end = amber[-1]["end_seconds"]
        insights.append(
            f"Learners showed moderate confusion between {_clock(start)} and "
            f"{_clock(end)}. Consider adding a short recap."
        )

    if doubts:
        by_bucket: dict[int, int] = defaultdict(int)
        for doubt in doubts:
            by_bucket[int(doubt.get("bucket", 0))] += 1
        if by_bucket:
            bucket, count = max(by_bucket.items(), key=lambda item: item[1])
            if count >= 2:
                insights.append(
                    f"{count} learner doubts cluster around {_clock(bucket * 10)}. "
                    "Add an explanation or worked example there."
                )
    return insights


def _clock(seconds: int | float) -> str:
    total = max(0, int(seconds))
    return f"{total // 60:02d}:{total % 60:02d}"
