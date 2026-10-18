import asyncio
import logging
import mimetypes
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Optional

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings, get_settings
from .db import Database
from .geocode import GooglePlacesGeocoder, NoGeocoder, make_geocoder
from .jobs import JobStore
from .library import Library
from .llm import ClaudeError, ClaudeService
from .media import UnsupportedURLError, find_url, platform_for
from .models import (
    CreateJobRequest,
    DayLegs,
    RoutesFromRequest,
    RoutesFromResponse,
    Job,
    JobStatus,
    LocateRequest,
    Place,
    PlaceUpdate,
    PlanRequest,
    PlanResult,
    PlanTripRequest,
    Reel,
    ReorderRequest,
    Trip,
    TripDetail,
    TripUpdate,
)
from .photos import PhotoStore
from .pipeline import Pipeline
from .routing import Router

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


# ---------- Places & reels ----------


@app.get("/v1/places", response_model=list[Place], dependencies=[Auth])
async def list_places(request: Request) -> list[Place]:
    return _db(request).list_places()


@app.patch("/v1/places/{place_id}", response_model=Place, dependencies=[Auth])
async def update_place(place_id: str, body: PlaceUpdate, request: Request) -> Place:
    place = _place_or_404(request, place_id)
    db, library = _db(request), _library(request)
    fields = body.model_fields_set
    simple = {k: getattr(body, k) for k in ("name", "category", "visited", "user_notes") if k in fields and getattr(body, k) is not None}
    if simple:
        db.update_place(place_id, **simple)
    if "day_number" in fields and body.day_number is not None:
        library.move_place(place, body.day_number or None)
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


@app.get("/share", include_in_schema=False)
async def share_target() -> FileResponse:
    """Android's share sheet opens /share?url=…&text=… (Web Share Target); the web app handles it."""
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="web")
