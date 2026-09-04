"""Parse raw batchexecute responses into structured review dicts."""

from __future__ import annotations
import json
import re
from datetime import datetime, timedelta
from typing import Any


def _safe(obj: Any, *keys) -> Any:
    for k in keys:
        if obj is None:
            return None
        if isinstance(obj, (list, tuple)):
            obj = obj[k] if isinstance(k, int) and k < len(obj) else None
        elif isinstance(obj, dict):
            obj = obj.get(k)
        else:
            return None
    return obj


def _review_text(d: Any) -> str:
    aspects = _safe(d, 2, 6)
    if not isinstance(aspects, list):
        return ""
    parts = []
    for asp in aspects:
        text = _safe(asp, 10, 0)
        if isinstance(text, str) and len(text) > 3:
            parts.append(text.strip())
    return " | ".join(parts)


def _owner_reply(d: Any) -> str:
    reply = _safe(d, 3, 14, 0, 0) or _safe(d, 3, 14, 1, 0) or ""
    return (reply or "").strip()


def _reviewer_level(d: Any) -> tuple[bool, int | None]:
    """Returns (is_local_guide, review_count)."""
    info_str = _safe(d, 1, 4, 5, 10, 0) or ""
    is_guide = "Local Guide" in info_str or "Guía Local" in info_str
    m = re.search(r"(\d[\d,]*)\s+review", info_str, re.I)
    count = int(m.group(1).replace(",", "")) if m else None
    return is_guide, count


_RELATIVE_RE = re.compile(
    r"(\d+)\s+(second|minute|hour|day|week|month|year)s?\s+ago",
    re.I,
)
_UNIT_DELTA = {
    "second": timedelta(seconds=1),
    "minute": timedelta(minutes=1),
    "hour": timedelta(hours=1),
    "day": timedelta(days=1),
    "week": timedelta(weeks=1),
    "month": timedelta(days=30),
    "year": timedelta(days=365),
}


def _estimate_date(relative: str, captured_at: datetime) -> str | None:
    m = _RELATIVE_RE.search(relative)
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2).lower()
    delta = _UNIT_DELTA.get(unit, timedelta(days=1)) * n
    estimated = captured_at - delta
    return estimated.strftime("%Y-%m")


def parse_batch(
    raw: str,
    captured_at: datetime | None = None,
) -> tuple[list[dict], str | None]:
    """Return (reviews, next_cursor). captured_at used for date estimation."""
    now = captured_at or datetime.now()
    lines = raw.split("\n")
    if len(lines) < 4:
        return [], None
    try:
        outer = json.loads(lines[3])
        inner_str = outer[0][2]
        if not inner_str:
            return [], None
        inner = json.loads(inner_str)
        next_cursor = inner[1] if len(inner) > 1 else None
        reviews_arr = inner[2] if len(inner) > 2 else []
        # total count is buried at inner[3][1] on the first page
        # (caller can extract separately if needed)
    except Exception:
        return [], None

    results: list[dict] = []
    for entry in reviews_arr or []:
        try:
            d = entry[0]
            is_guide, review_count = _reviewer_level(d)
            date_rel = _safe(d, 3, 3) or ""
            results.append({
                "review_id":    _safe(d, 0) or "",
                "author":       _safe(d, 1, 4, 5, 0) or "",
                "local_guide":  is_guide,
                "review_count": review_count,
                "rating":       _safe(d, 2, 0, 0) or "",
                "date_relative": date_rel,
                "date_estimated": _estimate_date(date_rel, now),
                "has_photos":   bool(_safe(d, 2, 2)),
                "likes":        _safe(d, 3, 1) or 0,
                "review_text":  _review_text(d),
                "owner_reply":  _owner_reply(d),
                "source":       "Google Maps",
            })
        except Exception:
            continue
    return results, next_cursor


def extract_total_count(raw: str) -> int | None:
    """Best-effort extraction of the total review count from first-page response."""
    try:
        lines = raw.split("\n")
        outer = json.loads(lines[3])
        inner = json.loads(outer[0][2])
        # Google embeds the count in a few possible locations
        for path in [(3, 1), (3, 2), (9,)]:
            v = _safe(inner, *path)
            if isinstance(v, int) and v > 0:
                return v
    except Exception:
        pass
    return None
