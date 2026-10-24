"""The personal side of the app: your taste profile, Claude-curated "edits" of each trip's saved places,
the Concierge chat, and a short briefing for each trip day. Each has a rules-based fallback, so the app
still works when Claude can't be reached."""

import hashlib
import json
import logging
import math
import re
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import sqlite3
from urllib.parse import urlparse

from .db import Database, normalize as _norm
from .geocode import GeoMatch
from .hours import summary as hours_summary
from .llm import ClaudeError, ClaudeService
from .models import (
    BriefingText,
    ConciergeReply,
    ConciergeRequest,
    DayBriefing,
    EditItem,
    EditSource,
    EditsResult,
    OpeningHours,
    Place,
    PlacePhoto,
    TasteProfile,
    TripDetail,
    TripEdit,
    TripEdits,
)

log = logging.getLogger(__name__)

EDITOR_VOICE = ("Write like a luxury travel editor (think Vogue or Condé Nast Traveller): assured, warm, specific, never "
                "gushing. No emoji, no exclamation marks.")

EDITS_SYSTEM = f"""You curate editorial lists ("edits") of places in one city for a traveler. You get their saved places
(with ids) and, usually, a numbered list of articles from travel and food publications with research notes on what
those articles recommend.

- Make 3 to 6 edits, each with 4 to 8 places. When articles are given, mix the traveler's saved places with places
  the articles recommend, so each edit brings something new: roughly half and half where both fit the theme.
- A saved place: set place_id to its exact id, other fields null. A place from the articles: place_id null, its
  name as the article gives it, its category and neighbourhood, and source = the number of the article that
  recommends it. Only use places the research notes say that article recommends; never invent a place or credit
  it to an article that didn't recommend it. When no articles are given, use saved places only.
- Tailor them to the traveler's taste profile when one is given: their pace, budget, food and interests.
- Mix kinds of edits: moods or occasions (date night, a rainy afternoon, a slow morning), walkable clusters in one
  neighborhood (use coordinates and neighborhoods), and highlights (must-dos, places several reels recommend).
- Titles are short and magazine-like: "The Date Night Edit", "One Perfect Afternoon in Williamsburg", "Worth the Queue".
- A place can appear in more than one edit, but vary them. Respect opening hours: no breakfast edit of places that open at 6 pm.
- {EDITOR_VOICE}"""

CONCIERGE_SYSTEM = f"""You are the traveler's personal travel concierge inside their trip-planning app. You know their saved
places, itinerary and taste profile (given below as JSON) and today's local time.

- Answer from their saved places first. When you suggest something they haven't saved, say so plainly and don't invent
  opening hours, prices or addresses.
- Use the opening hours and the local time: don't send them somewhere that's closed.
- When they ask for a change to the trip (move a stop, swap days, mark a must-do, set a reservation time, mark visited),
  propose it as actions with exact place ids; nothing changes until they confirm. Otherwise return no actions.
- List the saved places your answer is about in place_ids so they appear as cards.
- Be concise: under 120 words unless they ask for more. {EDITOR_VOICE}"""

BRIEFING_SYSTEM = f"""You write a short morning briefing for one day of a trip, from the facts given (stops in order with
times, that weekday's opening hours, reservations, tips). A headline under 8 words, then 2 to 4 short lines covering how
the day starts, anything closed or closing early, what to book or bring, and one insider tip from the notes.
Only use the facts given. {EDITOR_VOICE}"""

SLOTS = {"morning": (540, 690), "lunch": (720, 840), "afternoon": (840, 1020), "dinner": (1080, 1260), "evening": (1200, 1380)}
PACE = {"slow": "slow and savoured, few stops", "balanced": "balanced", "packed": "packed, sees as much as possible"}
BUDGET = {"value": "value and hidden gems", "mix": "a mix", "splurge": "happy to splurge"}
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


