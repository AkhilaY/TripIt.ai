"""The whole trip as a document: the day-by-day plan with its flights, stays and tables.

Three shapes, all from one Doc:
- pdf(doc, "designed"): a cover, the bookings at a glance, then a page per day with photos and notes.
- pdf(doc, "printable"): the same in two or three dense, ink-friendly pages.
- markdown(doc) / clip_html(doc): text that pastes into Apple Notes (rich text) or Notion (headings, to-dos).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from html import escape
from pathlib import Path
from typing import Callable, Optional

from .exports import CATEGORY_NAMES
from .models import Booking, TripDetail

FONTS = Path(__file__).parent / "static" / "fonts"
KIND_LABELS = {"flight": "Flights", "hotel": "Stays", "reservation": "Tables", "tour": "Tours", "car": "Cars", "other": "Other bookings"}
KIND_ONE = {"flight": "Flight", "hotel": "Stay", "reservation": "Table", "tour": "Tour", "car": "Car", "other": "Booking"}


@dataclass
class Stop:
    name: str
    kind: str = ""  # "Food", "Sights"…
    time: Optional[str] = None  # "09:30"
    estimated: bool = True
    area: Optional[str] = None  # neighbourhood, or the address
    note: Optional[str] = None  # the person's own note, else what the post said
    photo: Optional[str] = None  # a URL or file path the PDF can load
    booked: Optional[str] = None  # "Table for 2 at 19:30 · Ref ZK4471"


@dataclass
class Item:
    """A booking: a flight, stay, table, tour or car."""
    kind: str
    title: str
    when: str  # "Fri 11 Dec, 17:40 → Sat 12 Dec, 08:15"
    lines: list[str] = field(default_factory=list)  # route, address, party size, notes
    confirmation: Optional[str] = None
    day: Optional[int] = None  # the trip day it starts on
    time: Optional[str] = None


@dataclass
class Day:
    number: int
    date: Optional[date]
    title: str
    city: str = ""
    stops: list[Stop] = field(default_factory=list)
    bookings: list[Item] = field(default_factory=list)  # flights, check-ins and tours that start this day

    @property
    def label(self) -> str:
        return f"Day {self.number}" + (f" · {self.date:%a} {self.date.day} {self.date:%b}" if self.date else "")


@dataclass
class Doc:
    name: str
    route: list[str]
    start: Optional[date]
    end: Optional[date]
    days: list[Day]
    bookings: list[Item]
    cover: Optional[str] = None
    cover_credit: Optional[str] = None
    packing: list[tuple[str, list[str]]] = field(default_factory=list)
    size: str = "Letter"  # or "A4"

    @property
    def dates(self) -> str:
        if not self.start:
            return f"{len(self.days)} days"
        end = self.end or self.start
        if self.start.year == end.year and self.start.month == end.month:
            return f"{self.start:%a} {self.start.day} – {end:%a} {end.day} {end:%B %Y}"
        return f"{self.start:%a} {self.start.day} {self.start:%b} – {end:%a} {end.day} {end:%b %Y}"

    @property
    def place_count(self) -> int:
        return sum(len(d.stops) for d in self.days)

    def count(self, kind: str) -> int:
        return sum(1 for b in self.bookings if b.kind == kind)


# ---------- From a trip ----------

def _day_of(value: Optional[str]) -> Optional[date]:
    try:
        return date.fromisoformat(value[:10]) if value else None
    except ValueError:
        return None


def _when(b: Booking) -> tuple[str, Optional[str]]:
    def part(v: Optional[str]) -> str:
        d = _day_of(v)
        if not d:
            return ""
        return f"{d:%a} {d.day} {d:%b}" + (f", {v[11:16]}" if v and len(v) > 10 else "")
    start, end = part(b.start_at), part(b.end_at)
    time = b.start_at[11:16] if b.start_at and len(b.start_at) > 10 else None
    if b.kind == "hotel" and start and end:
        return f"{start.split(',')[0]} – {end.split(',')[0]}", time
    return (f"{start} → {end}" if start and end and start != end else start or end or "Date to be set"), time


def item(b: Booking, start: Optional[date]) -> Item:
    when, time = _when(b)
    lines = []
    if b.kind == "flight" and (b.origin or b.destination):
        lines.append(f"{b.origin or '?'} → {b.destination or '?'}")
    elif b.kind == "car" and (b.origin or b.destination):
        lines.append(f"Pick up {b.origin or '?'} · drop off {b.destination or b.origin or '?'}")
    if b.kind == "hotel":
        s, e = _day_of(b.start_at), _day_of(b.end_at)
        if s and e and e > s:
            lines.append(f"{(e - s).days} night{'s' if (e - s).days != 1 else ''}"
                         + (f", check in {b.start_at[11:16]}" if b.start_at and len(b.start_at) > 10 else ""))
    if b.address:
        lines.append(b.address)
    if b.party_size:
        lines.append(f"{b.party_size} {'person' if b.party_size == 1 else 'people'}")
    if b.notes:
        lines.append(b.notes.strip())
    d = _day_of(b.start_at)
    day = (d - start).days + 1 if d and start else None
    return Item(b.kind, b.title, when, lines, b.confirmation, day, time)


def from_trip(trip: TripDetail, photo: Callable[[object], Optional[str]] = lambda p: None,
              cover: Optional[str] = None, cover_credit: Optional[str] = None, size: str = "Letter") -> Doc:
    """photo(place) gives a loadable picture for a stop, or None."""
    times = {(s.place_id, s.day): s for s in trip.schedule}
    start = trip.start_date
    bookings = sorted((item(b, start) for b in trip.bookings), key=lambda i: (i.day or 999, i.time or "99"))
    tables = {re.sub(r"\W+", "", b.title.casefold()): b for b in trip.bookings if b.kind == "reservation"}
    days = []
    for n in range(1, (trip.day_count or 0) + 1):
        stops = []
        for p in trip.day_places(n):
            s = times.get((p.id, n))
            table = tables.get(re.sub(r"\W+", "", (p.resolved_name or p.name).casefold()))
            booked = None
            if table:
                booked = "Table booked" + (f" for {table.party_size}" if table.party_size else "") \
                         + (f" at {table.start_at[11:16]}" if table.start_at and len(table.start_at) > 10 else "") \
                         + (f" · Ref {table.confirmation}" if table.confirmation else "")
            note = (p.user_notes or p.day_note or p.summary or "").strip() or None
            stops.append(Stop(
                name=p.resolved_name or p.name, kind=CATEGORY_NAMES.get(p.category.value, ""),
                time=p.start_time or (s.time if s else None), estimated=not p.start_time and (s.estimated if s else True),
                area=p.neighborhood or p.address, note=note, photo=photo(p), booked=booked))
        city = next((r.city for r in (trip.stops or []) if r.start_day <= n <= r.end_day), trip.city)
        title = trip.day_titles[n - 1] if n - 1 < len(trip.day_titles) else ""
        days.append(Day(n, start + timedelta(days=n - 1) if start else None, title, city, stops,
                        [b for b in bookings if b.day == n and b.kind != "reservation"]))
    route = [r.city for r in trip.stops] if trip.stops else [trip.city]
    end = start + timedelta(days=max(0, trip.day_count - 1)) if start and trip.day_count else start
    return Doc(trip.name, route, start, end, days, bookings, cover, cover_credit, size=size)


# ---------- PDF ----------

def _fonts() -> str:
    faces = [("Light", 300), ("Regular", 400), ("Medium", 500)]
    return "".join(f"@font-face{{font-family:Jost;font-weight:{w};src:url('{(FONTS / f'Jost-{n}.ttf').as_uri()}')}}" for n, w in faces)


def _t(s: Optional[str]) -> str:
    return escape(s or "")


def _stats(doc: Doc) -> list[str]:
    out = [f"{len(doc.days)} days", f"{doc.place_count} places"]
    for kind in ("flight", "hotel", "reservation", "tour"):
        if n := doc.count(kind):
            out.append(f"{n} {KIND_LABELS[kind].lower() if n > 1 else KIND_ONE[kind].lower()}")
    return out


DESIGNED_CSS = """
@page { size: %(size)s; margin: 0.75in 0.75in 0.8in;
  @bottom-left { content: "%(name)s"; font: 300 7.5pt Jost; color: #9A948F; letter-spacing: .06em }
  @bottom-right { content: counter(page); font: 300 7.5pt Jost; color: #9A948F } }
@page cover { margin: 0; @bottom-left { content: none } @bottom-right { content: none } }
* { box-sizing: border-box }
body { font: 300 10pt/1.45 Jost; color: #19110B; margin: 0 }
.cover { page: cover; height: %(height)s; position: relative; background: #F4F0EA; break-after: page }
.cover .photo { height: 62%%; background-size: cover; background-position: center }
.cover .plain { height: 62%%; background: #19110B; color: #F4F0EA; padding: 0.9in 0.85in; }
.cover .plain .mark { font: 300 9pt Jost; letter-spacing: .3em; text-transform: uppercase; opacity: .7 }
.cover .words { padding: 0.55in 0.85in 0 }
.eyebrow { font: 400 7.5pt Jost; letter-spacing: .22em; text-transform: uppercase; color: #6F6A66 }
.cover h1 { font: 300 44pt/1.05 Jost; margin: 10pt 0 10pt; letter-spacing: -.01em }
.cover .route { font: 300 13pt Jost; color: #3B342F }
.cover .stats { margin-top: 18pt; font: 400 8.5pt Jost; letter-spacing: .08em; text-transform: uppercase; color: #6F6A66 }
.cover .stats span + span:before { content: "·"; margin: 0 7pt; color: #BDB6AF }
.cover .credit { position: absolute; bottom: .45in; left: .85in; right: .85in; font: 300 7pt Jost; color: #9A948F }
.cover .credit .made { float: right; letter-spacing: .12em; text-transform: uppercase }
h2 { font: 300 26pt/1.1 Jost; margin: 4pt 0 2pt; letter-spacing: -.005em }
.sub { color: #6F6A66; font-size: 10.5pt; margin-bottom: 16pt }
h3 { font: 400 8pt Jost; letter-spacing: .2em; text-transform: uppercase; color: #6F6A66; margin: 20pt 0 6pt;
     padding-bottom: 6pt; border-bottom: .6pt solid #E6E3DF }
.route-strip { display: flex; gap: 0; margin: 6pt 0 4pt }
.route-strip div { flex: 1; border-top: 2pt solid #19110B; padding-top: 6pt; margin-right: 8pt }
.route-strip b { font: 400 11pt Jost; display: block }
.route-strip span { color: #6F6A66; font-size: 8.5pt }
.card { border: .6pt solid #E6E3DF; border-radius: 9pt; padding: 10pt 12pt; margin-bottom: 7pt; break-inside: avoid }
.card .top { display: flex; justify-content: space-between; align-items: baseline }
.card .title { font: 400 11pt Jost }
.card .when { color: #3B342F; margin-top: 1pt }
.card .line { color: #6F6A66; font-size: 9pt }
.ref { font: 400 7.5pt Jost; letter-spacing: .1em; text-transform: uppercase; color: #6F6A66; white-space: nowrap }
.ref b { font-weight: 500; color: #19110B; letter-spacing: .06em }
.day { break-before: page }
.stop { display: flex; padding: 11pt 0; border-bottom: .6pt solid #E6E3DF; break-inside: avoid }
.stop .time { width: 46pt; flex: none; font: 400 9pt Jost; padding-top: 2pt }
.stop .time i { display: block; font: 300 7pt Jost; font-style: normal; color: #9A948F; letter-spacing: .04em }
.stop .body { flex: 1 }
.stop .name { font: 400 12pt Jost }
.stop .meta { color: #6F6A66; font-size: 8.5pt; margin-top: 1pt }
.stop .note { margin-top: 5pt; font-size: 9.5pt; color: #3B342F }
.stop .booked { display: inline-block; margin-top: 6pt; padding: 2pt 7pt; border-radius: 99pt; background: #EEF3EF;
                color: #2F6B47; font: 400 7.5pt Jost; letter-spacing: .06em; text-transform: uppercase }
.stop .pic { width: 92pt; height: 70pt; flex: none; margin-left: 14pt; border-radius: 7pt; background-size: cover;
             background-position: center }
.travel { margin: 8pt 0 2pt; padding: 8pt 12pt; border-radius: 9pt; background: #F4F0EA; font-size: 9pt }
.travel b { font-weight: 400 }
.pack { columns: 2; column-gap: 24pt }
.pack div { break-inside: avoid; margin-bottom: 10pt }
.pack b { font: 400 9pt Jost; display: block; margin-bottom: 3pt }
.pack span { display: block; font-size: 9pt; color: #3B342F }
.pack span:before { content: ""; display: inline-block; width: 7pt; height: 7pt; border: .7pt solid #9A948F;
                    border-radius: 2pt; margin-right: 6pt; vertical-align: -1pt }
"""


def _card(b: Item) -> str:
    ref = f'<div class="ref">Ref <b>{_t(b.confirmation)}</b></div>' if b.confirmation else ""
    lines = "".join(f'<div class="line">{_t(x)}</div>' for x in b.lines)
    return f'<div class="card"><div class="top"><div class="title">{_t(b.title)}</div>{ref}</div>' \
           f'<div class="when">{_t(b.when)}</div>{lines}</div>'


def _designed(doc: Doc) -> str:
    stats = "".join(f"<span>{_t(s)}</span>" for s in _stats(doc))
    top = f'<div class="photo" style="background-image:url(\'{_t(doc.cover)}\')"></div>' if doc.cover \
        else '<div class="plain"><div class="mark">The Travel Edit</div></div>'
    credit = f"Cover photo: {_t(doc.cover_credit)}" if doc.cover_credit else ""
    out = [f'<section class="cover">{top}<div class="words"><div class="eyebrow">{_t(doc.dates)}</div>'
           f'<h1>{_t(doc.name)}</h1><div class="route">{" → ".join(_t(c) for c in doc.route)}</div>'
           f'<div class="stats">{stats}</div></div>'
           f'<div class="credit">{credit}<span class="made">Made with The Travel Edit</span></div></section>']

    # At a glance: the route, then every booking by kind.
    glance = ['<section><div class="eyebrow">At a glance</div><h2>The trip</h2>'
              f'<div class="sub">{_t(doc.dates)}</div>']
    legs = _legs(doc)
    if len(legs) > 1:
        glance.append('<div class="route-strip">' + "".join(
            f'<div><b>{_t(city)}</b><span>{_t(span)}</span></div>' for city, span in legs) + "</div>")
    for kind in ("flight", "hotel", "reservation", "tour", "car", "other"):
        items = [b for b in doc.bookings if b.kind == kind]
        if items:
            glance.append(f"<h3>{KIND_LABELS[kind]}</h3>" + "".join(_card(b) for b in items))
    if not doc.bookings:
        glance.append('<h3>Bookings</h3><div class="sub">No flights, stays or tables added yet.</div>')
    out.append("".join(glance) + "</section>")

    last_city = None
    for d in doc.days:
        head = f'<section class="day"><div class="eyebrow">{_t(d.label)}</div><h2>{_t(d.title or d.city)}</h2>' \
               f'<div class="sub">{_t(d.city)} · {len(d.stops)} {"place" if len(d.stops) == 1 else "places"}</div>'
        rows = []
        if last_city and d.city != last_city:
            rows.append(f'<div class="travel"><b>{_t(last_city)} → {_t(d.city)}</b></div>')
        last_city = d.city
        for b in d.bookings:
            rows.append(f'<div class="travel"><b>{_t(KIND_ONE[b.kind])} · {_t(b.title)}</b> &nbsp;{_t(b.when)}'
                        + (f' &nbsp;<span class="ref">Ref <b>{_t(b.confirmation)}</b></span>' if b.confirmation else "")
                        + "</div>")
        for s in d.stops:
            time = f'{_t(s.time)}<i>{"about" if s.estimated else "booked"}</i>' if s.time else ""
            meta = " · ".join(_t(x) for x in (s.kind, s.area) if x)
            note = f'<div class="note">{_t(s.note)}</div>' if s.note else ""
            booked = f'<div class="booked">{_t(s.booked)}</div>' if s.booked else ""
            pic = f'<div class="pic" style="background-image:url(\'{_t(s.photo)}\')"></div>' if s.photo else ""
            rows.append(f'<div class="stop"><div class="time">{time}</div><div class="body"><div class="name">{_t(s.name)}'
                        f'</div><div class="meta">{meta}</div>{note}{booked}</div>{pic}</div>')
        if not d.stops:
            rows.append('<div class="sub">A free day.</div>')
        out.append(head + "".join(rows) + "</section>")

    if doc.packing:
        out.append('<section class="day"><div class="eyebrow">Before you go</div><h2>Packing list</h2><div class="pack">'
                   + "".join(f"<div><b>{_t(c)}</b>" + "".join(f"<span>{_t(i)}</span>" for i in items) + "</div>"
                             for c, items in doc.packing) + "</div></section>")
    return "".join(out)


PRINTABLE_CSS = """
@page { size: %(size)s; margin: 0.55in 0.6in 0.6in;
  @bottom-left { content: "%(name)s · Made with The Travel Edit"; font: 300 7pt Jost; color: #777 }
  @bottom-right { content: "Page " counter(page) " of " counter(pages); font: 300 7pt Jost; color: #777 } }
body { font: 400 8.6pt/1.35 Jost; color: #000; margin: 0 }
h1 { font: 400 20pt Jost; margin: 0 }
.top { display: flex; justify-content: space-between; align-items: baseline; border-bottom: 1.2pt solid #000; padding-bottom: 5pt }
.top .r { text-align: right; color: #333 }
h2 { font: 500 8pt Jost; letter-spacing: .16em; text-transform: uppercase; margin: 13pt 0 4pt }
table { width: 100%%; border-collapse: collapse }
td, th { text-align: left; vertical-align: top; padding: 3.5pt 6pt 3.5pt 0; border-bottom: .5pt solid #BBB }
th { font: 500 6.8pt Jost; letter-spacing: .12em; text-transform: uppercase; color: #555; border-bottom: .8pt solid #000 }
tr { break-inside: avoid }
td.t { width: 40pt; white-space: nowrap } td.k { width: 48pt; color: #444 } td.ref { width: 70pt; font-weight: 500 }
td .n { font-weight: 500 } td .s { color: #444 }
.day { break-inside: avoid; margin-top: 9pt }
.day .h { display: flex; justify-content: space-between; border-bottom: .8pt solid #000; padding-bottom: 2pt; margin-bottom: 1pt }
.day .h b { font-weight: 500; font-size: 9.5pt } .day .h span { color: #444 }
.box { display: inline-block; width: 6.5pt; height: 6.5pt; border: .6pt solid #000; margin-right: 4pt; vertical-align: -.5pt }
"""


def _printable(doc: Doc) -> str:
    out = [f'<div class="top"><h1>{_t(doc.name)}</h1><div class="r">{_t(doc.dates)}<br>'
           f'{" → ".join(_t(c) for c in doc.route)} · {" · ".join(_t(s) for s in _stats(doc))}</div></div>']
    if doc.bookings:
        out.append('<h2>Bookings</h2><table><tr><th>Type</th><th>What</th><th>When</th><th>Details</th><th>Ref</th></tr>')
        for b in doc.bookings:
            out.append(f'<tr><td class="k">{_t(KIND_ONE[b.kind])}</td><td><span class="n">{_t(b.title)}</span></td>'
                       f'<td>{_t(b.when)}</td><td class="s">{_t(" · ".join(b.lines))}</td><td class="ref">{_t(b.confirmation)}</td></tr>')
        out.append("</table>")
    out.append("<h2>Itinerary</h2>")
    for d in doc.days:
        rows = [f'<tr><td class="t"><span class="box"></span>{_t(b.time or "")}</td><td class="k">{_t(KIND_ONE[b.kind])}</td>'
                f'<td><span class="n">{_t(b.title)}</span> <span class="s">{_t(b.when)}</span></td><td class="ref">{_t(b.confirmation)}</td></tr>'
                for b in d.bookings]
        for s in d.stops:
            extra = " · ".join(x for x in (s.area, s.booked, s.note) if x)
            rows.append(f'<tr><td class="t"><span class="box"></span>{_t(("~" if s.estimated else "") + s.time if s.time else "")}</td>'
                        f'<td class="k">{_t(s.kind)}</td><td><span class="n">{_t(s.name)}</span>'
                        f'{"<br><span class=s>" + _t(_short(extra, 150)) + "</span>" if extra else ""}</td><td></td></tr>')
        title = " · ".join(x for x in (d.title, d.city) if x)
        out.append(f'<div class="day"><div class="h"><b>{_t(d.label)}</b><span>{_t(title)}</span></div>'
                   f'<table>{"".join(rows) or "<tr><td>A free day.</td></tr>"}</table></div>')
    if doc.packing:
        out.append("<h2>Packing</h2><table>" + "".join(
            f'<tr><td class="k">{_t(c)}</td><td>' + "&nbsp; ".join(f'<span class="box"></span>{_t(i)}' for i in items) + "</td></tr>"
            for c, items in doc.packing) + "</table>")
    return "".join(out)


def _short(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1].rsplit(" ", 1)[0] + "…"


def _legs(doc: Doc) -> list[tuple[str, str]]:
    legs: list[tuple[str, list[Day]]] = []
    for d in doc.days:
        if legs and legs[-1][0] == d.city:
            legs[-1][1].append(d)
        else:
            legs.append((d.city, [d]))
    out = []
    for city, days in legs:
        a, b = days[0], days[-1]
        if a.date:
            span = f"{a.date:%a} {a.date.day}" + (f" – {b.date:%a} {b.date.day} {b.date:%b}" if b is not a else f" {a.date:%b}")
        else:
            span = f"Day {a.number}" + (f"–{b.number}" if b is not a else "")
        out.append((city, f"{span} · {len(days)} night{'s' if len(days) != 1 else ''}" if a.date else span))
    return out


def html(doc: Doc, style: str = "designed") -> str:
    css = (PRINTABLE_CSS if style == "printable" else DESIGNED_CSS) % {
        "size": doc.size, "height": "297mm" if doc.size == "A4" else "11in", "name": _t(doc.name).replace('"', "'")}
    body = _printable(doc) if style == "printable" else _designed(doc)
    return f'<!doctype html><html><head><meta charset="utf-8"><title>{_t(doc.name)}</title>' \
           f"<style>{_fonts()}{css}</style></head><body>{body}</body></html>"


def pdf(doc: Doc, style: str = "designed") -> bytes:
    from weasyprint import HTML  # imported here: it loads Pango, which only the PDF route needs
    return HTML(string=html(doc, style)).write_pdf()


# ---------- Text for Notes and Notion ----------

def markdown(doc: Doc) -> str:
    """Pastes into Notion as headings and to-dos; reads cleanly as plain text anywhere else."""
    out = [f"# {doc.name}", f"{doc.dates} · {' → '.join(doc.route)}", ""]
    if doc.bookings:
        out.append("## Bookings")
        for kind in ("flight", "hotel", "reservation", "tour", "car", "other"):
            items = [b for b in doc.bookings if b.kind == kind]
            if items:
                out.append(f"### {KIND_LABELS[kind]}")
                for b in items:
                    ref = f" · Ref **{b.confirmation}**" if b.confirmation else ""
                    out.append(f"- **{b.title}** — {b.when}{ref}")
                    out += [f"  - {x}" for x in b.lines]
        out.append("")
    for d in doc.days:
        out.append(f"## {d.label}" + (f" — {d.title}" if d.title else ""))
        if d.city:
            out.append(f"_{d.city}_")
        for b in d.bookings:
            out.append(f"- [ ] {KIND_ONE[b.kind]}: **{b.title}** — {b.when}" + (f" · Ref {b.confirmation}" if b.confirmation else ""))
        for s in d.stops:
            time = f"{'~' if s.estimated else ''}{s.time} " if s.time else ""
            meta = " · ".join(x for x in (s.kind, s.area) if x)
            out.append(f"- [ ] {time}**{s.name}**" + (f" — {meta}" if meta else ""))
            if s.booked:
                out.append(f"  - {s.booked}")
            if s.note:
                out.append(f"  - {_short(s.note, 220)}")
        out.append("")
    if doc.packing:
        out.append("## Packing")
        for c, items in doc.packing:
            out.append(f"### {c}")
            out += [f"- [ ] {i}" for i in items]
    out.append("\n— Made with The Travel Edit")
    return "\n".join(out).strip() + "\n"


def clip_html(doc: Doc) -> str:
    """The same as rich text, for pasting into Apple Notes (which keeps headings, bold and lists from HTML)."""
    def inline(s: str) -> str:
        s = escape(s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
        return re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"<i>\1</i>", s)
    out, depth = [], 0
    for line in markdown(doc).splitlines():
        m = re.match(r"^( *)- (\[ \] )?(.*)$", line)
        level = (len(m.group(1)) // 2 + 1) if m else 0
        while depth > level:
            out.append("</ul>")
            depth -= 1
        while depth < level:
            out.append("<ul>")
            depth += 1
        if m:
            out.append(f"<li>{inline(m.group(3))}</li>")
        elif h := re.match(r"^(#{1,3}) (.*)$", line):
            n = len(h.group(1))
            out.append(f"<h{n}>{inline(h.group(2))}</h{n}>")
        elif line.strip():
            out.append(f"<p>{inline(line)}</p>")
    out += ["</ul>"] * depth
    return "<meta charset='utf-8'>" + "".join(out)
