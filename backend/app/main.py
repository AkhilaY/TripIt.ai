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
from typing import Annotated, Literal, Optional
from urllib.parse import quote

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .concierge import Curator, profile_text
from .config import Settings, get_settings
from .auth import Accounts, AuthError, User
from .db import CURRENT_USER, Database
from .discover import DiscoverService
from .calendar import CalendarService
from .events import EventsService, Ticketmaster
from .lounges import LoungeService
from . import tripcheck
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
    TripStopsRequest,
    WeatherDay,
    AddFromLinkRequest,
    AddToDayRequest,
    Booking,
    BookingDraft,
    BookingInput,
    BookingListItem,
    CalendarFeed,
    CalendarResult,
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
    DiscoverArea,
    DiscoverKind,
    DiscoverResult,
    HomeRequest,
    Folder,
    FolderInput,
    FolderRename,
    NewTripRequest,
    PlaceIds,
    PlaceDetail,
    LoungeResult,
    HomeSetting,
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
from .needs import NeedsService
from .packing import PackingService
from .photos import PhotoStore
from .reserve import find_reserve_link
from .pipeline import Pipeline
from .monitoring import RateLimit, init_monitoring, report_client_error, report_feedback, set_user
from .push import ApnsConfig, Push
from .routing import Router
from .usage import BudgetExceeded, Usage
from .weather import Weather

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
mimetypes.add_type("application/manifest+json", ".webmanifest")

STATIC_DIR = Path(__file__).parent / "static"


def build_services(app: FastAPI, settings: Settings) -> None:
    db = Database(settings.database_path)
    photos = PhotoStore(Path(settings.photos_dir or Path(settings.database_path).parent / "photos"), settings.app_api_key)
    db.photo_url = photos.url
    app.state.db = db
    app.state.accounts = Accounts(db, settings.app_api_key)
    app.state.photos = photos
    app.state.store = JobStore(db)
    app.state.claude = ClaudeService(settings)
    app.state.claude.usage = usage = Usage(db, settings)
    app.state.library = Library(db, make_geocoder(settings), photos=photos)
    app.state.pipeline = Pipeline(settings, app.state.store, app.state.claude, app.state.library)
    app.state.router = Router(db, settings)
    app.state.router.meter = usage.record_google
    if hasattr(app.state.library.geocoder, "meter"):
        app.state.library.geocoder.meter = usage.record_google
    app.state.push = Push(db, Path(settings.database_path).parent / "vapid_private.pem", settings.push_contact,
                          apns=ApnsConfig.from_settings(settings))
    app.state.curator = Curator(db, app.state.claude)
    app.state.discover = DiscoverService(db, app.state.claude, app.state.library.geocoder, photos)
    app.state.lounges = LoungeService(db, app.state.claude)
    cur = app.state.curator
    cur.geocoder, cur.photo_url = app.state.library.geocoder, app.state.discover.photo_url
    cur.web, cur.web_searches = settings.edits_web, settings.edits_web_searches
    app.state.calendar = CalendarService(db, photos)
    app.state.needs = NeedsService(db, app.state.claude)
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
    places = [p for p in app.state.db.list_places(saved_only=True) if job.reel_id and job.reel_id in p.reel_ids]
    cities = [p.city for p in places if p.city]
    city = max(set(cities), key=cities.count) if cities else None
    if job.status == JobStatus.done:
        n = job.added_places
        where = f" in {city}" if city else ""
        if n:
            title = f"{n} new place{'s' if n != 1 else ''} saved{where}"
        elif places:
            title = f"Already in your saved places{where}"
        else:
            title = "No places found in that reel"
        body = (job.result.title if job.result and job.result.title else job.message) or ""
        if job.reel and job.reel.uploader:
            body = f"{body} · @{job.reel.uploader}" if body else f"@{job.reel.uploader}"
        url = f"/#/saved?reel={job.reel_id}" if places else "/#/imports"
    else:
        title, body, url = "Couldn't import a reel", job.message or "Tap to see what happened", "/#/imports"
    await app.state.push.send_all({"title": title, "body": body, "url": url, "tag": job.id})

@asynccontextmanager
async def lifespan(app: FastAPI):
    if not hasattr(app.state, "pipeline"):  # tests inject their own services
        build_services(app, get_settings())
    app.state.tasks = set()
    # Pick up imports that were interrupted by a restart, each as the person who started it.
    for job in app.state.db.unfinished_jobs():
        reset = CURRENT_USER.set(job.user_id)
        try:
            start_job(app, job.id, job.url, app.state.db.job_shared_text(job.id))
        finally:
            CURRENT_USER.reset(reset)
    yield


init_monitoring(get_settings())
app = FastAPI(title="TripIt.ai", lifespan=lifespan)


def start_job(app: FastAPI, job_id: str, url: str, shared_text: Optional[str]) -> None:
    task = asyncio.create_task(app.state.pipeline.run(job_id, url, shared_text))
    app.state.tasks.add(task)
    task.add_done_callback(app.state.tasks.discard)


SESSION_COOKIE = "tripit_session"
IMPORT_PATHS = {"/v1/jobs", "/v1/jobs/screenshots"}


def _accounts(request: Request) -> Accounts:
    return request.app.state.accounts