PLATFORM_NAMES = {"tiktok": "TikTok", "instagram": "Instagram", "youtube": "YouTube"}
SITE_NAMES = {
    "eater.com": "Eater", "theinfatuation.com": "The Infatuation", "timeout.com": "Time Out", "cntraveler.com": "Condé Nast Traveler",
    "cntraveller.com": "Condé Nast Traveller", "guide.michelin.com": "Michelin Guide", "nytimes.com": "The New York Times",
    "bonappetit.com": "Bon Appétit", "lonelyplanet.com": "Lonely Planet", "theguardian.com": "The Guardian",
    "travelandleisure.com": "Travel + Leisure", "afar.com": "AFAR", "vogue.com": "Vogue", "ft.com": "Financial Times",
    "telegraph.co.uk": "The Telegraph", "worlds50best.com": "The World's 50 Best", "theworlds50best.com": "The World's 50 Best",
    "foodandwine.com": "Food & Wine", "newyorker.com": "The New Yorker", "nymag.com": "New York Magazine",
    "grubstreet.com": "Grub Street", "saveur.com": "Saveur", "wallpaper.com": "Wallpaper*", "monocle.com": "Monocle",
    "cnn.com": "CNN Travel", "bbc.com": "BBC Travel", "latimes.com": "Los Angeles Times", "sfchronicle.com": "San Francisco Chronicle",
    "secretldn.com": "Secret London", "standard.co.uk": "Evening Standard", "hot-dinners.com": "Hot Dinners",
}


def source_name(url: str) -> str:
    """A publication's name from its address ("Eater" for ny.eater.com), else the site's own address."""
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    for domain, name in SITE_NAMES.items():
        if host == domain or host.endswith("." + domain):
            return name
    return host or "The web"


def _signature(*parts) -> str:
    return hashlib.sha1(json.dumps(parts, default=str).encode()).hexdigest()[:16]


def _minutes(t: str) -> int:
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def _clock(t: str) -> str:
    h, m = map(int, t.split(":"))
    if h == 24:
        return "midnight"
    return f"{h % 12 or 12}{f':{m:02d}' if m else ''} {'AM' if h < 12 else 'PM'}"


