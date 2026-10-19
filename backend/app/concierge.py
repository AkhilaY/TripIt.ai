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

from .db import Database
from .hours import summary as hours_summary
from .llm import ClaudeError, ClaudeService
from .models import (
    BriefingText,
    ConciergeReply,
    ConciergeRequest,
    DayBriefing,
    EditsResult,
    Place,
    TasteProfile,
    TripDetail,
    TripEdit,
    TripEdits,
)

log = logging.getLogger(__name__)

EDITOR_VOICE = ("Write like a luxury travel editor (think Vogue or Condé Nast Traveller): assured, warm, specific, never "
                "gushing. No emoji, no exclamation marks.")

EDITS_SYSTEM = f"""You curate a traveler's saved places into editorial lists ("edits") for one city.

- Make 3 to 6 edits, each with 3 to 8 places, chosen from the saved places only (use their exact ids).
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
    def __init__(self, db: Database, claude: Optional[ClaudeService]):
        self.db = db
        self.claude = claude

    # ---------- Taste profile ----------

    def profile(self) -> TasteProfile:
        return TasteProfile.model_validate(self.db.get_setting("taste_profile") or {})

    def save_profile(self, profile: TasteProfile) -> TasteProfile:
        profile.updated_at = datetime.now(timezone.utc)
        self.db.set_setting("taste_profile", profile.model_dump(mode="json"))
        return profile

    # ---------- Edits ----------

    @staticmethod
    def _places_signature(trip: TripDetail) -> str:
        return _signature(sorted(p.id for p in trip.places))

    def edits(self, trip: TripDetail) -> TripEdits:
        row = self.db.get_edits(trip.id)
        if not row:
            return TripEdits(trip_id=trip.id, trip_name=trip.name)
        by_id = {p.id: p for p in trip.places}
        edits = []
        for e in json.loads(row["data"]):
            entries = [x for x in e["entries"] if x["place_id"] in by_id]
            if len(entries) >= 2 or (entries and e.get("id") == "must"):
                # Cover: the first entry with a real photo, else the first with any photo.
                photos = [by_id[x["place_id"]].photos[0] for x in entries if by_id[x["place_id"]].photos]
                cover = next((ph for ph in photos if ph.source != "reel"), photos[0] if photos else None)
                edits.append(TripEdit(**{**e, "entries": entries, "cover_photo": cover}))
        return TripEdits(trip_id=trip.id, trip_name=trip.name, edits=edits, curated_by=row["curated_by"],
                         created_at=row["created_at"], stale=row["signature"] != self._places_signature(trip))

    async def curate(self, trip: TripDetail) -> TripEdits:
        edits: list[dict] = []
        curated_by = "offline"
        if self.claude is not None:
            payload = {"city": trip.city, "taste_profile": profile_text(self.profile()),
                       "places": [place_brief(p) for p in trip.places]}
            try:
                result = await self.claude._parse(
                    EDITS_SYSTEM, [{"type": "text", "text": "Curate edits from these saved places:\n\n" + json.dumps(payload)}],
                    EditsResult)
                edits = self._clean(result, trip)
                curated_by = "claude" if edits else curated_by
            except ClaudeError as e:
                log.warning("Claude curation failed, using offline edits: %s", e)
        if not edits:
            edits = offline_edits(trip)
        self.db.save_edits(trip.id, edits, curated_by, self._places_signature(trip))
        return self.edits(trip)

    @staticmethod
    def _clean(result: EditsResult, trip: TripDetail) -> list[dict]:
        valid = {p.id for p in trip.places}
        out = []
        for edit in result.edits[:6]:
            seen, entries = set(), []
            for entry in edit.entries:
                if entry.place_id in valid and entry.place_id not in seen:
                    seen.add(entry.place_id)
                    entries.append({"place_id": entry.place_id, "note": entry.note.strip()[:200]})
            if len(entries) >= 2:
                out.append({"id": f"e{len(out) + 1}", "title": edit.title.strip()[:80], "dek": edit.dek.strip()[:240],
                            "entries": entries[:8]})
        return out

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
        reply = await self.claude._parse(system, [], ConciergeReply, effort="low", messages=messages)
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
                text = await self.claude._parse(BRIEFING_SYSTEM, [{"type": "text", "text": json.dumps(facts)}], BriefingText)
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
