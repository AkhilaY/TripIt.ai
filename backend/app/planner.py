"""Offline itinerary planner, used when Claude can't be reached.

Groups nearby places into days with k-means on coordinates, then orders each day by time of day.
"""

import math
from collections import Counter

from .models import Place, PlaceCategory, PlanResult, PlannedDay, PlannedStop, TimeOfDay

PREFERRED_TIME = {
    PlaceCategory.cafe: TimeOfDay.morning,
    PlaceCategory.food: TimeOfDay.lunch,
    PlaceCategory.drinks: TimeOfDay.evening,
    PlaceCategory.nightlife: TimeOfDay.evening,
    PlaceCategory.stay: TimeOfDay.evening,
}
TIME_ORDER = list(TimeOfDay)


def preferred_time(category: PlaceCategory) -> TimeOfDay:
    return PREFERRED_TIME.get(category, TimeOfDay.afternoon)


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    dlat = a[0] - b[0]
    dlon = (a[1] - b[1]) * math.cos(math.radians(a[0]))
    return dlat * dlat + dlon * dlon


def _kmeans(places: list[Place], k: int) -> list[list[Place]]:
    points = [(p.latitude, p.longitude) for p in places]
    order = sorted(range(len(points)), key=lambda i: points[i][0])
    centers = [points[order[i * len(order) // k]] for i in range(k)]
    assignment = [0] * len(points)
    for _ in range(15):
        assignment = [min(range(k), key=lambda c: _dist(p, centers[c])) for p in points]
        for c in range(k):
            members = [points[i] for i in range(len(points)) if assignment[i] == c]
            if members:
                centers[c] = (sum(m[0] for m in members) / len(members), sum(m[1] for m in members) / len(members))
    groups = [[places[i] for i in range(len(places)) if assignment[i] == c] for c in range(k)]
    return [g for g in groups if g]


def _order_day(group: list[Place]) -> list[Place]:
    """Time of day first; within each slot, walk to the nearest next place to avoid zigzagging."""
    ordered: list[Place] = []
    last = None
    for slot in TIME_ORDER:
        remaining = [p for p in group if preferred_time(p.category) == slot]
        while remaining:
            located = [p for p in remaining if p.latitude is not None]
            if last is not None and located:
                nxt = min(located, key=lambda p: _dist(last, (p.latitude, p.longitude)))
            else:
                nxt = remaining[0]
            remaining.remove(nxt)
            ordered.append(nxt)
            if nxt.latitude is not None:
                last = (nxt.latitude, nxt.longitude)
    return ordered


def offline_plan(places: list[Place], days: int, city: str) -> PlanResult:
    located = [p for p in places if p.latitude is not None and p.longitude is not None]
    unlocated = [p for p in places if p.latitude is None or p.longitude is None]

    groups = _kmeans(located, max(1, min(days, len(located)))) if located else []
    if not groups:
        groups = [[] for _ in range(max(1, min(days, len(unlocated))))]
    for p in unlocated:  # spread over the lightest days
        min(groups, key=len).append(p)

    result_days = []
    for i, group in enumerate(groups, start=1):
        group[:] = _order_day(group)
        hoods = Counter(p.neighborhood for p in group if p.neighborhood)
        title = " & ".join(h for h, _ in hoods.most_common(2)) or city
        result_days.append(PlannedDay(
            day_number=i,
            title=title,
            stops=[PlannedStop(place_id=p.id, time_of_day=preferred_time(p.category), note=None) for p in group],
        ))
    return PlanResult(days=result_days, unscheduled_place_ids=[], notes=None)