async def authenticate(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    x_api_key: Annotated[Optional[str], Header()] = None,
    authorization: Annotated[Optional[str], Header()] = None,
    x_tripit: Annotated[Optional[str], Header()] = None,
) -> Optional[User]:
    """Works out who is asking and limits the request to their data (see db.CURRENT_USER).

    - A session: the web app's cookie, or "Authorization: Bearer <token>" from the iOS app.
    - X-API-Key: the server key (the owner, or everyone's shared data before accounts existed), or someone's
      personal Shortcut key, which may only send links and screenshots to import.
    Async on purpose: it must run in the request's own task so the user it sets carries into the endpoint."""
    accounts = _accounts(request)
    user: Optional[User] = None
    if authorization and authorization.lower().startswith("bearer "):
        user = accounts.session_user(authorization[7:].strip())
        if user is None:
            raise HTTPException(status_code=401, detail="Your session has ended. Sign in again.")
    elif request.cookies.get(SESSION_COOKIE):
        user = accounts.session_user(request.cookies[SESSION_COOKIE])
        if user is not None and request.method not in ("GET", "HEAD", "OPTIONS") and x_tripit != "1":
            raise HTTPException(status_code=403, detail="This request didn't come from the app")
        if user is None and not x_api_key:
            raise HTTPException(status_code=401, detail="Your session has ended. Sign in again.")
    if user is None and x_api_key:
        if settings.app_api_key and secrets.compare_digest(x_api_key, settings.app_api_key):
            user = accounts.owner()  # None until the first account exists: the old single-user setup
        else:
            found = accounts.key_user(x_api_key)
            if found is None:
                raise HTTPException(status_code=401, detail="Invalid API key")
            user, scope = found
            if scope == "import" and not (request.method == "POST" and request.url.path in IMPORT_PATHS):
                raise HTTPException(status_code=403, detail="This key can only send links to The Travel Edit")
    elif user is None:
        if settings.app_api_key:
            raise HTTPException(status_code=401, detail="Sign in to The Travel Edit")
        user = accounts.owner()  # local development without a key
    CURRENT_USER.set(user.id if user else None)
    request.state.user = user
    set_user(user.id if user else None)
    return user


Auth = Depends(authenticate)


def _me(request: Request) -> User:
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=403, detail="Create your account first")
    return user


def _claude_http(e: ClaudeError) -> HTTPException:
    """429 when a budget or today's limit stopped the call (the message says when it resets), else 502."""
    return HTTPException(status_code=429 if isinstance(e, BudgetExceeded) else 502, detail=str(e))


def _allow(request: Request, feature: str) -> None:
    """Turns work away up front (before downloading a reel, say) when its AI call wouldn't be allowed."""
    usage = getattr(request.app.state.claude, "usage", None)
    if usage is not None:
        try:
            usage.check(feature)
        except BudgetExceeded as e:
            raise _claude_http(e)


def _count_google(request: Request, kind: str) -> None:
    usage = getattr(request.app.state.claude, "usage", None)
    if usage is not None:
        usage.record_google(kind)


def _admin(request: Request) -> User:
    user = _me(request)
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Only the owner can do that")
    return user


def _db(request: Request) -> Database:
    return request.app.state.db


def _library(request: Request) -> Library:
    return request.app.state.library


def _trip_or_404(request: Request, trip_id: str) -> TripDetail:
    trip = _db(request).get_trip_detail(trip_id)
    if trip is None:
        raise HTTPException(status_code=404, detail="Trip not found")
    trip.closures = tripcheck.closures(trip)
    return trip


def _place_or_404(request: Request, place_id: str) -> Place:
    place = _db(request).get_place(place_id)
    if place is None:
        raise HTTPException(status_code=404, detail="Place not found")
    return place


# ---------- Accounts ----------


class SignUpRequest(BaseModel):
    email: str = Field(max_length=200)
    password: str = Field(max_length=200)
    invite: str = Field(max_length=200)
    name: str = Field(default="", max_length=80)


class SignInRequest(BaseModel):
    email: str = Field(max_length=200)
    password: str = Field(max_length=200)


class PasswordChange(BaseModel):
    current: str = Field(max_length=200)
    new: str = Field(max_length=200)


class PasswordCheck(BaseModel):
    password: str = Field(max_length=200)


class InviteRequest(BaseModel):
    note: str = Field(default="", max_length=80)


class MeOut(BaseModel):
    id: str
    email: str
    name: str
    is_admin: bool
    has_import_key: bool = False


class SessionOut(BaseModel):
    user: MeOut
    token: str  # for the iOS app's "Authorization: Bearer"; the web app uses the cookie


def _me_out(request: Request, user: User) -> MeOut:
    return MeOut(id=user.id, email=user.email, name=user.name, is_admin=user.is_admin,
                 has_import_key=_accounts(request).has_import_key(user))


def _start_session(request: Request, response: Response, user: User) -> SessionOut:
    token = _accounts(request).new_session(user, request.headers.get("user-agent", ""))
    https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(SESSION_COOKIE, token, max_age=90 * 86400, httponly=True, secure=https, samesite="lax", path="/")
    return SessionOut(user=_me_out(request, user), token=token)


@app.get("/v1/auth/status")
async def auth_status(request: Request) -> dict:
    """Whether accounts exist yet (if not, the first one is made with the server key) and whether you're signed in."""
    accounts = _accounts(request)
    signed_in = accounts.session_user(request.cookies.get(SESSION_COOKIE, "")) is not None
    return {"accounts": accounts.owner() is not None, "signed_in": signed_in}


