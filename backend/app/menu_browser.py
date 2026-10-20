"""Opening a restaurant's website in a real browser and clicking through to its menu.

Many restaurant sites draw their menu with JavaScript, hide it behind a "Menu" tab, or only show it as
pictures, so reading the page's HTML finds nothing. This loads the site in headless Chromium (Playwright),
finds the Menu link or tab the way a person would, opens it, and hands back the page text plus screenshots
for Claude to read.

Everything the browser requests goes through the same public-address check as the plain fetcher, so a page
can't make the server call into its own network. One browser runs at a time and each visit has a time limit.
"""

import asyncio
import logging
import re
from typing import Optional
from urllib.parse import urlsplit

from .menus import (
    BROWSER_UA, MAX_IMAGES, MAX_TEXT_CHARS, PAGE_TEXT_CHARS, Material, SafeFetcher, looks_like_menu, score_link,
)

log = logging.getLogger(__name__)

TOTAL_TIMEOUT = 75  # seconds for one website
SLICE_HEIGHT = 1400
MAX_SLICES = 4
MAX_PAGE_HEIGHT = SLICE_HEIGHT * MAX_SLICES
MAX_STEPS = 3  # menu links or tabs to open
BLOCKED_TYPES = {"media", "font", "websocket", "eventsource"}

FIND_TARGETS = """() => {
  const out = [];
  const sel = 'a[href], button, [role="tab"], [role="link"], [role="menuitem"], summary';
  document.querySelectorAll(sel).forEach((el, i) => {
    const r = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    if (style.visibility === 'hidden' || style.display === 'none' || (!r.width && !r.height)) return;
    const text = (el.innerText || el.getAttribute('aria-label') || el.getAttribute('title') || '').replace(/\\s+/g, ' ').trim();
    if (!text || text.length > 40) return;
    el.setAttribute('data-tripit-i', String(i));
    out.push({ i, text, href: el.tagName === 'A' ? el.href : '' });
  });
  return out;
}"""
ALL_LINKS = """() => Array.from(document.querySelectorAll('a[href]')).slice(0, 400).map((a) =>
  [a.href, (a.innerText || a.getAttribute('aria-label') || a.title || '').replace(/\\s+/g, ' ').trim().slice(0, 80)])"""
PAGE_TEXT = "() => (document.body ? document.body.innerText : '')"
SCROLL = """async () => {
  const limit = Math.min(document.body.scrollHeight, 6000);
  for (let y = 0; y < limit; y += 800) { window.scrollTo(0, y); await new Promise((r) => setTimeout(r, 120)); }
  window.scrollTo(0, 0);
}"""
COOKIE_BUTTON = re.compile(r"^(accept( all)?|i agree|agree|allow( all)?|got it|ok(ay)?|continue)$", re.I)


def tidy(text: str) -> str:
    return "\n".join(line for line in (" ".join(raw.split()) for raw in (text or "").splitlines()) if line)


def browser_available() -> bool:
    try:
        import playwright.async_api  # noqa: F401
        return True
    except ImportError:
        return False


