"""Keeps itineraries realistic.

balance_plan() checks any plan (Claude's, the offline planner's or a tidy) before it's saved: one breakfast, one lunch
and one dinner a day, coffee, sweets and drinks in moderation, and days of a sensible size. A restaurant that would be a
second lunch moves to a free meal on the same day, then to another day in the same city, and otherwise stays off the
plan rather than stacking up.

day_times() turns a day's ordered stops into clock times: each kind of place takes its usual time, there's travel
between stops, and meals don't start before people eat.
"""

from __future__ import annotations

import math
from typing import Callable, Optional

from .models import Place, PlaceCategory, PlanResult, PlannedStop, ScheduledStop, TimeOfDay
from .planner import preferred_time, slot_for_time

TIME_ORDER = list(TimeOfDay)
MAX_STOPS = 7
# How many of each kind fit in one day.
DAILY_LIMIT = {"cafe": 2, "dessert": 2, "drinks": 2}
DRINK_CATEGORIES = {PlaceCategory.drinks, PlaceCategory.nightlife}

# When each part of the day starts, in minutes after midnight.
SLOT_START = {TimeOfDay.morning: 9 * 60 + 30, TimeOfDay.lunch: 12 * 60 + 30, TimeOfDay.afternoon: 14 * 60,
              TimeOfDay.dinner: 19 * 60, TimeOfDay.evening: 21 * 60}
# How long a visit usually takes, in minutes.
DURATION = {PlaceCategory.cafe: 40, PlaceCategory.dessert: 30, PlaceCategory.drinks: 75, PlaceCategory.nightlife: 120,
            PlaceCategory.attraction: 90, PlaceCategory.activity: 120, PlaceCategory.event: 120,
            PlaceCategory.nature: 90, PlaceCategory.shopping: 60, PlaceCategory.stay: 30, PlaceCategory.other: 60}
MEAL_DURATION = {"breakfast": 45, "lunch": 75, "dinner": 90}


def meal_of(category: PlaceCategory, slot: TimeOfDay) -> Optional[str]:
    """Which meal a restaurant stop is: breakfast, lunch (incl. a late one) or dinner."""
    if category != PlaceCategory.food:
        return None
    return {TimeOfDay.morning: "breakfast", TimeOfDay.lunch: "lunch", TimeOfDay.afternoon: "lunch"}.get(slot, "dinner")


def _kind(category: PlaceCategory) -> Optional[str]:
    if category == PlaceCategory.cafe:
        return "cafe"
    if category == PlaceCategory.dessert:
        return "dessert"
    if category in DRINK_CATEGORIES:
        return "drinks"
    return None


class _Day:
    def __init__(self, number: int, stops: list[PlannedStop]):
        self.number = number
        self.stops = stops

    def meals(self, places: dict[str, Place], skip: Optional[str] = None) -> set[str]:
        return {meal_of(places[s.place_id].category, s.time_of_day) for s in self.stops
                if s.place_id != skip and places[s.place_id].category == PlaceCategory.food}

    def count(self, kind: str, places: dict[str, Place]) -> int:
        return sum(1 for s in self.stops if _kind(places[s.place_id].category) == kind)


