"""Reading Google Maps and Apple Maps links, so a shared place can be added without a reel.

Short links (maps.app.goo.gl, goo.gl/maps, maps.apple/p/…) are followed, but only through map hosts,
so the server can't be pointed at arbitrary URLs.
"""

import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qs, unquote_plus, urljoin, urlparse

import httpx

GOOGLE_HOST = re.compile(r"^(www\.|maps\.)?google\.[a-z]{2,3}(\.[a-z]{2})?$")
SHORT_HOSTS = {"maps.app.goo.gl", "goo.gl", "g.co"}
APPLE_HOSTS = {"maps.apple.com", "maps.apple", "collections.apple.com"}
COORDS = re.compile(r"^\s*(-?\d{1,2}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)\s*$")


class NotAMapLink(ValueError):
    pass


@dataclass
class MapLink:
    name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


def is_map_host(host: str) -> bool:
    host = host.lower()
    return bool(GOOGLE_HOST.match(host)) or host in SHORT_HOSTS or host in APPLE_HOSTS or host.endswith(".maps.apple.com")


def is_map_link(url: str) -> bool:
    parsed = urlparse(url.strip())
    return parsed.scheme in ("http", "https") and bool(parsed.hostname) and is_map_host(parsed.hostname)


async def resolve(url: str, client: Optional[httpx.AsyncClient] = None, max_hops: int = 5) -> str:
    """Follows short-link redirects, staying on map hosts."""
    own = client is None
    client = client or httpx.AsyncClient(timeout=10, headers={"User-Agent": "Mozilla/5.0 (TripIt link reader)"})
    try:
        for _ in range(max_hops):
            parsed = urlparse(url)
            host = (parsed.hostname or "").lower()
            if host == "consent.google.com":  # EU consent interstitial wraps the real link
                url = parse_qs(parsed.query).get("continue", [url])[0]
                continue
            if not is_map_host(host):
                raise NotAMapLink("That link doesn't go to Google Maps or Apple Maps")
            if host not in SHORT_HOSTS and not (host in APPLE_HOSTS and parsed.path.startswith("/p/")):
                return url
            try:
                response = await client.get(url, follow_redirects=False)
            except httpx.HTTPError as e:
                raise NotAMapLink("Couldn't open that map link") from e
            location = response.headers.get("location")
            if not location:
                return url
            url = urljoin(url, location)
        return url
    finally:
        if own:
            await client.aclose()


def _coords(text: str) -> Optional[tuple[float, float]]:
    m = COORDS.match(text or "")
    if not m:
        return None
    lat, lon = float(m.group(1)), float(m.group(2))
    return (lat, lon) if -90 <= lat <= 90 and -180 <= lon <= 180 else None


def parse(url: str) -> MapLink:
    """Pulls a place name and/or coordinates out of a (resolved) Google or Apple Maps URL."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    query = {k: v[0] for k, v in parse_qs(parsed.query).items() if v}
    link = MapLink()

    def set_coords(text: Optional[str]) -> None:
        c = _coords(text or "")
        if c and link.latitude is None:
            link.latitude, link.longitude = c

    if GOOGLE_HOST.match(host):
        path = unquote_plus(parsed.path)
        # Place pins carry exact coordinates as !3d<lat>!4d<lon>; "@lat,lon" is only the map's center.
        pin = re.search(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)", url)
        if pin:
            link.latitude, link.longitude = float(pin.group(1)), float(pin.group(2))
        m = re.search(r"/maps/(?:place|search)/([^/@]+)", path)
        if m:
            text = m.group(1).strip()
            if _coords(text):
                set_coords(text)
            else:
                link.name = text
        for key in ("q", "query", "destination", "daddr"):
            if key in query:
                if _coords(query[key]):
                    set_coords(query[key])
                elif not link.name:
                    link.name = query[key].strip()
        set_coords(query.get("ll") or query.get("center"))
        center = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+)", path)
        if center and link.name:  # a bare map view isn't a place
            set_coords(f"{center.group(1)},{center.group(2)}")
    elif host in APPLE_HOSTS or host.endswith(".maps.apple.com"):
        link.name = (query.get("name") or query.get("q") or "").strip() or None
        if link.name and _coords(link.name):
            set_coords(link.name)
            link.name = None
        for key in ("coordinate", "ll", "sll", "daddr"):
            set_coords(query.get(key))
        if not link.name and query.get("daddr") and not _coords(query["daddr"]):
            link.name = query["daddr"].strip()
        if not link.name and query.get("address"):
            link.name = query["address"].split(",")[0].strip() or None
    else:
        raise NotAMapLink("That link doesn't go to Google Maps or Apple Maps")

    if link.name:
        link.name = re.sub(r"\s+", " ", link.name)[:200]
    if not link.name and link.latitude is None:
        raise NotAMapLink("Couldn't find a place in that map link. Share the place itself rather than a map view.")
    return link