class BrowserRenderer:
    def __init__(self, fetcher: SafeFetcher, executable: str = ""):
        self.fetcher = fetcher
        self.executable = executable or None
        self._busy = asyncio.Semaphore(1)
        self.last_note = ""  # what the last visit did, for the lookup's trace

    async def capture(self, website: str) -> tuple[list[Material], list[tuple[str, str]]]:
        """(page text and screenshots from the website's menu, every link seen along the way). A pop-up listing
        menus as PDFs yields its links here, for the caller to download."""
        if not await self.fetcher.allowed(website):
            self.last_note = "the address isn't a public website"
            return [], []
        async with self._busy:
            self.last_note = ""
            try:
                return await asyncio.wait_for(self._capture(website), timeout=TOTAL_TIMEOUT)
            except asyncio.TimeoutError:
                self.last_note = "the site took too long to open"
                log.info("Browser visit to %s timed out", website)
            except Exception as e:  # a broken site or browser must never break the menu lookup
                self.last_note = f"couldn't run ({type(e).__name__}: {str(e).splitlines()[0][:100] if str(e) else ''})"
                log.warning("Browser visit to %s failed: %s", website, e)
        return [], []

    async def _capture(self, website: str) -> tuple[list[Material], list[tuple[str, str]]]:
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(executable_path=self.executable,
                                               args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"])
            try:
                context = await browser.new_context(viewport={"width": 1280, "height": 900}, user_agent=BROWSER_UA,
                                                    service_workers="block", accept_downloads=False, locale="en-US")
                verdicts: dict[str, bool] = {}

                async def gate(route):
                    request = route.request
                    url = request.url
                    if url.startswith(("data:", "blob:", "about:")):
                        await route.continue_()
                        return
                    if request.resource_type in BLOCKED_TYPES:
                        await route.abort()
                        return
                    host = urlsplit(url).hostname or ""
                    if host not in verdicts:
                        verdicts[host] = await self.fetcher.allowed(url)
                    await (route.continue_() if verdicts[host] else route.abort())

                await context.route("**/*", gate)
                page = await context.new_page()
                page.set_default_timeout(10_000)
                return await self._walk(page, website)
            finally:
                await browser.close()

    async def _settle(self, page) -> None:
        try:
            await page.wait_for_load_state("networkidle", timeout=6000)
        except Exception:
            pass
        await page.wait_for_timeout(400)

    async def _dismiss_banner(self, page) -> None:
        try:
            await page.get_by_role("button", name=COOKIE_BUTTON).first.click(timeout=800)
            await page.wait_for_timeout(300)
        except Exception:
            pass

    async def _page_text(self, page) -> str:
        parts = []
        for frame in page.frames:  # menus are often embedded from another site
            try:
                text = tidy(await frame.evaluate(PAGE_TEXT))
            except Exception:
                continue
            if len(text) >= 40:
                parts.append(text)
        return "\n\n".join(parts)

    async def _links(self, page) -> list[tuple[str, str]]:
        out = []
        for frame in page.frames:
            try:
                found = await frame.evaluate(ALL_LINKS)
            except Exception:
                continue
            out.extend((href, text) for href, text in found if href.lower().startswith(("http://", "https://")))
        return out

    async def _screenshots(self, page, label: str, url: str, limit: int) -> list[Material]:
        try:
            await page.evaluate(SCROLL)
            height = int(await page.evaluate("document.documentElement.scrollHeight"))
        except Exception:
            return []
        height = max(1, min(height, MAX_PAGE_HEIGHT))
        shots = []
        for index in range(min(MAX_SLICES, limit, -(-height // SLICE_HEIGHT))):
            y = index * SLICE_HEIGHT
            try:
                data = await page.screenshot(type="jpeg", quality=72, full_page=True,
                                             clip={"x": 0, "y": y, "width": 1280, "height": min(SLICE_HEIGHT, height - y)})
            except Exception:
                break
            shots.append(Material("image", f"{label}, part {index + 1}", url, data=data, media_type="image/jpeg"))
        return shots

    async def _targets(self, page, here: str) -> list[dict]:
        try:
            found = await page.evaluate(FIND_TARGETS)
        except Exception:
            return []
        scored = []
        seen: set[str] = set()
        for t in found:
            href = t["href"]
            if href.lower().endswith(".pdf") or href == here or href.rstrip("/") == here.rstrip("/"):
                continue
            score = score_link(href, t["text"])
            key = (href or t["text"]).lower()
            if score > 0 and key not in seen:
                seen.add(key)
                scored.append((score + (2 if not href else 0), t))  # tabs and buttons that show a menu in place
        return [t for _, t in sorted(scored, key=lambda x: -x[0])[:MAX_STEPS]]

    async def _walk(self, page, website: str) -> tuple[list[Material], list[tuple[str, str]]]:
        await page.goto(website, wait_until="domcontentloaded")
        await self._settle(page)
        await self._dismiss_banner(page)
        home = page.url
        materials: list[Material] = []
        links: dict[str, str] = {}
        used = 0

        async def note_links() -> None:
            for href, text in await self._links(page):
                if href not in links or (text and not links[href]):
                    links[href] = text

        async def take(label: str) -> bool:
            """Adds what's on screen; returns True when it looks like a menu."""
            nonlocal used
            await note_links()
            text = (await self._page_text(page))[:PAGE_TEXT_CHARS]
            menu_like = looks_like_menu(text)
            if len(text) >= 60 and used + len(text) <= MAX_TEXT_CHARS:
                materials.append(Material("text", f"{label} (text)", page.url, text=text))
                used += len(text)
            room = MAX_IMAGES - sum(1 for m in materials if m.kind == "image")
            if room > 0 and not menu_like:  # a page full of prices reads fine as text; otherwise it may be pictures
                materials.extend(await self._screenshots(page, label, page.url, room))
            return menu_like

        targets = await self._targets(page, home)
        self.last_note = f"opened the site; {len(targets)} Menu-like link(s) or tab(s)" + (": " + ", ".join(repr(t["text"]) for t in targets) if targets else "")
        if await take("Home page") and not targets:
            return materials, list(links.items())
        for t in targets:
            try:
                if t["href"] and urlsplit(t["href"]).scheme in ("http", "https") and t["href"].split("#")[0] != home.split("#")[0]:
                    await page.goto(t["href"], wait_until="domcontentloaded")
                else:
                    await page.locator(f'[data-tripit-i="{t["i"]}"]').first.click(timeout=4000)
                await self._settle(page)
            except Exception as e:
                log.info("Couldn't open %r on %s: %s", t["text"], website, e)
                continue
            if await take(f"After opening '{t['text']}'"):
                break
            if len(materials) >= 2 * MAX_STEPS + 2:
                break
            if page.url != home:  # go back so the next tab is clicked on the page it was found on
                try:
                    await page.goto(home, wait_until="domcontentloaded")
                    await self._settle(page)
                    await self._targets(page, home)
                except Exception:
                    break
        self.last_note += f"; clicked through, read {len(materials)} item(s), saw {len(links)} link(s)"
        return materials, list(links.items())
