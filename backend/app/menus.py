"""Finding a place's menu and turning it into neat sections.

1. The place's website: the home page, then the pages, PDFs and images it links to that look like a menu.
2. When the website has none (or there is no website) and it's allowed: photos listed for the place on
   Google Maps, which may include a photographed menu card.

Claude reads whatever was found (page text, PDFs, images) and returns structured sections. Everything
fetched from the web is untrusted: it is only ever shown as escaped text, and Claude is told to ignore
instructions inside it. Fetching is restricted to public http(s) addresses so a link on a page can't make
the server call into its own network.
"""

import asyncio
import contextlib
import time
from collections import OrderedDict
import ipaddress
import json
import logging
import re
import socket
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Awaitable, Callable, Optional
from urllib.parse import unquote, urldefrag, urljoin, urlsplit

import httpx

from .config import Settings
from .db import Database
from .geocode import Geocoder, GooglePlacesGeocoder
from .llm import ClaudeError, ClaudeService
from .models import MenuResult, Place, PlaceMenu

log = logging.getLogger(__name__)

# Places that get a Menu tab.
MENU_CATEGORIES = {"food", "cafe", "dessert", "drinks", "nightlife"}

# Restaurant sites often refuse anything that doesn't look like a browser.
BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
BROWSER_HEADERS = {"User-Agent": BROWSER_UA, "Accept-Language": "en-US,en;q=0.9",
                   "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf,image/*;q=0.8,*/*;q=0.5"}
PROBE_PATHS = ["/menu", "/menus", "/food", "/dinner", "/our-menu", "/menu.pdf"]  # tried when links don't lead to a menu
MAX_PROBES = 5
MAX_REDIRECTS = 4
HTML_BYTES = 2_000_000
PDF_BYTES = 5_000_000
IMAGE_BYTES = 3_500_000
MAX_CANDIDATES = 3
MAX_PDFS = 6  # a restaurant can have food, lunch, dessert, wine and cocktail menus as separate files
MAX_PAGES = 3
PICK_FROM = 40  # links offered to Claude when there are too many menu-like ones to read them all
MAX_IMAGES = 6
MAX_TEXT_CHARS = 40_000
PAGE_TEXT_CHARS = 14_000
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}

STRONG = re.compile(r"menu|menú|carte|speisekarte", re.I)
WEAK = re.compile(r"\b(food|drinks?|dinner|lunch|brunch|breakfast|cocktails?|wine|dessert|beverages?|eat)\b", re.I)
NOISE = re.compile(r"privacy|terms|cookie|reserv|contact|about|cart\b|shop|allerg", re.I)
# Pages that are about something other than the everyday menu: pulled down harder.
OFF_MENU = re.compile(r"gift|career|jobs?|press|login|catering|events?|private|festive|christmas|new year|nye|valentine|easter|diwali|thanksgiving", re.I)
PRICE = re.compile(r"(?:[$€£¥]\s?\d|\d\s?[$€£¥]|\b\d{1,3}[.,]\d{2}\b)")


@dataclass
class Fetched:
    url: str
    content_type: str
    body: bytes
    truncated: bool = False


@dataclass
class Material:
    """One piece of evidence for Claude to read."""
    kind: str  # "text" | "image" | "pdf"
    label: str
    url: str
    text: Optional[str] = None
    data: Optional[bytes] = None
    media_type: Optional[str] = None


async def _resolve(host: str) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [info[4][0] for info in infos]


