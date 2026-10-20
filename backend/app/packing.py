"""Packing lists made from the trip itself: its days and stops, the weather, your taste, and what you
usually leave unused. Claude writes the list; without Claude a rule-based list covers the essentials."""

import json
import logging
import re
import threading
from datetime import date, datetime, timezone
from typing import Optional

from .db import Database, new_id, normalize
from .library import Library
from .llm import ClaudeError, ClaudeService
from .models import PackingDraftItem, PackingItem, PackingList, PackingResult, TripDetail, WeatherDay
from .concierge import profile_text
from .models import TasteProfile
from .weather import Weather

log = logging.getLogger(__name__)

MAX_ITEMS = 80
UNUSED_KEY = "packing_unused"


def item_key(text: str) -> str:
    """The same thing whatever the quantity: '5 tops' and '4 tops' are both 'tops'."""
    return normalize(re.sub(r"^\d+\s*[x×]?\s*", "", text))


def clean_items(drafts: list[PackingDraftItem], days: int) -> list[PackingItem]:
    out: list[PackingItem] = []
    seen: set[str] = set()
    for d in drafts:
        text = " ".join(d.text.split())[:120]
        key = item_key(text)
        if not text or not key or key in seen:
            continue
        seen.add(key)
        reason = " ".join((d.reason or "").split())[:140] or None
        out.append(PackingItem(id=new_id(), text=text, group=d.group, reason=reason,
                               days=sorted({n for n in d.days if 1 <= n <= max(days, 1)})[:21], day_bag=bool(d.day_bag)))
        if len(out) >= MAX_ITEMS:
            break
    return out


def offline_list(trip: TripDetail, weather: list[WeatherDay], carry_on_only: bool, unused: set[str]) -> PackingResult:
    """The essentials by rule, for when Claude can't be reached."""
    days = max(trip.day_count, 1)
    items: list[PackingDraftItem] = []

    def add(text, group, reason=None, days_on=(), day_bag=False):
        items.append(PackingDraftItem(text=text, group=group, reason=reason, days=list(days_on), day_bag=day_bag))

    n = min(days, 5) if carry_on_only else min(days + 1, 8)
    add("Passport or ID", "documents")
    add("Cards and a little local cash", "documents")
    if trip.bookings:
        add("Booking confirmations, saved offline", "documents", "Flights and stays are in your Bookings")
    add("Phone and charger", "tech")
    add("Power bank", "tech")
    add("Plug adapter if needed", "tech", f"Check the sockets in {trip.country or trip.city}" if (trip.country or trip.city) else None)
    add("Toothbrush and toiletries", "toiletries")
    add("Any medication you take", "toiletries")
    add(f"{n} tops", "clothes", "Re-wear or do a quick wash on longer trips" if days > 5 else None)
    add(f"{max(2, min(days // 2 + 1, 4))} bottoms", "clothes")
    add(f"Underwear and socks for {min(days, 7)} days", "clothes")
    add("Sleepwear", "clothes")
    add("Comfortable walking shoes", "shoes", "You'll be on your feet between stops")
    add("Refillable water bottle", "daybag", None, (), True)
    add("Phone charger or power bank", "daybag", None, (), True)

    rainy = [w.day for w in weather if (w.rain_chance or 0) >= 50 or any(x in w.summary.lower() for x in ("rain", "shower", "drizzle", "thunder"))]
    if rainy:
        add("Compact umbrella", "daybag", f"Rain expected on day {rainy[0]}" + (" and others" if len(rainy) > 1 else ""), rainy, True)
        add("Light waterproof jacket", "clothes", "Wet weather in the forecast" if any(w.source == "forecast" for w in weather) else "It was wet around these dates last year", rainy)
    if weather and max(w.temp_max for w in weather) >= 26:
        add("Sunscreen", "toiletries", "Warm, sunny days", (), True)
        add("Sunglasses and a hat", "shoes", "Warm, sunny days", (), True)
        add("Light, breathable clothes", "clothes", f"Highs up to {round(max(w.temp_max for w in weather))}°C")
    if weather and min(w.temp_min for w in weather) <= 8:
        add("Warm layer or coat", "clothes", f"Lows down to {round(min(w.temp_min for w in weather))}°C")
    if weather and min(w.temp_min for w in weather) <= 0:
        add("Gloves and a hat", "clothes", "Freezing at times")
    cats = {p.category.value for p in trip.places}
    if cats & {"nightlife", "drinks"}:
        add("One smart outfit for the evening", "clothes", "Bars and nightlife are on your list")
    if cats & {"nature", "activity"}:
        add("Sturdy shoes for outdoor stops", "shoes", "Outdoor stops are on your list")
    if "shopping" in cats and not carry_on_only:
        add("Foldable tote bag", "other", "Shopping is on your list")
    items = [i for i in items if item_key(i.text) not in unused]
    return PackingResult(items=items, notes=None)


