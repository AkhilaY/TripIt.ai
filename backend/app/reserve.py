"""Finding where a restaurant takes reservations.

Resy and OpenTable don't offer open booking APIs, so TripIt doesn't book or check availability. It finds
the restaurant's own page on a booking platform by reading links on the restaurant's website, and sends
people there. Only a link that matches a known platform's address pattern is ever kept.
"""

import asyncio
import logging
import re
from typing import Optional
from urllib.parse import urlsplit

from .menus import HTML_BYTES, SafeFetcher, parse_page

log = logging.getLogger(__name__)

# (provider name, address pattern for a restaurant's own page)
PROVIDERS = [
    ("Resy", re.compile(r"^https?://(www\.)?resy\.com/cities/[a-z0-9-]+/[^\s?#]+", re.I)),
    ("OpenTable", re.compile(r"^https?://(www\.|reserve\.)?opentable\.(com|co\.uk|ca|de|es|fr|it|nl|jp|ie|com\.au|com\.mx|ae|sg|hk)/(r/|restaurant/profile/|restref/|booking/|[a-z0-9-]+-restaurant)", re.I)),
    ("Tock", re.compile(r"^https?://(www\.)?exploretock\.com/[a-z0-9-]+", re.I)),
    ("SevenRooms", re.compile(r"^https?://(www\.)?sevenrooms\.com/(reservations|explore)/[a-z0-9-]+", re.I)),
]
BOOKING_WORDS = re.compile(r"reserv|book|table|dine|dining", re.I)
MAX_URL = 500


def provider_for(url: str) -> Optional[str]:
    if len(url) > MAX_URL or any(ch.isspace() for ch in url):
        return None
    for name, pattern in PROVIDERS:
        if pattern.match(url):
            return name
    return None


def _scan(links: list[tuple[str, str]]) -> Optional[tuple[str, str]]:
    for url, _text in links:
        name = provider_for(url)
        if name:
            return name, url
    return None


async def find_reserve_link(fetcher: SafeFetcher, website: str) -> Optional[tuple[str, str]]:
    """(provider, url) for the restaurant's booking page, or None."""
    home = await fetcher.get(website, HTML_BYTES)
    if home is None or "html" not in home.content_type:
        return None
    page = parse_page(home.url, home.body)
    found = _scan(page.links)
    if found:
        return found
    # The link is often one click away, on a Reservations page of the restaurant's own site.
    host = (urlsplit(home.url).hostname or "").removeprefix("www.")
    pages = []
    for url, text in page.links:
        parts = urlsplit(url)
        if (parts.hostname or "").removeprefix("www.") == host and url != home.url and (BOOKING_WORDS.search(text) or BOOKING_WORDS.search(parts.path)):
            if url not in pages:
                pages.append(url)
    for got in await asyncio.gather(*(fetcher.get(url, HTML_BYTES) for url in pages[:2])):
        if got is not None and "html" in got.content_type:
            found = _scan(parse_page(got.url, got.body).links)
            if found:
                return found
    return None