@app.post("/v1/auth/signup", response_model=SessionOut, status_code=201)
async def sign_up(body: SignUpRequest, request: Request, response: Response) -> SessionOut:
    try:
        user = _accounts(request).sign_up(body.email, body.password, body.invite, body.name)
    except AuthError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _start_session(request, response, user)


@app.post("/v1/auth/login", response_model=SessionOut)
async def sign_in(body: SignInRequest, request: Request, response: Response) -> SessionOut:
    try:
        user = _accounts(request).sign_in(body.email, body.password)
    except AuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    return _start_session(request, response, user)


@app.post("/v1/auth/logout", status_code=204)
async def sign_out(request: Request, response: Response, authorization: Annotated[Optional[str], Header()] = None) -> Response:
    token = request.cookies.get(SESSION_COOKIE) or (authorization[7:].strip() if authorization and authorization.lower().startswith("bearer ") else "")
    if token:
        _accounts(request).end_session(token)
    out = Response(status_code=204)
    out.delete_cookie(SESSION_COOKIE, path="/")
    return out


@app.get("/v1/me", response_model=Optional[MeOut], dependencies=[Auth])
async def me(request: Request) -> Optional[MeOut]:
    """You, or null in the single-user setup from before accounts."""
    user = getattr(request.state, "user", None)
    return _me_out(request, user) if user else None


@app.post("/v1/me/password", status_code=204, dependencies=[Auth])
async def change_password(body: PasswordChange, request: Request) -> Response:
    try:
        _accounts(request).change_password(_me(request), body.current, body.new)
    except AuthError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return Response(status_code=204)


@app.post("/v1/me/import-key", dependencies=[Auth])
async def new_import_key(request: Request) -> dict:
    """A personal key for the iPhone share Shortcut. It can only send links and screenshots; a new one replaces the old."""
    return {"key": _accounts(request).new_import_key(_me(request))}


@app.delete("/v1/me", status_code=204, dependencies=[Auth])
async def delete_account(body: PasswordCheck, request: Request) -> Response:
    """Deletes your account and everything in it: places, folders, trips, bookings and photos."""
    accounts, user = _accounts(request), _me(request)
    try:
        accounts.sign_in(user.email, body.password)
    except AuthError:
        raise HTTPException(status_code=422, detail="Your password isn't right")
    library = _library(request)
    if library.photos:
        for place in _db(request).list_places():
            library.photos.delete(_db(request).photo_refs(place.id))
    accounts.delete_user(user)
    out = Response(status_code=204)
    out.delete_cookie(SESSION_COOKIE, path="/")
    return out


@app.get("/v1/admin/users", dependencies=[Auth])
async def admin_users(request: Request) -> list[dict]:
    _admin(request)
    return [{"id": u.id, "email": u.email, "name": u.name, "is_admin": u.is_admin, "created_at": u.created_at}
            for u in _accounts(request).list_users()]


@app.post("/v1/admin/users/{user_id}/reset-password", dependencies=[Auth])
async def admin_reset_password(user_id: str, request: Request) -> dict:
    """A temporary password to give the person; it signs them out everywhere."""
    _admin(request)
    if _accounts(request).get_user(user_id) is None:
        raise HTTPException(status_code=404, detail="No such account")
    return {"password": _accounts(request).reset_password(user_id)}


@app.get("/v1/admin/invites", dependencies=[Auth])
async def admin_invites(request: Request) -> list[dict]:
    _admin(request)
    return _accounts(request).list_invites()


@app.post("/v1/admin/invites", status_code=201, dependencies=[Auth])
async def admin_new_invite(body: InviteRequest, request: Request) -> dict:
    """A one-time invite code. It's shown once; only a hash is kept."""
    return {"code": _accounts(request).create_invite(_admin(request), body.note)}


@app.delete("/v1/admin/invites/{invite_id}", status_code=204, dependencies=[Auth])
async def admin_delete_invite(invite_id: str, request: Request) -> Response:
    _admin(request)
    _accounts(request).delete_invite(invite_id)
    return Response(status_code=204)


# ---------- Error reports and feedback ----------


class ClientError(BaseModel):
    source: Literal["web", "ios", "ios-web"] = "web"
    message: str = Field(max_length=2000)
    stack: str = Field(default="", max_length=10000)
    url: str = Field(default="", max_length=500)
    version: str = Field(default="", max_length=40)


class FeedbackIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    screen: str = Field(default="", max_length=200)
    version: str = Field(default="", max_length=40)
    platform: str = Field(default="", max_length=40)


_client_errors = RateLimit(limit=20)


def _signed_in(request: Request, authorization: Optional[str]) -> Optional[User]:
    """Who sent a report, if they're signed in (reports are accepted either way)."""
    token = authorization[7:].strip() if authorization and authorization.lower().startswith("bearer ") else request.cookies.get(SESSION_COOKIE, "")
    return _accounts(request).session_user(token) if token else None


@app.post("/v1/client-errors", status_code=204)
async def client_error(body: ClientError, request: Request, authorization: Annotated[Optional[str], Header()] = None) -> Response:
    """JavaScript errors from the web app (and the iOS app's web screens) and errors the iOS app catches, passed on
    to error reporting. No sign-in needed, so errors on the sign-in screen are seen too; limited per address."""
    ip = request.headers.get("fly-client-ip") or (request.client.host if request.client else "unknown")
    if _client_errors.allow(ip):
        user = _signed_in(request, authorization)
        report_client_error(body.source, body.message, stack=body.stack, url=body.url, version=body.version,
                            user_id=user.id if user else None)
    return Response(status_code=204)