def is_public_address(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%")[0])
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


class SafeFetcher:
    """GET for public web pages only: http(s) on the usual ports, public IPs, a few redirects, size limits."""

    def __init__(self, client: Optional[httpx.AsyncClient] = None,
                 resolver: Callable[[str], Awaitable[list[str]]] = _resolve, min_interval: float = 0.5,
                 retry_cap: float = 8.0, cache_seconds: float = 600.0):
        self.client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(12.0, connect=5.0), headers=BROWSER_HEADERS)
        self._resolve = resolver
        self.failures: dict[str, str] = {}  # url -> why the last fetch failed, for the lookup's trace
        # Be gentle with each site: one request at a time per host with a pause between, a retry when a site says
        # "slow down", and a short memory of pages already fetched, so trying again doesn't hammer it.
        self.min_interval = min_interval
        self.retry_cap = retry_cap
        self.cache_seconds = cache_seconds
        self._gates: dict[str, asyncio.Lock] = {}
        self._last: dict[str, float] = {}
        self._cache: "OrderedDict[str, tuple[float, Fetched]]" = OrderedDict()

    async def allowed(self, url: str) -> bool:
        try:
            parts = urlsplit(url)
            host = parts.hostname
            port = parts.port
        except ValueError:
            return False
        if parts.scheme not in ("http", "https") or not host or parts.username or parts.password:
            return False
        if port not in (None, 80, 443):
            return False
        try:
            addresses = await self._resolve(host)
        except OSError:
            return False
        return bool(addresses) and all(is_public_address(a) for a in addresses)

    async def get(self, url: str, max_bytes: int) -> Optional[Fetched]:
        hit = self._cache.get(url)
        if hit and time.monotonic() - hit[0] < self.cache_seconds and (len(hit[1].body) <= max_bytes):
            return hit[1]
        got = await self._get(url, max_bytes)
        if got is not None and not got.truncated and len(got.body) <= 2_000_000:
            self._cache[url] = (time.monotonic(), got)
            while len(self._cache) > 40:
                self._cache.popitem(last=False)
        return got

    async def _pace(self, url: str) -> None:
        """One request at a time per host, with a pause between them."""
        host = urlsplit(url).hostname or ""
        gate = self._gates.setdefault(host, asyncio.Lock())
        async with gate:
            wait = self.min_interval - (time.monotonic() - self._last.get(host, 0.0))
            if wait > 0:
                await asyncio.sleep(wait)
            self._last[host] = time.monotonic()

    async def _get(self, url: str, max_bytes: int, attempt: int = 0) -> Optional[Fetched]:
        first = url
        for _ in range(MAX_REDIRECTS + 1):
            if not await self.allowed(url):
                self.failures[first] = "not a public web address"
                return None
            await self._pace(url)
            try:
                async with self.client.stream("GET", url, follow_redirects=False) as response:
                    if response.is_redirect:
                        url = urljoin(url, response.headers.get("location", ""))
                        continue
                    if response.status_code in (429, 503) and attempt == 0:
                        try:
                            pause = float(response.headers.get("retry-after", "3"))
                        except ValueError:
                            pause = 3.0
                        await asyncio.sleep(min(max(pause, 0.0), self.retry_cap))
                        return await self._get(first, max_bytes, attempt=1)
                    if response.status_code != 200:
                        self.failures[first] = (f"the site answered HTTP {response.status_code}"
                                                + (" (it is limiting requests; try again in a few minutes)" if response.status_code == 429 else ""))
                        return None
                    kind = response.headers.get("content-type", "").split(";")[0].strip().lower()
                    body = bytearray()
                    truncated = False
                    async with contextlib.aclosing(response.aiter_bytes()) as chunks:
                        async for chunk in chunks:
                            body += chunk
                            if len(body) > max_bytes:
                                del body[max_bytes:]
                                truncated = True
                                break
                    self.failures.pop(first, None)
                    return Fetched(url=url, content_type=kind, body=bytes(body), truncated=truncated)
            except (httpx.HTTPError, ValueError) as e:
                self.failures[first] = f"couldn't connect ({type(e).__name__})"
                return None
        self.failures[first] = "too many redirects"
        return None


# ---------- Reading a web page ----------


@dataclass
class Page:
    url: str
    text: str = ""
    links: list[tuple[str, str]] = field(default_factory=list)  # (absolute url, link text)
    images: list[tuple[str, str]] = field(default_factory=list)  # (absolute url, alt text)
    jsonld: list[str] = field(default_factory=list)


