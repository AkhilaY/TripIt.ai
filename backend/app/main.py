import asyncio
import base64
import binascii
import hashlib
import hmac
import html
import logging
import mimetypes
import re
import secrets
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Optional
from urllib.parse import quote

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .concierge import Curator
from .config import Settings, get_settings
from .db import Database
from .events import EventsService, Ticketmaster
from .exports import ExportError, ics, kml, schedule
from .geocode import GooglePlacesGeocoder, NoGeocoder, clean_website, make_geocoder
from .jobs import JobStore
from .library import Library
from .llm import ClaudeError, ClaudeService
from .maplinks import NotAMapLink, is_map_link
from .maplinks import parse as parse_map_link
from .maplinks import resolve as resolve_map_link
from .media import UnsupportedURLError, find_url, platform_for
from .models import (
    AddFromLinkRequest,
    AddToDayRequest,
    Booking,
    BookingDraft,
    BookingInput,
    AddPlaceRequest,
    AddPlaceResult,
    BriefingRequest,
    ConciergeReply,
    ConciergeRequest,
    CreateJobRequest,
    DayBriefing,
    DayLegs,
    RoutesFromRequest,
    RoutesFromResponse,
    Job,
    JobStatus,
    LocateRequest,
    MenuRequest,
    MenuUploadRequest,
    PlaceMenu,
    MoveRequest,
    PackingItemInput,
    PackingList,
    PackingRequest,
    Place,
    PlaceUpdate,
    PlanRequest,
    PlanResult,
    PlaceCandidate,
    PlanTripRequest,
    PushSubscriptionRequest,
    Reel,
    ReadBookingsRequest,
    ReorderRequest,
    ScreenshotJobRequest,
    SearchPlacesRequest,
    TidyRequest,
    TripEvents,
    ShareLink,
    Trip,
    TasteProfile,
    TripDetail,
    TripEdits,
    TripUpdate,
)
from .menu_browser import BrowserRenderer, browser_available
from .menus import MENU_CATEGORIES, MenuService, SafeFetcher
from .packing import PackingService
from .photos import PhotoStore
from .reserve import find_reserve_link
from .pipeline import Pipeline
from .push import Push
from .routing import Router
from .weather import Weather

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
mimetypes.add_type("application/manifest+json", ".webmanifest")

STATIC_DIR = Path(__file__).parent / "static"


def build_services(app: FastAPI, settings: Settings) -> None:
    db = Database(settings.database_path)
    photos = PhotoStore(Path(settings.photos_dir or Path(settings.database_path).parent / "photos"), settings.app_api_key)
    db.photo_url = photos.url
    app.state.db = db
    app.state.photos = photos
    app.state.store = JobStore(db)
    app.state.claude = ClaudeService(settings)
    app.state.library = Library(db, make_geocoder(settings), photos=photos)
    app.state.pipeline = Pipeline(settings, app.state.store, app.state.claude, app.state.library)
    app.state.router = Router(db, settings)
    app.state.push = Push(db, Path(settings.database_path).parent / "vapid_private.pem", settings.push_contact)
    app.state.curator = Curator(db, app.state.claude)
    app.state.events = EventsService(db, app.state.claude, Ticketmaster(settings), app.state.library)
    app.state.packing = PackingService(db, app.state.claude, Weather(settings), app.state.library)
    fetcher = SafeFetcher()
    renderer = BrowserRenderer(fetcher, settings.menu_browser_path) if settings.menu_browser and browser_available() else None
    app.state.menus = MenuService(db, app.state.claude, fetcher, app.state.library.geocoder, settings, renderer)
    app.state.pipeline.on_finished = lambda job: notify_import(app, job)


async def notify_import(app: FastAPI, job: Optional[Job]) -> None:
    """Push notification when an import finishes, since sharing from TikTok happens in the background."""
    if job is None or not getattr(app.state, "push", None):
        return
    trip = app.state.db.get_trip(job.trip_id) if job.trip_id else None
    if job.status == JobStatus.done:
        n = job.added_places
        if trip and n:
            title = f"{n} new place{'s' if n != 1 else ''} saved to {trip.name}"
        elif trip:
            title = f"Already saved in {trip.name}"
        else:
            title = "No places found in that reel"
        body = (job.result.title if job.result and job.result.title else job.message) or ""
        if job.reel and job.reel.uploader:
            body = f"{body} · @{job.reel.uploader}" if body else f"@{job.reel.uploader}"
        url = f"/#/trip/{trip.id}" if trip else "/#/imports"
    else:
        title, body, url = "Couldn't import a reel", job.message or "Tap to see what happened", "/#/imports"
    await app.state.push.send_all({"title": title, "body": body, "url": url, "tag": job.id})

@asynccontextmanager
async def lifespan(app: FastAPI):
    if not hasattr(app.state, "pipeline"):  # tests inject their own services
        build_services(app, get_settings())
    app.state.tasks = set()
    # Pick up imports that were interrupted by a restart.
    for job in app.state.db.unfinished_jobs():
        start_job(app, job.id, job.url, app.state.db.job_shared_text(job.id))
    yield


app = FastAPI(title="TripIt.ai", lifespan=lifespan)


def start_job(app: FastAPI, job_id: str, url: str, shared_text: Optional[str]) -> None:
    task = asyncio.create_task(app.state.pipeline.run(job_id, url, shared_text))
    app.state.tasks.add(task)
    task.add_done_callback(app.state.tasks.discard)