@app.post("/v1/feedback", status_code=201, dependencies=[Auth])
async def send_feedback(body: FeedbackIn, request: Request) -> dict:
    """Feedback from Profile → Send feedback: kept on the server and forwarded to error reporting, with the
    sender's email so you can reply."""
    user = getattr(request.state, "user", None)
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="Write a few words first")
    context = {"screen": body.screen, "version": body.version, "platform": body.platform}
    feedback_id = _db(request).add_feedback(user.id if user else None, message, context)
    report_feedback(message, user_id=user.id if user else None, email=user.email if user else "", context=context)
    return {"id": feedback_id}


def _usage(request: Request) -> Usage:
    usage = getattr(request.app.state.claude, "usage", None)
    if usage is None:
        raise HTTPException(status_code=404, detail="Usage tracking isn't set up")
    return usage


@app.get("/v1/admin/usage", dependencies=[Auth])
async def admin_usage(request: Request, days: int = 30) -> dict:
    """AI spend by day, feature and person, Google Maps calls, and the budgets and limits in force."""
    _admin(request)
    return _usage(request).report(min(max(days, 1), 120))


@app.put("/v1/admin/usage/limits", dependencies=[Auth])
async def admin_usage_limits(body: dict[str, Optional[float]], request: Request) -> dict:
    """Changes budgets and daily limits (keys as in "config"); null puts one back to the server setting."""
    _admin(request)
    return _usage(request).set_config(body)


@app.get("/v1/admin/feedback", dependencies=[Auth])
async def admin_feedback(request: Request, limit: int = 100) -> list[dict]:
    _admin(request)
    users = {u.id: u.email for u in _accounts(request).list_users()}
    items = _db(request).list_feedback(min(max(limit, 1), 500))
    for item in items:
        item["email"] = users.get(item["user_id"] or "", "")
    return items


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
    _allow(request, "import")
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
    _allow(request, "import")
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
    _allow(request, "import")
    store.update(job_id, status=JobStatus.queued, message="Retrying", warnings=[])
    start_job(request.app, job_id, job.url, _db(request).job_shared_text(job_id))
    return store.get(job_id)


# ---------- Trips ----------


@app.get("/v1/trips", response_model=list[Trip], dependencies=[Auth])
async def list_trips(request: Request) -> list[Trip]:
    return _db(request).list_trips()


@app.post("/v1/trips", response_model=TripDetail, status_code=201, dependencies=[Auth])
async def create_trip(body: NewTripRequest, request: Request) -> TripDetail:
    """Makes a trip: a city, how many days, the saved places to include, and whether AI plans it
    (optionally adding suggestions for quiet days) or you build the days yourself."""
    unknown = [pid for pid in body.place_ids if _db(request).get_place(pid) is None]
    if unknown:
        raise HTTPException(status_code=422, detail="Some of those places are no longer saved")
    return await _library(request).create_trip(body, request.app.state.claude, _taste(request))


def _taste(request: Request) -> Optional[str]:
    try:
        return profile_text(request.app.state.curator.profile()) or None
    except Exception:  # the taste profile is a nice-to-have here
        return None


@app.post("/v1/trips/{trip_id}/places", response_model=TripDetail, dependencies=[Auth])
async def add_trip_places(trip_id: str, body: PlaceIds, request: Request) -> TripDetail:
    """Adds saved places to a trip (unscheduled until you put them on a day)."""
    _trip_or_404(request, trip_id)
    db = _db(request)
    for pid in dict.fromkeys(body.place_ids):
        if db.get_place(pid) is None:
            raise HTTPException(status_code=422, detail="Some of those places are no longer saved")
        db.add_to_trip(trip_id, pid)
    return _trip_or_404(request, trip_id)


@app.delete("/v1/trips/{trip_id}/places/{place_id}", response_model=TripDetail, dependencies=[Auth])
async def remove_trip_place(trip_id: str, place_id: str, request: Request) -> TripDetail:
    """Takes a place off the trip. It stays in your saved places (a suggestion you never kept is dropped)."""
    _trip_or_404(request, trip_id)
    _library(request).remove_from_trip(trip_id, place_id)
    return _trip_or_404(request, trip_id)


@app.post("/v1/trips/{trip_id}/places/{place_id}/keep", response_model=TripDetail, dependencies=[Auth])
async def keep_suggestion(trip_id: str, place_id: str, request: Request) -> TripDetail:
    """Keeps a place the planner suggested: it joins your saved places and loses its "Suggested" label."""
    _trip_or_404(request, trip_id)
    if _library(request).keep_suggestion(trip_id, place_id) is None:
        raise HTTPException(status_code=404, detail="Place not found in this trip")
    return _trip_or_404(request, trip_id)


@app.post("/v1/trips/{trip_id}/suggest", response_model=TripDetail, dependencies=[Auth])
async def suggest_for_trip(trip_id: str, request: Request) -> TripDetail:
    """Adds a few suggestions to the trip's quiet days (days with fewer than three stops)."""
    trip = _trip_or_404(request, trip_id)
    if not trip.day_count:
        raise HTTPException(status_code=422, detail="Set up the trip's days first")
    if request.app.state.claude is None:
        raise HTTPException(status_code=503, detail="Suggestions need Claude, which isn't set up on the server")
    await _library(request).fill_gaps(trip_id, request.app.state.claude, _taste(request))
    return _trip_or_404(request, trip_id)


# ---------- Folders ----------