class _PageParser(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "template", "head", "iframe"}
    BLOCKS = {"p", "div", "li", "br", "tr", "section", "article", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "table", "dt", "dd"}

    def __init__(self, base: str):
        super().__init__(convert_charrefs=True)
        self.base = base
        self.page = Page(url=base)
        self._chunks: list[str] = []
        self._skip = 0
        self._ld = False
        self._ld_buf: list[str] = []
        self._link: Optional[list] = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script" and (a.get("type") or "").lower() == "application/ld+json":
            self._ld, self._ld_buf = True, []
            return
        if tag in self.SKIP:
            self._skip += 1
            return
        if tag in self.BLOCKS:
            self._chunks.append("\n")
        if tag == "a" and a.get("href"):
            href = a["href"].strip()
            if href and not href.lower().startswith(("mailto:", "tel:", "javascript:", "#")):
                self._link = [urldefrag(urljoin(self.base, href))[0], []]
        elif tag == "img":
            src = a.get("src") or a.get("data-src") or a.get("data-lazy-src")
            if src and not src.startswith("data:"):
                self.page.images.append((urljoin(self.base, src.strip()), (a.get("alt") or "").strip()))

    def handle_endtag(self, tag):
        if tag == "script" and self._ld:
            self._ld = False
            blob = "".join(self._ld_buf).strip()
            if blob:
                self.page.jsonld.append(blob)
            return
        if tag in self.SKIP:
            self._skip = max(0, self._skip - 1)
            return
        if tag in self.BLOCKS:
            self._chunks.append("\n")
        if tag == "a" and self._link:
            self.page.links.append((self._link[0], " ".join("".join(self._link[1]).split())))
            self._link = None

    def handle_data(self, data):
        if self._ld:
            self._ld_buf.append(data)
        elif not self._skip:
            self._chunks.append(data)
            if self._link:
                self._link[1].append(data)

    def result(self) -> Page:
        text = "".join(self._chunks)
        lines = (" ".join(line.split()) for line in text.splitlines())
        self.page.text = "\n".join(line for line in lines if line)
        return self.page


def parse_page(url: str, body: bytes) -> Page:
    parser = _PageParser(url)
    try:
        parser.feed(body.decode("utf-8", errors="replace"))
        parser.close()
    except Exception:  # malformed markup shouldn't sink the lookup; use what was read
        log.debug("Odd HTML at %s", url, exc_info=True)
    return parser.result()


def score_link(url: str, text: str) -> int:
    path = unquote(urlsplit(url).path)
    score = 0
    if STRONG.search(text):
        score += 6
    if STRONG.search(path):
        score += 5
    if WEAK.search(text):
        score += 2
    if WEAK.search(path):
        score += 1
    if path.lower().endswith(".pdf"):
        score += 3  # a PDF on a restaurant's site is nearly always a menu, whatever it's called
    if NOISE.search(text) or NOISE.search(path):
        score -= 3
    if OFF_MENU.search(text) or OFF_MENU.search(path):
        score -= 6
    return score


STOP_WORDS = {"the", "restaurant", "restaurants", "bar", "cafe", "café", "and", "kitchen", "grill", "london", "new", "york"}


def name_words(name: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9À-ÿ']+", name.lower()) if len(w) >= 4 and w not in STOP_WORDS]


def mentions(words: list[str], url: str, text: str) -> bool:
    haystack = f"{text} {unquote(urlsplit(url).path)}".lower().replace("-", " ").replace("_", " ")
    return any(w in haystack for w in words)


def candidate_links(page: Page, limit: int = MAX_CANDIDATES, name: str = "") -> list[str]:
    """Links that probably lead to a menu. On a site that covers several restaurants, the ones that mention this
    restaurant's name come first."""
    words = name_words(name)
    best: dict[str, int] = {}
    for url, text in page.links:
        if url == page.url or not url.lower().startswith(("http://", "https://")):
            continue
        score = score_link(url, text)
        if score > 0 and words and mentions(words, url, text):
            score += 5
        if score > 0 and score > best.get(url, 0):
            best[url] = score
    return [u for u, _ in sorted(best.items(), key=lambda kv: -kv[1])[:limit]]


def _near(place: Place, match) -> Optional[bool]:
    """Whether a geocoder match is at the saved pin (within 300 m); None when it can't tell."""
    if place.latitude is None or place.longitude is None or match is None:
        return None
    import math
    dlat, dlon = math.radians(match.latitude - place.latitude), math.radians(match.longitude - place.longitude)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(place.latitude)) * math.cos(math.radians(match.latitude)) * math.sin(dlon / 2) ** 2
    return 6_371_000 * 2 * math.asin(math.sqrt(a)) <= 300


