"""Turns Claude's extraction into saved trips and places, and applies itineraries."""

import logging
import math
from datetime import date, datetime, timezone
from typing import Callable, Optional

from .db import Database, normalize
from .geocode import Geocoder
from .hours import summary as hours_summary
from .llm import ClaudeError, ClaudeService
from .models import (
    ExtractedPlace,
    ExtractionResult,
    Place,
    PlanPlace,
    PlanRequest,
    PlanResult,
    ReelMetadata,
    TripDetail,
)
from .planner import offline_plan

log = logging.getLogger(__name__)


class Library:
    def __init__(self, db: Database, geocoder: Geocoder):
        self.db = db
        self.geocoder = geocoder

    async def save_extraction(
        self,
        reel_meta: ReelMetadata,
        result: ExtractionResult,
        progress: Callable[[str], None] = lambda _: None,
    ) -> tuple[Optional[str], Optional[str], int]:
        """Saves places into a trip per city. Returns (first trip id, reel id, places added)."""
        reel = self.db.add_reel(reel_meta, title=result.title, summary=result.summary)
        first_trip: Optional[str] = None
        added = 0

        for index, extracted in enumerate(result.places, start=1):
            city = extracted.city.strip() or (result.destination_city or "Saved places")
            country = extracted.country.strip() or (result.destination_country or "")
            trip = self.db.find_trip_by_city(city) or self.db.create_trip(name=city, city=city, country=country)
            first_trip = first_trip or trip.id

            existing = next(
                (p for p in self.db.list_places(trip.id) if normalize(p.name) == normalize(extracted.name)), None
            )
            if existing:
                self._merge(existing, extracted)
                continue

            progress(f"Pinning places on the map ({index}/{len(result.places)})")
            place = self.db.add_place(
                trip_id=trip.id,
                reel_id=reel.id,
                name=extracted.name,
                category=extracted.category,
                summary=extracted.description,
                recommended_items=extracted.recommended_items,
                price_hint=extracted.price_hint,
                tips=extracted.tips,
                confidence=extracted.confidence,
                neighborhood=extracted.neighborhood,
                address=extracted.address,
                city=city,
                country=country,
            )
            await self.locate(place)
            added += 1

        self.db.set_reel_trip(reel.id, first_trip)
        return first_trip, reel.id, added

    async def locate(self, place: Place, query: Optional[str] = None) -> bool:
        match = await self.geocoder.locate(place.name, place.neighborhood, place.city, place.country, query=query)
        if not match:
            return False
        self.db.update_place(
            place.id,
            latitude=match.latitude,
            longitude=match.longitude,
            address=place.address or match.address,
            maps_url=match.maps_url,
            resolved_name=match.name if normalize(match.name) != normalize(place.name) else None,
            opening_hours=match.hours,
            hours_checked_at=datetime.now(timezone.utc),
        )
        return True

    async def refresh_details(self, trip_id: str, limit: int = 30) -> int:
        """Looks up opening hours (and a pin, if missing) for places that haven't been checked yet.
        Keeps the current pin when the new match is somewhere else (> 300 m away)."""
        updated = 0
        for place in self.db.list_places(trip_id):
            if updated >= limit:
                break
            if place.hours_checked_at is not None and place.latitude is not None:
                continue  # already looked up; "Find" on the place page re-runs it on demand
            match = await self.geocoder.locate(place.name, place.neighborhood, place.city, place.country)
            if not match:
                self.db.update_place(place.id, hours_checked_at=datetime.now(timezone.utc))
                continue
            if place.latitude is None:
                await self.locate(place)
            elif _meters(place.latitude, place.longitude, match.latitude, match.longitude) <= 300:
                self.db.update_place(place.id, opening_hours=match.hours, hours_checked_at=datetime.now(timezone.utc),
                                     maps_url=place.maps_url or match.maps_url)
            updated += 1
        return updated

    def _merge(self, place: Place, extracted: ExtractedPlace) -> None:
        items = place.recommended_items + [i for i in extracted.recommended_items if i not in place.recommended_items]
        summary = place.summary
        if extracted.description and extracted.description not in summary:
            summary = f"{summary}\n\n{extracted.description}" if summary else extracted.description
        self.db.update_place(
            place.id,
            recommended_items=items,
            summary=summary,
            tips=place.tips or extracted.tips,
            price_hint=place.price_hint or extracted.price_hint,
        )

    # ---------- Itineraries ----------

    async def plan_trip(
        self, trip_id: str, days: int, start_date: Optional[date], preferences: Optional[str],
        claude: Optional[ClaudeService],
    ) -> TripDetail:
        trip = self.db.get_trip(trip_id)
        places = self.db.list_places(trip_id)
        planned_by = "offline"
        result: Optional[PlanResult] = None
        if claude is not None:
            request = PlanRequest(
                city=trip.city,
                days=days,
                start_date=start_date,
                preferences=preferences,
                places=[
                    PlanPlace(id=p.id, name=p.name, category=p.category, latitude=p.latitude,
                              longitude=p.longitude, neighborhood=p.neighborhood, notes=p.summary[:300] or None,
                              opening_hours=hours_summary(p.opening_hours))
                    for p in places
                ],
            )
            try:
                result = await claude.plan_itinerary(request)
                planned_by = "claude"
            except ClaudeError as e:
                log.warning("Claude planning failed, using offline planner: %s", e)
        if result is None:
            result = offline_plan(places, days, trip.city)

        self.apply_plan(trip_id, result, start_date, planned_by)
        return self.db.get_trip_detail(trip_id)

    def apply_plan(self, trip_id: str, result: PlanResult, start_date: Optional[date], planned_by: str) -> None:
        self.clear_plan(trip_id)
        for day_index, day in enumerate(result.days, start=1):
            for order, stop in enumerate(day.stops):
                self.db.update_place(
                    stop.place_id, day_number=day_index, day_order=order, time_of_day=stop.time_of_day,
                    day_note=stop.note,
                )
        self.db.update_trip(
            trip_id,
            day_count=len(result.days),
            day_titles=[d.title for d in result.days],
            plan_notes=result.notes,
            start_date=start_date,
            planned_by=planned_by,
        )

    def clear_plan(self, trip_id: str) -> None:
        for p in self.db.list_places(trip_id):
            self.db.update_place(p.id, day_number=None, day_order=0, time_of_day=None, day_note=None)
        self.db.update_trip(trip_id, day_count=0, day_titles=[], plan_notes=None, planned_by=None)

    def move_place(self, place: Place, day: Optional[int]) -> None:
        """Moves a place to the end of a day (or unschedules it with None)."""
        if day is None:
            self.db.update_place(place.id, day_number=None, day_order=0)
            return
        trip = self.db.get_trip(place.trip_id)
        if day > trip.day_count:
            titles = trip.day_titles + [f"Day {n}" for n in range(len(trip.day_titles) + 1, day + 1)]
            self.db.update_trip(trip.id, day_count=day, day_titles=titles)
        last = max((p.day_order for p in self.db.list_places(place.trip_id) if p.day_number == day), default=-1)
        self.db.update_place(place.id, day_number=day, day_order=last + 1)

    def reorder_day(self, trip_id: str, day: int, place_ids: list[str]) -> None:
        on_day = {p.id for p in self.db.list_places(trip_id) if p.day_number == day}
        for order, place_id in enumerate(pid for pid in place_ids if pid in on_day):
            self.db.update_place(place_id, day_order=order)


def _meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return 6_371_000 * 2 * math.asin(math.sqrt(a))