def _km(a: tuple[float, float], b: tuple[float, float]) -> float:
    dlat, dlon = math.radians(b[0] - a[0]), math.radians(b[1] - a[1])
    h = math.sin(dlat / 2) ** 2 + math.cos(math.radians(a[0])) * math.cos(math.radians(b[0])) * math.sin(dlon / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def profile_text(p: TasteProfile) -> dict:
    data = {
        "pace": PACE.get(p.pace or ""), "budget": BUDGET.get(p.budget or ""), "food": p.food or None,
        "interests": p.interests or None, "mornings": {"early": "early riser", "late": "late starts"}.get(p.mornings or ""),
        "notes": p.notes,
    }
    return {k: v for k, v in data.items() if v}


def place_brief(p: Place) -> dict:
    data = {
        "id": p.id, "name": p.name, "category": p.category.value, "neighborhood": p.neighborhood,
        "lat": round(p.latitude, 5) if p.latitude is not None else None,
        "lon": round(p.longitude, 5) if p.longitude is not None else None,
        "about": p.summary[:240] or None, "try": p.recommended_items[:4] or None, "price": p.price_hint, "tip": p.tips,
        "hours": hours_summary(p.opening_hours), "must_do": p.must_do or None,
        "mentions": p.mention_count if p.mention_count > 1 else None,
        "day": p.day_number, "order": p.day_order if p.day_number else None,
        "time_of_day": p.time_of_day.value if p.time_of_day else None, "start_time": p.start_time,
        "visited": p.visited or None, "my_notes": p.user_notes[:200] or None,
    }
    return {k: v for k, v in data.items() if v is not None}


def _closed_or_conflict(p: Place, weekday: int) -> Optional[str]:
    """'closed' if the place is shut that weekday, 'Opens at 6 PM'-style text if shut during its slot, else None."""
    if not p.opening_hours or not p.opening_hours.weekly:
        return None
    ranges = p.opening_hours.weekly[weekday] or []
    if not ranges:
        return "closed that day"
    if len(ranges) == 1 and ranges[0].open == "00:00" and ranges[0].close == "24:00":
        return None
    if p.start_time:
        slot = (_minutes(p.start_time), _minutes(p.start_time) + 60)
    elif p.time_of_day:
        slot = SLOTS[p.time_of_day.value]
    else:
        return None
    spans = []
    for r in ranges:
        o, c = _minutes(r.open), _minutes(r.close)
        spans.append((o, c + 1440 if c <= o else c))
    if any(o < slot[1] and c > slot[0] for o, c in spans):
        return None
    first = min(spans)
    return f"opens at {_clock(ranges[spans.index(first)].open)}" if first[0] >= slot[1] else "closed at its planned time"


class Curator:
    def __init__(self, db: Database, claude: Optional[ClaudeService], geocoder=None, photo_url=None,
                 web: bool = True, web_searches: int = 4):
        self.db = db
        self.claude = claude
        self.geocoder = geocoder  # checks that publications' picks are real places, and pins them
        self.photo_url = photo_url  # signs Google photo links for picks that aren't saved yet
        self.web = web
        self.web_searches = web_searches
        self.refreshing: set[str] = set()

    # ---------- Taste profile ----------

    def profile(self) -> TasteProfile:
        return TasteProfile.model_validate(self.db.get_setting("taste_profile") or {})

    def save_profile(self, profile: TasteProfile) -> TasteProfile:
        profile.updated_at = datetime.now(timezone.utc)
        self.db.set_setting("taste_profile", profile.model_dump(mode="json"))
        return profile

    # ---------- Edits ----------
    # Edits mix your saved places in the trip's city with places travel and food publications recommend (found
    # with web search, each checked on the map and linked to the article that recommends it). They refresh at
    # most once a day; saving an edit to the Library keeps it as a folder.

    EDITS_FRESH = timedelta(hours=24)

    def _pool(self, trip: TripDetail) -> list[Place]:
        """The trip's places plus everything else you saved in its city."""
        on_trip = {p.id for p in trip.places}
        city = _norm(trip.city)
        extra = [p for p in self.db.list_places(saved_only=True) if p.id not in on_trip and _norm(p.city) == city]
        return [p for p in trip.places if p.saved] + extra[:60]

    def _places_signature(self, trip: TripDetail) -> str:
        return _signature(sorted(p.id for p in self._pool(trip)))

    def _reel_source(self, place: Place) -> EditSource:
        reels = self.db.place_reels(place.id)
        r = reels[0] if reels else None
        if r and r.platform in ("tiktok", "instagram", "youtube"):
            who = f"@{r.creator} on " if r.creator else ""
            return EditSource(name=f"{who}{PLATFORM_NAMES[r.platform]}", title=r.title or None, url=r.url)
        if r and r.platform == "screenshot":
            return EditSource(name="Your screenshot", title=r.title or None)
        return EditSource(name="Your saved places")

    def _item_for(self, e: dict, i: int, trip: TripDetail) -> Optional[EditItem]:
        place = self.db.get_place(e["place_id"]) if e.get("place_id") else None
        if place is None and e.get("name"):  # a publication's pick: saved since?
            place = self.db.find_saved(e["name"], e.get("city") or trip.city)
        if e.get("place_id") and place is None:
            return None  # a saved place that was deleted
        if place is not None:
            photo = next((ph for ph in place.photos if ph.source != "reel"), place.photos[0] if place.photos else None)
            src = EditSource(**e["source"]) if e.get("source") else self._reel_source(place)
            return EditItem(id=e.get("id") or f"i{i}", place_id=place.id, saved=True, name=place.name, category=place.category,
                            neighborhood=place.neighborhood, city=place.city, note=e.get("note") or "", source=src, photo=photo,
                            rating=place.rating, rating_count=place.rating_count, latitude=place.latitude,
                            longitude=place.longitude, maps_url=place.maps_url)
        g = e.get("geo") or {}
        ref = next((ph["ref"] for ph in g.get("photos") or [] if ph.get("source") == "google"), None)
        photo = PlacePhoto(source="google", url=self.photo_url(ref), attribution="Google") if ref and self.photo_url else None
        return EditItem(id=e.get("id") or f"i{i}", name=e["name"], category=e.get("category") or "other",
                        neighborhood=e.get("neighborhood"), city=e.get("city") or trip.city, note=e.get("note") or "",
                        source=EditSource(**e["source"]) if e.get("source") else None, photo=photo,
                        rating=g.get("rating"), rating_count=g.get("rating_count"), latitude=g.get("latitude"),
                        longitude=g.get("longitude"), maps_url=g.get("maps_url"))

    def edits(self, trip: TripDetail) -> TripEdits:
        row = self.db.get_edits(trip.id)
        refreshing = trip.id in self.refreshing
        if not row:
            return TripEdits(trip_id=trip.id, trip_name=trip.name, refreshing=refreshing)
        folders = {f.id for f in self.db.list_folders()}
        edits = []
        for e in json.loads(row["data"]):
            items = [it for it in (self._item_for(x, i, trip) for i, x in enumerate(e["entries"], start=1)) if it]
            if len(items) >= 2 or (items and e.get("id") == "must"):
                photos = [it.photo for it in items if it.photo]
                cover = next((ph for ph in photos if ph.source != "reel"), photos[0] if photos else None)
                edits.append(TripEdit(id=e["id"], title=e["title"], dek=e["dek"], entries=items, cover_photo=cover,
                                      folder_id=e.get("folder_id") if e.get("folder_id") in folders else None,
                                      new_count=sum(1 for it in items if not it.saved)))
        created = datetime.fromisoformat(row["created_at"])
        stale = row["signature"] != self._places_signature(trip) or datetime.now(timezone.utc) - created > self.EDITS_FRESH
        return TripEdits(trip_id=trip.id, trip_name=trip.name, edits=edits, curated_by=row["curated_by"],
                         created_at=row["created_at"], stale=stale, refreshing=refreshing)

    async def curate(self, trip: TripDetail) -> TripEdits:
        self.refreshing.add(trip.id)
        try:
            await self._curate(trip)
        finally:
            self.refreshing.discard(trip.id)
        return self.edits(trip)

    async def _curate(self, trip: TripDetail) -> None:
        pool = self._pool(trip)
        edits: list[dict] = []
        curated_by = "offline"
        if self.claude is not None:
            taste = profile_text(self.profile())
            notes, sources = "", []
            if self.web:
                try:
                    notes, sources = await self.claude.research_edits(
                        {"city": trip.city, "country": trip.country or None, "taste_profile": taste or None,
                         "already_saved": [p.name for p in pool][:60]}, self.web_searches)
                except ClaudeError as e:
                    log.warning("Edit research failed, using saved places only: %s", e)
            numbered = [{"number": i, "site": source_name(s["url"]), "title": s["title"], "url": s["url"]}
                        for i, s in enumerate(sources, start=1)]
            payload = {"city": trip.city, "taste_profile": taste, "saved_places": [place_brief(p) for p in pool]}
            if numbered:
                payload["articles"] = numbered
                payload["research_notes"] = notes
            try:
                result = await self.claude._parse(
                    EDITS_SYSTEM, [{"type": "text", "text": "Curate edits:\n\n" + json.dumps(payload, default=str)}], EditsResult, feature="edits")
                edits = await self._clean(result, pool, numbered, trip)
                if edits:
                    curated_by = "claude+web" if any(x.get("source") for e in edits for x in e["entries"]) else "claude"
            except ClaudeError as e:
                log.warning("Claude curation failed, using offline edits: %s", e)
        if not edits:
            edits = offline_edits(TripDetail(**{**trip.model_dump(), "places": pool}))
        self.db.save_edits(trip.id, edits, curated_by, self._places_signature(trip))

    async def _clean(self, result: EditsResult, pool: list[Place], sources: list[dict], trip: TripDetail) -> list[dict]:
        """Keeps saved places that exist, and publication picks that cite a real article and can be found on
        the map (so every outside place is a real, current place you can save)."""
        valid = {p.id for p in pool}
        by_name = {_norm(p.name): p.id for p in pool}
        found: dict[str, Optional[dict]] = {}
        out = []
        for edit in result.edits[:6]:
            seen, entries = set(), []
            for entry in edit.entries:
                note = " ".join(entry.note.split())[:200]
                if entry.place_id:
                    if entry.place_id in valid and entry.place_id not in seen:
                        seen.add(entry.place_id)
                        entries.append({"id": f"i{len(entries) + 1}", "place_id": entry.place_id, "note": note})
                    continue
                name = " ".join((entry.name or "").split())[:150]
                if not name or not entry.source or not 1 <= entry.source <= len(sources):
                    continue  # an outside place must cite one of the articles found
                if _norm(name) in by_name:  # it's one of yours after all
                    pid = by_name[_norm(name)]
                    if pid not in seen:
                        seen.add(pid)
                        entries.append({"id": f"i{len(entries) + 1}", "place_id": pid, "note": note})
                    continue
                key = _norm(name)
                if key not in found:
                    found[key] = await self._locate(name, entry.neighborhood, trip)
                geo = found[key]
                if geo is None or key in seen:
                    continue
                seen.add(key)
                src = sources[entry.source - 1]
                entries.append({"id": f"i{len(entries) + 1}", "name": name, "category": (entry.category.value if entry.category else "other"),
                                "neighborhood": entry.neighborhood, "city": trip.city, "note": note, "geo": geo,
                                "source": {"name": src["site"], "title": src["title"] or None, "url": src["url"]}})
            if len(entries) >= 2:
                out.append({"id": f"e{len(out) + 1}", "title": edit.title.strip()[:80], "dek": edit.dek.strip()[:240],
                            "entries": entries[:8]})
        return out

    async def _locate(self, name: str, neighborhood: Optional[str], trip: TripDetail) -> Optional[dict]:
        if self.geocoder is None:
            return None
        try:
            m = await self.geocoder.locate(name, neighborhood, trip.city, trip.country)
        except Exception as e:  # a lookup problem shouldn't sink the edits
            log.warning("Couldn't look up %s: %s", name, e)
            return None
        if m is None:
            return None
        return {"latitude": m.latitude, "longitude": m.longitude, "address": m.address, "maps_url": m.maps_url,
                "photos": m.photos[:3], "rating": m.rating, "rating_count": m.rating_count, "website": m.website,
                "phone": m.phone, "place_id": m.place_id, "resolved": m.name,
                "hours": m.hours.model_dump(mode="json") if m.hours else None}

    def _stored(self, trip_id: str) -> tuple[Optional[sqlite3.Row], list[dict]]:
        row = self.db.get_edits(trip_id)
        return row, json.loads(row["data"]) if row else []

    async def save_entry(self, trip: TripDetail, edit_id: str, entry_id: str, library) -> Optional[Place]:
        """Saves one of an edit's places to your saved places (a publication's pick becomes a saved place)."""
        row, data = self._stored(trip.id)
        edit = next((e for e in data if e["id"] == edit_id), None)
        entry = next((x for i, x in enumerate(edit["entries"], start=1) if (x.get("id") or f"i{i}") == entry_id), None) if edit else None
        if entry is None:
            return None
        place = await self._save(entry, trip, library)
        self.db.save_edits(trip.id, data, row["curated_by"], row["signature"], created_at=row["created_at"])
        return place

    async def _save(self, entry: dict, trip: TripDetail, library) -> Place:
        if entry.get("place_id") and self.db.get_place(entry["place_id"]):
            return self.db.get_place(entry["place_id"])
        g = entry.get("geo") or {}
        if g:
            match = GeoMatch(name=entry["name"], latitude=g["latitude"], longitude=g["longitude"], address=g.get("address"),
                             maps_url=g.get("maps_url"), hours=OpeningHours(**g["hours"]) if g.get("hours") else None,
                             photos=g.get("photos") or [], rating=g.get("rating"), rating_count=g.get("rating_count"),
                             website=g.get("website"), phone=g.get("phone"), place_id=g.get("place_id"),
                             category=entry.get("category") or "other", city=entry.get("city") or trip.city, country=trip.country)
            place, _ = await library.add_match(match)
        else:
            place, _ = await library.add_by_name(entry["name"], None, city=entry.get("city") or trip.city, category=entry.get("category") or "other")
        src = entry.get("source") or {}
        if src.get("name") and not place.summary:
            self.db.update_place(place.id, summary=f"{entry.get('note') or ''} Recommended by {src['name']}.".strip(),
                                 neighborhood=place.neighborhood or entry.get("neighborhood"))
        entry["place_id"] = place.id
        return self.db.get_place(place.id)

    async def bookmark(self, trip: TripDetail, edit_id: str, library) -> Optional[str]:
        """Saves the whole edit to the Library as a folder (its new places become saved places), so it outlives
        the daily refresh. Returns the folder id."""
        row, data = self._stored(trip.id)
        edit = next((e for e in data if e["id"] == edit_id), None)
        if edit is None:
            return None
        if edit.get("folder_id") and self.db.get_folder(edit["folder_id"]):
            return edit["folder_id"]
        title = edit["title"] if _norm(trip.city) in _norm(edit["title"]) else f"{edit['title']} · {trip.city}"
        folder = self.db.create_folder(title[:80])
        for i, entry in enumerate(edit["entries"], start=1):
            if entry.get("place_id") and not self.db.get_place(entry["place_id"]):
                continue
            place = await self._save(entry, trip, library)
            self.db.add_to_folder(folder.id, place.id)
        edit["folder_id"] = folder.id
        self.db.save_edits(trip.id, data, row["curated_by"], row["signature"], created_at=row["created_at"])
        return folder.id

    # ---------- Concierge ----------

    def _context(self, req: ConciergeRequest) -> dict:
        context: dict = {"local_time": req.local_time or datetime.now().strftime("%Y-%m-%dT%H:%M"),
                         "taste_profile": profile_text(self.profile())}
        if req.local_time:
            try:
                context["weekday"] = datetime.fromisoformat(req.local_time[:16]).strftime("%A")
            except ValueError:
                pass
        trip = self.db.get_trip_detail(req.trip_id) if req.trip_id else None
        if trip:
            context["trip"] = {
                "name": trip.name, "city": trip.city, "start_date": trip.start_date, "days": trip.day_count,
                "day_titles": trip.day_titles, "places": [place_brief(p) for p in trip.places],
            }
            if req.latitude is not None and req.longitude is not None:
                here = (req.latitude, req.longitude)
                near = sorted((p for p in trip.places if p.latitude is not None),
                              key=lambda p: _km(here, (p.latitude, p.longitude)))[:6]
                context["nearest_saved_places"] = [{"id": p.id, "km": round(_km(here, (p.latitude, p.longitude)), 1)} for p in near]
        else:
            context["trips"] = [{"id": t.id, "name": t.name, "places": t.place_count, "start_date": t.start_date,
                                 "days": t.day_count} for t in self.db.list_trips()[:20]]
        return context

    async def chat(self, req: ConciergeRequest) -> ConciergeReply:
        if self.claude is None:
            raise ClaudeError("The concierge needs Claude, which isn't configured on the server")
        # Claude expects the conversation to start with the traveler and alternate turns.
        messages: list[dict] = []
        for m in req.messages:
            if not messages and m.role != "user":
                continue
            if messages and messages[-1]["role"] == m.role:
                messages[-1]["content"] += "\n\n" + m.content
            else:
                messages.append({"role": m.role, "content": m.content})
        if not messages or messages[-1]["role"] != "user":
            raise ClaudeError("Ask the concierge something first")
        system = CONCIERGE_SYSTEM + "\n\nContext:\n" + json.dumps(self._context(req), default=str)
        reply = await self.claude._parse(system, [], ConciergeReply, effort="low", messages=messages, feature="concierge")
        return self._clean_reply(reply, req.trip_id)

    def _clean_reply(self, reply: ConciergeReply, trip_id: Optional[str]) -> ConciergeReply:
        trip = self.db.get_trip_detail(trip_id) if trip_id else None
        valid = {p.id for p in trip.places} if trip else set()
        reply.place_ids = list(dict.fromkeys(pid for pid in reply.place_ids if pid in valid))[:6]
        actions = []
        for a in reply.actions if trip else []:
            if a.place_id not in valid:
                continue
            if a.type == "move" and (a.day is None or not 0 <= a.day <= 21):
                continue
            if a.type in ("must_do", "visited") and a.value is None:
                continue
            if a.type == "set_time" and (a.time is None or (a.time and not TIME_RE.match(a.time))):
                continue
            actions.append(a)
        reply.actions = actions[:8]
        return reply

    # ---------- Daily briefing ----------

    def _day_facts(self, trip: TripDetail, day: int, on_date: date) -> dict:
        stops = sorted((p for p in trip.places if p.day_number == day), key=lambda p: p.day_order)
        weekday = on_date.weekday()
        facts = []
        for p in stops:
            ranges = (p.opening_hours.weekly[weekday] if p.opening_hours and p.opening_hours.weekly else None)
            fact = {"name": p.name, "when": _clock(p.start_time) if p.start_time else (p.time_of_day.value if p.time_of_day else None),
                    "reservation": bool(p.start_time), "must_do": p.must_do, "tip": p.tips, "note": p.day_note,
                    "hours_that_day": None if ranges is None else (", ".join(f"{_clock(r.open)}–{_clock(r.close)}" for r in ranges) or "closed"),
                    "problem": _closed_or_conflict(p, weekday)}
            facts.append({k: v for k, v in fact.items() if v})
        return {"city": trip.city, "day": day, "title": trip.day_titles[day - 1] if day <= len(trip.day_titles) else "",
                "weekday": on_date.strftime("%A"), "stops": facts, "taste_profile": profile_text(self.profile())}

    async def briefing(self, trip: TripDetail, day: int, on_date: Optional[date], refresh: bool = False) -> DayBriefing:
        if not 1 <= day <= max(trip.day_count, 1):
            raise ValueError("No such day in this trip")
        if on_date is None:
            on_date = (trip.start_date + timedelta(days=day - 1)) if trip.start_date else date.today()
        stops = sorted((p for p in trip.places if p.day_number == day), key=lambda p: p.day_order)
        signature = _signature([(p.id, p.time_of_day, p.start_time) for p in stops])
        cached = self.db.get_briefing(trip.id, day, on_date.isoformat())
        if cached and not refresh and cached["signature"] == signature:
            return DayBriefing.model_validate(json.loads(cached["data"]))

        facts = self._day_facts(trip, day, on_date)
        text: Optional[BriefingText] = None
        curated_by = "offline"
        if self.claude is not None and stops:
            try:
                text = await self.claude._parse(BRIEFING_SYSTEM, [{"type": "text", "text": json.dumps(facts)}], BriefingText, feature="briefing")
                text.points = [p.strip() for p in text.points if p.strip()][:4]
                curated_by = "claude"
            except ClaudeError as e:
                log.warning("Claude briefing failed, using the offline one: %s", e)
        if text is None or not text.points:
            text = offline_briefing(facts)
            curated_by = "offline"
        briefing = DayBriefing(trip_id=trip.id, day=day, headline=text.headline.strip()[:80], points=text.points,
                               curated_by=curated_by, created_at=datetime.now(timezone.utc))
        self.db.save_briefing(trip.id, day, on_date.isoformat(), signature, briefing.model_dump(mode="json"))
        return briefing


def offline_edits(trip: TripDetail) -> list[dict]:
    """Simple edits by rule when Claude isn't available."""
    places = trip.places

    def entries(items: list[Place]) -> list[dict]:
        return [{"place_id": p.id, "note": (p.summary.split(". ")[0][:140] if p.summary else "")} for p in items[:8]]

    groups = [
        ("must", "The Must-Do Edit", "The places you starred: the ones the trip is built around.",
         [p for p in places if p.must_do], 1),
        ("loved", "Most Recommended", "Places more than one of your saved reels swear by.",
         sorted((p for p in places if p.mention_count > 1), key=lambda p: -p.mention_count), 2),
        ("morning", "Coffee & Pastry", "Slow mornings, good coffee and something sweet.",
         [p for p in places if p.category.value in ("cafe", "dessert")], 2),
        ("table", "The Table", "Where to eat, from quick bites to the reservation worth making.",
         [p for p in places if p.category.value == "food"], 3),
        ("dark", "After Dark", "Drinks, late tables and the places that come alive at night.",
         [p for p in places if p.category.value in ("drinks", "nightlife")], 2),
        ("culture", "Sights & Culture", "Museums, landmarks and the things you came to see.",
         [p for p in places if p.category.value in ("attraction", "activity")], 2),
        ("air", "Fresh Air", "Parks, views and somewhere to walk it all off.",
         [p for p in places if p.category.value == "nature"], 2),
    ]
    return [{"id": gid, "title": title, "dek": dek, "entries": entries(items)}
            for gid, title, dek, items, minimum in groups if len(items) >= minimum]


def offline_briefing(facts: dict) -> BriefingText:
    stops = facts["stops"]
    if not stops:
        return BriefingText(headline="A free day", points=["Nothing is planned yet. Move saved places to this day from their pages."])
    first = stops[0]
    points = [f"Start with {first['name']}" + (f" ({first['when']})" if first.get("when") else "") + "."]
    for s in stops:
        if s.get("problem"):
            points.append(f"{s['name']} is {s['problem']}; check before you go.")
    for s in stops:
        if s.get("reservation"):
            points.append(f"{s['name']} at {s['when']}: confirm the booking.")
    tip = next((s for s in stops if s.get("tip")), None)
    if tip:
        points.append(f"{tip['name']}: {tip['tip']}")
    return BriefingText(headline=f"{len(stops)} stops" + (f" in {facts['title']}" if facts.get("title") else ""), points=points[:4])
