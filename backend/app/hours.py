"""Opening hours from Google Places or OpenStreetMap, normalized to one weekly format.

`weekly` has 7 lists (index 0 = Monday) of {"open": "HH:MM", "close": "HH:MM"} ranges. A close time
earlier than the open time means the place closes after midnight. An empty list means closed that day.
When hours can't be parsed (e.g. OSM rules with months or holidays only), `weekly` is None and the
original text is kept for display.
"""

import re
from typing import Optional

from .models import OpeningHours, TimeRange

DAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _hhmm(hour: int, minute: int) -> str:
    return f"{hour:02d}:{minute:02d}"


def from_google(data: Optional[dict]) -> Optional[OpeningHours]:
    """Converts Places API (New) `regularOpeningHours`."""
    if not data:
        return None
    periods = data.get("periods") or []
    weekly: list[list[TimeRange]] = [[] for _ in range(7)]
    for period in periods:
        start = period.get("open") or {}
        end = period.get("close")
        day = (int(start.get("day", 0)) + 6) % 7  # Google: 0 = Sunday
        if end is None:  # open 24 hours, every day
            weekly = [[TimeRange(open="00:00", close="24:00")] for _ in range(7)]
            break
        weekly[day].append(TimeRange(
            open=_hhmm(start.get("hour", 0), start.get("minute", 0)),
            close=_hhmm(end.get("hour", 0), end.get("minute", 0)),
        ))
    text = data.get("weekdayDescriptions") or _describe(weekly)
    return OpeningHours(weekly=weekly if periods else None, text=text, source="google")


# ---------- OpenStreetMap ----------

_TIME = r"(\d{1,2}):(\d{2})"
_RANGE_RE = re.compile(rf"^{_TIME}\s*-\s*{_TIME}\+?$")
_UNSUPPORTED = re.compile(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|week|sunrise|sunset|dawn|dusk|easter)\b", re.I)


def _expand_days(spec: str) -> Optional[list[int]]:
    days: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if part == "PH" or part == "SH":
            continue  # public/school holidays: not modelled
        if "-" in part:
            a, b = (p.strip()[:2] for p in part.split("-", 1))
            if a not in DAYS or b not in DAYS:
                return None
            i, j = DAYS.index(a), DAYS.index(b)
            days.extend(range(i, j + 1) if i <= j else list(range(i, 7)) + list(range(0, j + 1)))
        else:
            if part[:2] not in DAYS:
                return None
            days.append(DAYS.index(part[:2]))
    return days


def _parse_times(spec: str) -> Optional[list[TimeRange]]:
    spec = spec.strip().strip('"')
    if spec.lower() in ("off", "closed"):
        return []
    ranges = []
    for part in spec.split(","):
        match = _RANGE_RE.match(part.strip())
        if not match:
            return None
        h1, m1, h2, m2 = (int(x) for x in match.groups())
        if h1 > 24 or h2 > 48 or m1 > 59 or m2 > 59:
            return None
        if h2 >= 24 and not (h2 == 24 and m2 == 0):
            h2 -= 24  # "18:00-26:00" means 2 AM the next day
        ranges.append(TimeRange(open=_hhmm(h1, m1), close=_hhmm(h2, m2)))
    return ranges


def parse_osm(raw: Optional[str]) -> Optional[OpeningHours]:
    """Parses the common subset of the OSM opening_hours syntax, e.g. "Mo-Fr 08:00-18:00; Sa 09:00-14:00; Su off"."""
    if not raw or not raw.strip():
        return None
    raw = raw.strip()
    fallback = OpeningHours(weekly=None, text=[raw], source="openstreetmap", raw=raw)
    if raw == "24/7":
        weekly = [[TimeRange(open="00:00", close="24:00")] for _ in range(7)]
        return OpeningHours(weekly=weekly, text=_describe(weekly), source="openstreetmap", raw=raw)
    if _UNSUPPORTED.search(raw) or "||" in raw:
        return fallback

    weekly: list[Optional[list[TimeRange]]] = [None] * 7
    for rule in filter(None, (r.strip() for r in raw.split(";"))):
        match = re.match(r"^((?:PH|SH|Mo|Tu|We|Th|Fr|Sa|Su)[A-Za-z]*(?:\s*[-,]\s*(?:PH|SH|Mo|Tu|We|Th|Fr|Sa|Su)[A-Za-z]*)*)\s*(.*)$", rule)
        if match:
            days = _expand_days(match.group(1).replace(" ", ""))
            times_spec = match.group(2) or "00:00-24:00"
            if days is None:
                return fallback
            if not days:
                continue  # holiday-only rule
        else:
            days, times_spec = list(range(7)), rule
        times = _parse_times(times_spec)
        if times is None:
            return fallback
        for d in days:  # later rules override earlier ones, as in OSM
            weekly[d] = times
    if all(d is None for d in weekly):
        return fallback
    final = [d if d is not None else [] for d in weekly]
    return OpeningHours(weekly=final, text=_describe(final), source="openstreetmap", raw=raw)


def _fmt(t: str) -> str:
    h, m = (int(x) for x in t.split(":"))
    if h == 24:
        return "midnight"
    suffix = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d} {suffix}" if m else f"{h12} {suffix}"


def _describe(weekly: list[list[TimeRange]]) -> list[str]:
    lines = []
    for name, ranges in zip(DAY_NAMES, weekly):
        if not ranges:
            lines.append(f"{name}: Closed")
        elif ranges == [TimeRange(open="00:00", close="24:00")]:
            lines.append(f"{name}: Open 24 hours")
        else:
            lines.append(f"{name}: " + ", ".join(f"{_fmt(r.open)} – {_fmt(r.close)}" for r in ranges))
    return lines


def summary(hours: Optional[OpeningHours]) -> Optional[str]:
    """Compact text for the itinerary planner prompt."""
    if not hours:
        return None
    if hours.weekly is None:
        return "; ".join(hours.text)[:200]
    parts = []
    for name, ranges in zip(DAY_NAMES, hours.weekly):
        parts.append(f"{name[:3]} " + (",".join(f"{r.open}-{r.close}" for r in ranges) if ranges else "closed"))
    return "; ".join(parts)
