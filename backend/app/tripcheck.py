"""Checks on a dated trip plan: places put on a day they're closed (with the nearest day they're open), and
fitting the places that aren't on a day yet into the days of their own city."""

from __future__ import annotations

import unicodedata
from datetime import timedelta
from typing import Optional

from .models import Place, TripClosure, TripDetail

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def city_key(city: str) -> str:
    text = unicodedata.normalize("NFKD", city or "").encode("ascii", "ignore").decode()
    return " ".join(text.lower().replace("-", " ").split())


def _closed_on(place: Place, weekday: int) -> Optional[bool]:
    """True if the place is shut all day on that weekday (Monday = 0); None when its hours aren't known."""
    weekly = place.opening_hours.weekly if place.opening_hours else None
    if not weekly or len(weekly) != 7:
        return None
    return not weekly[weekday]


def _weekday(trip: TripDetail, day: int) -> Optional[int]:
    return (trip.start_date + timedelta(days=day - 1)).weekday() if trip.start_date else None


def _stop_days(trip: TripDetail, place: Place) -> list[int]:
    """The days of the stop in the place's city, or every day when no stop matches."""
    key = city_key(place.city)
    days = [d for s in trip.stops if city_key(s.city) == key for d in range(s.start_day, s.end_day + 1)]
    return [d for d in days if d <= trip.day_count] or list(range(1, trip.day_count + 1))


def closures(trip: TripDetail) -> list[TripClosure]:
    """Places planned on a day they're closed, each with the nearest day in the same city they're open."""
    if not trip.start_date or not trip.day_count:
        return []
    out = []
    for p in trip.places:
        if not p.day_number or p.visited:
            continue
        weekday = _weekday(trip, p.day_number)
        if not _closed_on(p, weekday):
            continue
        options = sorted((d for d in _stop_days(trip, p) if d != p.day_number and not _closed_on(p, _weekday(trip, d))),
                         key=lambda d: (abs(d - p.day_number), d < p.day_number))
        move = options[0] if options else None
        out.append(TripClosure(place_id=p.id, day=p.day_number, message=f"Closed on {WEEKDAYS[weekday]}s",
                               move_to_day=move, move_to_label=WEEKDAYS[_weekday(trip, move)][:3] if move else None))
    return out


def fit_plan(trip: TripDetail) -> list[tuple[str, int]]:
    """Where each place that isn't on a day goes: a day in its city's stop with the fewest stops, avoiding days it's
    closed. Starred places and places more Reels mention go first."""
    load = {d: 0 for d in range(1, trip.day_count + 1)}
    for p in trip.places:
        if p.day_number in load:
            load[p.day_number] += 1
    waiting = sorted((p for p in trip.places if not p.day_number), key=lambda p: (not p.must_do, -p.mention_count))
    moves = []
    for p in waiting:
        days = _stop_days(trip, p)
        open_days = [d for d in days if not _closed_on(p, _weekday(trip, d))] if trip.start_date else days
        day = min(open_days or days, key=lambda d: (load[d], d))
        load[day] += 1
        moves.append((p.id, day))
    return moves