def looks_like_menu(text: str) -> bool:
    return len(PRICE.findall(text)) >= 5


# ---------- Finding the menu ----------


class MenuService:
    def __init__(self, db: Database, claude: Optional[ClaudeService], fetcher: SafeFetcher,
                 geocoder: Optional[Geocoder], settings: Settings, renderer=None):
        self.renderer = renderer  # menu_browser.BrowserRenderer, or None
        self.db = db
        self.claude = claude
        self.fetcher = fetcher
        self.geocoder = geocoder
        self.settings = settings
        self._running: dict[str, asyncio.Task] = {}

    def stored(self, place_id: str) -> PlaceMenu:
        row = self.db.get_menu(place_id)
        if row is None:
            return PlaceMenu()
        data = json.loads(row["data"]) if row["data"] else {}
        return PlaceMenu(
            status=row["status"], sections=data.get("sections", []), notes=data.get("notes"),
            source_kind=row["source_kind"], source_url=row["source_url"], fetched_at=row["fetched_at"],
            trace=data.get("trace", []),
        )

    async def find(self, place: Place, refresh: bool = False) -> PlaceMenu:
        """Returns the saved menu, or looks for one. A second request for the same place waits for the first."""
        if not refresh and self.db.get_menu(place.id) is not None:
            return self.stored(place.id)
        task = self._running.get(place.id)
        if task is None:
            task = asyncio.ensure_future(self._look(place))
            self._running[place.id] = task
            task.add_done_callback(lambda _t, pid=place.id: self._running.pop(pid, None))
        return await asyncio.shield(task)

    async def _look(self, place: Place) -> PlaceMenu:
        if self.claude is None:
            raise ClaudeError("Claude isn't configured on the server")
        result: Optional[MenuResult] = None
        kind: Optional[str] = None
        source: Optional[str] = None
        trace: list[str] = []
        host = lambda u: (urlsplit(u).hostname or u).removeprefix("www.")

        website = place.website
        if website:
            trace.append(f"Website on file: {host(website)}")
        else:
            website = await self._find_website(place)
            trace.append(f"No website was saved; looked one up: {host(website)}" if website else "No website is saved for this place, and none could be found")
        if website:
            materials = await self.gather_website(website, place.name, trace)
            if materials:
                result = clean_menu(await self.claude.extract_menu(place, materials, from_photos=False))
                trace.append(f"Claude read {len(materials)} item(s) from the website and {'found a menu' if result.found else 'found no menu in them'}")
                if result.found:
                    kind = "website"
                    source = self._best_source(materials, website)
        if (result is None or not result.found) and self.settings.menu_google_photos \
                and isinstance(self.geocoder, GooglePlacesGeocoder):
            photos = await self.geocoder.menu_photos(place.name, place.neighborhood, place.city, place.country)
            if photos:
                materials = [Material("image", f"Photo {i}", "", data=data, media_type=media_type)
                             for i, (media_type, data) in enumerate(photos, start=1)]
                result = clean_menu(await self.claude.extract_menu(place, materials, from_photos=True))
                if result.found:
                    kind, source = "photos", None
                trace.append(f"Google Maps photos: checked {len(photos)}, {'found a menu' if result.found else 'none was a readable menu'}")
            else:
                trace.append("Google Maps photos: none available")
        elif result is None or not result.found:
            trace.append("Google Maps photos: skipped (" + ("turned off" if not self.settings.menu_google_photos else "no Google key") + ")")
        if (result is None or not result.found) and website:
            if self.renderer is None:
                trace.append("Browser click-through: not available on this server")
            else:
                # Last resort: open the site in a browser and click through to the menu, like a person would.
                materials, links = await self.renderer.capture(website)
                trace.append(f"Browser click-through: {getattr(self.renderer, 'last_note', '') or 'ran'}")
                if links:  # the pop-up or tab it opened is often a list of PDFs: read the ones that are this restaurant's menus
                    chosen = await self._choose_links(links, place.name, website)
                    read = await self._read_links(chosen)
                    materials += read
                    trace.append(f"Browser found {len(links)} link(s); {len(chosen)} looked like menus; {len(read)} could be read")
                if materials:
                    result = clean_menu(await self.claude.extract_menu(place, materials, from_photos=False))
                    trace.append(f"Claude read {len(materials)} item(s) from the browser visit and {'found a menu' if result.found else 'found no menu in them'}")
                    if result.found:
                        kind, source = "website", self._best_source(materials, website)
        log.info("Menu for %s: %s", place.name, " | ".join(trace))

        if result is not None and result.found:
            self.db.save_menu(place.id, "found", {"sections": [s.model_dump() for s in result.sections], "notes": result.notes, "trace": trace},
                              kind, source)
        else:
            self.db.save_menu(place.id, "none", {"trace": trace}, None, None)
        return self.stored(place.id)

    async def read_upload(self, place: Place, images: list[bytes], pdfs: list[bytes]) -> Optional[PlaceMenu]:
        """A menu the person photographed or downloaded: for sites the server can't read. None when it holds no menu."""
        if self.claude is None:
            raise ClaudeError("Claude isn't configured on the server")
        materials = [Material("image", f"Photo {i}", "", data=d, media_type="image/jpeg") for i, d in enumerate(images, start=1)]
        materials += [Material("pdf", f"PDF {i}", "", data=d, media_type="application/pdf") for i, d in enumerate(pdfs, start=1)]
        result = clean_menu(await self.claude.extract_menu(place, materials, from_photos=bool(images)))
        if not result.found:
            return None
        self.db.save_menu(place.id, "found", {"sections": [s.model_dump() for s in result.sections], "notes": result.notes,
                                              "trace": ["Read from a photo or PDF you added"]}, "upload", None)
        return self.stored(place.id)

    async def _find_website(self, place: Place) -> Optional[str]:
        """Places saved without Google details have no website yet: ask the geocoder for it once."""
        if place.contact_checked_at is not None or self.geocoder is None:
            return place.website
        try:
            match = await self.geocoder.locate(place.name, place.neighborhood, place.city, place.country)
        except Exception as e:
            log.info("Website lookup for %s failed: %s", place.name, e)
            return None
        website = match.website if match else None
        if match and place.latitude is not None and _near(place, match) is False:
            website = None  # a different place with the same name
        self.db.update_place(place.id, website=website or place.website, phone=place.phone or (match.phone if match else None),
                             contact_checked_at=datetime.now(timezone.utc))
        return website

    @staticmethod
    def _best_source(materials: list[Material], fallback: str) -> str:
        for m in materials:
            if m.url:
                return m.url
        return fallback

    async def _choose_links(self, links: list[tuple[str, str]], name: str, here: str) -> list[tuple[str, str]]:
        """(address, link text) for the links most likely to be this restaurant's menus. With many candidates (a
        site listing a dozen PDFs) Claude picks the main ones; otherwise the best-scored are all taken."""
        words = name_words(name)
        scored: dict[str, tuple[int, str]] = {}
        for url, text in links:
            if not url.lower().startswith(("http://", "https://")) or url.split("#")[0] == here.split("#")[0]:
                continue
            score = score_link(url, text)
            if score > 0 and words and mentions(words, url, text):
                score += 5
            if score > 0 and score > scored.get(url, (0, ""))[0]:
                scored[url] = (score, text)
        ranked = sorted(scored.items(), key=lambda kv: -kv[1][0])
        if len(ranked) <= MAX_PDFS + MAX_PAGES - 1:
            return [(u, t) for u, (_, t) in ranked]
        top = ranked[:PICK_FROM]
        if self.claude is not None:
            try:
                picked = await self.claude.pick_menu_links(name or "this restaurant", [(t, u) for u, (_, t) in top])
                if picked:
                    return [(top[i][0], top[i][1][1]) for i in picked]
            except ClaudeError as e:
                log.info("Picking menu links failed, using the best-scored: %s", e)
        return [(u, t) for u, (_, t) in top[:MAX_PDFS]]

    async def _read_links(self, chosen: list[tuple[str, str]]) -> list[Material]:
        """Downloads menu links found by the browser: PDFs and images as they are, pages as text."""
        out: list[Material] = []
        pdfs = images = pages = 0
        for (url, text), got in zip(chosen, await asyncio.gather(*(self.fetcher.get(u, PDF_BYTES) for u, _ in chosen))):
            if got is None:
                continue
            label = text or "menu"
            if got.content_type == "application/pdf" and not got.truncated and pdfs < MAX_PDFS:
                pdfs += 1
                out.append(Material("pdf", f"Menu PDF: {label}", got.url, data=got.body, media_type="application/pdf"))
            elif got.content_type in IMAGE_TYPES and not got.truncated and len(got.body) <= IMAGE_BYTES and images < MAX_IMAGES:
                images += 1
                out.append(Material("image", f"Menu image: {label}", got.url, data=got.body, media_type=got.content_type))
            elif "html" in got.content_type and pages < MAX_PAGES:
                text_ = parse_page(got.url, got.body).text[:PAGE_TEXT_CHARS]
                if len(text_) >= 60:
                    pages += 1
                    out.append(Material("text", f"Web page: {label}", got.url, text=text_))
        return out

    async def gather_website(self, website: str, name: str = "", trace: Optional[list[str]] = None) -> list[Material]:
        trace = trace if trace is not None else []
        home = await self.fetcher.get(website, HTML_BYTES)
        if home is None:
            trace.append(f"Couldn't open the website's home page: {self.fetcher.failures.get(website, 'no answer')}")
            return []
        trace.append("Opened the website's home page")
        if home.content_type == "application/pdf" and not home.truncated:
            return [Material("pdf", "Menu PDF", home.url, data=home.body, media_type="application/pdf")]
        if home.content_type in IMAGE_TYPES and len(home.body) <= IMAGE_BYTES and not home.truncated:
            return [Material("image", "Menu image", home.url, data=home.body, media_type=home.content_type)]
        if "html" not in home.content_type:
            return []

        pages = [parse_page(home.url, home.body)]
        materials: list[Material] = []
        pdfs = images = 0
        chosen = await self._choose_links(pages[0].links, name, home.url)
        trace.append(f"The home page has {len(pages[0].links)} link(s); {len(chosen)} look like menus" + (": " + ", ".join(t or "(no text)" for _, t in chosen[:8]) if chosen else ""))
        candidates = [u for u, _ in chosen]
        link_text = dict((u, t) for u, t in chosen if t)
        for blob in pages[0].jsonld:  # a site can name its menu page in its structured data
            for url in re.findall(r'"hasMenu"\s*:\s*(?:\{[^{}]*?"url"\s*:\s*)?"(https?://[^"]+)"', blob)[:2]:
                if url not in candidates:
                    candidates.insert(0, url)
        fetched = list(await asyncio.gather(*(self.fetcher.get(url, PDF_BYTES) for url in candidates)))
        if not any(g and (g.content_type == "application/pdf" or g.content_type in IMAGE_TYPES
                          or ("html" in g.content_type and looks_like_menu(parse_page(g.url, g.body).text))) for g in fetched) \
                and not looks_like_menu(pages[0].text):
            # No link led to a menu: try the addresses restaurants usually use for it.
            probes = [urljoin(home.url, path) for path in PROBE_PATHS]
            probes = [u for u in dict.fromkeys(probes) if u not in candidates and u.rstrip("/") != home.url.rstrip("/")][:MAX_PROBES]
            for got in await asyncio.gather(*(self.fetcher.get(url, PDF_BYTES) for url in probes)):
                if got is not None and not (got.content_type == "text/html" and got.body[:4000] == home.body[:4000]):
                    fetched.append(got)
        words = name_words(name)
        menuish = lambda g: bool(g and (g.content_type == "application/pdf" or g.content_type in IMAGE_TYPES
                                        or ("html" in g.content_type and looks_like_menu(parse_page(g.url, g.body).text))))
        if words:
            # A site for several restaurants: this restaurant's own page comes first, and its menu beats the others'.
            host = (urlsplit(home.url).hostname or "").removeprefix("www.")
            venues = [u for u, t in pages[0].links if u.startswith(("http://", "https://")) and mentions(words, u, t)
                      and not urlsplit(u).path.lower().endswith((".pdf", ".jpg", ".jpeg", ".png", ".webp"))
                      and (urlsplit(u).hostname or "").removeprefix("www.") == host and u.rstrip("/") != home.url.rstrip("/")]
            venues = list(dict.fromkeys(venues))[:2]
            own: list = []
            own_pages: list[Page] = []
            for venue in await asyncio.gather(*(self.fetcher.get(u, HTML_BYTES) for u in venues)):
                if venue is None or "html" not in venue.content_type:
                    continue
                page = parse_page(venue.url, venue.body)
                own_pages.append(page)
                own.append(venue)
                deeper = [u for u in candidate_links(page, name=name) if u != venue.url]
                own.extend(await asyncio.gather(*(self.fetcher.get(u, PDF_BYTES) for u in deeper)))
            if any(menuish(g) for g in own):
                fetched = own
                pages = pages[:1] + own_pages
        for got in fetched:
            if got is None or got.truncated and "html" not in got.content_type:
                continue
            if got.content_type == "application/pdf" and pdfs < MAX_PDFS:
                pdfs += 1
                materials.append(Material("pdf", f"Menu PDF: {link_text.get(got.url) or pdfs}", got.url, data=got.body, media_type="application/pdf"))
            elif got.content_type in IMAGE_TYPES and images < MAX_IMAGES and len(got.body) <= IMAGE_BYTES:
                images += 1
                materials.append(Material("image", f"Menu image: {link_text.get(got.url) or images}", got.url, data=got.body, media_type=got.content_type))
            elif "html" in got.content_type and len(pages) <= MAX_PAGES:
                pages.append(parse_page(got.url, got.body))

        # The home page counts when it has no menu page to point to, or is itself full of prices.
        use = pages if len(pages) == 1 or looks_like_menu(pages[0].text) else pages[1:]
        used = 0
        for page in use:
            text = page.text[:PAGE_TEXT_CHARS]
            if len(text) >= 60 and used + len(text) <= MAX_TEXT_CHARS:
                materials.append(Material("text", f"Web page {len(materials) + 1}", page.url, text=text))
                used += len(text)
            for blob in page.jsonld:
                if re.search(r'"(hasMenu|Menu|MenuItem|MenuSection)"', blob) and used + len(blob) <= MAX_TEXT_CHARS:
                    materials.append(Material("text", "Structured menu data", page.url, text=blob[:PAGE_TEXT_CHARS]))
                    used += min(len(blob), PAGE_TEXT_CHARS)
        # Menus are often pictures: take the menu-looking images from those pages.
        wanted = [(u, alt) for page in use for u, alt in page.images if STRONG.search(alt) or STRONG.search(unquote(urlsplit(u).path))]
        for url, _alt in list(dict.fromkeys(wanted))[:MAX_IMAGES - images]:
            got = await self.fetcher.get(url, IMAGE_BYTES)
            if got and got.content_type in IMAGE_TYPES and not got.truncated:
                images += 1
                materials.append(Material("image", f"Menu image {images}", got.url, data=got.body, media_type=got.content_type))
        kinds = [m.kind for m in materials]
        if not kinds:
            trace.append("Nothing readable was found on the website's pages")
        else:
            trace.append(f"Read {kinds.count('pdf')} PDF(s), {kinds.count('image')} image(s) and {kinds.count('text')} page(s) from the website")
        return materials


def clean_menu(result: MenuResult) -> MenuResult:
    """Trims what Claude returned into sizes the app is happy to store and show."""
    sections = []
    for section in result.sections[:40]:
        items = []
        for item in section.items[:150]:
            name = " ".join(item.name.split())[:150]
            if not name:
                continue
            item.name = name
            item.description = " ".join((item.description or "").split())[:500] or None
            item.price = " ".join((item.price or "").split())[:40] or None
            item.tags = list(dict.fromkeys(item.tags))
            items.append(item)
        if items:
            section.title = " ".join(section.title.split())[:120] or "Menu"
            section.note = " ".join((section.note or "").split())[:300] or None
            section.items = items
            sections.append(section)
    result.sections = sections
    result.notes = " ".join((result.notes or "").split())[:400] or None
    result.found = bool(sections)
    return result