def require_api_key(
    settings: Annotated[Settings, Depends(get_settings)],
    x_api_key: Annotated[Optional[str], Header()] = None,
) -> None:
    if settings.app_api_key and not secrets.compare_digest(x_api_key or "", settings.app_api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")


Auth = Depends(require_api_key)


def _db(request: Request) -> Database:
    return request.app.state.db


def _library(request: Request) -> Library:
    return request.app.state.library


def _trip_or_404(request: Request, trip_id: str) -> TripDetail:
    trip = _db(request).get_trip_detail(trip_id)
    if trip is None:
        raise HTTPException(status_code=404, detail="Trip not found")
    return trip


def _place_or_404(request: Request, place_id: str) -> Place:
    place = _db(request).get_place(place_id)
    if place is None:
        raise HTTPException(status_code=404, detail="Place not found")
    return place


@app.get("/health")
async def health() -> dict:
    return {"ok": True}


@app.get("/v1/config", dependencies=[Auth])
async def config(request: Request, settings: Annotated[Settings, Depends(get_settings)]) -> dict:
    """Also used by the web app to check the API key."""
    geocoder = request.app.state.library.geocoder
    name = "google" if isinstance(geocoder, GooglePlacesGeocoder) else "none" if isinstance(geocoder, NoGeocoder) else "openstreetmap"
    return {
        "ok": True,
        "geocoder": name,
        "routing": request.app.state.router.provider,
        "google_maps_key": settings.google_maps_browser_key or None,
        "push_public_key": request.app.state.push.public_key if getattr(request.app.state, "push", None) else None,
    }


# ---------- Imports (jobs) ----------


@app.post("/v1/jobs", response_model=Job, status_code=202, dependencies=[Auth])
async def create_job(body: CreateJobRequest, request: Request) -> Job:
    # The iOS Shortcut may send the link in either field, wrapped in caption text.
    url = find_url(body.url) or find_url(body.shared_text or "") or body.url.strip()
    try:
        platform_for(url)
    except UnsupportedURLError as e:
        raise HTTPException(status_code=422, detail=str(e))

    shared_text = body.shared_text if body.shared_text and body.shared_text.strip() != url else None
    job, created = await request.app.state.store.create(url, shared_text)
    if created:
        start_job(request.app, job.id, url, shared_text)
    return job


def _decode_images(items: list[str]) -> list[bytes]:
    images = []
    for item in items:
        data = item.split(",", 1)[1] if item.startswith("data:") else item
        try:
            raw = base64.b64decode(data, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(status_code=422, detail="One of the images couldn't be read")
        if len(raw) > 6 * 1024 * 1024:
            raise HTTPException(status_code=422, detail="Each image must be under 6 MB")
        if not raw.startswith(b"\xff\xd8\xff"):
            raise HTTPException(status_code=422, detail="Images must be JPEGs")
        images.append(raw)
    return images


@app.post("/v1/jobs/screenshots", response_model=Job, status_code=202, dependencies=[Auth])
async def create_screenshot_job(body: ScreenshotJobRequest, request: Request) -> Job:
    """Finds places in screenshots (of a post, map or article) instead of a reel link."""
    images = _decode_images(body.images)
    url = request.app.state.pipeline.save_upload(images)
    note = (body.note or "").strip() or None
    job, _ = await request.app.state.store.create(url, note)
    start_job(request.app, job.id, url, note)
    return job


@app.get("/v1/jobs", response_model=list[Job], dependencies=[Auth])
async def list_jobs(request: Request, limit: int = 30) -> list[Job]:
    jobs = request.app.state.store.list(min(max(limit, 1), 100))
    for job in jobs:
        job.result = None  # keep the list light; GET /v1/jobs/{id} has the full result
    return jobs


@app.get("/v1/jobs/{job_id}", response_model=Job, dependencies=[Auth])
async def get_job(job_id: str, request: Request) -> Job:
    job = request.app.state.store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/v1/jobs/{job_id}/retry", response_model=Job, dependencies=[Auth])
async def retry_job(job_id: str, request: Request) -> Job:
    store = request.app.state.store
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != JobStatus.failed:
        raise HTTPException(status_code=409, detail="Only failed imports can be retried")
    store.update(job_id, status=JobStatus.queued, message="Retrying", warnings=[])
    start_job(request.app, job_id, job.url, _db(request).job_shared_text(job_id))
    return store.get(job_id)


# ---------- Trips ----------


@app.get("/v1/trips", response_model=list[Trip], dependencies=[Auth])
async def list_trips(request: Request) -> list[Trip]:
    return _db(request).list_trips()


@app.get("/v1/trips/{trip_id}", response_model=TripDetail, dependencies=[Auth])
async def get_trip(trip_id: str, request: Request) -> TripDetail:
    return _trip_or_404(request, trip_id)


@app.patch("/v1/trips/{trip_id}", response_model=TripDetail, dependencies=[Auth])
async def update_trip(trip_id: str, body: TripUpdate, request: Request) -> TripDetail:
    _trip_or_404(request, trip_id)
    changes = {k: getattr(body, k) for k in body.model_fields_set}
    if changes.get("name") is None:
        changes.pop("name", None)
    _db(request).update_trip(trip_id, **changes)
    return _trip_or_404(request, trip_id)


@app.delete("/v1/trips/{trip_id}", status_code=204, dependencies=[Auth])
async def delete_trip(trip_id: str, request: Request) -> Response:
    _trip_or_404(request, trip_id)
    _library(request).delete_trip(trip_id)
    return Response(status_code=204)


@app.post("/v1/trips/{trip_id}/plan", response_model=TripDetail, dependencies=[Auth])
async def plan_trip(trip_id: str, body: PlanTripRequest, request: Request) -> TripDetail:
    trip = _trip_or_404(request, trip_id)
    if not trip.places:
        raise HTTPException(status_code=422, detail="Save some places to this trip first")
    return await _library(request).plan_trip(
        trip_id, body.days, body.start_date, body.preferences, request.app.state.claude
    )


@app.delete("/v1/trips/{trip_id}/plan", response_model=TripDetail, dependencies=[Auth])
async def clear_plan(trip_id: str, request: Request) -> TripDetail:
    _trip_or_404(request, trip_id)
    _library(request).clear_plan(trip_id)
    return _trip_or_404(request, trip_id)


@app.post("/v1/trips/{trip_id}/days/{day}/order", response_model=TripDetail, dependencies=[Auth])
async def reorder_day(trip_id: str, day: int, body: ReorderRequest, request: Request) -> TripDetail:
    _trip_or_404(request, trip_id)
    _library(request).reorder_day(trip_id, day, body.place_ids)
    return _trip_or_404(request, trip_id)


@app.post("/v1/trips/{trip_id}/move", response_model=TripDetail, dependencies=[Auth])
async def move_in_itinerary(trip_id: str, body: MoveRequest, request: Request) -> TripDetail:
    """Drag and drop: puts a place at a position in a day (day 0 = not scheduled)."""
    _trip_or_404(request, trip_id)
    place = _place_or_404(request, body.place_id)
    if place.trip_id != trip_id:
        raise HTTPException(status_code=404, detail="Place not found in this trip")
    _library(request).move_to(place, body.day or None, body.index)
    return _trip_or_404(request, trip_id)


@app.post("/v1/trips/{trip_id}/add-to-day", response_model=TripDetail, dependencies=[Auth])
async def add_to_day(trip_id: str, body: AddToDayRequest, request: Request) -> TripDetail:
    """Builds the itinerary by hand: puts the chosen places at the end of a day (a new day when none is given)."""
    trip = _trip_or_404(request, trip_id)
    known = {p.id for p in trip.places}
    if any(pid not in known for pid in body.place_ids):
        raise HTTPException(status_code=422, detail="Pick places from one trip")
    try:
        _library(request).add_to_day(trip_id, body.place_ids, body.day)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _trip_or_404(request, trip_id)


@app.post("/v1/trips/{trip_id}/tidy", response_model=TripDetail, dependencies=[Auth])
async def tidy_trip(trip_id: str, body: TidyRequest, request: Request) -> TripDetail:
    """Optional AI pass over a hand-built itinerary: orders stops, suggests times, follows an instruction."""
    _trip_or_404(request, trip_id)
    try:
        await _library(request).tidy_trip(trip_id, body.instruction, request.app.state.claude)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _trip_or_404(request, trip_id)


# ---------- What's on ----------


@app.get("/v1/trips/{trip_id}/events", response_model=TripEvents, dependencies=[Auth])
async def trip_events(trip_id: str, request: Request) -> TripEvents:
    """Events near the trip during its dates, matched to the person's taste (Ticketmaster)."""
    trip = _trip_or_404(request, trip_id)
    return await request.app.state.events.get(trip, request.app.state.curator.profile())


@app.post("/v1/trips/{trip_id}/events/refresh", response_model=TripEvents, dependencies=[Auth])
async def refresh_trip_events(trip_id: str, request: Request) -> TripEvents:
    trip = _trip_or_404(request, trip_id)
    return await request.app.state.events.get(trip, request.app.state.curator.profile(), refresh=True)


@app.post("/v1/trips/{trip_id}/events/{event_id}/add", response_model=TripDetail, dependencies=[Auth])
async def add_event_to_trip(trip_id: str, event_id: str, request: Request) -> TripDetail:
    """Saves an event as a stop on the trip, on its day with its start time."""
    trip = _trip_or_404(request, trip_id)
    place, _created = await request.app.state.events.add_to_trip(trip, event_id)
    if place is None:
        raise HTTPException(status_code=404, detail="That event isn't in the list any more. Refresh it.")
    return _trip_or_404(request, trip_id)


# ---------- Packing ----------


@app.get("/v1/trips/{trip_id}/packing", response_model=Optional[PackingList], dependencies=[Auth])
async def get_packing(trip_id: str, request: Request) -> Optional[PackingList]:
    """The trip's packing list, or null when none has been made yet."""
    _trip_or_404(request, trip_id)
    return request.app.state.packing.get(trip_id)


@app.post("/v1/trips/{trip_id}/packing", response_model=PackingList, dependencies=[Auth])
async def make_packing(trip_id: str, request: Request, body: Optional[PackingRequest] = None) -> PackingList:
    """Writes (or rewrites) the list from the trip's days, stops, weather and the person's taste. Items they
    added stay, and ticked items stay ticked."""
    trip = _trip_or_404(request, trip_id)
    body = body or PackingRequest()
    return await request.app.state.packing.generate(trip, request.app.state.curator.profile(), body.carry_on_only, body.keep_packed)


@app.post("/v1/trips/{trip_id}/packing/items", response_model=PackingList, status_code=201, dependencies=[Auth])
async def add_packing_item(trip_id: str, body: PackingItemInput, request: Request) -> PackingList:
    _trip_or_404(request, trip_id)
    if not body.text:
        raise HTTPException(status_code=422, detail="What should be on the list?")
    result = request.app.state.packing.add_item(trip_id, body.text, body.group or "other")
    if result is None:
        raise HTTPException(status_code=404, detail="Make the packing list first")
    return result


@app.patch("/v1/trips/{trip_id}/packing/items/{item_id}", response_model=PackingList, dependencies=[Auth])
async def update_packing_item(trip_id: str, item_id: str, body: PackingItemInput, request: Request) -> PackingList:
    _trip_or_404(request, trip_id)
    result = request.app.state.packing.update_item(trip_id, item_id, body.model_dump(exclude_none=True))
    if result is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return result


@app.delete("/v1/trips/{trip_id}/packing/items/{item_id}", response_model=PackingList, dependencies=[Auth])
async def delete_packing_item(trip_id: str, item_id: str, request: Request) -> PackingList:
    _trip_or_404(request, trip_id)
    result = request.app.state.packing.delete_item(trip_id, item_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return result


# ---------- Bookings ----------


def _booking_or_404(request: Request, trip_id: str, booking_id: str) -> Booking:
    booking = _db(request).get_booking(booking_id)
    if booking is None or booking.trip_id != trip_id:
        raise HTTPException(status_code=404, detail="Booking not found")
    return booking


def _check_booking_place(request: Request, trip_id: str, place_id: Optional[str]) -> None:
    if place_id:
        place = _db(request).get_place(place_id)
        if place is None or place.trip_id != trip_id:
            raise HTTPException(status_code=422, detail="That place isn't in this trip")


@app.post("/v1/trips/{trip_id}/bookings/read", response_model=list[BookingDraft], dependencies=[Auth])
async def read_bookings(trip_id: str, body: ReadBookingsRequest, request: Request) -> list[BookingDraft]:
    """Reads flights, stays and reservations from pasted text or screenshots. Nothing is saved: the app shows
    the result for the person to check, then saves each booking with POST /v1/trips/{id}/bookings."""
    trip = _trip_or_404(request, trip_id)
    text = (body.text or "").strip() or None
    if not text and not body.images:
        raise HTTPException(status_code=422, detail="Paste the confirmation or add a screenshot")
    images = _decode_images(body.images)
    try:
        result = await request.app.state.claude.extract_bookings(
            text, images, date.today().isoformat(), trip.name, trip.start_date.isoformat() if trip.start_date else None)
    except ClaudeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return _library(request).clean_drafts(result.bookings)


@app.post("/v1/trips/{trip_id}/bookings", response_model=TripDetail, status_code=201, dependencies=[Auth])
async def add_booking(trip_id: str, body: BookingInput, request: Request) -> TripDetail:
    _trip_or_404(request, trip_id)
    if not body.kind or not body.title:
        raise HTTPException(status_code=422, detail="A booking needs a type and a name")
    _check_booking_place(request, trip_id, body.place_id)
    fields = {k: getattr(body, k) for k in body.model_fields_set if k != "place_id" or body.kind == "reservation"}
    _library(request).add_booking(trip_id, fields)
    return _trip_or_404(request, trip_id)


@app.patch("/v1/trips/{trip_id}/bookings/{booking_id}", response_model=TripDetail, dependencies=[Auth])
async def update_booking(trip_id: str, booking_id: str, body: BookingInput, request: Request) -> TripDetail:
    booking = _booking_or_404(request, trip_id, booking_id)
    changes = {k: getattr(body, k) for k in body.model_fields_set}
    if "kind" in changes and changes["kind"] is None or "title" in changes and changes["title"] is None:
        raise HTTPException(status_code=422, detail="A booking needs a type and a name")
    if changes.get("place_id"):
        _check_booking_place(request, trip_id, changes["place_id"])
    _library(request).update_booking(booking, changes)
    return _trip_or_404(request, trip_id)


@app.delete("/v1/trips/{trip_id}/bookings/{booking_id}", response_model=TripDetail, dependencies=[Auth])
async def delete_booking(trip_id: str, booking_id: str, request: Request) -> TripDetail:
    booking = _booking_or_404(request, trip_id, booking_id)
    _library(request).delete_booking(booking)
    return _trip_or_404(request, trip_id)


@app.post("/v1/trips/{trip_id}/refresh-details", response_model=TripDetail, dependencies=[Auth])
async def refresh_details(trip_id: str, request: Request) -> TripDetail:
    """Looks up opening hours (and missing pins) for places that haven't been checked yet."""
    _trip_or_404(request, trip_id)
    await _library(request).refresh_details(trip_id)
    return _trip_or_404(request, trip_id)


@app.get("/v1/trips/{trip_id}/days/{day}/legs", response_model=DayLegs, dependencies=[Auth])
async def day_legs(trip_id: str, day: int, request: Request) -> DayLegs:
    trip = _trip_or_404(request, trip_id)
    stops = sorted((p for p in trip.places if p.day_number == day), key=lambda p: p.day_order)
    router: Router = request.app.state.router
    legs = await router.day_legs(stops)
    return DayLegs(day=day, provider=router.provider, legs=legs)


@app.post("/v1/routes/from", response_model=RoutesFromResponse, dependencies=[Auth])
async def routes_from(body: RoutesFromRequest, request: Request) -> RoutesFromResponse:
    """Travel times from a point (your current location) to the given places."""
    db = _db(request)
    places = [p for p in (db.get_place(pid) for pid in body.place_ids) if p is not None]
    router: Router = request.app.state.router
    legs = await router.from_point((body.latitude, body.longitude), places)
    return RoutesFromResponse(provider=router.provider, legs=legs)


# ---------- Sharing & exports ----------


def _origin(request: Request) -> str:
    proto = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}"


@app.post("/v1/trips/{trip_id}/share", response_model=ShareLink, dependencies=[Auth])
async def share_trip(trip_id: str, request: Request) -> ShareLink:
    """Creates (or returns) a public read-only link to the trip."""
    trip = _trip_or_404(request, trip_id)
    token = trip.share_token or secrets.token_urlsafe(16)
    if not trip.share_token:
        _db(request).update_trip(trip_id, share_token=token)
    return ShareLink(token=token, path=f"/s/{token}")


@app.delete("/v1/trips/{trip_id}/share", status_code=204, dependencies=[Auth])
async def unshare_trip(trip_id: str, request: Request) -> Response:
    _trip_or_404(request, trip_id)
    _db(request).update_trip(trip_id, share_token=None)
    return Response(status_code=204)


def _shared_or_404(request: Request, token: str) -> TripDetail:
    trip = _db(request).trip_by_share_token(token)
    if trip is None:
        raise HTTPException(status_code=404, detail="This trip link isn't available")
    return trip


def _public_trip(trip: TripDetail, settings: Settings) -> dict:
    """What a shared link shows: everything but your own notes."""
    data = trip.model_dump(mode="json", exclude={"share_token", "bookings"})
    for p in data["places"]:
        for key in ("user_notes", "hours_checked_at", "photos_checked_at", "rating_checked_at", "contact_checked_at", "reserve_checked_at"):
            p.pop(key, None)
    data["reels"] = [
        {k: r[k] for k in ("id", "url", "platform", "title", "creator")}
        for r in data["reels"] if r["url"].startswith("http")
    ]
    data["google_maps_key"] = settings.google_maps_browser_key or None
    return data


@app.get("/v1/shared/{token}", include_in_schema=False)
async def shared_trip(token: str, request: Request, settings: Annotated[Settings, Depends(get_settings)]) -> dict:
    return _public_trip(_shared_or_404(request, token), settings)


@app.get("/s/{token}", include_in_schema=False)
async def shared_page(token: str, request: Request) -> HTMLResponse:
    trip = _db(request).trip_by_share_token(token)
    if trip is None:
        return HTMLResponse(NOT_SHARED_PAGE, status_code=404)
    origin = _origin(request)
    days = f" · {trip.day_count}-day plan" if trip.day_count else ""
    values = {
        "title": f"{trip.name} · TripIt",
        "description": f"{len(trip.places)} saved place{'s' if len(trip.places) != 1 else ''}{days}. Open for the map and itinerary.",
        "image": f"{origin}{trip.cover_photo.url}&w=1200" if trip.cover_photo else f"{origin}/icons/icon-512.png",
        "url": f"{origin}/s/{token}",
    }
    page = (STATIC_DIR / "shared.html").read_text()
    for key, value in values.items():
        page = page.replace("{{" + key + "}}", html.escape(value, quote=True))
    return HTMLResponse(page, headers={"Cache-Control": "no-cache", "X-Robots-Tag": "noindex"})


NOT_SHARED_PAGE = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>TripIt</title><style>body{font:17px -apple-system,system-ui,sans-serif;display:grid;place-items:center;min-height:90vh;margin:0;
text-align:center;color:#3c3c43;background:#f2f2f7}h1{font-size:22px;color:#000}</style>
<div><h1>This trip link isn't available</h1><p>It may have been turned off by the person who shared it.</p></div>"""


def _export_response(trip: TripDetail, fmt: str) -> Response:
    ascii_name = re.sub(r"[^A-Za-z0-9 _-]", "", trip.name).strip() or "trip"
    disposition = "inline" if fmt == "ics" else "attachment"
    headers = {"Content-Disposition": f'{disposition}; filename="{ascii_name}.{fmt}"; filename*=UTF-8\'\'{quote(trip.name)}.{fmt}'}
    if fmt == "ics":
        try:
            return Response(ics(trip), media_type="text/calendar; charset=utf-8", headers=headers)
        except ExportError as e:
            raise HTTPException(status_code=422, detail=str(e))
    return Response(kml(trip), media_type="application/vnd.google-earth.kml+xml", headers=headers)


def _export_sig(settings: Settings, trip_id: str, fmt: str, exp: int) -> str:
    return hmac.new(settings.app_api_key.encode(), f"export:{trip_id}:{fmt}:{exp}".encode(), hashlib.sha256).hexdigest()[:32]


@app.post("/v1/trips/{trip_id}/export-link", dependencies=[Auth])
async def export_link(
    trip_id: str, request: Request, settings: Annotated[Settings, Depends(get_settings)],
    format: str = Query(pattern="^(ics|kml)$"),
) -> dict:
    """A short-lived download link (the browser opens it directly, so it can't send the API key)."""
    trip = _trip_or_404(request, trip_id)
    if format == "ics":
        try:
            schedule(trip)
        except ExportError as e:
            raise HTTPException(status_code=422, detail=str(e))
    elif not any(p.latitude is not None for p in trip.places):
        raise HTTPException(status_code=422, detail="None of this trip's places are on the map yet")
    exp = int(time.time()) + 3600
    return {"url": f"/v1/trips/{trip_id}/export.{format}?exp={exp}&sig={_export_sig(settings, trip_id, format, exp)}"}


@app.get("/v1/trips/{trip_id}/export.{fmt}", include_in_schema=False)
async def export_file(
    trip_id: str, fmt: str, request: Request, settings: Annotated[Settings, Depends(get_settings)], exp: int = 0, sig: str = "",
) -> Response:
    if fmt not in ("ics", "kml"):
        raise HTTPException(status_code=404, detail="Not found")
    if exp < time.time() or not hmac.compare_digest(_export_sig(settings, trip_id, fmt, exp), sig):
        raise HTTPException(status_code=403, detail="This export link expired. Export again from the app.")
    return _export_response(_trip_or_404(request, trip_id), fmt)


@app.get("/s/{token}/trip.{fmt}", include_in_schema=False)
async def shared_export(token: str, fmt: str, request: Request) -> Response:
    if fmt not in ("ics", "kml"):
        raise HTTPException(status_code=404, detail="Not found")
    return _export_response(_shared_or_404(request, token), fmt)


# ---------- Taste profile, edits, concierge, briefings ----------


def _curator(request: Request) -> Curator:
    return request.app.state.curator


@app.get("/v1/profile", response_model=TasteProfile, dependencies=[Auth])
async def get_profile(request: Request) -> TasteProfile:
    return _curator(request).profile()


@app.put("/v1/profile", response_model=TasteProfile, dependencies=[Auth])
async def put_profile(body: TasteProfile, request: Request) -> TasteProfile:
    body.food = [f.strip()[:40] for f in body.food if f.strip()]
    body.interests = [i.strip()[:40] for i in body.interests if i.strip()]
    return _curator(request).save_profile(body)


@app.get("/v1/edits", response_model=list[TripEdits], dependencies=[Auth])
async def all_edits(request: Request) -> list[TripEdits]:
    """Curated edits across trips, for the home screen."""
    out = []
    for trip in _db(request).list_trips():
        detail = _db(request).get_trip_detail(trip.id)
        edits = _curator(request).edits(detail)
        if edits.edits:
            out.append(edits)
    return out


@app.get("/v1/trips/{trip_id}/edits", response_model=TripEdits, dependencies=[Auth])
async def trip_edits(trip_id: str, request: Request) -> TripEdits:
    return _curator(request).edits(_trip_or_404(request, trip_id))


@app.post("/v1/trips/{trip_id}/edits", response_model=TripEdits, dependencies=[Auth])
async def curate_trip(trip_id: str, request: Request) -> TripEdits:
    """(Re)curates the trip's edits with Claude, or by simple rules if Claude is unavailable."""
    trip = _trip_or_404(request, trip_id)
    if len(trip.places) < 3:
        raise HTTPException(status_code=422, detail="Save at least three places to curate edits")
    return await _curator(request).curate(trip)


@app.post("/v1/concierge", response_model=ConciergeReply, dependencies=[Auth])
async def concierge(body: ConciergeRequest, request: Request) -> ConciergeReply:
    if body.trip_id:
        _trip_or_404(request, body.trip_id)
    try:
        return await _curator(request).chat(body)
    except ClaudeError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/v1/trips/{trip_id}/days/{day}/briefing", response_model=DayBriefing, dependencies=[Auth])
async def day_briefing(trip_id: str, day: int, body: BriefingRequest, request: Request) -> DayBriefing:
    trip = _trip_or_404(request, trip_id)
    try:
        return await _curator(request).briefing(trip, day, body.local_date, body.refresh)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ---------- Notifications ----------


def _push(request: Request) -> Push:
    return request.app.state.push


@app.get("/v1/push/key", dependencies=[Auth])
async def push_key(request: Request) -> dict:
    return {"public_key": _push(request).public_key}


@app.post("/v1/push/subscriptions", status_code=204, dependencies=[Auth])
async def push_subscribe(body: PushSubscriptionRequest, request: Request) -> Response:
    try:
        _push(request).subscribe(body.endpoint, body.keys.get("p256dh", ""), body.keys.get("auth", ""), _origin(request))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return Response(status_code=204)


@app.delete("/v1/push/subscriptions", status_code=204, dependencies=[Auth])
async def push_unsubscribe(body: PushSubscriptionRequest, request: Request) -> Response:
    _db(request).delete_push_subscription(body.endpoint)
    return Response(status_code=204)


@app.post("/v1/push/test", dependencies=[Auth])
async def push_test(request: Request) -> dict:
    sent = await _push(request).send_all({"title": "Notifications are on", "body": "TripIt will tell you when a reel's places are saved.",
                                          "url": "/#/settings", "tag": "test"})
    return {"sent": sent}


# ---------- Places & reels ----------


@app.get("/v1/places", response_model=list[Place], dependencies=[Auth])
async def list_places(request: Request) -> list[Place]:
    return _db(request).list_places()


@app.post("/v1/places/search", response_model=list[PlaceCandidate], dependencies=[Auth])
async def search_places(body: SearchPlacesRequest, request: Request) -> list[PlaceCandidate]:
    library = _library(request)
    matches = await library.geocoder.search(body.query.strip(), near=library.trip_center(body.trip_id), limit=6)
    return [
        PlaceCandidate(candidate_id=m.place_id, name=m.name, address=m.address, category=m.category or "other",
                       latitude=m.latitude, longitude=m.longitude)
        for m in matches if m.place_id
    ]


@app.post("/v1/places", response_model=AddPlaceResult, status_code=201, dependencies=[Auth])
async def add_place(body: AddPlaceRequest, request: Request, response: Response) -> AddPlaceResult:
    """Adds a place without a reel: a search result, or just a name."""
    library = _library(request)
    if body.trip_id and not _db(request).get_trip(body.trip_id):
        raise HTTPException(status_code=404, detail="Trip not found")
    if body.candidate_id:
        match = await library.geocoder.details(body.candidate_id)
        if match is None:
            raise HTTPException(status_code=422, detail="Couldn't load that place. Try searching again.")
        place, created = await library.add_match(match, body.trip_id)
    elif body.name:
        if not body.trip_id and not body.city:
            raise HTTPException(status_code=422, detail="Choose a trip or a city for this place")
        place, created = await library.add_by_name(body.name.strip(), body.trip_id, city=body.city, category=body.category.value)
    else:
        raise HTTPException(status_code=422, detail="Search for a place or enter its name")
    if not created:
        response.status_code = 200
    return AddPlaceResult(place=place, created=created)


@app.post("/v1/places/from-link", response_model=AddPlaceResult, status_code=201, dependencies=[Auth])
async def add_place_from_link(body: AddFromLinkRequest, request: Request, response: Response) -> AddPlaceResult:
    """Adds the place from a Google Maps or Apple Maps link."""
    if body.trip_id and not _db(request).get_trip(body.trip_id):
        raise HTTPException(status_code=404, detail="Trip not found")
    url = find_url(body.url) or body.url.strip()
    if not is_map_link(url):
        raise HTTPException(status_code=422, detail="Paste a Google Maps or Apple Maps link")
    try:
        link = parse_map_link(await resolve_map_link(url))
    except NotAMapLink as e:
        raise HTTPException(status_code=422, detail=str(e))
    place, created = await _library(request).add_from_link(link, body.trip_id)
    if not created:
        response.status_code = 200
    return AddPlaceResult(place=place, created=created)


@app.patch("/v1/places/{place_id}", response_model=Place, dependencies=[Auth])
async def update_place(place_id: str, body: PlaceUpdate, request: Request) -> Place:
    place = _place_or_404(request, place_id)
    db, library = _db(request), _library(request)
    fields = body.model_fields_set
    simple = {k: getattr(body, k) for k in ("name", "category", "visited", "user_notes", "must_do", "start_time")
              if k in fields and getattr(body, k) is not None}
    if "website" in fields and body.website is not None:
        site = clean_website(body.website) if body.website.strip() else None
        if body.website.strip() and not site:
            raise HTTPException(status_code=422, detail="That doesn't look like a website address")
        # A new website means the old menu and booking link were for something else: look again.
        db.update_place(place_id, website=site, contact_checked_at=datetime.now(timezone.utc), reserve_url=None,
                        reserve_provider=None, reserve_checked_at=None)
        db.delete_menu(place_id)
    if simple:
        db.update_place(place_id, **simple)
    if "day_number" in fields and body.day_number is not None:
        library.move_place(place, body.day_number or None)
    if body.clear_start_time:
        db.update_place(place_id, start_time=None)
    if body.clear_time_of_day:
        db.update_place(place_id, time_of_day=None)
    elif body.time_of_day is not None:
        db.update_place(place_id, time_of_day=body.time_of_day)
    return db.get_place(place_id)


@app.delete("/v1/places/{place_id}", status_code=204, dependencies=[Auth])
async def delete_place(place_id: str, request: Request) -> Response:
    _place_or_404(request, place_id)
    _library(request).delete_place(place_id)
    return Response(status_code=204)


@app.post("/v1/places/{place_id}/locate", response_model=Place, dependencies=[Auth])
async def locate_place(place_id: str, body: LocateRequest, request: Request) -> Place:
    place = _place_or_404(request, place_id)
    if not await _library(request).locate(place, query=body.query):
        raise HTTPException(status_code=422, detail="Couldn't find that on the map. Try adding the street or neighborhood.")
    return _db(request).get_place(place_id)


@app.post("/v1/places/{place_id}/reserve-link", response_model=Place, dependencies=[Auth])
async def find_reservation_link(place_id: str, request: Request) -> Place:
    """Looks on the restaurant's website for its Resy, OpenTable, Tock or SevenRooms page. Checked once."""
    place = _place_or_404(request, place_id)
    if place.category.value not in MENU_CATEGORIES or not place.website or place.reserve_checked_at is not None:
        return place
    found = await find_reserve_link(request.app.state.menus.fetcher, place.website)
    _db(request).update_place(
        place_id, reserve_provider=found[0] if found else None, reserve_url=found[1] if found else None,
        reserve_checked_at=datetime.now(timezone.utc),
    )
    return _db(request).get_place(place_id)


@app.post("/v1/places/{place_id}/menu/upload", response_model=PlaceMenu, dependencies=[Auth])
async def upload_menu(place_id: str, body: MenuUploadRequest, request: Request) -> PlaceMenu:
    """Reads a menu from photos or PDFs the person adds, for places whose website the server can't read."""
    place = _place_or_404(request, place_id)
    if place.category.value not in MENU_CATEGORIES:
        raise HTTPException(status_code=422, detail="Menus are for restaurants, cafés, bars and sweet shops")
    if not body.images and not body.pdfs:
        raise HTTPException(status_code=422, detail="Add a photo or a PDF of the menu")
    images = _decode_images(body.images)
    pdfs = []
    for item in body.pdfs:
        data = item.split(",", 1)[1] if item.startswith("data:") else item
        try:
            raw = base64.b64decode(data, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(status_code=422, detail="One of the PDFs couldn't be read")
        if len(raw) > 6 * 1024 * 1024 or not raw.startswith(b"%PDF"):
            raise HTTPException(status_code=422, detail="PDFs must be real PDF files under 6 MB")
        pdfs.append(raw)
    try:
        menu = await request.app.state.menus.read_upload(place, images, pdfs)
    except ClaudeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    if menu is None:
        raise HTTPException(status_code=422, detail="Couldn't find a menu in that. Try a clearer photo of the menu itself.")
    return menu


@app.get("/v1/places/{place_id}/menu", response_model=PlaceMenu, dependencies=[Auth])
async def get_menu(place_id: str, request: Request) -> PlaceMenu:
    """The menu saved for a place (status "unknown" when nobody has looked for one yet)."""
    _place_or_404(request, place_id)
    return request.app.state.menus.stored(place_id)


@app.post("/v1/places/{place_id}/menu", response_model=PlaceMenu, dependencies=[Auth])
async def find_menu(place_id: str, request: Request, body: Optional[MenuRequest] = None) -> PlaceMenu:
    """Looks for the menu on the place's website (then, if allowed, in its Google photos) and saves it."""
    place = _place_or_404(request, place_id)
    if place.category.value not in MENU_CATEGORIES:
        raise HTTPException(status_code=422, detail="Menus are for restaurants, cafés, bars and sweet shops")
    try:
        return await request.app.state.menus.find(place, refresh=bool(body and body.refresh))
    except ClaudeError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/v1/places/{place_id}/photos/{index}", include_in_schema=False)
async def place_photo(
    place_id: str, index: int, request: Request, settings: Annotated[Settings, Depends(get_settings)],
    sig: str = "", w: int = 1000,
):
    """Serves a place photo. Authorized by the signature in the URL, since <img> tags can't send headers."""
    refs = _db(request).photo_refs(place_id)
    if index < 0 or index >= len(refs):
        raise HTTPException(status_code=404, detail="Photo not found")
    photo = refs[index]
    if not request.app.state.photos.check(place_id, index, photo["ref"], sig):
        raise HTTPException(status_code=403, detail="Bad photo link")
    if photo["source"] == "reel":
        path = request.app.state.photos.path(photo["ref"])
        if not path:
            raise HTTPException(status_code=404, detail="Photo file missing")
        return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=2592000, immutable"})
    if photo["source"] == "wikimedia":
        return RedirectResponse(photo["ref"], status_code=302, headers={"Cache-Control": "private, max-age=86400"})
    if photo["source"] == "google" and settings.google_maps_api_key:
        width = min(max(w, 100), 1600)
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                r = await client.get(f"https://places.googleapis.com/v1/{photo['ref']}/media",
                                     params={"maxWidthPx": width, "key": settings.google_maps_api_key})
        except httpx.HTTPError:
            raise HTTPException(status_code=502, detail="Couldn't load photo")
        if r.status_code != 200:
            raise HTTPException(status_code=404, detail="Photo no longer available")
        return Response(r.content, media_type=r.headers.get("content-type", "image/jpeg"),
                        headers={"Cache-Control": "private, max-age=86400"})
    raise HTTPException(status_code=404, detail="Photo not available")


@app.get("/v1/reels", response_model=list[Reel], dependencies=[Auth])
async def list_reels(request: Request) -> list[Reel]:
    return _db(request).list_reels()


# Stateless planner kept for the native iOS app.
@app.post("/v1/itineraries", response_model=PlanResult, dependencies=[Auth])
async def plan_itinerary(body: PlanRequest, request: Request) -> PlanResult:
    try:
        return await request.app.state.claude.plan_itinerary(body)
    except ClaudeError as e:
        raise HTTPException(status_code=502, detail=str(e))


# ---------- Web app ----------


@lru_cache
def _static_version() -> str:
    """Changes whenever any web app file changes, so the service worker refreshes its cached copy."""
    digest = hashlib.sha256()
    for path in sorted(STATIC_DIR.rglob("*")):
        if path.is_file():
            digest.update(str(path.relative_to(STATIC_DIR)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


@app.get("/sw.js", include_in_schema=False)
async def service_worker() -> Response:
    body = (STATIC_DIR / "sw.js").read_text().replace("__VERSION__", _static_version())
    return Response(body, media_type="application/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/share", include_in_schema=False)
async def share_target() -> FileResponse:
    """Android's share sheet opens /share?url=…&text=… (Web Share Target); the web app handles it."""
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="web")
