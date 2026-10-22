"""The calendar: saved events, bookings, planned stops and trips on their dates, plus exports.

Each item can go to Google Calendar (a prefilled link) or any calendar app (a signed .ics link). The whole calendar
can also be subscribed to through a private feed URL, so new events keep arriving; Google refreshes subscribed
calendars every few hours, Apple Calendar on the interval it is set to.
"""

import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote, urlencode

from .db import Database
from .exports import SLOTS, _fold, _ics_text, maps_link
from .models import CalendarFeed, CalendarItem, CalendarResult, Place, TripDetail
from .photos import PhotoStore

BOOKING_LABEL = {"flight": "Flight", "hotel": "Stay", "reservation": "Table", "car": "Car", "other": "Booking"}
FEED_SETTING = "calendar_feed_token"


def _hm(value: Optional[str]) -> Optional[str]:
    return value[11:16] if value and len(value) >= 16 else None


def _plus(t: str, minutes: int) -> str:
    h, m = map(int, t.split(":"))
    total = min(h * 60 + m + minutes, 23 * 60 + 59)
    return f"{total // 60:02d}:{total % 60:02d}"


class CalendarService:
    def __init__(self, db: Database, photos: PhotoStore):
        self.db = db
        self.photos = photos

    # ---------- Items ----------

    def _event(self, p: Place, trip_name: str) -> CalendarItem:
        where = p.venue or p.neighborhood or p.address or p.city
        parts = [x for x in (where, trip_name) if x]
        subtitle = " · ".join(dict.fromkeys(parts)) or None  # "Soho · New York", never "New York · New York"
        return CalendarItem(id=f"event:{p.id}", kind="event", title=p.name, date=p.event_date, end_date=p.event_end_date,
                            time=p.start_time if p.event_date else None, subtitle=subtitle,
                            category="event", place_id=p.id, trip_id=p.trip_id)

    def items(self) -> tuple[list[CalendarItem], list[CalendarItem]]:
        dated: list[CalendarItem] = []
        undated: list[CalendarItem] = []
        for p in self.db.list_places(saved_only=True):  # events you saved, in a trip or not
            if p.category.value == "event":
                (dated if p.event_date else undated).append(self._event(p, p.city))
        for trip in self.db.list_trips():
            detail: Optional[TripDetail] = self.db.get_trip_detail(trip.id)
            if detail is None:
                continue
            if detail.start_date and detail.day_count:
                last = detail.start_date + timedelta(days=detail.day_count - 1)
                dated.append(CalendarItem(id=f"trip:{detail.id}", kind="trip", title=detail.name, date=detail.start_date,
                                          end_date=last if last > detail.start_date else None, trip_id=detail.id,
                                          subtitle=f"{detail.day_count}-day trip"))
                for p in detail.places:
                    if not p.day_number or (p.category.value == "event" and p.event_date):
                        continue
                    dated.append(CalendarItem(
                        id=f"stop:{p.id}", kind="stop", title=p.name, date=detail.start_date + timedelta(days=p.day_number - 1),
                        time=p.start_time, part_of_day=(p.time_of_day.value if p.time_of_day else "afternoon") if not p.start_time else None,
                        subtitle=p.neighborhood or None,
                        category=p.category.value, place_id=p.id, trip_id=detail.id,
                    ))
        for b in self.db.list_all_bookings():
            if not b.start_at:
                continue
            start = date.fromisoformat(b.start_at[:10])
            end = date.fromisoformat(b.end_at[:10]) if b.end_at else None
            route = f"{b.origin} → {b.destination}" if b.kind == "flight" and b.origin and b.destination else None
            dated.append(CalendarItem(
                id=f"booking:{b.id}", kind="booking", title=f"{b.title}" + (f" {route}" if route else ""),
                date=start, end_date=end if end and end > start and b.kind in ("hotel", "car") else None,
                time=_hm(b.start_at), end_time=_hm(b.end_at) if end == start else None,
                subtitle=" · ".join(x for x in (BOOKING_LABEL.get(b.kind, "Booking"), f"Ref {b.confirmation}" if b.confirmation else None, b.trip_name) if x),
                category=b.kind, booking_id=b.id, trip_id=b.trip_id,
            ))
        dated.sort(key=lambda i: (i.date, i.kind != "trip", i.time or self._slot_time(i) or "99", i.title))
        return dated, undated

    def result(self, base_url: str) -> CalendarResult:
        dated, undated = self.items()
        for item in dated:
            if item.kind != "trip":
                item.google_url = self.google_url(item)
                item.ics_url = self.ics_url(item.id)
        return CalendarResult(items=dated, undated=undated, feed=self.feed(base_url))

    # ---------- Exports ----------

    def ics_url(self, item_id: str) -> str:
        return f"/v1/calendar/item.ics?id={quote(item_id, safe='')}&sig={self.photos.signature('ics', 0, item_id)}"

    def check_ics(self, item_id: str, sig: str) -> bool:
        return self.photos.check("ics", 0, item_id, sig)

    @staticmethod
    def _slot_time(item: CalendarItem) -> Optional[str]:
        if not item.part_of_day:
            return None
        h, m, _ = SLOTS[item.part_of_day]
        return f"{h:02d}:{m:02d}"

    @classmethod
    def _span(cls, item: CalendarItem) -> tuple[bool, datetime, datetime]:
        """(all day, start, end). Times are floating (local wherever the phone is). All-day ends are exclusive."""
        time = item.time or cls._slot_time(item)
        if time:
            h, m = map(int, time.split(":"))
            start = datetime(item.date.year, item.date.month, item.date.day, h, m)
            end_time = item.end_time or _plus(time, 120 if item.kind == "event" else 90)
            eh, em = map(int, end_time.split(":"))
            last = item.end_date or item.date
            end = datetime(last.year, last.month, last.day, eh, em)
            return False, start, max(end, start + timedelta(minutes=30))
        last = item.end_date or item.date
        return True, datetime(item.date.year, item.date.month, item.date.day), datetime(last.year, last.month, last.day) + timedelta(days=1)

    def google_url(self, item: CalendarItem) -> str:
        all_day, start, end = self._span(item)
        fmt = "%Y%m%d" if all_day else "%Y%m%dT%H%M%S"
        params = {"action": "TEMPLATE", "text": item.title, "dates": f"{start:{fmt}}/{end:{fmt}}"}
        place = self.db.get_place(item.place_id) if item.place_id else None
        if place:
            params["location"] = place.venue or place.address or ", ".join(x for x in (place.resolved_name or place.name, place.city) if x)
            params["details"] = "\n".join(x for x in (place.summary, maps_link(place)) if x)
        elif item.subtitle:
            params["details"] = item.subtitle
        return "https://calendar.google.com/calendar/render?" + urlencode(params)

    def ics(self, items: list[CalendarItem], name: str = "TripIt") -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//TripIt//Calendar//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
                 f"X-WR-CALNAME:{_ics_text(name)}", "REFRESH-INTERVAL;VALUE=DURATION:PT4H", "X-PUBLISHED-TTL:PT4H"]
        for item in items:
            if item.kind == "trip" or item.date is None:
                continue
            all_day, start, end = self._span(item)
            place = self.db.get_place(item.place_id) if item.place_id else None
            lines += ["BEGIN:VEVENT", f"UID:{item.id.replace(':', '-')}@tripit", f"DTSTAMP:{stamp}"]
            if all_day:
                lines += [f"DTSTART;VALUE=DATE:{start:%Y%m%d}", f"DTEND;VALUE=DATE:{end:%Y%m%d}"]
            else:
                lines += [f"DTSTART:{start:%Y%m%dT%H%M%S}", f"DTEND:{end:%Y%m%dT%H%M%S}"]
            lines.append(f"SUMMARY:{_ics_text(item.title)}")
            if place:
                location = place.venue or place.address or ", ".join(x for x in (place.resolved_name or place.name, place.city) if x)
                lines += [f"LOCATION:{_ics_text(location)}", f"DESCRIPTION:{_ics_text(chr(10).join(x for x in (place.summary, maps_link(place)) if x))}",
                          f"URL:{maps_link(place)}"]
            elif item.subtitle:
                lines.append(f"DESCRIPTION:{_ics_text(item.subtitle)}")
            lines.append("END:VEVENT")
        lines.append("END:VCALENDAR")
        return "\r\n".join(_fold(line) for line in lines) + "\r\n"

    # ---------- Subscription feed ----------

    def feed(self, base_url: str) -> Optional[CalendarFeed]:
        token = self.db.get_setting(FEED_SETTING)
        if not token:
            return None
        url = f"{base_url.rstrip('/')}/cal/{token}.ics"
        webcal = "webcal://" + url.split("://", 1)[1]
        return CalendarFeed(url=url, webcal_url=webcal, google_url="https://calendar.google.com/calendar/r?cid=" + quote(webcal, safe=""))

    def start_feed(self, base_url: str) -> CalendarFeed:
        """A new private feed link; any earlier link stops working."""
        self.db.set_setting(FEED_SETTING, secrets.token_urlsafe(24))
        return self.feed(base_url)

    def stop_feed(self) -> None:
        self.db.set_setting(FEED_SETTING, None)

    def feed_token_ok(self, token: str) -> bool:
        current = self.db.get_setting(FEED_SETTING)
        return bool(current) and secrets.compare_digest(current, token)