@app.get("/v1/folders", response_model=list[Folder], dependencies=[Auth])
async def list_folders(request: Request) -> list[Folder]:
    return _db(request).list_folders()


def _folder_or_404(request: Request, folder_id: str) -> Folder:
    folder = _db(request).get_folder(folder_id)
    if folder is None:
        raise HTTPException(status_code=404, detail="Folder not found")
    return folder


@app.post("/v1/folders", response_model=Folder, status_code=201, dependencies=[Auth])
async def create_folder(body: FolderInput, request: Request) -> Folder:
    db = _db(request)
    folder = db.create_folder(" ".join(body.name.split()))
    for pid in dict.fromkeys(body.place_ids):
        if db.get_place(pid):
            db.add_to_folder(folder.id, pid)
    return db.get_folder(folder.id)


@app.patch("/v1/folders/{folder_id}", response_model=Folder, dependencies=[Auth])
async def rename_folder(folder_id: str, body: FolderRename, request: Request) -> Folder:
    _folder_or_404(request, folder_id)
    _db(request).rename_folder(folder_id, " ".join(body.name.split()))
    return _folder_or_404(request, folder_id)


@app.delete("/v1/folders/{folder_id}", status_code=204, dependencies=[Auth])
async def delete_folder(folder_id: str, request: Request) -> Response:
    """Deletes the folder; its places stay saved."""
    _folder_or_404(request, folder_id)
    _db(request).delete_folder(folder_id)
    return Response(status_code=204)


@app.post("/v1/folders/{folder_id}/places", response_model=Folder, dependencies=[Auth])
async def add_folder_places(folder_id: str, body: PlaceIds, request: Request) -> Folder:
    _folder_or_404(request, folder_id)
    db = _db(request)
    for pid in dict.fromkeys(body.place_ids):
        if db.get_place(pid):
            db.add_to_folder(folder_id, pid)
    return _folder_or_404(request, folder_id)


@app.delete("/v1/folders/{folder_id}/places/{place_id}", response_model=Folder, dependencies=[Auth])
async def remove_folder_place(folder_id: str, place_id: str, request: Request) -> Folder:
    _folder_or_404(request, folder_id)
    _db(request).remove_from_folder(folder_id, place_id)
    return _folder_or_404(request, folder_id)


@app.get("/v1/trips/{trip_id}", response_model=TripDetail, dependencies=[Auth])
async def get_trip(trip_id: str, request: Request) -> TripDetail:
    return _trip_or_404(request, trip_id)


@app.patch("/v1/trips/{trip_id}", response_model=TripDetail, dependencies=[Auth])
async def update_trip(trip_id: str, body: TripUpdate, request: Request) -> TripDetail:
    _trip_or_404(request, trip_id)
    changes = {k: getattr(body, k) for k in body.model_fields_set}
    for key in ("name", "kind"):
        if changes.get(key) is None:
            changes.pop(key, None)
    _db(request).update_trip(trip_id, **changes)
    return _trip_or_404(request, trip_id)


_WEATHER_CACHE: dict[tuple, tuple[float, Optional[WeatherDay]]] = {}


@app.get("/v1/weather/today", response_model=Optional[WeatherDay], dependencies=[Auth])
async def weather_today(request: Request, lat: float = Query(ge=-90, le=90), lon: float = Query(ge=-180, le=180),
                        on: Optional[date] = None) -> Optional[WeatherDay]:
    """The day's weather where you are (for Home during a trip); null when it isn't available. Kept for an hour."""
    day = on or date.today()
    key = (round(lat, 1), round(lon, 1), day.isoformat())
    hit = _WEATHER_CACHE.get(key)
    if hit and time.monotonic() - hit[0] < 3600:
        return hit[1]
    weather = request.app.state.packing.weather
    found = await weather.days(lat, lon, day, 1)
    result = found[0] if found else None
    if len(_WEATHER_CACHE) > 500:
        _WEATHER_CACHE.clear()
    _WEATHER_CACHE[key] = (time.monotonic(), result)
    return result


@app.put("/v1/trips/{trip_id}/stops", response_model=TripDetail, dependencies=[Auth])
async def set_trip_stops(trip_id: str, body: TripStopsRequest, request: Request) -> TripDetail:
    """Sets the trip's route: its cities in order, how many days in each and how you travel between them.
    The trip grows to fit; if it's longer, the last stop keeps the extra days (nothing on the plan moves)."""
    trip = _trip_or_404(request, trip_id)
    if trip.kind == "local":
        raise HTTPException(status_code=422, detail="Your home city doesn't have a route")
    total = sum(s.days for s in body.stops)
    if total > 21:
        raise HTTPException(status_code=422, detail="A trip can be up to 21 days")
    stops = [{"city": s.city.strip(), "country": (s.country or "").strip(), "days": s.days,
              **({"travel_mode": s.travel_mode} if s.travel_mode and i else {}),
              **({"travel_minutes": s.travel_minutes} if s.travel_minutes is not None and i else {}),
              **({"travel_note": s.travel_note.strip()} if s.travel_note and s.travel_note.strip() and i else {})}
             for i, s in enumerate(body.stops)]
    first = stops[0]
    _db(request).update_trip(trip_id, stops=stops, city=first["city"], country=first["country"] or trip.country,
                             day_count=max(trip.day_count, total))
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
    place = _db(request).get_place(body.place_id, trip_id)
    if place is None:
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