def balance_plan(result: PlanResult, places: list[Place], allowed_days: Callable[[Place], list[int]],
                 move_days: bool = True) -> PlanResult:
    """Fixes a plan that's unrealistic. allowed_days(place) lists the days a place may go on (its city's days).
    With move_days=False (a tidy of a hand-built plan) places only change their time of day, never their day."""
    by_id = {p.id: p for p in places}
    days = [_Day(d.day_number, [s for s in d.stops if s.place_id in by_id]) for d in result.days]
    by_number = {d.number: d for d in days}
    left_out: list[str] = []

    def fixed(stop: PlannedStop) -> bool:
        return bool(by_id[stop.place_id].start_time)

    def fits(day: _Day, place: Place, slot: TimeOfDay) -> bool:
        if len(day.stops) >= MAX_STOPS:
            return False
        meal = meal_of(place.category, slot)
        if meal and meal in day.meals(by_id):
            return False
        kind = _kind(place.category)
        return not (kind and day.count(kind, by_id) >= DAILY_LIMIT[kind])

    def free_meal_slot(day: _Day, place: Place) -> Optional[TimeOfDay]:
        taken = day.meals(by_id, skip=place.id)
        for slot, meal in ((TimeOfDay.lunch, "lunch"), (TimeOfDay.dinner, "dinner")):  # a lunch spot isn't breakfast
            if meal not in taken:
                return slot
        return None

    for day in days:
        kept: list[PlannedStop] = []
        for stop in day.stops:
            place = by_id[stop.place_id]
            probe = _Day(day.number, kept)
            if fixed(stop) or fits(probe, place, stop.time_of_day):
                kept.append(stop)
                continue
            # A second lunch can often be dinner the same day.
            if meal_of(place.category, stop.time_of_day):
                slot = free_meal_slot(probe, place)
                if slot and fits(probe, place, slot):
                    kept.append(stop.model_copy(update={"time_of_day": slot}))
                    continue
            if not move_days:
                kept.append(stop)  # a hand-built day keeps what the person put on it
                continue
            left_out.append(stop.place_id)
        day.stops = kept

    # Try the stops that didn't fit on another day in the same city.
    for pid in left_out:
        place = by_id[pid]
        options = [by_number[n] for n in allowed_days(place) if n in by_number]
        placed = False
        for day in sorted(options, key=lambda d: (len(d.stops), d.number)):
            slot = preferred_time(place.category)
            if meal_of(place.category, slot):
                slot = free_meal_slot(day, place) or slot
            if fits(day, place, slot):
                day.stops.append(PlannedStop(place_id=pid, time_of_day=slot, note=None))
                placed = True
                break
        if not placed:
            result.unscheduled_place_ids.append(pid)

    for day, planned in zip(days, result.days):
        order = {s.place_id: i for i, s in enumerate(day.stops)}
        planned.stops = sorted(day.stops, key=lambda s: (TIME_ORDER.index(s.time_of_day), order[s.place_id]))
    result.unscheduled_place_ids = list(dict.fromkeys(result.unscheduled_place_ids))
    return result


def _walk_minutes(a: Place, b: Place) -> int:
    if a.latitude is None or b.latitude is None or a.longitude is None or b.longitude is None:
        return 15
    dlat = math.radians(b.latitude - a.latitude)
    dlon = math.radians(b.longitude - a.longitude) * math.cos(math.radians(a.latitude))
    meters = 6_371_000 * math.hypot(dlat, dlon)
    # Walk up to ~25 minutes; past that people take a cab or the metro, which rarely takes more than 35.
    minutes = meters / 80 if meters < 2000 else 15 + meters / 400
    return int(max(5, min(minutes, 45)))


def _minutes(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[3:5])


def day_times(stops: list[Place]) -> list[ScheduledStop]:
    """Clock times for a day's stops in their planned order. A stop with an exact time keeps it; the others start
    after the one before (its usual length plus travel), never before their part of the day begins."""
    out = []
    clock: Optional[int] = None
    previous: Optional[Place] = None
    for p in stops:
        slot = slot_for_time(p.start_time) if p.start_time else p.time_of_day or preferred_time(p.category)
        meal = meal_of(p.category, slot)
        if p.start_time:
            start, estimated = _minutes(p.start_time), False
        else:
            earliest = SLOT_START[slot]
            start = earliest if clock is None else max(clock + _walk_minutes(previous, p), earliest)
            start = -(-start // 15) * 15  # to the next quarter hour
            estimated = True
        clock = start + (MEAL_DURATION[meal] if meal else DURATION.get(p.category, 60))
        previous = p
        out.append(ScheduledStop(place_id=p.id, day=p.day_number or 0,
                                 time=f"{(start // 60) % 24:02d}:{start % 60:02d}", estimated=estimated))
    return out
