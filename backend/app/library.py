"""Turns Claude's extraction into saved trips and places, and applies itineraries."""

import logging
import math
import re
import re as _re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from .db import Database, normalize
from .geocode import GeoMatch, Geocoder
from .maplinks import MapLink
from .hours import summary as hours_summary
from .photos import PhotoStore
from .photos import merge as merge_photos
from .llm import ClaudeError, ClaudeService
from .models import (
    Booking,
    BookingDraft,
    BOOKING_TIME,
    ExtractedPlace,
    ExtractionResult,
    Place,
    PlanCity,
    PlanPlace,
    PlanRequest,
    PlanResult,
    ReelMetadata,
    Trip,
    TripDetail,
)
from .planner import offline_plan, offline_tidy, slot_for_time
from .schedule import balance_plan
from .tripcheck import city_key

log = logging.getLogger(__name__)



def _city_days(route, days: int):
    """The days a place may go on: its own city's days on a multi-city trip, otherwise any day."""
    def allowed(place) -> list[int]:
        key = city_key(place.city)
        found = [d for s in route if city_key(s.city) == key for d in range(s.start_day, min(s.end_day, days) + 1)]
        return found or list(range(1, days + 1))
    return allowed

class Library:
    def __init__(self, db: Database, geocoder: Geocoder, photos: Optional[PhotoStore] = None):
        self.db = db
        self.geocoder = geocoder
        self.photos = photos

    async def save_extraction(
        self,
        reel_meta: ReelMetadata,
        result: ExtractionResult,
        progress: Callable[[str], None] = lambda _: None,
        images: Optional[dict[str, Path]] = None,
        photo_attribution: str = "From the reel",
    ) -> tuple[Optional[str], Optional[str], int]:
        """Saves the post's places to your saved places (not to a trip). Returns (None, reel id, places added);
        the first value is kept for older callers that expected a trip."""
        reel = self.db.add_reel(reel_meta, title=result.title, summary=result.summary)
        first_trip: Optional[str] = None
        added = 0

        for index, extracted in enumerate(result.places, start=1):
            city = extracted.city.strip() or (result.destination_city or "")
            country = extracted.country.strip() or (result.destination_country or "")
            existing = self.db.find_saved(extracted.name, city)
            if existing:
                self._merge(existing, extracted)
                self.db.add_mention(existing.id, reel.id)
                self._add_reel_photos(existing.id, extracted.image_labels, images, photo_attribution)
                continue

            progress(f"Pinning places on the map ({index}/{len(result.places)})")
            place = self.db.add_place(
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
                event_date=extracted.event_date,
                event_end_date=extracted.event_end_date if extracted.event_date and extracted.event_end_date and extracted.event_end_date > extracted.event_date else None,
                start_time=extracted.event_time if extracted.event_date else None,
                venue=" ".join((extracted.venue or "").split())[:200] or None,
            )
            self._add_reel_photos(place.id, extracted.image_labels, images, photo_attribution)
            # An event's own name isn't on the map; its venue is.
            venue = extracted.venue if extracted.category == "event" and extracted.venue else None
            await self.locate(self.db.get_place(place.id), query=f"{venue}, {city}" if venue else None)
            added += 1

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
            photos=merge_photos(self.db.photo_refs(place.id), match.photos, replace_sources=("google", "wikimedia")),
            photos_checked_at=datetime.now(timezone.utc),
            rating=match.rating, rating_count=match.rating_count, rating_checked_at=datetime.now(timezone.utc),
            website=match.website, phone=match.phone, contact_checked_at=datetime.now(timezone.utc),
        )
        return True

    def _add_reel_photos(
        self, place_id: str, labels: list[str], images: Optional[dict[str, Path]], attribution: str = "From the reel",
    ) -> None:
        if not self.photos or not images:
            return
        new = []
        for label in labels[:3]:
            path = images.get(label.strip())
            if path and path.exists():
                ref = self.photos.save_reel_image(place_id, path)
                if ref:
                    new.append({"source": "reel", "ref": ref, "attribution": attribution})
        if new:
            self.db.update_place(place_id, photos=merge_photos(self.db.photo_refs(place_id), new))

    # ---------- Adding places by hand ----------

    def trip_center(self, trip_id: Optional[str]) -> Optional[tuple[float, float]]:
        points = [(p.latitude, p.longitude) for p in self.db.list_places(trip_id) if p.latitude is not None] if trip_id else []
        if not points:
            return None
        return sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points)

    def home(self) -> Optional[dict]:
        return self.db.get_setting("home")

    def _file(self, place: Place, trip_id: Optional[str], folder_id: Optional[str]) -> None:
        if trip_id:
            self.db.add_to_trip(trip_id, place.id)
        if folder_id:
            self.db.add_to_folder(folder_id, place.id)

    def _result(self, place_id: str, trip_id: Optional[str]) -> Place:
        return (self.db.get_place(place_id, trip_id) if trip_id else None) or self.db.get_place(place_id)

    async def add_match(self, match: GeoMatch, trip_id: Optional[str] = None, folder_id: Optional[str] = None,
                        saved: bool = True) -> tuple[Place, bool]:
        """Saves a place picked from search results (and adds it to a trip or folder when given). Returns
        (place, created); a place you already saved with the same name is reused instead of duplicated."""
        existing = self.db.find_saved(match.name, match.city) if saved else None
        if existing:
            self._file(existing, trip_id, folder_id)
            return self._result(existing.id, trip_id), False
        trip = self.db.get_trip(trip_id) if trip_id else None
        checked = datetime.now(timezone.utc)
        place = self.db.add_place(
            name=match.name, category=match.category or "other",
            city=match.city or (trip.city if trip else ""), country=match.country or (trip.country if trip else ""), address=match.address,
            latitude=match.latitude, longitude=match.longitude, maps_url=match.maps_url,
            opening_hours=match.hours, hours_checked_at=checked if match.hours or match.place_id else None,
            photos=merge_photos([], match.photos), photos_checked_at=checked if match.photos else None,
            rating=match.rating, rating_count=match.rating_count, rating_checked_at=checked if match.place_id else None,
            website=match.website, phone=match.phone, contact_checked_at=checked if match.place_id else None,
            saved=saved,
        )
        self._file(place, trip_id, folder_id)
        return self._result(place.id, trip_id), True

    async def add_by_name(self, name: str, trip_id: Optional[str], city: Optional[str] = None, category: str = "other",
                          latitude: Optional[float] = None, longitude: Optional[float] = None,
                          folder_id: Optional[str] = None) -> tuple[Place, bool]:
        """Saves a place by name (and pin, if known), then tries to find it on the map."""
        trip = self.db.get_trip(trip_id) if trip_id else None
        city = city or (trip.city if trip else "")
        existing = self.db.find_saved(name, city)
        if existing:
            self._file(existing, trip_id, folder_id)
            return self._result(existing.id, trip_id), False
        place = self.db.add_place(name=name, category=category, city=city, country=trip.country if trip else "",
                                  latitude=latitude, longitude=longitude)
        if latitude is None:
            await self.locate(place)
        self._file(place, trip_id, folder_id)
        return self._result(place.id, trip_id), True

    async def add_from_link(self, link: MapLink, trip_id: Optional[str] = None, folder_id: Optional[str] = None) -> tuple[Place, bool]:
        """Saves the place from a Google/Apple Maps link, filling in details from a search near its pin."""
        near = (link.latitude, link.longitude) if link.latitude is not None else self.trip_center(trip_id)
        if link.name:
            for candidate in await self.geocoder.search(link.name, near=near, limit=3):
                if link.latitude is None or _meters(link.latitude, link.longitude, candidate.latitude, candidate.longitude) <= 400:
                    full = (await self.geocoder.details(candidate.place_id) if candidate.place_id else None) or candidate
                    if link.latitude is not None:  # the link's pin is exact; keep it
                        full.latitude, full.longitude = link.latitude, link.longitude
                    return await self.add_match(full, trip_id, folder_id)
        return await self.add_by_name(link.name or "Dropped pin", trip_id, latitude=link.latitude, longitude=link.longitude, folder_id=folder_id)

    def delete_place(self, place_id: str) -> None:
        if self.photos:
            self.photos.delete(self.db.photo_refs(place_id))
        self.db.delete_place(place_id)

    def delete_trip(self, trip_id: str) -> None:
        """Deletes the trip but keeps its places saved; suggestions you never kept are removed with it."""
        unsaved = [p.id for p in self.db.list_places(trip_id) if not p.saved]
        refs = {pid: self.db.photo_refs(pid) for pid in unsaved}
        self.db.delete_trip(trip_id)
        if self.photos:
            for pid in unsaved:
                if self.db.get_place(pid) is None:
                    self.photos.delete(refs[pid])

    def remove_from_trip(self, trip_id: str, place_id: str) -> None:
        """Takes a stop off a trip (it stays saved); a suggestion you never kept is removed altogether."""
        place = self.db.get_place(place_id, trip_id)
        if place is None:
            return
        if place.day_number:
            self.move_to(place, None, None)
        self.db.remove_from_trip(trip_id, place_id)
        if not place.saved and not self.db.get_place(place_id).trip_ids:
            self.delete_place(place_id)

    async def refresh_details(self, trip_id: str, limit: int = 30) -> int:
        """Looks up opening hours (and a pin, if missing) for places that haven't been checked yet.
        Keeps the current pin when the new match is somewhere else (> 300 m away)."""
        updated = 0
        for place in self.db.list_places(trip_id):
            if updated >= limit:
                break
            if (place.hours_checked_at is not None and place.photos_checked_at is not None
                    and place.rating_checked_at is not None and place.contact_checked_at is not None
                    and place.latitude is not None):
                continue  # already looked up; "Find" on the place page re-runs it on demand
            match = await self.geocoder.locate(place.name, place.neighborhood, place.city, place.country)
            if not match:
                now = datetime.now(timezone.utc)
                self.db.update_place(place.id, hours_checked_at=now, photos_checked_at=now, rating_checked_at=now,
                                     contact_checked_at=now)
                continue
            if place.latitude is None:
                await self.locate(place)
            elif _meters(place.latitude, place.longitude, match.latitude, match.longitude) <= 300:
                self.db.update_place(
                    place.id, opening_hours=match.hours, hours_checked_at=datetime.now(timezone.utc),
                    maps_url=place.maps_url or match.maps_url,
                    photos=merge_photos(self.db.photo_refs(place.id), match.photos, replace_sources=("google", "wikimedia")),
                    photos_checked_at=datetime.now(timezone.utc),
                    rating=match.rating, rating_count=match.rating_count, rating_checked_at=datetime.now(timezone.utc),
                    website=match.website, phone=match.phone, contact_checked_at=datetime.now(timezone.utc),
                )
            else:  # the lookup found somewhere else; keep the pin, and don't look again
                self.db.update_place(place.id, rating_checked_at=datetime.now(timezone.utc),
                                     contact_checked_at=datetime.now(timezone.utc))
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
        route = [s for s in trip.stops if s.start_day <= days] if len(trip.stops) > 1 else []
        if claude is not None:
            request = PlanRequest(
                city=trip.city,
                days=days,
                start_date=start_date,
                preferences=preferences,
                places=[
                    PlanPlace(id=p.id, name=p.name, category=p.category, latitude=p.latitude,
                              longitude=p.longitude, neighborhood=p.neighborhood, notes=p.summary[:300] or None,
                              opening_hours=hours_summary(p.opening_hours), must_do=p.must_do,
                              mentions=max(1, p.mention_count), city=p.city or None)
                    for p in places
                ],
                route=[PlanCity(city=s.city, first_day=s.start_day, last_day=min(s.end_day, days)) for s in route],
            )
            try:
                result = await claude.plan_itinerary(request)
                planned_by = "claude"
            except ClaudeError as e:
                log.warning("Claude planning failed, using offline planner: %s", e)
        if result is None:
            result = offline_plan(places, days, trip.city)
        result = balance_plan(result, places, _city_days(route, days))

        self.apply_plan(trip_id, result, start_date, planned_by)
        return self.db.get_trip_detail(trip_id)

    # ---------- Bookings ----------

    def clean_drafts(self, drafts: list[BookingDraft]) -> list[BookingDraft]:
        """Keeps what Claude read in shapes the app accepts; anything malformed becomes "not shown"."""
        def text(value, limit):
            return " ".join((value or "").split())[:limit] or None

        out = []
        for d in drafts[:20]:
            title = text(d.title, 160)
            if not title:
                continue
            valid = lambda v: v if v and _re.match(BOOKING_TIME, v) and _valid_date(v) else None
            out.append(BookingDraft(
                kind=d.kind, title=title, start_at=valid(d.start_at), end_at=valid(d.end_at),
                origin=text(d.origin, 80), destination=text(d.destination, 80), address=text(d.address, 300),
                confirmation=text(d.confirmation, 60), party_size=d.party_size if d.party_size and 1 <= d.party_size <= 100 else None,
                notes=text(d.notes, 2000),
            ))
        return out

    def add_booking(self, trip_id: str, fields: dict) -> Booking:
        booking = self.db.add_booking(trip_id, **fields)
        self._apply_reservation(booking)
        return booking

    def update_booking(self, booking: Booking, changes: dict) -> Booking:
        self.db.update_booking(booking.id, **changes)
        booking = self.db.get_booking(booking.id)
        self._apply_reservation(booking)
        return booking

    def delete_booking(self, booking: Booking) -> None:
        place = self.db.get_place(booking.place_id, booking.trip_id) if booking.place_id and booking.kind == "reservation" else None
        if place is not None and booking.start_at and place.start_time == booking.start_at[11:16]:
            self.db.update_place(place.id, trip_id=booking.trip_id, start_time=None)  # the reservation was what set it
        self.db.delete_booking(booking.id)

    def _apply_reservation(self, booking: Booking) -> None:
        """A table booked for a saved place sets its exact time and, when the trip has dates, puts it on that day."""
        if booking.kind != "reservation" or not booking.place_id or not booking.start_at:
            return
        place = self.db.get_place(booking.place_id, booking.trip_id)
        if place is None:
            return
        day_part, _, time_part = booking.start_at.partition("T")
        if time_part:
            self.db.update_place(place.id, trip_id=booking.trip_id, start_time=time_part, time_of_day=slot_for_time(time_part))
        trip = self.db.get_trip(booking.trip_id)
        if trip.start_date:
            try:
                day = (date.fromisoformat(day_part) - trip.start_date).days + 1
            except ValueError:
                return
            if 1 <= day <= 21 and place.day_number != day:
                self.move_to(self.db.get_place(place.id, booking.trip_id), day, None)

    async def tidy_trip(self, trip_id: str, instruction: Optional[str], claude: Optional[ClaudeService]) -> TripDetail:
        """Orders the stops on the days the person built, suggests times and tips, and (when asked) applies
        their instruction. Places they haven't put on a day stay unscheduled unless the instruction says otherwise."""
        trip = self.db.get_trip(trip_id)
        places = self.db.list_places(trip_id)
        scheduled = [p for p in places if p.day_number]
        if not scheduled:
            raise ValueError("Add some places to a day first")
        day_count = max(trip.day_count, max(p.day_number for p in scheduled))
        result: Optional[PlanResult] = None
        planned_by = "offline"
        if claude is not None:
            request = PlanRequest(
                city=trip.city, days=day_count, start_date=trip.start_date, preferences=None,
                places=[
                    PlanPlace(id=p.id, name=p.name, category=p.category, latitude=p.latitude, longitude=p.longitude,
                              neighborhood=p.neighborhood, notes=p.summary[:300] or None,
                              opening_hours=hours_summary(p.opening_hours), must_do=p.must_do,
                              mentions=max(1, p.mention_count), start_time=p.start_time, current_day=p.day_number)
                    for p in places
                ],
            )
            try:
                result = await claude.tidy_itinerary(request, instruction)
                planned_by = "claude"
            except ClaudeError as e:
                log.warning("Claude tidy failed, using offline ordering: %s", e)
        if result is None:
            result = offline_tidy(places, day_count)
        result = balance_plan(result, places, _city_days([], day_count), move_days=False)
        titles = {i: t for i, t in enumerate(trip.day_titles, start=1) if t and not re.fullmatch(r"Day \d+", t)}
        for i, day in enumerate(result.days, start=1):
            if i in titles and day.day_number == i:
                day.title = titles[i]
        self.apply_plan(trip_id, result, trip.start_date, planned_by)
        return self.db.get_trip_detail(trip_id)

    def add_to_day(self, trip_id: str, place_ids: list[str], day: Optional[int]) -> None:
        """Puts places at the end of a day (a new last day when day is None). Places already on that day stay put."""
        trip = self.db.get_trip(trip_id)
        target = day if day is not None else trip.day_count + 1
        if target > 21:
            raise ValueError("Trips can have at most 21 days")
        for place_id in dict.fromkeys(place_ids):
            place = self.db.get_place(place_id, trip_id)
            if place is None or place.day_number == target:
                continue
            self.move_to(place, target, None)

    def apply_plan(self, trip_id: str, result: PlanResult, start_date: Optional[date], planned_by: str) -> None:
        self.clear_plan(trip_id)
        for day_index, day in enumerate(result.days, start=1):
            for order, stop in enumerate(day.stops):
                self.db.update_place(
                    stop.place_id, trip_id=trip_id, day_number=day_index, day_order=order, time_of_day=stop.time_of_day,
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
            self.db.update_place(p.id, trip_id=trip_id, day_number=None, day_order=0, time_of_day=None, day_note=None)
        self.db.update_trip(trip_id, day_count=0, day_titles=[], plan_notes=None, planned_by=None)

    def move_place(self, place: Place, day: Optional[int]) -> None:
        """Moves a place to the end of a day (or unschedules it with None)."""
        self.move_to(place, day, None)

    def move_to(self, place: Place, day: Optional[int], index: Optional[int]) -> None:
        """Puts a place at a position within a day (end of the day when index is None), or unschedules it
        with day None. Renumbers the day it left and the day it joined."""
        trip_id = place.trip_id
        if not trip_id:
            raise ValueError("Open the place from its trip to move it between days")
        places = self.db.list_places(trip_id)
        if place.day_number is not None and place.day_number != day:
            left = sorted((p for p in places if p.day_number == place.day_number and p.id != place.id), key=lambda p: p.day_order)
            for order, p in enumerate(left):
                self.db.update_place(p.id, trip_id=trip_id, day_order=order)
        if day is None:
            self.db.update_place(place.id, trip_id=trip_id, day_number=None, day_order=0)
            return
        trip = self.db.get_trip(place.trip_id)
        if day > trip.day_count:
            titles = trip.day_titles + [f"Day {n}" for n in range(len(trip.day_titles) + 1, day + 1)]
            self.db.update_trip(trip.id, day_count=day, day_titles=titles)
        target = sorted((p for p in places if p.day_number == day and p.id != place.id), key=lambda p: p.day_order)
        target.insert(len(target) if index is None else max(0, min(index, len(target))), place)
        for order, p in enumerate(target):
            self.db.update_place(p.id, trip_id=trip_id, day_number=day, day_order=order)

    def reorder_day(self, trip_id: str, day: int, place_ids: list[str]) -> None:
        on_day = {p.id for p in self.db.list_places(trip_id) if p.day_number == day}
        for order, place_id in enumerate(pid for pid in place_ids if pid in on_day):
            self.db.update_place(place_id, trip_id=trip_id, day_order=order)

    # ---------- New trips ----------

    async def create_trip(self, req, claude: Optional[ClaudeService], taste: Optional[str] = None) -> TripDetail:
        """A trip made on purpose: links the chosen saved places, then plans it with AI or sets up empty days
        for the person to fill. With fill_gaps, AI adds a few clearly marked suggestions to quiet days."""
        picked = [p for p in (self.db.get_place(pid) for pid in dict.fromkeys(req.place_ids)) if p is not None]
        country = req.country or next((p.country for p in picked if p.country and normalize(p.city) == normalize(req.city)), "")
        city = " ".join(req.city.split())
        trip = self.db.create_trip(name=(req.name or "").strip() or city, city=city, country=country)
        for p in picked:
            self.db.add_to_trip(trip.id, p.id)
        if req.plan == "ai" and picked:
            await self.plan_trip(trip.id, req.days, req.start_date, req.preferences, claude)
        else:
            self.db.update_trip(trip.id, day_count=req.days, day_titles=[f"Day {n}" for n in range(1, req.days + 1)],
                                start_date=req.start_date, planned_by="you" if req.plan == "manual" else None)
        if req.plan == "ai" and req.fill_gaps:
            await self.fill_gaps(trip.id, claude, taste, req.preferences)
        return self.db.get_trip_detail(trip.id)

    async def fill_gaps(self, trip_id: str, claude: Optional[ClaudeService], taste: Optional[str] = None,
                        preferences: Optional[str] = None, per_day: int = 3, limit: int = 8) -> int:
        """Suggests well-known places for days with fewer than per_day stops. Each is checked on the map and
        added as a suggestion (kept out of your saved places until you keep it). Returns how many were added."""
        if claude is None:
            return 0
        trip = self.db.get_trip_detail(trip_id)
        counts = {d: 0 for d in range(1, trip.day_count + 1)}
        for p in trip.places:
            if p.day_number in counts:
                counts[p.day_number] += 1
        quiet = {d: per_day - n for d, n in counts.items() if n < per_day}
        if not quiet:
            return 0
        try:
            found = await claude.suggest_places({
                "city": trip.city, "country": trip.country or None, "taste": taste, "preferences": preferences,
                "already_planned": [{"name": p.name, "type": p.category.value, "day": p.day_number} for p in trip.places],
                "quiet_days": [{"day": d, "places_wanted": n} for d, n in quiet.items()],
                "max_suggestions": min(limit, sum(quiet.values())),
            })
        except ClaudeError as e:
            log.warning("Claude suggestions failed: %s", e)
            return 0
        added = 0
        taken = {normalize(p.name) for p in trip.places}
        for s in found.suggestions[:limit]:
            if s.day not in quiet or quiet[s.day] <= 0 or normalize(s.name) in taken:
                continue
            match = await self.geocoder.locate(s.name, s.neighborhood, trip.city, trip.country)
            if match is None:
                continue  # couldn't confirm it exists; leave it out rather than guess
            saved = self.db.find_saved(match.name, match.city or trip.city)
            if saved:
                place = saved
                self.db.add_to_trip(trip_id, place.id)
            else:
                match.category = s.category.value if hasattr(s.category, "value") else s.category
                place, _ = await self.add_match(match, None, saved=False)
                self.db.add_to_trip(trip_id, place.id, suggested=True, note=" ".join((s.why or "").split())[:160] or None)
            stop = self.db.get_place(place.id, trip_id)
            self.move_to(stop, s.day, None)
            if s.time_of_day:
                self.db.update_place(place.id, trip_id=trip_id, time_of_day=s.time_of_day)
            taken.add(normalize(s.name))
            quiet[s.day] -= 1
            added += 1
        return added

    def keep_suggestion(self, trip_id: str, place_id: str) -> Optional[Place]:
        place = self.db.get_place(place_id, trip_id)
        if place is None:
            return None
        self.db.update_place(place_id, trip_id=trip_id, suggested=False, suggestion_note=None)
        self.db.update_place(place_id, saved=True)
        return self.db.get_place(place_id, trip_id)


def _valid_date(value: str) -> bool:
    try:
        date.fromisoformat(value[:10])
        return True
    except ValueError:
        return False


def _meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return 6_371_000 * 2 * math.asin(math.sqrt(a))