@app.post("/v1/trips/{trip_id}/fit", response_model=TripDetail, dependencies=[Auth])
async def fit_unplanned(trip_id: str, request: Request) -> TripDetail:
    """Puts every place that isn't on a day yet onto a day in its own city's stop: the lightest day it's open."""
    trip = _trip_or_404(request, trip_id)
    if not trip.day_count:
        raise HTTPException(status_code=422, detail="Set up the trip's days first")
    library = _library(request)
    for place_id, day in tripcheck.fit_plan(trip):
        library.add_to_day(trip_id, [place_id], day)
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


@app.get("/v1/home", response_model=Optional[HomeSetting], dependencies=[Auth])
async def get_home(request: Request) -> Optional[HomeSetting]:
    home = _library(request).home()
    return HomeSetting(**home) if home else None


@app.put("/v1/home", response_model=HomeSetting, dependencies=[Auth])
async def set_home(body: HomeRequest, request: Request) -> HomeSetting:
    """Sets the city whose places are kept as a local collection instead of a trip."""
    library = _library(request)
    found = await library.geocoder.search(body.city.strip(), limit=1)
    if not found:
        raise HTTPException(status_code=422, detail="Couldn't find that city. Try adding the country.")
    match = found[0]
    detail = await library.geocoder.details(match.place_id) if match.place_id else None
    home = HomeSetting(city=(detail.city if detail and detail.city else body.city.strip()),
                       country=(detail.country if detail and detail.country else match.country or ""),
                       latitude=match.latitude, longitude=match.longitude)
    _db(request).set_setting("home", home.model_dump())
    return home


@app.delete("/v1/home", status_code=204, dependencies=[Auth])
async def clear_home(request: Request) -> Response:
    _db(request).set_setting("home", None)
    return Response(status_code=204)


@app.get("/v1/discover", response_model=DiscoverResult, dependencies=[Auth])
async def discover(
    request: Request, kind: DiscoverKind = "restaurants", area: str = "home", trip_id: Optional[str] = None,
    lat: Optional[float] = Query(default=None, ge=-90, le=90), lon: Optional[float] = Query(default=None, ge=-180, le=180),
    radius: int = Query(default=4000, ge=500, le=20000), refresh: bool = False,
) -> DiscoverResult:
    """Well-rated places near home, near a trip's stops, or near the given point, picked for the person's taste."""
    library = _library(request)
    where: Optional[DiscoverArea] = None
    if area == "home":
        home = library.home()
        where = DiscoverArea(name=home["city"], latitude=home["latitude"], longitude=home["longitude"]) if home else None
    elif area == "trip" and trip_id:
        trip = _db(request).get_trip(trip_id)
        center = library.trip_center(trip_id) if trip else None
        where = DiscoverArea(name=trip.city, latitude=center[0], longitude=center[1]) if trip and center else None
    elif area == "here" and lat is not None and lon is not None:
        where = DiscoverArea(name="Near you", latitude=lat, longitude=lon)
    if where is None:
        return DiscoverResult(status="no_area", kind=kind)
    return await request.app.state.discover.discover(kind, where, radius, request.app.state.curator.profile(), refresh)


@app.get("/v1/discover/photo", include_in_schema=False)
async def discover_photo(request: Request, settings: Annotated[Settings, Depends(get_settings)], ref: str = "", sig: str = "", w: int = 800):
    """A photo for a recommendation (not saved yet). Authorized by the signature in the link."""
    if not ref.startswith("places/") or not request.app.state.photos.check("discover", 0, ref, sig):
        raise HTTPException(status_code=403, detail="Bad photo link")
    if not settings.google_maps_api_key:
        raise HTTPException(status_code=404, detail="Photo not available")
    _count_google(request, "photo")
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            r = await client.get(f"https://places.googleapis.com/v1/{ref}/media",
                                 params={"maxWidthPx": min(max(w, 100), 1200), "key": settings.google_maps_api_key})
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Couldn't load photo")
    if r.status_code != 200:
        raise HTTPException(status_code=404, detail="Photo no longer available")
    return Response(r.content, media_type=r.headers.get("content-type", "image/jpeg"), headers={"Cache-Control": "private, max-age=86400"})


@app.post("/v1/trips/{trip_id}/booking-needs", response_model=TripDetail, dependencies=[Auth])
async def check_booking_needs(trip_id: str, request: Request) -> TripDetail:
    """Marks which places need a reservation or tickets (once per place; Claude's best judgement)."""
    trip = _trip_or_404(request, trip_id)
    try:
        await request.app.state.needs.check(trip)
    except ClaudeError as e:
        raise _claude_http(e)
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
        if _db(request).get_place(place_id, trip_id) is None:
            raise HTTPException(status_code=422, detail="That place isn't in this trip")


def _public_base(request: Request) -> str:
    """The app's own address as the phone sees it (Fly terminates TLS, so trust its forwarded scheme)."""
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    return f"{proto}://{request.headers.get('host') or request.url.netloc}"


@app.get("/v1/calendar", response_model=CalendarResult, dependencies=[Auth])
async def calendar(request: Request) -> CalendarResult:
    """Everything dated: saved events, bookings, planned stops and trips, soonest first, plus events with no date yet."""
    return request.app.state.calendar.result(_public_base(request))


@app.post("/v1/calendar/feed", response_model=CalendarFeed, dependencies=[Auth])
async def start_calendar_feed(request: Request) -> CalendarFeed:
    """A private link Google or Apple Calendar can subscribe to. Making a new one turns the old one off."""
    return request.app.state.calendar.start_feed(_public_base(request))