class PackingService:
    def __init__(self, db: Database, claude: Optional[ClaudeService], weather: Weather, library: Library):
        self.db = db
        self.claude = claude
        self.weather = weather
        self.library = library
        self._lock = threading.RLock()

    # ---------- Reading and writing ----------

    def get(self, trip_id: str) -> Optional[PackingList]:
        data = self.db.get_packing(trip_id)
        return PackingList(trip_id=trip_id, **data) if data else None

    def _save(self, trip_id: str, current: PackingList) -> PackingList:
        data = current.model_dump(mode="json", exclude={"trip_id"})
        self.db.save_packing(trip_id, data)
        return self.get(trip_id)

    def unused_counts(self) -> dict[str, int]:
        return self.db.get_setting(UNUSED_KEY) or {}

    # ---------- Making the list ----------

    def _context(self, trip: TripDetail, weather: list[WeatherDay], carry_on_only: bool, custom: list[str], unused: list[str]) -> dict:
        days = []
        for d in range(1, trip.day_count + 1):
            stops = sorted((p for p in trip.places if p.day_number == d), key=lambda p: p.day_order)
            days.append({"day": d, "stops": [{k: v for k, v in {"name": p.name, "type": p.category.value, "when": p.time_of_day.value if p.time_of_day else None,
                                                                 "at": p.start_time, "area": p.neighborhood}.items() if v} for p in stops]})
        loose = [{"name": p.name, "type": p.category.value} for p in trip.places if not p.day_number][:30]
        data = {
            "trip": {k: v for k, v in {"name": trip.name, "city": trip.city, "country": trip.country,
                                       "start_date": trip.start_date.isoformat() if trip.start_date else None,
                                       "days": trip.day_count or None}.items() if v},
            "itinerary": days or None, "saved_places_not_scheduled": loose or None,
            "weather": [w.model_dump(exclude_none=True) for w in weather] or None,
            "bookings": [{"type": b.kind, "title": b.title, "starts": b.start_at} for b in trip.bookings[:12]] or None,
            "luggage": "carry-on only" if carry_on_only else "checked bag is fine",
            "already_on_the_list_added_by_the_person": custom or None,
            "usually_left_unused": unused or None,
        }
        return {k: v for k, v in data.items() if v}

    async def generate(self, trip: TripDetail, taste: TasteProfile, carry_on_only: Optional[bool], keep_packed: bool) -> PackingList:
        previous = self.get(trip.id)
        carry = previous.carry_on_only if (carry_on_only is None and previous) else bool(carry_on_only)
        weather: list[WeatherDay] = []
        center = self.library.trip_center(trip.id)
        if trip.start_date and center:
            weather = await self.weather.days(center[0], center[1], trip.start_date, trip.day_count or 4)

        counts = self.unused_counts()
        often_unused = sorted((k for k, v in counts.items() if v >= 1), key=lambda k: -counts[k])[:15]
        custom = [i.text for i in (previous.items if previous else []) if i.custom]
        result: Optional[PackingResult] = None
        by = "offline"
        if self.claude is not None:
            context = self._context(trip, weather, carry, custom, often_unused)
            context["taste"] = profile_text(taste) or None
            try:
                result = await self.claude.plan_packing({k: v for k, v in context.items() if v})
                by = "claude"
            except ClaudeError as e:
                log.warning("Claude packing list failed, using the basic list: %s", e)
        if result is None:
            result = offline_list(trip, weather, carry, {k for k, v in counts.items() if v >= 2})

        items = clean_items(result.items, trip.day_count)
        if previous:
            old = {item_key(i.text): i for i in previous.items}
            for item in items:
                match = old.get(item_key(item.text))
                if match and keep_packed:
                    item.packed = match.packed
            have = {item_key(i.text) for i in items}
            items += [i for i in previous.items if i.custom and item_key(i.text) not in have]
        fresh = PackingList(
            trip_id=trip.id, items=items, weather=weather, notes=" ".join((result.notes or "").split())[:200] or None,
            carry_on_only=carry, generated_by=by, generated_at=datetime.now(timezone.utc),
        )
        with self._lock:
            return self._save(trip.id, fresh)

    # ---------- Editing ----------

    def add_item(self, trip_id: str, text: str, group: str) -> Optional[PackingList]:
        with self._lock:
            current = self.get(trip_id)
            if current is None or len(current.items) >= MAX_ITEMS + 40:
                return current
            current.items.append(PackingItem(id=new_id(), text=" ".join(text.split())[:120], group=group, custom=True))
            return self._save(trip_id, current)

    def update_item(self, trip_id: str, item_id: str, changes: dict) -> Optional[PackingList]:
        with self._lock:
            current = self.get(trip_id)
            item = next((i for i in current.items if i.id == item_id), None) if current else None
            if item is None:
                return None
            if changes.get("text") is not None:
                item.text = " ".join(changes["text"].split())[:120] or item.text
            if changes.get("group") is not None:
                item.group = changes["group"]
            if changes.get("packed") is not None:
                item.packed = changes["packed"]
            if changes.get("unused") is not None and changes["unused"] != item.unused:
                item.unused = changes["unused"]
                counts = self.unused_counts()
                key = item_key(item.text)
                counts[key] = max(0, counts.get(key, 0) + (1 if item.unused else -1))
                self.db.set_setting(UNUSED_KEY, {k: v for k, v in counts.items() if v})
            return self._save(trip_id, current)

    def delete_item(self, trip_id: str, item_id: str) -> Optional[PackingList]:
        with self._lock:
            current = self.get(trip_id)
            if current is None or not any(i.id == item_id for i in current.items):
                return None
            current.items = [i for i in current.items if i.id != item_id]
            return self._save(trip_id, current)
