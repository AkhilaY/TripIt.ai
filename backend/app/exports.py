"""Trip exports: an .ics calendar of the itinerary and a .kml file for Google My Maps / Google Earth."""

from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote
from xml.sax.saxutils import escape

from .models import Place, TripDetail

# Start time and length (minutes) used for a time-of-day slot when a stop has no exact time.
SLOTS = {"morning": (9, 0, 120), "lunch": (12, 30, 90), "afternoon": (14, 30, 150), "dinner": (19, 0, 120), "evening": (21, 0, 120)}
CATEGORY_NAMES = {
    "food": "Food", "cafe": "Cafés", "dessert": "Sweets", "drinks": "Drinks", "nightlife": "Nightlife", "attraction": "Sights",
    "activity": "Things to do", "event": "Events", "nature": "Outdoors", "shopping": "Shopping", "stay": "Stay", "other": "Other",
}


class ExportError(ValueError):
    pass


def maps_link(p: Place) -> str:
    if p.maps_url:
        return p.maps_url
    if p.latitude is not None:
        return f"https://www.google.com/maps/search/?api=1&query={p.latitude},{p.longitude}"
    return "https://www.google.com/maps/search/?api=1&query=" + quote(", ".join(x for x in (p.name, p.city) if x))


def _details(p: Place) -> str:
    lines = [p.summary.strip()] if p.summary.strip() else []
    if p.recommended_items:
        lines.append("Try: " + ", ".join(p.recommended_items))
    if p.tips:
        lines.append("Tip: " + p.tips)
    if p.day_note:
        lines.append(p.day_note)
    lines.append(maps_link(p))
    return "\n".join(lines)


def _day_stops(trip: TripDetail, day: int) -> list[Place]:
    return sorted((p for p in trip.places if p.day_number == day), key=lambda p: p.day_order)


def _ics_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n")


def _fold(line: str) -> str:
    """Lines longer than 75 octets continue on the next line after a space (RFC 5545 §3.1)."""
    out, current = [], b""
    for ch in line:
        b = ch.encode()
        if len(current) + len(b) > (75 if not out else 74):
            out.append(current.decode())
            current = b""
        current += b
    out.append(current.decode())
    return "\r\n ".join(out)


def schedule(trip: TripDetail) -> list[tuple[Place, datetime, datetime]]:
    """Clock times for each scheduled stop. Exact times win; otherwise stops share their slot in order."""
    if not trip.start_date:
        raise ExportError("Set a start date for the trip first (Re-plan → Set start date).")
    if not trip.day_count:
        raise ExportError("Plan the trip first, so there's an itinerary to add to your calendar.")
    events = []
    for day in range(1, trip.day_count + 1):
        date = trip.start_date + timedelta(days=day - 1)
        stops = _day_stops(trip, day)
        by_slot: dict[str, list[Place]] = {}
        for p in stops:
            if not p.start_time:
                by_slot.setdefault(p.time_of_day.value if p.time_of_day else "afternoon", []).append(p)
        for p in stops:
            if p.start_time:
                h, m = map(int, p.start_time.split(":"))
                start = datetime(date.year, date.month, date.day, h, m)
                events.append((p, start, start + timedelta(minutes=90)))
                continue
            slot = p.time_of_day.value if p.time_of_day else "afternoon"
            h, m, length = SLOTS[slot]
            group = by_slot[slot]
            share = max(30, length // len(group))
            start = datetime(date.year, date.month, date.day, h, m) + timedelta(minutes=share * group.index(p))
            events.append((p, start, start + timedelta(minutes=share)))
    return events


def ics(trip: TripDetail, now: Optional[datetime] = None) -> str:
    """Times are "floating" (no time zone), so they show at local time wherever the phone is: in the city."""
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//TripIt//Itinerary//EN", "CALSCALE:GREGORIAN",
             f"X-WR-CALNAME:{_ics_text(trip.name)}"]
    for p, start, end in schedule(trip):
        location = p.address or ", ".join(x for x in (p.resolved_name or p.name, p.city) if x)
        lines += [
            "BEGIN:VEVENT",
            f"UID:{p.id}-{trip.id}@tripit",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{start:%Y%m%dT%H%M%S}",
            f"DTEND:{end:%Y%m%dT%H%M%S}",
            f"SUMMARY:{_ics_text(p.name)}",
            f"LOCATION:{_ics_text(location)}",
            f"DESCRIPTION:{_ics_text(_details(p))}",
            f"URL:{maps_link(p)}",
        ]
        if p.latitude is not None:
            lines.append(f"GEO:{p.latitude:.6f};{p.longitude:.6f}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


def _placemark(p: Place) -> str:
    description = escape(_details(p)).replace("\n", "<br>")
    return (f"<Placemark><name>{escape(p.name)}</name><description>{description}</description>"
            f"<Point><coordinates>{p.longitude:.6f},{p.latitude:.6f},0</coordinates></Point></Placemark>")


def kml(trip: TripDetail) -> str:
    """One folder per day (or per category when there's no plan). Places without a pin are left out."""
    mapped = [p for p in trip.places if p.latitude is not None and p.longitude is not None]
    folders: list[tuple[str, list[Place]]] = []
    if trip.day_count:
        for day in range(1, trip.day_count + 1):
            title = trip.day_titles[day - 1] if day <= len(trip.day_titles) else ""
            folders.append((f"Day {day}" + (f" · {title}" if title and title != f"Day {day}" else ""),
                            [p for p in _day_stops(trip, day) if p in mapped]))
        folders.append(("Not scheduled", [p for p in mapped if p.day_number is None]))
    else:
        for category, name in CATEGORY_NAMES.items():
            folders.append((name, [p for p in mapped if p.category.value == category]))
    body = "".join(
        f"<Folder><name>{escape(name)}</name>{''.join(_placemark(p) for p in places)}</Folder>"
        for name, places in folders if places
    )
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
            f"<name>{escape(trip.name)}</name>{body}</Document></kml>\n")