@app.delete("/v1/calendar/feed", status_code=204, dependencies=[Auth])
async def stop_calendar_feed(request: Request) -> Response:
    request.app.state.calendar.stop_feed()
    return Response(status_code=204)


@app.get("/v1/calendar/item.ics", include_in_schema=False)
async def calendar_item_ics(request: Request, id: str = "", sig: str = "", u: str = "") -> Response:
    """One item as an .ics file, for Apple Calendar's "Add" prompt. Authorized by the signature in the link."""
    cal = request.app.state.calendar
    if not id or not cal.check_ics(id, sig, u):
        raise HTTPException(status_code=403, detail="Bad calendar link")
    CURRENT_USER.set(u or None)
    item = next((i for i in cal.items()[0] if i.id == id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="That's no longer on your calendar")
    return Response(cal.ics([item], name=item.title), media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": 'inline; filename="event.ics"', "Cache-Control": "no-store"})


@app.get("/cal/{token}.ics", include_in_schema=False)
async def calendar_feed(token: str, request: Request) -> Response:
    """The subscribed calendar. The token in the address is the only key, so it can be turned off or replaced."""
    cal = request.app.state.calendar
    owner = cal.feed_owner(token)
    if owner is None:
        raise HTTPException(status_code=404, detail="Not found")
    CURRENT_USER.set(owner or None)
    return Response(cal.ics(cal.items()[0]), media_type="text/calendar; charset=utf-8", headers={"Cache-Control": "no-store"})


@app.get("/v1/bookings", response_model=list[BookingListItem], dependencies=[Auth])
async def list_all_bookings(request: Request) -> list[BookingListItem]:
    """Every booking across trips, soonest first (undated ones last), for the Bookings tab."""
    return _db(request).list_all_bookings()


@app.get("/v1/trips/{trip_id}/bookings/{booking_id}/lounges", response_model=LoungeResult, dependencies=[Auth])
async def booking_lounges(trip_id: str, booking_id: str, request: Request, refresh: bool = False) -> LoungeResult:
    """Lounges at the airport a flight departs from: name, terminal, and how to get in. From Claude's knowledge, so to be checked."""
    booking = _booking_or_404(request, trip_id, booking_id)
    if booking.kind != "flight":
        raise HTTPException(status_code=422, detail="Lounges are for flights")
    return await request.app.state.lounges.lookup(booking.origin, refresh)


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
        raise _claude_http(e)
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
        for key in ("user_notes", "hours_checked_at", "photos_checked_at", "rating_checked_at", "contact_checked_at", "reserve_checked_at", "booking_checked_at"):
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
        "title": f"{trip.name} · The Travel Edit",
        "description": f"{len(trip.places)} saved place{'s' if len(trip.places) != 1 else ''}{days}. Open for the map and itinerary.",
        "image": f"{origin}{trip.cover_photo.url}&w=1200" if trip.cover_photo else f"{origin}/icons/icon-512.png",
        "url": f"{origin}/s/{token}",
    }
    page = (STATIC_DIR / "shared.html").read_text()
    for key, value in values.items():
        page = page.replace("{{" + key + "}}", html.escape(value, quote=True))
    return HTMLResponse(page, headers={"Cache-Control": "no-cache", "X-Robots-Tag": "noindex"})


NOT_SHARED_PAGE = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>The Travel Edit</title><style>body{font:17px -apple-system,system-ui,sans-serif;display:grid;place-items:center;min-height:90vh;margin:0;
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
async def curate_trip(trip_id: str, request: Request, wait: bool = False) -> TripEdits:
    """(Re)curates the trip's edits: your saved places in its city mixed with places travel and food publications
    recommend. Researching takes a minute, so this starts it in the background and returns the current edits with
    refreshing=true; poll GET until it's false (or pass wait=true to block)."""
    trip = _trip_or_404(request, trip_id)
    curator = _curator(request)
    if len(curator._pool(trip)) < 3:
        raise HTTPException(status_code=422, detail="Save at least three places to curate edits")
    if wait:
        return await curator.curate(trip)
    if trip_id not in curator.refreshing:
        curator.refreshing.add(trip_id)
        task = asyncio.create_task(curator.curate(trip))
        request.app.state.tasks.add(task)
        task.add_done_callback(request.app.state.tasks.discard)
    return curator.edits(trip)


@app.post("/v1/trips/{trip_id}/edits/{edit_id}/entries/{entry_id}/save", response_model=Place, dependencies=[Auth])
async def save_edit_entry(trip_id: str, edit_id: str, entry_id: str, request: Request) -> Place:
    """Saves one place from an edit to your saved places."""
    place = await _curator(request).save_entry(_trip_or_404(request, trip_id), edit_id, entry_id, _library(request))
    if place is None:
        raise HTTPException(status_code=404, detail="This edit was refreshed. Open it again to see the latest.")
    return place


@app.post("/v1/trips/{trip_id}/edits/{edit_id}/bookmark", response_model=Folder, dependencies=[Auth])
async def bookmark_edit(trip_id: str, edit_id: str, request: Request) -> Folder:
    """Saves a whole edit to the Library as a folder, so it stays after the edits refresh."""
    folder_id = await _curator(request).bookmark(_trip_or_404(request, trip_id), edit_id, _library(request))
    if folder_id is None:
        raise HTTPException(status_code=404, detail="This edit was refreshed. Open it again to see the latest.")
    return _db(request).get_folder(folder_id)


@app.post("/v1/concierge", response_model=ConciergeReply, dependencies=[Auth])
async def concierge(body: ConciergeRequest, request: Request) -> ConciergeReply:
    if body.trip_id:
        _trip_or_404(request, body.trip_id)
    try:
        return await _curator(request).chat(body)
    except ClaudeError as e:
        raise _claude_http(e)


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


class ApnsRegistration(BaseModel):
    token: str = Field(max_length=200)  # the device token, as hex
    environment: Literal["production", "sandbox"] = "production"  # sandbox for builds run from Xcode


@app.post("/v1/push/apns", status_code=204, dependencies=[Auth])
async def apns_register(body: ApnsRegistration, request: Request) -> Response:
    """The iOS app's device token, so it gets notifications through Apple's push service."""
    try:
        _push(request).subscribe_apns(body.token, body.environment)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return Response(status_code=204)


@app.delete("/v1/push/apns/{token}", status_code=204, dependencies=[Auth])
async def apns_unregister(token: str, request: Request) -> Response:
    _push(request).unsubscribe_apns(token)
    return Response(status_code=204)


@app.post("/v1/push/test", dependencies=[Auth])
async def push_test(request: Request) -> dict:
    sent = await _push(request).send_all({"title": "Notifications are on", "body": "The Travel Edit will tell you when a reel's places are saved.",
                                          "url": "/#/settings", "tag": "test"})
    return {"sent": sent}


# ---------- Places & reels ----------


@app.get("/v1/places", response_model=list[Place], dependencies=[Auth])
async def list_places(request: Request) -> list[Place]:
    """Everything you've saved, from reels, screenshots, searches and Discover (with the trips and folders it's in)."""
    return _db(request).list_places(saved_only=True)


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
    if body.folder_id:
        _folder_or_404(request, body.folder_id)
    if body.candidate_id:
        match = await library.geocoder.details(body.candidate_id)
        if match is None:
            raise HTTPException(status_code=422, detail="Couldn't load that place. Try searching again.")
        place, created = await library.add_match(match, body.trip_id, body.folder_id)
    elif body.name:
        place, created = await library.add_by_name(body.name.strip(), body.trip_id, city=body.city, category=body.category.value,
                                                   folder_id=body.folder_id)
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
    if body.folder_id:
        _folder_or_404(request, body.folder_id)
    url = find_url(body.url) or body.url.strip()
    if not is_map_link(url):
        raise HTTPException(status_code=422, detail="Paste a Google Maps or Apple Maps link")
    try:
        link = parse_map_link(await resolve_map_link(url))
    except NotAMapLink as e:
        raise HTTPException(status_code=422, detail=str(e))
    place, created = await _library(request).add_from_link(link, body.trip_id, body.folder_id)
    if not created:
        response.status_code = 200
    return AddPlaceResult(place=place, created=created)


@app.get("/v1/places/{place_id}", response_model=PlaceDetail, dependencies=[Auth])
async def get_place(place_id: str, request: Request) -> PlaceDetail:
    """One saved place with the posts that recommended it (its trips and folders are in trip_ids / folder_ids)."""
    place = _place_or_404(request, place_id)
    return PlaceDetail(place=place, reels=_db(request).place_reels(place_id))


@app.patch("/v1/places/{place_id}", response_model=Place, dependencies=[Auth])
async def update_place(place_id: str, body: PlaceUpdate, request: Request) -> Place:
    place = _place_or_404(request, place_id)
    db, library = _db(request), _library(request)
    fields = body.model_fields_set
    # Day, time slot and exact time belong to one trip. An event's own start time doesn't.
    event_time = place.category.value == "event" and not body.trip_id
    trip_scoped = ({"day_number", "time_of_day"} & fields or body.clear_time_of_day
                   or (({"start_time"} & fields or body.clear_start_time) and not event_time))
    trip_id = body.trip_id or (place.trip_ids[0] if len(place.trip_ids) == 1 else None)
    if trip_scoped:
        if not trip_id:
            raise HTTPException(status_code=422, detail="Say which trip this is for")
        if db.get_place(place_id, trip_id) is None:
            raise HTTPException(status_code=404, detail="Place not found in this trip")
    scope = None if event_time else trip_id
    simple = {k: getattr(body, k) for k in ("name", "category", "visited", "user_notes", "must_do")
              if k in fields and getattr(body, k) is not None}
    if "start_time" in fields and body.start_time is not None:
        db.update_place(place_id, trip_id=scope, start_time=body.start_time)
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
        library.move_place(db.get_place(place_id, trip_id), body.day_number or None)
    if body.clear_event_date:
        db.update_place(place_id, event_date=None, event_end_date=None)
    elif "event_date" in fields and body.event_date is not None:
        end = body.event_end_date if body.event_end_date and body.event_end_date > body.event_date else None
        db.update_place(place_id, event_date=body.event_date, event_end_date=end)
    if body.clear_start_time:
        db.update_place(place_id, trip_id=scope, start_time=None)
    if body.clear_time_of_day:
        db.update_place(place_id, trip_id=trip_id, time_of_day=None)
    elif body.time_of_day is not None:
        db.update_place(place_id, trip_id=trip_id, time_of_day=body.time_of_day)
    return (db.get_place(place_id, scope) if scope else None) or db.get_place(place_id)


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
        raise _claude_http(e)
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
        raise _claude_http(e)


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
        _count_google(request, "photo")
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
        raise _claude_http(e)


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
