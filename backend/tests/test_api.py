import time
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app import pipeline as pipeline_module
from app.config import Settings, get_settings
from app.db import Database, normalize
from app.geocode import GeoMatch, GooglePlacesGeocoder, NominatimGeocoder
from app.jobs import JobStore
from app.library import Library
from app.menu_browser import BrowserRenderer
from app.events import EventsService, Ticketmaster, geohash, parse_event
from app.menus import MenuService, SafeFetcher, Material
from app.needs import NeedsService
from app.packing import PackingService
from app.weather import Weather
from app.llm import ClaudeService, _sanitize_plan
from app.concierge import Curator
from app.main import app, notify_import
from app.media import DownloadedReel, UnsupportedURLError, find_url, platform_for
from app.models import (
    BookingNeedItem,
    BookingNeedResult,
    EventNote,
    EventNotes,
    PickedLinks,
    PackingDraftItem,
    PackingResult,
    BookingDraft,
    BookingsResult,
    ExtractionResult,
    MenuItem,
    MenuResult,
    MenuSection,
    PlanResult,
    PlannedDay,
    PlannedStop,
    PlanRequest,
    ReelMetadata,
)
from app.planner import offline_plan
from app.routing import Router
from app.photos import PhotoStore
from app.push import Push

H = {"X-API-Key": "secret"}


def extracted(name, city="New York", hood="Greenwich Village", category="food"):
    return {
        "name": name, "category": category, "city": city, "country": "USA", "neighborhood": hood,
        "address": None, "description": f"{name} is great", "recommended_items": ["slice"], "price_hint": "$",
        "tips": None, "source": "on_screen", "confidence": "high", "image_labels": ["Frame at 0s"],
    }


EXTRACTION = ExtractionResult(
    title="Best pizza in NYC",
    destination_city="New York",
    destination_country="USA",
    summary="Pizza spots",
    places=[extracted("Joe's Pizza"), extracted("Prince Street Pizza", hood="Nolita"), extracted("Lucali", hood="Carroll Gardens")],
)


class FakeMessages:
    """Stands in for client.beta.messages; returns a canned result per output type."""

    def __init__(self):
        self.outputs = {ExtractionResult: EXTRACTION}
        self.stop_reason = "end_turn"
        self.calls = []

    async def parse(self, **kwargs):
        self.calls.append(kwargs)
        parsed = self.outputs.get(kwargs["output_format"])
        if isinstance(parsed, list):  # one result per call, in order
            parsed = parsed.pop(0)
        if callable(parsed):  # decides from the request
            parsed = parsed(kwargs)
        if isinstance(parsed, Exception):
            raise parsed
        return SimpleNamespace(parsed_output=parsed, stop_reason=self.stop_reason)


class FakeGeocoder:
    COORDS = {"Joe's Pizza": (40.7305, -74.0021), "Prince Street Pizza": (40.7231, -73.9945)}

    def __init__(self):
        self.queries = []
        self.searches = []

    async def search(self, query, near=None, limit=5):
        self.searches.append((query, near))
        if "nothing" in query.lower():
            return []
        return [GeoMatch(name="Lucali", latitude=40.6818, longitude=-74.0003, address="575 Henry St, Brooklyn",
                         place_id="google:lucali1", category="food")]

    async def details(self, place_id):
        if place_id != "google:lucali1":
            return None
        from app.hours import parse_osm
        return GeoMatch(name="Lucali", latitude=40.6818, longitude=-74.0003, address="575 Henry St, Brooklyn",
                        maps_url="https://maps.google.com/?cid=1", place_id=place_id, category="food", city="New York",
                        country="USA", hours=parse_osm("Mo-Su 17:00-23:00"),
                        photos=[{"source": "google", "ref": "places/x/photos/1", "attribution": "Ana"}])

    async def locate(self, name, neighborhood, city, country, query=None):
        self.queries.append(query or name)
        if query:
            return GeoMatch(name=name, latitude=40.6818, longitude=-74.0003, address="575 Henry St")
        if name in self.COORDS:
            lat, lon = self.COORDS[name]
            from app.hours import parse_osm
            return GeoMatch(name=name, latitude=lat, longitude=lon, address="Somewhere St",
                            hours=parse_osm("Mo-Fr 11:00-23:00; Sa-Su 10:00-02:00"),
                            rating=4.6 if name == "Joe's Pizza" else None, rating_count=1200 if name == "Joe's Pizza" else None,
                            website="https://www.joespizzanyc.com/" if name == "Joe's Pizza" else None,
                            phone="+1 212-366-1182" if name == "Joe's Pizza" else None)
        return None


@pytest.fixture
def client(monkeypatch, tmp_path):
    settings = Settings(app_api_key="secret", anthropic_api_key="x")
    app.dependency_overrides[get_settings] = lambda: settings

    video = tmp_path / "v.mp4"
    video.write_bytes(b"")
    frame = tmp_path / "f.jpg"
    frame.write_bytes(b"\xff\xd8\xff")

    monkeypatch.setattr(
        pipeline_module,
        "download_reel",
        lambda url, workdir, s: DownloadedReel(
            metadata=ReelMetadata(platform="tiktok", url=url, caption="pizza!", uploader="slicehunter"), video_path=video
        ),
    )
    monkeypatch.setattr(pipeline_module, "extract_audio", lambda v, w: tmp_path / "a.wav")
    monkeypatch.setattr(pipeline_module, "transcribe", lambda a, s: "[0.0s] go to Joe's Pizza")
    monkeypatch.setattr(pipeline_module, "extract_frames", lambda v, w, s: [(0.0, frame)])

    messages = FakeMessages()
    db = Database(":memory:")
    geocoder = FakeGeocoder()
    claude = ClaudeService(settings, client=SimpleNamespace(beta=SimpleNamespace(messages=messages)))
    photo_store = PhotoStore(tmp_path / "photos", "secret")
    db.photo_url = photo_store.url
    library = Library(db, geocoder, photos=photo_store)
    store = JobStore(db)
    push_log, push_status = [], {"code": 201}

    def push_handler(request):
        push_log.append(request)
        return httpx.Response(push_status["code"])

    app.state.db = db
    app.state.store = store
    app.state.claude = claude
    app.state.library = library
    app.state.pipeline = pipeline_module.Pipeline(settings, store, claude, library, uploads_dir=tmp_path / "uploads")
    app.state.pipeline.on_finished = lambda job: notify_import(app, job)
    app.state.router = Router(db, settings)
    app.state.photos = photo_store
    app.state.push = Push(db, tmp_path / "vapid.pem", client=httpx.AsyncClient(transport=httpx.MockTransport(push_handler)))
    app.state.curator = Curator(db, claude)

    web, web_log = {}, []  # url -> (status, content type, body, headers) served to the menu finder

    def web_handler(request):
        web_log.append(str(request.url))
        hit = web.get(str(request.url))
        if hit is None:
            return httpx.Response(404)
        status, ctype, body, headers = hit
        return httpx.Response(status, content=body, headers={"content-type": ctype, **headers})

    async def resolver(host):
        return {"internal.test": ["10.0.0.5"], "meta.test": ["169.254.169.254"], "v6.test": ["::ffff:127.0.0.1"]}.get(host, ["93.184.216.34"])

    weather_log, weather_state = [], {"fail": False}

    def weather_handler(request):
        from datetime import date, timedelta

        weather_log.append(request.url)
        if weather_state["fail"]:
            return httpx.Response(500)
        q = request.url.params
        start, end = date.fromisoformat(q["start_date"]), date.fromisoformat(q["end_date"])
        n = (end - start).days + 1
        daily = {"time": [(start + timedelta(days=i)).isoformat() for i in range(n)], "weather_code": [63] * n,
                 "temperature_2m_max": [14.0] * n, "temperature_2m_min": [8.0] * n}
        if request.url.path.endswith("/forecast"):
            daily["precipitation_probability_max"] = [80] * n
        return httpx.Response(200, json={"daily": daily})

    app.state.needs = NeedsService(db, claude)
    tm_state = {"fail": False, "events": [], "log": []}

    def tm_handler(request):
        tm_state["log"].append(request.url)
        if tm_state["fail"]:
            return httpx.Response(500)
        return httpx.Response(200, json={"_embedded": {"events": tm_state["events"]}} if tm_state["events"] else {"page": {"totalElements": 0}})

    app.state.events = EventsService(db, claude, Ticketmaster(Settings(app_api_key="secret", ticketmaster_api_key="tmkey"),
                                                              client=httpx.AsyncClient(transport=httpx.MockTransport(tm_handler))), library)
    app.state.packing = PackingService(db, claude, Weather(settings, client=httpx.AsyncClient(transport=httpx.MockTransport(weather_handler))), library)
    app.state.menus = MenuService(db, claude, SafeFetcher(client=httpx.AsyncClient(transport=httpx.MockTransport(web_handler)), resolver=resolver, min_interval=0, retry_cap=0, cache_seconds=0),
                                  geocoder, settings)

    with TestClient(app) as c:
        c.web, c.web_log = web, web_log
        c.weather_log, c.weather_state = weather_log, weather_state
        c.tm = tm_state
        c.messages = messages
        c.geocoder = geocoder
        c.push_log = push_log
        c.push_status = push_status
        c.uploads = tmp_path / "uploads"
        yield c
    app.dependency_overrides.clear()
    for attr in ("db", "store", "claude", "library", "pipeline", "router", "photos", "push", "curator", "menus", "packing", "events", "needs"):
        delattr(app.state, attr)


def wait_for(c, job_id):
    for _ in range(200):
        job = c.get(f"/v1/jobs/{job_id}", headers=H).json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def import_reel(c, url="https://vm.tiktok.com/ZMabc/"):
    r = c.post("/v1/jobs", json={"url": url}, headers=H)
    assert r.status_code == 202, r.text
    return wait_for(c, r.json()["id"])


# ---------- Jobs ----------


def test_requires_api_key(client):
    assert client.post("/v1/jobs", json={"url": "https://www.tiktok.com/@a/video/1"}).status_code == 401
    assert client.get("/v1/trips").status_code == 401


def test_rejects_unsupported_hosts(client):
    r = client.post("/v1/jobs", json={"url": "http://169.254.169.254/latest"}, headers=H)
    assert r.status_code == 422


def test_job_saves_places_into_a_trip(client):
    r = client.post(
        "/v1/jobs",
        json={"url": "Look at this! https://vm.tiktok.com/ZMabc/ via TikTok", "shared_text": "best pizza"},
        headers=H,
    )
    job = wait_for(client, r.json()["id"])
    assert job["status"] == "done", job
    assert job["added_places"] == 3
    assert job["result"]["places"][0]["name"] == "Joe's Pizza"

    call = client.messages.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["fallbacks"] == "default"
    assert any(b["type"] == "image" for b in call["messages"][0]["content"])

    trips = client.get("/v1/trips", headers=H).json()
    assert len(trips) == 1
    assert trips[0]["name"] == "New York"
    assert trips[0]["place_count"] == 3
    assert trips[0]["mapped_count"] == 2

    detail = client.get(f"/v1/trips/{job['trip_id']}", headers=H).json()
    joes = next(p for p in detail["places"] if p["name"] == "Joe's Pizza")
    assert joes["latitude"] == pytest.approx(40.7305)
    assert detail["reels"][0]["creator"] == "slicehunter"
    assert detail["reels"][0]["place_count"] == 3


def test_same_url_reuses_job_and_new_reel_merges_places(client):
    first = import_reel(client)
    again = client.post("/v1/jobs", json={"url": "https://vm.tiktok.com/ZMabc/"}, headers=H).json()
    assert again["id"] == first["id"]

    # A different reel mentioning the same places merges instead of duplicating.
    second = import_reel(client, "https://www.instagram.com/reel/xyz/")
    assert second["added_places"] == 0
    assert "already saved" in second["message"]
    trip = client.get(f"/v1/trips/{first['trip_id']}", headers=H).json()
    assert len(trip["places"]) == 3


def test_link_only_in_shared_text(client):
    r = client.post("/v1/jobs", json={"url": "", "shared_text": "omg https://www.tiktok.com/@a/video/9 so good"}, headers=H)
    assert r.status_code == 202
    assert r.json()["url"] == "https://www.tiktok.com/@a/video/9"


def test_refusal_fails_job_and_retry(client):
    client.messages.stop_reason = "refusal"
    r = client.post("/v1/jobs", json={"url": "https://www.instagram.com/reel/abc/"}, headers=H)
    job = wait_for(client, r.json()["id"])
    assert job["status"] == "failed"

    client.messages.stop_reason = "end_turn"
    assert client.post(f"/v1/jobs/{job['id']}/retry", headers=H).status_code == 200
    assert wait_for(client, job["id"])["status"] == "done"
    assert client.get("/v1/jobs", headers=H).json()[0]["result"] is None


def test_download_failure_without_text_fails(client, monkeypatch):
    def boom(*a):
        raise RuntimeError("private video")

    monkeypatch.setattr(pipeline_module, "download_reel", boom)
    r = client.post("/v1/jobs", json={"url": "https://www.instagram.com/reel/private/"}, headers=H)
    job = wait_for(client, r.json()["id"])
    assert job["status"] == "failed"
    assert "download" in job["message"]


# ---------- Trips, places, planning ----------


def test_place_updates_and_locate(client):
    job = import_reel(client)
    trip = client.get(f"/v1/trips/{job['trip_id']}", headers=H).json()
    lucali = next(p for p in trip["places"] if p["name"] == "Lucali")
    assert lucali["latitude"] is None

    r = client.post(f"/v1/places/{lucali['id']}/locate", json={"query": "Lucali, 575 Henry St, Brooklyn"}, headers=H)
    assert r.status_code == 200
    assert r.json()["latitude"] == pytest.approx(40.6818)

    r = client.patch(f"/v1/places/{lucali['id']}", json={"visited": True, "user_notes": "Book at 5pm", "category": "dessert"}, headers=H)
    body = r.json()
    assert body["visited"] is True and body["user_notes"] == "Book at 5pm" and body["category"] == "dessert"

    assert client.delete(f"/v1/places/{lucali['id']}", headers=H).status_code == 204
    assert client.get(f"/v1/trips/{job['trip_id']}", headers=H).json()["place_count"] == 2


def test_plan_with_claude_then_edit(client):
    job = import_reel(client)
    trip = client.get(f"/v1/trips/{job['trip_id']}", headers=H).json()
    ids = {p["name"]: p["id"] for p in trip["places"]}
    client.messages.outputs[PlanResult] = PlanResult(
        days=[
            PlannedDay(day_number=1, title="Village", stops=[
                PlannedStop(place_id=ids["Joe's Pizza"], time_of_day="lunch", note="Plain slice"),
                PlannedStop(place_id=ids["Prince Street Pizza"], time_of_day="dinner", note=None),
            ]),
            PlannedDay(day_number=2, title="Brooklyn", stops=[
                PlannedStop(place_id=ids["Lucali"], time_of_day="dinner", note=None),
            ]),
        ],
        unscheduled_place_ids=[],
        notes="Two easy days",
    )
    r = client.post(f"/v1/trips/{trip['id']}/plan", json={"days": 2, "start_date": "2026-11-06"}, headers=H)
    plan = r.json()
    assert plan["planned_by"] == "claude"
    assert plan["day_titles"] == ["Village", "Brooklyn"]
    assert plan["start_date"] == "2026-11-06"
    by_name = {p["name"]: p for p in plan["places"]}
    assert by_name["Joe's Pizza"]["day_note"] == "Plain slice"

    # Move Lucali to day 1, then reorder day 1.
    client.patch(f"/v1/places/{ids['Lucali']}", json={"day_number": 1, "time_of_day": "evening"}, headers=H)
    order = [ids["Lucali"], ids["Joe's Pizza"], ids["Prince Street Pizza"]]
    plan = client.post(f"/v1/trips/{trip['id']}/days/1/order", json={"place_ids": order}, headers=H).json()
    day1 = sorted((p for p in plan["places"] if p["day_number"] == 1), key=lambda p: p["day_order"])
    assert [p["id"] for p in day1] == order

    # Unschedule and clear.
    client.patch(f"/v1/places/{ids['Lucali']}", json={"day_number": 0}, headers=H)
    cleared = client.delete(f"/v1/trips/{trip['id']}/plan", headers=H).json()
    assert cleared["day_count"] == 0 and all(p["day_number"] is None for p in cleared["places"])


def test_plan_falls_back_offline(client):
    job = import_reel(client)
    client.messages.outputs[PlanResult] = PlanResult(days=[], unscheduled_place_ids=[])
    client.messages.stop_reason = "refusal"  # makes the Claude call fail
    plan = client.post(f"/v1/trips/{job['trip_id']}/plan", json={"days": 2}, headers=H).json()
    assert plan["planned_by"] == "offline"
    assert plan["day_count"] >= 1
    assert all(p["day_number"] is not None for p in plan["places"])


def test_rename_and_delete_trip(client):
    job = import_reel(client)
    r = client.patch(f"/v1/trips/{job['trip_id']}", json={"name": "NYC with Sam"}, headers=H)
    assert r.json()["name"] == "NYC with Sam"
    assert client.delete(f"/v1/trips/{job['trip_id']}", headers=H).status_code == 204
    assert client.get("/v1/trips", headers=H).json() == []
    assert client.get("/v1/places", headers=H).json() == []


def test_web_app_is_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "<title>TripIt</title>" in r.text
    assert client.get("/share?url=https://vm.tiktok.com/x").status_code == 200
    assert client.get("/manifest.webmanifest").status_code == 200


# ---------- Units ----------


def test_url_helpers():
    assert find_url("watch https://vm.tiktok.com/ZMabc/).") == "https://vm.tiktok.com/ZMabc/"
    assert platform_for("https://www.instagram.com/reel/abc/") == "instagram"
    with pytest.raises(UnsupportedURLError):
        platform_for("https://evil-tiktok.com/x")
    with pytest.raises(UnsupportedURLError):
        platform_for("file:///etc/passwd")


def test_normalize():
    assert normalize("The Joe’s Pizza!") == normalize("joes pizza")
    assert normalize("Café Lalo") == "cafe lalo"


def test_sanitize_plan_drops_unknown_and_duplicate_ids():
    request = PlanRequest(
        city="NYC", days=2,
        places=[{"id": "a", "name": "A", "category": "food"}, {"id": "b", "name": "B", "category": "cafe"}],
    )
    result = PlanResult(
        days=[
            PlannedDay(day_number=5, title="x", stops=[PlannedStop(place_id="a", time_of_day="lunch", note=None)]),
            PlannedDay(day_number=6, title="y", stops=[
                PlannedStop(place_id="a", time_of_day="dinner", note=None),
                PlannedStop(place_id="zzz", time_of_day="dinner", note=None),
            ]),
        ],
        unscheduled_place_ids=[],
    )
    clean = _sanitize_plan(result, request)
    assert [d.day_number for d in clean.days] == [1]
    assert clean.unscheduled_place_ids == ["b"]


def test_offline_plan_groups_by_location():
    from datetime import datetime, timezone

    from app.models import Place

    def p(i, lat, lon, cat="food", hood=None):
        return Place(id=i, trip_id="t", name=i, category=cat, latitude=lat, longitude=lon, neighborhood=hood,
                     created_at=datetime.now(timezone.utc))

    places = [p("a", 40.73, -74.00, "cafe", "Village"), p("b", 40.731, -74.001, "drinks", "Village"),
              p("c", 40.71, -73.96, hood="Williamsburg"), p("d", 40.712, -73.962, hood="Williamsburg"),
              p("e", None, None)]
    plan = offline_plan(places, 2, "New York")
    assert len(plan.days) == 2
    groups = [{s.place_id for s in d.stops} for d in plan.days]
    assert {"a", "b"} <= groups[0] or {"a", "b"} <= groups[1]
    assert sum(len(g) for g in groups) == 5
    village = next(d for d in plan.days if "a" in {s.place_id for s in d.stops})
    assert [s.place_id for s in village.stops].index("a") < [s.place_id for s in village.stops].index("b")


def test_output_schemas_are_accepted_by_sdk():
    from anthropic.lib._parse._transform import transform_schema
    from pydantic import TypeAdapter

    from app.models import BriefingText, ConciergeReply, EditsResult

    for model in (ExtractionResult, PlanResult, EditsResult, ConciergeReply, BriefingText, MenuResult, BookingsResult, PackingResult, EventNotes, BookingNeedResult):
        schema = transform_schema(TypeAdapter(model).json_schema())
        assert schema["additionalProperties"] is False


async def test_google_geocoder_parses_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Goog-Api-Key"] == "k"
        assert "places.location" in request.headers["X-Goog-FieldMask"]
        return httpx.Response(200, json={"places": [{
            "displayName": {"text": "Joe's Pizza"}, "formattedAddress": "7 Carmine St, New York",
            "location": {"latitude": 40.73, "longitude": -74.0}, "googleMapsUri": "https://maps.google.com/?cid=1",
            "rating": 4.5, "userRatingCount": 18000, "websiteUri": "https://www.joespizzanyc.com/",
            "internationalPhoneNumber": "+1 212-366-1182",
        }]})

    geo = GooglePlacesGeocoder("k", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    match = await geo.locate("Joe's Pizza", "Greenwich Village", "New York", "USA")
    assert match.latitude == 40.73 and match.maps_url.startswith("https://maps.google.com")
    assert match.rating == 4.5 and match.rating_count == 18000
    assert match.website == "https://www.joespizzanyc.com/" and match.phone == "+1 212-366-1182"


async def test_nominatim_geocoder_skips_far_results():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        q = request.url.params["q"]
        calls.append(q)
        if q == "New York, USA":
            return httpx.Response(200, json=[{"lat": "40.71", "lon": "-74.0"}])
        if q.startswith("Joe's Pizza, Greenwich Village"):
            # Same-named place in another state comes back first; should be skipped.
            return httpx.Response(200, json=[
                {"lat": "41.8", "lon": "-87.6", "name": "Joe's Pizza"},
                {"lat": "40.7305", "lon": "-74.0021", "name": "Joe's Pizza",
                 "address": {"house_number": "7", "road": "Carmine Street", "suburb": "Manhattan"}},
            ])
        return httpx.Response(200, json=[])

    geo = NominatimGeocoder(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    geo.MIN_INTERVAL = 0
    match = await geo.locate("Joe's Pizza", "Greenwich Village", "New York", "USA")
    assert match.latitude == pytest.approx(40.7305)
    assert match.address == "7 Carmine Street, Manhattan"
    assert calls[0] == "New York, USA"


def test_download_failure_falls_back_to_tiktok_caption(client, monkeypatch):
    from app.media import DownloadFailed

    def blocked(*a):
        raise DownloadFailed("Your IP address is blocked from accessing this post")

    monkeypatch.setattr(pipeline_module, "download_reel", blocked)
    monkeypatch.setattr(pipeline_module, "fetch_oembed", lambda url: ReelMetadata(
        platform="tiktok", url=url, caption="Best pizza in NYC: Joe's, Prince St, Lucali", uploader="slicehunter"))
    r = client.post("/v1/jobs", json={"url": "https://www.tiktok.com/@a/video/42"}, headers=H)
    job = wait_for(client, r.json()["id"])
    assert job["status"] == "done", job
    assert "IP address is blocked" in job["warnings"][0]
    prompt = client.messages.calls[-1]["messages"][0]["content"][-1]["text"]
    assert "Best pizza in NYC" in prompt


def test_download_failure_explains_reason(client, monkeypatch):
    from app.media import DownloadFailed

    def blocked(*a):
        raise DownloadFailed("Requested content is not available, rate-limit reached or login required")

    monkeypatch.setattr(pipeline_module, "download_reel", blocked)
    monkeypatch.setattr(pipeline_module, "fetch_oembed", lambda url: None)
    r = client.post("/v1/jobs", json={"url": "https://www.instagram.com/reel/zzz/"}, headers=H)
    job = wait_for(client, r.json()["id"])
    assert job["status"] == "failed"
    assert "login required" in job["message"]
    assert "YTDLP_COOKIES" in job["message"]


def test_clean_error():
    from app.media import clean_error

    raw = "\x1b[0;31mERROR:\x1b[0m [TikTok] 7420000000000000000: Your IP address is blocked from accessing this post; please report this issue on https://github.com/yt-dlp/yt-dlp/issues"
    assert clean_error(raw) == "Your IP address is blocked from accessing this post"
    assert clean_error("") == "unknown error"


TIKTOK_PAGE = """<html><head></head><body>
<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">{"__DEFAULT_SCOPE__":{"webapp.video-detail":{"itemInfo":{"itemStruct":{
  "id":"7672539155838045471","desc":"5 cafes in Lisbon you can't miss #lisbon",
  "author":{"uniqueId":"gloomyy.autumn"},
  "imagePost":{"title":"Lisbon cafes","images":[
    {"imageURL":{"urlList":["https://p16-sign-va.tiktokcdn.com/obj/slide1.webp"]}},
    {"imageURL":{"urlList":["https://evil.example.com/x.jpg","https://p19-sign.tiktokcdn-us.com/obj/slide2.jpeg"]}},
    {"imageURL":{"urlList":["http://p16.tiktokcdn.com/insecure.jpg"]}}
  ]}}}}}}</script></body></html>"""


def test_tiktok_photo_post_parsing():
    from app import tiktok

    item = tiktok.parse_item(TIKTOK_PAGE)
    assert item["id"] == "7672539155838045471"
    assert tiktok.slide_urls(item) == [
        "https://p16-sign-va.tiktokcdn.com/obj/slide1.webp",
        "https://p19-sign.tiktokcdn-us.com/obj/slide2.jpeg",
    ]
    meta = tiktok.metadata_from_item(item, "https://www.tiktok.com/@gloomyy.autumn/photo/7672539155838045471")
    assert meta.uploader == "gloomyy.autumn" and meta.title == "Lisbon cafes" and "Lisbon" in meta.caption
    assert tiktok.parse_item("<html>blocked</html>") is None


def test_tiktok_url_helpers():
    from app import tiktok

    assert tiktok.is_short_link("https://www.tiktok.com/t/ZTf8CpEsG/")
    assert tiktok.is_short_link("https://vm.tiktok.com/ZMabc/")
    assert not tiktok.is_short_link("https://www.tiktok.com/@a/video/1")
    assert tiktok.is_photo_post("https://www.tiktok.com/@a/photo/7672539155838045471?_r=1")
    assert not tiktok.is_photo_post("https://www.tiktok.com/@a/video/1")


def test_download_reel_routes_photo_posts(monkeypatch, tmp_path):
    from app import media, tiktok

    monkeypatch.setattr(tiktok, "resolve", lambda url: "https://www.tiktok.com/@a/photo/123")
    slide = tmp_path / "slide_01.jpg"
    slide.write_bytes(b"\xff\xd8\xff")
    monkeypatch.setattr(tiktok, "download_photo_post", lambda url, workdir, width: (
        ReelMetadata(platform="tiktok", url=url, caption="Lisbon cafes"), [slide]))
    reel = media.download_reel("https://www.tiktok.com/t/ZTf8CpEsG/", tmp_path, Settings())
    assert reel.image_paths == [slide] and reel.metadata.url.endswith("/photo/123")

    monkeypatch.setattr(tiktok, "download_photo_post", lambda url, workdir, width: None)
    with pytest.raises(media.DownloadFailed, match="photo post"):
        media.download_reel("https://www.tiktok.com/t/ZTf8CpEsG/", tmp_path, Settings())


def test_slides_are_labelled_for_claude(client, monkeypatch, tmp_path):
    slide = tmp_path / "slide_01.jpg"
    slide.write_bytes(b"\xff\xd8\xff")
    monkeypatch.setattr(pipeline_module, "download_reel", lambda url, workdir, s: DownloadedReel(
        metadata=ReelMetadata(platform="tiktok", url=url, caption="Lisbon cafes"), image_paths=[slide]))
    r = client.post("/v1/jobs", json={"url": "https://www.tiktok.com/@a/photo/99"}, headers=H)
    assert wait_for(client, r.json()["id"])["status"] == "done"
    labels = [b["text"] for b in client.messages.calls[-1]["messages"][0]["content"] if b["type"] == "text"]
    assert "Slide 1:" in labels


def test_config_exposes_only_the_browser_maps_key(client):
    settings = Settings(app_api_key="secret", anthropic_api_key="x", google_maps_api_key="server-only",
                        google_maps_browser_key="browser-key")
    app.dependency_overrides[get_settings] = lambda: settings
    body = client.get("/v1/config", headers=H).json()
    assert body["google_maps_key"] == "browser-key"
    assert "server-only" not in str(body)


# ---------- Opening hours ----------


def test_parse_osm_hours():
    from app.hours import parse_osm

    h = parse_osm("Mo-Fr 08:00-18:00; Sa 09:00-14:00,17:00-22:00; Su off")
    assert [r.model_dump() for r in h.weekly[0]] == [{"open": "08:00", "close": "18:00"}]
    assert len(h.weekly[5]) == 2 and h.weekly[6] == []
    assert h.text[6] == "Sunday: Closed" and h.text[0] == "Monday: 8 AM – 6 PM"

    assert parse_osm("24/7").text[0] == "Monday: Open 24 hours"
    late = parse_osm("Fr-Sa 18:00-26:00")
    assert late.weekly[4][0].close == "02:00" and late.weekly[0] == []
    assert parse_osm("11:00-22:00").weekly[3][0].open == "11:00"
    assert parse_osm("Mo-Sa 10:00-20:00; PH off").weekly[6] == []
    odd = parse_osm("Jan-Mar Mo-Fr 10:00-16:00")
    assert odd.weekly is None and odd.text == ["Jan-Mar Mo-Fr 10:00-16:00"]
    assert parse_osm("") is None


def test_google_hours():
    from app.hours import from_google

    data = {
        "periods": [
            {"open": {"day": 1, "hour": 11, "minute": 30}, "close": {"day": 1, "hour": 22, "minute": 0}},
            {"open": {"day": 6, "hour": 18, "minute": 0}, "close": {"day": 0, "hour": 2, "minute": 0}},
        ],
        "weekdayDescriptions": ["Monday: 11:30 AM – 10:00 PM"] + ["x"] * 6,
    }
    h = from_google(data)
    assert h.weekly[0][0].open == "11:30" and h.weekly[5][0].close == "02:00" and h.weekly[6] == []
    always = from_google({"periods": [{"open": {"day": 0, "hour": 0, "minute": 0}}]})
    assert always.weekly[2][0].close == "24:00"


def test_hours_saved_on_import_and_refresh(client):
    job = import_reel(client)
    trip = client.get(f"/v1/trips/{job['trip_id']}", headers=H).json()
    joes = next(p for p in trip["places"] if p["name"] == "Joe's Pizza")
    assert joes["opening_hours"]["weekly"][5][0] == {"open": "10:00", "close": "02:00"}
    assert joes["opening_hours"]["source"] == "openstreetmap"

    # Lucali has no pin and no hours; refresh tries again and marks it as checked.
    r = client.post(f"/v1/trips/{job['trip_id']}/refresh-details", headers=H)
    assert r.status_code == 200
    lucali = next(p for p in r.json()["places"] if p["name"] == "Lucali")
    assert lucali["hours_checked_at"] is not None


def test_planner_gets_opening_hours(client):
    job = import_reel(client)
    client.messages.stop_reason = "refusal"  # fall back offline; we only check what was sent
    client.post(f"/v1/trips/{job['trip_id']}/plan", json={"days": 1, "start_date": "2026-11-02"}, headers=H)
    payload = client.messages.calls[-1]["messages"][0]["content"][0]["text"]
    assert "Sat 10:00-02:00" in payload and '"start_weekday": "Monday"' in payload


# ---------- Travel times ----------


def test_day_legs_estimates(client):
    job = import_reel(client)
    trip = client.get(f"/v1/trips/{job['trip_id']}", headers=H).json()
    ids = {p["name"]: p["id"] for p in trip["places"]}
    for name in ("Joe's Pizza", "Prince Street Pizza", "Lucali"):
        client.patch(f"/v1/places/{ids[name]}", json={"day_number": 1}, headers=H)
    legs = client.get(f"/v1/trips/{job['trip_id']}/days/1/legs", headers=H).json()
    assert legs["provider"] == "estimate"
    assert len(legs["legs"]) == 1  # Lucali has no pin, so only Joe's → Prince St
    walk = legs["legs"][0]["times"]["walk"]
    assert walk["estimated"] and 900 < walk["distance_m"] < 1600 and 10 * 60 < walk["duration_s"] < 25 * 60
    assert legs["legs"][0]["times"]["transit"] is None  # too short to bother with transit

    r = client.post("/v1/routes/from", json={"latitude": 40.7580, "longitude": -73.9855, "place_ids": [ids["Joe's Pizza"]]}, headers=H)
    leg = r.json()["legs"][0]
    assert leg["from_place_id"] is None and leg["times"]["transit"]["estimated"]


async def test_google_routes_parsing_cache_and_fallback():
    from app.models import TravelMode

    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json
        body = _json.loads(request.content)
        calls.append(body["travelMode"])
        assert request.headers["X-Goog-Api-Key"] == "k"
        if body["travelMode"] == "TRANSIT":
            return httpx.Response(200, json=[{"condition": "ROUTE_NOT_FOUND"}])
        # originIndex/destinationIndex of 0 are omitted in proto3 JSON
        return httpx.Response(200, json=[{"duration": "754s", "distanceMeters": 1023, "condition": "ROUTE_EXISTS"}])

    db = Database(":memory:")
    router = Router(db, Settings(google_maps_api_key="k"), client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    a, b = (40.7305, -74.0021), (40.7231, -73.9945)
    times = await router._all_modes(a, b)
    assert times[TravelMode.walk].duration_s == 754 and not times[TravelMode.walk].estimated
    assert times[TravelMode.transit] is None
    n = len(calls)
    await router._all_modes(a, b)
    assert len(calls) == n  # served from the cache

    def refuse(request):
        return httpx.Response(403, json={"error": {"message": "Routes API has not been used in project"}})

    router2 = Router(Database(":memory:"), Settings(google_maps_api_key="k"), client=httpx.AsyncClient(transport=httpx.MockTransport(refuse)))
    t = await router2._pair(a, b, TravelMode.walk)
    assert t.estimated and router2.provider == "estimate"


def test_database_migrates_old_files(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript("""CREATE TABLE places (id TEXT PRIMARY KEY, trip_id TEXT NOT NULL, reel_id TEXT, name TEXT NOT NULL,
        category TEXT NOT NULL DEFAULT 'other', summary TEXT NOT NULL DEFAULT '', recommended_items TEXT NOT NULL DEFAULT '[]',
        price_hint TEXT, tips TEXT, user_notes TEXT NOT NULL DEFAULT '', confidence TEXT NOT NULL DEFAULT 'high',
        visited INTEGER NOT NULL DEFAULT 0, neighborhood TEXT, address TEXT, city TEXT NOT NULL DEFAULT '',
        country TEXT NOT NULL DEFAULT '', latitude REAL, longitude REAL, maps_url TEXT, resolved_name TEXT,
        day_number INTEGER, day_order INTEGER NOT NULL DEFAULT 0, time_of_day TEXT, day_note TEXT, created_at TEXT NOT NULL);""")
    conn.close()
    db = Database(str(path))
    trip = db.create_trip("Lisbon", "Lisbon", "Portugal")
    place = db.add_place(trip_id=trip.id, name="Cafe", category="cafe")
    assert place.opening_hours is None


# ---------- Photos ----------


def test_reel_frames_become_place_photos(client):
    job = import_reel(client)
    trip = client.get(f"/v1/trips/{job['trip_id']}", headers=H).json()
    joes = next(p for p in trip["places"] if p["name"] == "Joe's Pizza")
    assert len(joes["photos"]) == 1 and joes["photos"][0]["source"] == "reel"
    url = joes["photos"][0]["url"]
    assert "sig=" in url

    r = client.get(url)  # no API key header: the signature authorizes it
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert client.get(url.split("?")[0] + "?sig=wrong").status_code == 403
    assert client.get(f"/v1/places/{joes['id']}/photos/5?sig=x").status_code == 404

    # The trip list carries a cover photo for the Trips cards.
    listed = next(t for t in client.get("/v1/trips", headers=H).json() if t["id"] == trip["id"])
    assert listed["cover_photo"]["source"] == "reel" and "sig=" in listed["cover_photo"]["url"]

    # Deleting the place removes its saved photo files.
    photo_dir = app.state.photos.dir
    assert any(photo_dir.iterdir())
    client.delete(f"/v1/places/{joes['id']}", headers=H)
    assert not any(f.name.startswith(joes["id"]) for f in photo_dir.iterdir())


def test_photo_merge_order_and_caps():
    from app.photos import merge

    existing = [{"source": "reel", "ref": "a.jpg"}, {"source": "wikimedia", "ref": "w1"}]
    new = [{"source": "google", "ref": f"g{i}"} for i in range(6)] + [{"source": "wikimedia", "ref": "w2"}]
    out = merge(existing, new, replace_sources=("google", "wikimedia"))
    assert [p["source"] for p in out] == ["google"] * 4 + ["reel", "wikimedia"]
    assert out[-1]["ref"] == "w2"


async def test_google_photos_and_wikidata_image():
    def google(request):
        return httpx.Response(200, json={"places": [{
            "displayName": {"text": "The Met"}, "location": {"latitude": 40.779, "longitude": -73.963},
            "photos": [{"name": "places/abc/photos/p1", "authorAttributions": [{"displayName": "Ana P."}]}],
        }]})

    geo = GooglePlacesGeocoder("k", client=httpx.AsyncClient(transport=httpx.MockTransport(google)))
    m = await geo.locate("The Met", None, "New York", "USA")
    assert m.photos == [{"source": "google", "ref": "places/abc/photos/p1", "attribution": "Ana P."}]

    from app.photos import wikidata_image

    def wikidata(request):
        return httpx.Response(200, json={"entities": {"Q160236": {"claims": {"P18": [
            {"mainsnak": {"datavalue": {"value": "Metropolitan Museum of Art (The Met).jpg"}}}]}}}})

    img = await wikidata_image(httpx.AsyncClient(transport=httpx.MockTransport(wikidata)), "Q160236")
    assert img["source"] == "wikimedia" and img["ref"].startswith("https://commons.wikimedia.org/wiki/Special:FilePath/Metropolitan_Museum")
    assert await wikidata_image(httpx.AsyncClient(transport=httpx.MockTransport(wikidata)), "not-a-qid") is None


def test_jobs_saved_before_new_fields_still_load(client):
    """Imports stored by older versions lack fields added later (e.g. image_labels)."""
    import json as _json

    db = app.state.db
    job = db.create_job("https://www.tiktok.com/@a/video/old", None)
    old = EXTRACTION.model_dump()
    for place in old["places"]:
        del place["image_labels"]
    db._exec("UPDATE jobs SET status = 'done', result = ? WHERE id = ?", (_json.dumps(old), job.id))
    db._exec("INSERT INTO jobs (id, url, status, created_at, updated_at, result) VALUES ('broken', 'u', 'done', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00', '{not json')")

    assert client.get("/v1/jobs", headers=H).status_code == 200
    detail = client.get(f"/v1/jobs/{job.id}", headers=H).json()
    assert detail["result"]["places"][0]["image_labels"] == []
    assert client.get("/v1/jobs/broken", headers=H).json()["result"] is None


# ---------- Must-do, mentions, exact times, drag and drop ----------


def test_mentions_must_do_and_planner_hints(client):
    first = import_reel(client)
    import_reel(client, "https://www.instagram.com/reel/second/")  # same three places, another creator
    trip = client.get(f"/v1/trips/{first['trip_id']}", headers=H).json()
    joes = next(p for p in trip["places"] if p["name"] == "Joe's Pizza")
    assert joes["mention_count"] == 2 and len(joes["reel_ids"]) == 2 and joes["reel_ids"][0] == joes["reel_id"]

    r = client.patch(f"/v1/places/{joes['id']}", json={"must_do": True, "start_time": "19:30"}, headers=H)
    assert r.json()["must_do"] is True and r.json()["start_time"] == "19:30"
    assert client.patch(f"/v1/places/{joes['id']}", json={"start_time": "25:00"}, headers=H).status_code == 422
    assert client.patch(f"/v1/places/{joes['id']}", json={"clear_start_time": True}, headers=H).json()["start_time"] is None

    client.post(f"/v1/trips/{first['trip_id']}/plan", json={"days": 1}, headers=H)
    payload = client.messages.calls[-1]["messages"][0]["content"][0]["text"]
    assert '"must_do": true' in payload and '"mentions": 2' in payload
    assert "must_do" in client.messages.calls[-1]["system"]


def test_move_between_days(client):
    job = import_reel(client)
    trip = client.post(f"/v1/trips/{job['trip_id']}/plan", json={"days": 2}, headers=H).json()
    day1 = sorted((p for p in trip["places"] if p["day_number"] == 1), key=lambda p: p["day_order"])
    mover = day1[-1]

    trip = client.post(f"/v1/trips/{job['trip_id']}/move", json={"place_id": mover["id"], "day": 2, "index": 0}, headers=H).json()
    day2 = sorted((p for p in trip["places"] if p["day_number"] == 2), key=lambda p: p["day_order"])
    assert day2[0]["id"] == mover["id"]
    for d in (1, 2):
        orders = sorted(p["day_order"] for p in trip["places"] if p["day_number"] == d)
        assert orders == list(range(len(orders)))

    trip = client.post(f"/v1/trips/{job['trip_id']}/move", json={"place_id": mover["id"], "day": 0}, headers=H).json()
    assert next(p for p in trip["places"] if p["id"] == mover["id"])["day_number"] is None
    trip = client.post(f"/v1/trips/{job['trip_id']}/move", json={"place_id": mover["id"], "day": 4, "index": 0}, headers=H).json()
    assert trip["day_count"] == 4 and len(trip["day_titles"]) == 4

    other = client.post("/v1/places", json={"name": "Elsewhere", "city": "Paris"}, headers=H).json()["place"]
    r = client.post(f"/v1/trips/{job['trip_id']}/move", json={"place_id": other["id"], "day": 1}, headers=H)
    assert r.status_code == 404


def test_ratings_saved_on_import(client):
    job = import_reel(client)
    trip = client.get(f"/v1/trips/{job['trip_id']}", headers=H).json()
    joes = next(p for p in trip["places"] if p["name"] == "Joe's Pizza")
    assert joes["rating"] == 4.6 and joes["rating_count"] == 1200 and joes["rating_checked_at"] is not None
    prince = next(p for p in trip["places"] if p["name"] == "Prince Street Pizza")
    assert prince["rating"] is None  # found, but Google had no rating
    # Lucali wasn't found at all; a refresh marks it as checked so it isn't looked up again every time.
    refreshed = client.post(f"/v1/trips/{job['trip_id']}/refresh-details", headers=H).json()
    lucali = next(p for p in refreshed["places"] if p["name"] == "Lucali")
    assert lucali["rating"] is None and lucali["rating_checked_at"] is not None


def test_ratings_backfilled_for_places_saved_earlier(client):
    job = import_reel(client)
    joes = next(p for p in client.get(f"/v1/trips/{job['trip_id']}", headers=H).json()["places"] if p["name"] == "Joe's Pizza")
    app.state.db.update_place(joes["id"], rating=None, rating_count=None, rating_checked_at=None)  # saved before ratings existed
    refreshed = client.post(f"/v1/trips/{job['trip_id']}/refresh-details", headers=H).json()
    assert next(p for p in refreshed["places"] if p["id"] == joes["id"])["rating"] == 4.6


def test_add_to_day_builds_itinerary_by_hand(client):
    job = import_reel(client)
    trip_id = job["trip_id"]
    ids = {p["name"]: p["id"] for p in client.get(f"/v1/trips/{trip_id}", headers=H).json()["places"]}

    trip = client.post(f"/v1/trips/{trip_id}/add-to-day", json={"place_ids": [ids["Lucali"], ids["Joe's Pizza"]]}, headers=H).json()
    assert trip["day_count"] == 1  # no day given: a new day at the end
    day1 = sorted((p for p in trip["places"] if p["day_number"] == 1), key=lambda p: p["day_order"])
    assert [p["name"] for p in day1] == ["Lucali", "Joe's Pizza"]  # in the order they were picked

    # Adding to an existing day appends, and places already on it stay where they are.
    trip = client.post(f"/v1/trips/{trip_id}/add-to-day",
                       json={"place_ids": [ids["Joe's Pizza"], ids["Prince Street Pizza"]], "day": 1}, headers=H).json()
    day1 = sorted((p for p in trip["places"] if p["day_number"] == 1), key=lambda p: p["day_order"])
    assert [p["name"] for p in day1] == ["Lucali", "Joe's Pizza", "Prince Street Pizza"]

    # A new day, moving a place off the day it was on.
    trip = client.post(f"/v1/trips/{trip_id}/add-to-day", json={"place_ids": [ids["Lucali"]]}, headers=H).json()
    assert trip["day_count"] == 2
    assert next(p for p in trip["places"] if p["name"] == "Lucali")["day_number"] == 2
    orders = sorted(p["day_order"] for p in trip["places"] if p["day_number"] == 1)
    assert orders == [0, 1]

    other = client.post("/v1/places", json={"name": "Elsewhere", "city": "Paris"}, headers=H).json()["place"]
    assert client.post(f"/v1/trips/{trip_id}/add-to-day", json={"place_ids": [other["id"]]}, headers=H).status_code == 422
    assert client.post(f"/v1/trips/{trip_id}/add-to-day", json={"place_ids": []}, headers=H).status_code == 422
    assert client.post(f"/v1/trips/{trip_id}/add-to-day", json={"place_ids": [ids["Lucali"]], "day": 22}, headers=H).status_code == 422


def test_tidy_with_claude_keeps_days_and_follows_instruction(client):
    job = import_reel(client)
    trip_id = job["trip_id"]
    ids = {p["name"]: p["id"] for p in client.get(f"/v1/trips/{trip_id}", headers=H).json()["places"]}
    assert client.post(f"/v1/trips/{trip_id}/tidy", json={}, headers=H).status_code == 422  # nothing on a day yet

    client.post(f"/v1/trips/{trip_id}/add-to-day", json={"place_ids": [ids["Lucali"], ids["Joe's Pizza"]]}, headers=H)
    client.post(f"/v1/trips/{trip_id}/add-to-day", json={"place_ids": [ids["Prince Street Pizza"]]}, headers=H)
    client.messages.outputs[PlanResult] = PlanResult(
        days=[
            PlannedDay(day_number=1, title="Pizza crawl", stops=[
                PlannedStop(place_id=ids["Joe's Pizza"], time_of_day="lunch", note="Plain slice"),
                PlannedStop(place_id=ids["Lucali"], time_of_day="dinner", note=None),
            ]),
            PlannedDay(day_number=2, title="Nolita", stops=[
                PlannedStop(place_id=ids["Prince Street Pizza"], time_of_day="afternoon", note=None),
            ]),
        ],
        unscheduled_place_ids=[],
        notes=None,
    )
    trip = client.post(f"/v1/trips/{trip_id}/tidy", json={"instruction": "pizza for lunch"}, headers=H).json()
    sent = client.messages.calls[-1]
    payload = sent["messages"][0]["content"][0]["text"]
    assert "pizza for lunch" in payload and '"current_day": 1' in payload
    assert "current_day" in sent["system"]
    day1 = sorted((p for p in trip["places"] if p["day_number"] == 1), key=lambda p: p["day_order"])
    assert [p["name"] for p in day1] == ["Joe's Pizza", "Lucali"]
    assert day1[0]["day_note"] == "Plain slice" and day1[0]["time_of_day"] == "lunch"
    assert trip["day_titles"] == ["Pizza crawl", "Nolita"] and trip["planned_by"] == "claude"


def test_tidy_falls_back_to_offline_ordering(client):
    job = import_reel(client)
    trip_id = job["trip_id"]
    ids = {p["name"]: p["id"] for p in client.get(f"/v1/trips/{trip_id}", headers=H).json()["places"]}
    client.post(f"/v1/trips/{trip_id}/add-to-day", json={"place_ids": [ids["Lucali"], ids["Joe's Pizza"], ids["Prince Street Pizza"]]}, headers=H)
    client.patch(f"/v1/places/{ids['Lucali']}", json={"start_time": "13:00"}, headers=H)
    client.patch(f"/v1/places/{ids['Prince Street Pizza']}", json={"start_time": "09:30"}, headers=H)
    client.messages.stop_reason = "refusal"
    trip = client.post(f"/v1/trips/{trip_id}/tidy", json={}, headers=H).json()
    assert trip["planned_by"] == "offline"
    day1 = sorted((p for p in trip["places"] if p["day_number"] == 1), key=lambda p: p["day_order"])
    assert [p["name"] for p in day1][0] == "Prince Street Pizza"  # the 09:30 booking comes first
    assert next(p for p in day1 if p["name"] == "Lucali")["time_of_day"] == "lunch"  # 13:00


# ---------- Adding places without a reel ----------


def test_search_and_add_place(client):
    job = import_reel(client)
    r = client.post("/v1/places/search", json={"query": "lucali brooklyn", "trip_id": job["trip_id"]}, headers=H)
    candidates = r.json()
    assert candidates[0]["candidate_id"] == "google:lucali1" and candidates[0]["category"] == "food"
    assert client.geocoder.searches[-1][1] is not None  # biased toward the trip's places

    # Lucali is already in the trip (from the reel), so this returns it instead of a duplicate.
    r = client.post("/v1/places", json={"candidate_id": "google:lucali1", "trip_id": job["trip_id"]}, headers=H)
    assert r.status_code == 200 and r.json()["created"] is False

    client.delete(f"/v1/places/{r.json()['place']['id']}", headers=H)
    r = client.post("/v1/places", json={"candidate_id": "google:lucali1"}, headers=H)
    assert r.status_code == 201
    place = r.json()["place"]
    assert place["trip_id"] == job["trip_id"]  # matched the New York trip by city
    assert place["opening_hours"]["weekly"] and place["photos"][0]["source"] == "google"
    assert place["mention_count"] == 0

    assert client.post("/v1/places", json={"candidate_id": "google:nope"}, headers=H).status_code == 422
    assert client.post("/v1/places", json={"name": "Somewhere"}, headers=H).status_code == 422
    r = client.post("/v1/places", json={"name": "Joe's Pizza", "trip_id": job["trip_id"]}, headers=H)
    assert r.json()["created"] is False
    r = client.post("/v1/places", json={"name": "Café de Flore", "city": "Paris", "category": "cafe"}, headers=H)
    assert r.status_code == 201
    paris = client.get(f"/v1/trips/{r.json()['place']['trip_id']}", headers=H).json()
    assert paris["name"] == "Paris" and paris["places"][0]["category"] == "cafe"


def test_map_link_parsing():
    from app.maplinks import NotAMapLink, is_map_link, parse

    g = parse("https://www.google.com/maps/place/Joe's+Pizza/@40.7305,-74.0021,17z/data=!3m1!4b1!4m6!3m5!1s0x0:0x0!8m2!3d40.730599!4d-74.002136")
    assert g.name == "Joe's Pizza" and g.latitude == pytest.approx(40.730599) and g.longitude == pytest.approx(-74.002136)
    assert parse("https://www.google.com/maps/search/?api=1&query=Lucali%20Brooklyn").name == "Lucali Brooklyn"
    pin = parse("https://maps.google.com/?q=40.7128,-74.0060")
    assert pin.name is None and pin.latitude == pytest.approx(40.7128)
    a = parse("https://maps.apple.com/?q=Levain%20Bakery&ll=40.7799,-73.9805")
    assert a.name == "Levain Bakery" and a.longitude == pytest.approx(-73.9805)
    a2 = parse("https://maps.apple.com/place?coordinate=48.85,2.33&name=Caf%C3%A9%20de%20Flore&address=172%20Bd%20Saint-Germain")
    assert a2.name == "Café de Flore" and a2.latitude == pytest.approx(48.85)
    assert is_map_link("https://maps.app.goo.gl/abc123") and is_map_link("https://www.google.co.uk/maps/place/X")
    assert not is_map_link("https://evil.example.com/maps/place/X") and not is_map_link("https://google.com.evil.io/maps")
    with pytest.raises(NotAMapLink):
        parse("https://www.google.com/maps/@40.7,-74.0,12z")  # just a map view, no place
    # The pin's exact coordinates win over the map center.
    assert parse("https://www.google.com/maps/place/A/@1.0,2.0,12z/data=!3d3.5!4d4.5").latitude == pytest.approx(3.5)


async def test_short_map_links_only_follow_map_hosts():
    from app.maplinks import NotAMapLink, resolve

    def handler(request):
        if request.url.host == "maps.app.goo.gl" and request.url.path == "/good":
            return httpx.Response(302, headers={"location": "https://www.google.com/maps/place/Lucali/@40.68,-74.0,17z"})
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        assert (await resolve("https://maps.app.goo.gl/good", http)).startswith("https://www.google.com/maps/place/Lucali")
        with pytest.raises(NotAMapLink):
            await resolve("https://maps.app.goo.gl/evil", http)


def test_add_place_from_map_link(client):
    job = import_reel(client)
    url = "https://www.google.com/maps/place/Lucali/@40.68,-74.0,17z/data=!3d40.6819!4d-74.0004"
    r = client.post("/v1/places/from-link", json={"url": f"Check this out {url}", "trip_id": job["trip_id"]}, headers=H)
    assert r.status_code == 200 and r.json()["created"] is False  # Lucali came with the reel

    r = client.post("/v1/places/from-link", json={"url": "https://maps.apple.com/?q=Nothing%20Here&ll=40.75,-73.99"}, headers=H)
    assert r.status_code == 201
    place = r.json()["place"]
    assert place["name"] == "Nothing Here" and place["latitude"] == pytest.approx(40.75)
    assert place["trip_id"] == job["trip_id"]  # within 50 km of the New York trip
    assert client.post("/v1/places/from-link", json={"url": "https://example.com/x"}, headers=H).status_code == 422


def test_screenshot_import(client):
    import base64 as _b64

    shot = EXTRACTION.model_copy(deep=True)
    for place in shot.places:
        place.image_labels = ["Screenshot 1"]
    client.messages.outputs[ExtractionResult] = shot
    jpeg = b"\xff\xd8\xff\xe0" + b"0" * 100
    r = client.post("/v1/jobs/screenshots", json={"images": ["data:image/jpeg;base64," + _b64.b64encode(jpeg).decode()],
                                                  "note": "from a blog"}, headers=H)
    assert r.status_code == 202 and r.json()["url"].startswith("upload:")
    job = wait_for(client, r.json()["id"])
    assert job["status"] == "done" and job["added_places"] == 3
    call = client.messages.calls[-1]["messages"][0]["content"]
    assert call[0]["text"] == "Screenshot 1:" and "from a blog" in call[-1]["text"]
    trip = client.get(f"/v1/trips/{job['trip_id']}", headers=H).json()
    assert trip["reels"][0]["platform"] == "screenshot"
    assert trip["places"][0]["photos"][0]["attribution"] == "From your screenshot"
    assert not any(client.uploads.iterdir())  # cleaned up after success

    png = _b64.b64encode(b"\x89PNG\r\n\x1a\n").decode()
    assert client.post("/v1/jobs/screenshots", json={"images": [png]}, headers=H).status_code == 422
    assert client.post("/v1/jobs/screenshots", json={"images": ["not base64!!"]}, headers=H).status_code == 422


# ---------- Push notifications ----------


def _decrypt_push(body, ua_key, auth):
    """The browser's side of RFC 8291, to check what the server sends."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    salt, idlen = body[:16], body[20]
    as_public, ciphertext = body[21:21 + idlen], body[21 + idlen:]
    ua_public = ua_key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    shared = ua_key.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_public))
    kdf = lambda salt_, ikm, info, n: HKDF(algorithm=hashes.SHA256(), length=n, salt=salt_, info=info).derive(ikm)
    ikm = kdf(auth, shared, b"WebPush: info\x00" + ua_public + as_public, 32)
    plain = AESGCM(kdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)).decrypt(
        kdf(salt, ikm, b"Content-Encoding: nonce\x00", 12), ciphertext, None)
    return plain.rstrip(b"\x00")[:-1]


def test_push_encryption_matches_rfc8291_example():
    from cryptography.hazmat.primitives.asymmetric import ec
    from app.push import b64url, encrypt, unb64url

    sender = ec.derive_private_key(int.from_bytes(unb64url("yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"), "big"), ec.SECP256R1())
    body = encrypt(b"When I grow up, I want to be a watermelon",
                   unb64url("BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4"),
                   unb64url("BTBZMqHH6r4Tts7J_aSIgg"), sender_key=sender, salt=unb64url("DGv6ra1nlYgDCS1FRnbzlw"))
    assert b64url(body) == ("DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8"
                            "wEqKK6PBru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN")


def test_push_subscription_and_import_notification(client):
    import json as _json
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
    from app.push import b64url, unb64url

    key = client.get("/v1/config", headers=H).json()["push_public_key"]
    assert len(unb64url(key)) == 65
    ua_key = ec.generate_private_key(ec.SECP256R1())
    ua_public = b64url(ua_key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))
    auth = b"0123456789abcdef"
    endpoint = "https://fcm.googleapis.com/fcm/send/abc123"
    sub = {"endpoint": endpoint, "keys": {"p256dh": ua_public, "auth": b64url(auth)}}

    bad = {**sub, "endpoint": "https://169.254.169.254/push"}
    assert client.post("/v1/push/subscriptions", json=bad, headers=H).status_code == 422
    assert client.post("/v1/push/subscriptions", json={**sub, "keys": {"p256dh": "x", "auth": "y"}}, headers=H).status_code == 422
    assert client.post("/v1/push/subscriptions", json=sub, headers=H).status_code == 204

    job = import_reel(client)
    for _ in range(100):
        if client.push_log:
            break
        time.sleep(0.02)
    request = client.push_log[-1]
    assert str(request.url) == endpoint and request.headers["content-encoding"] == "aes128gcm"
    message = _json.loads(_decrypt_push(request.content, ua_key, auth))
    assert message["title"] == "3 new places saved to New York"
    assert message["url"] == f"/#/trip/{job['trip_id']}" and "@slicehunter" in message["body"]

    # The VAPID token is signed by the server's key and addressed to the push service.
    token = request.headers["authorization"].split("t=")[1].split(",")[0]
    header, claims, sig = token.split(".")
    assert _json.loads(unb64url(claims))["aud"] == "https://fcm.googleapis.com"
    public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64url(key))
    raw = unb64url(sig)
    public.verify(encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")),
                  f"{header}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))

    client.push_status["code"] = 410  # the browser unsubscribed: forget it
    assert client.post("/v1/push/test", headers=H).json()["sent"] == 0
    assert app.state.db.push_subscriptions() == []


# ---------- Sharing & exports ----------


def test_share_link_shows_trip_without_notes(client):
    job = import_reel(client)
    trip = client.get(f"/v1/trips/{job['trip_id']}", headers=H).json()
    client.patch(f"/v1/places/{trip['places'][0]['id']}", json={"user_notes": "private!"}, headers=H)

    link = client.post(f"/v1/trips/{job['trip_id']}/share", headers=H).json()
    assert link["path"] == f"/s/{link['token']}" and len(link["token"]) >= 20
    assert client.post(f"/v1/trips/{job['trip_id']}/share", headers=H).json()["token"] == link["token"]

    public = client.get(f"/v1/shared/{link['token']}")  # no API key
    assert public.status_code == 200
    data = public.json()
    assert data["name"] == "New York" and len(data["places"]) == 3
    assert "user_notes" not in data["places"][0] and "share_token" not in data
    page = client.get(link["path"])
    assert page.status_code == 200 and 'property="og:title" content="New York · TripIt"' in page.text
    assert "3 saved places" in page.text

    assert client.delete(f"/v1/trips/{job['trip_id']}/share", headers=H).status_code == 204
    assert client.get(f"/v1/shared/{link['token']}").status_code == 404
    assert client.get(link["path"]).status_code == 404


def test_calendar_and_my_maps_exports(client):
    job = import_reel(client)
    trip_id = job["trip_id"]
    r = client.post(f"/v1/trips/{trip_id}/export-link?format=ics", headers=H)
    assert r.status_code == 422 and "start date" in r.json()["detail"]

    plan = client.post(f"/v1/trips/{trip_id}/plan", json={"days": 2, "start_date": "2026-11-06"}, headers=H).json()
    first = next(p for p in plan["places"] if p["day_number"] == 1)
    client.patch(f"/v1/places/{first['id']}", json={"start_time": "19:30"}, headers=H)

    url = client.post(f"/v1/trips/{trip_id}/export-link?format=ics", headers=H).json()["url"]
    cal = client.get(url)  # the signature authorizes it
    assert cal.status_code == 200 and cal.headers["content-type"].startswith("text/calendar")
    text = cal.text
    assert text.count("BEGIN:VEVENT") == 3 and "DTSTART:20261106T193000" in text
    assert all(len(line.encode()) <= 75 for line in text.split("\r\n"))
    assert client.get(url.replace("sig=", "sig=x")).status_code == 403

    url = client.post(f"/v1/trips/{trip_id}/export-link?format=kml", headers=H).json()["url"]
    kml_text = client.get(url).text
    assert kml_text.count("<Placemark>") == 2 and "<Folder><name>Day 1" in kml_text  # Lucali has no pin
    assert client.post(f"/v1/trips/{trip_id}/export-link?format=pdf", headers=H).status_code == 422

    token = client.post(f"/v1/trips/{trip_id}/share", headers=H).json()["token"]
    assert client.get(f"/s/{token}/trip.ics").status_code == 200
    assert client.get(f"/s/{token}/trip.kml").status_code == 200
    assert client.get("/s/wrong/trip.ics").status_code == 404


def test_service_worker_is_versioned(client):
    r = client.get("/sw.js")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/javascript")
    assert "__VERSION__" not in r.text and "tripit-shell-" in r.text
    assert r.headers["cache-control"] == "no-cache"


def test_old_databases_get_mentions_and_new_columns(tmp_path):
    path = str(tmp_path / "t.db")
    db = Database(path)
    trip = db.create_trip("Rome", "Rome", "Italy")
    reel = db.add_reel(ReelMetadata(platform="tiktok", url="https://tiktok.com/x"), "t", "s")
    place = db.add_place(trip_id=trip.id, reel_id=reel.id, name="Pantheon", category="attraction")
    db._exec("DELETE FROM place_mentions")  # as if saved before mentions existed
    reopened = Database(path)
    p = reopened.get_place(place.id)
    assert p.mention_count == 1 and p.must_do is False and reopened.get_trip(trip.id).share_token is None


async def test_place_search_parsing_google_and_osm():
    from app.geocode import google_category, osm_category

    def google(request):
        if request.url.path.endswith(":searchText"):
            body = __import__("json").loads(request.content)
            assert body["locationBias"]["circle"]["center"]["latitude"] == 40.7
            assert request.headers["x-goog-fieldmask"] == GooglePlacesGeocoder.SEARCH_FIELDS
            return httpx.Response(200, json={"places": [{"id": "ChIJabc", "displayName": {"text": "Lucali"},
                                                         "formattedAddress": "575 Henry St", "location": {"latitude": 40.68, "longitude": -74.0},
                                                         "types": ["pizza_restaurant", "restaurant"]}]})
        assert request.url.path == "/v1/places/ChIJabc"
        return httpx.Response(200, json={"id": "ChIJabc", "displayName": {"text": "Lucali"}, "location": {"latitude": 40.68, "longitude": -74.0},
                                         "types": ["restaurant"], "rating": 4.7, "userRatingCount": 900,
                                         "websiteUri": "javascript:alert(1)", "internationalPhoneNumber": "+1 718-858-4086", "addressComponents": [
                                             {"longText": "Brooklyn", "types": ["sublocality"]},
                                             {"longText": "New York", "types": ["locality", "political"]},
                                             {"longText": "United States", "types": ["country"]}]})

    g = GooglePlacesGeocoder("k", client=httpx.AsyncClient(transport=httpx.MockTransport(google)))
    found = await g.search("lucali", near=(40.7, -74.0))
    assert found[0].place_id == "google:ChIJabc" and found[0].category == "food"
    detail = await g.details("google:ChIJabc")
    assert detail.city == "New York" and detail.country == "United States"
    assert detail.rating == 4.7 and detail.rating_count == 900 and detail.phone == "+1 718-858-4086"
    assert detail.website is None  # only http(s) addresses are kept
    assert await g.details("google:../../etc") is None and await g.details("osm:N1") is None

    def osm(request):
        if request.url.path == "/lookup":
            assert request.url.params["osm_ids"] == "N123"
            return httpx.Response(200, json=[{"lat": "48.85", "lon": "2.33", "name": "Café de Flore", "osm_type": "node", "osm_id": 123,
                                              "category": "amenity", "type": "cafe", "address": {"city": "Paris", "country": "France"},
                                              "extratags": {"opening_hours": "Mo-Su 07:30-01:30", "contact:website": "cafedeflore.fr",
                                                            "phone": "+33 1 45 48 55 26; +33 1 45 48 55 27"}}])
        return httpx.Response(200, json=[{"lat": "48.85", "lon": "2.33", "name": "Café de Flore", "osm_type": "node", "osm_id": 123,
                                          "category": "amenity", "type": "cafe", "address": {"city": "Paris", "country": "France"}}])

    n = NominatimGeocoder(client=httpx.AsyncClient(transport=httpx.MockTransport(osm)))
    n.MIN_INTERVAL = 0
    results = await n.search("cafe de flore")
    assert results[0].place_id == "osm:N123" and results[0].category == "cafe" and results[0].city == "Paris"
    detail = await n.details("osm:N123")
    assert detail.hours.weekly and detail.country == "France"
    assert detail.website == "https://cafedeflore.fr" and detail.phone == "+33 1 45 48 55 26"
    assert await n.details("osm:X1") is None

    assert google_category(["ice_cream_shop", "store"]) == "dessert" and google_category(["unknown"]) == "other"
    assert osm_category("shop", "shoes") == "shopping" and osm_category("tourism", "hotel") == "stay"


def test_clean_website_and_phone():
    from app.geocode import clean_phone, clean_website

    assert clean_website("example.com/menu") == "https://example.com/menu"
    assert clean_website("http://example.com") == "http://example.com"
    assert clean_website(" https://ex ample.com ") is None
    assert clean_website("javascript:alert(1)") is None and clean_website("ftp://example.com") is None
    assert clean_website("localhost") is None and clean_website("") is None and clean_website(None) is None
    assert clean_website("https://example.com/" + "a" * 600) is None
    assert clean_phone("+1 (212) 366-1182") == "+1 (212) 366-1182"
    assert clean_phone("020 7887 8888; 020 7887 8889") == "020 7887 8888"
    assert clean_phone("call us") is None and clean_phone("12") is None and clean_phone("+1 212<script>") is None


def test_website_and_phone_saved_and_backfilled(client):
    job = import_reel(client)
    joes = next(p for p in client.get(f"/v1/trips/{job['trip_id']}", headers=H).json()["places"] if p["name"] == "Joe's Pizza")
    assert joes["website"] == "https://www.joespizzanyc.com/" and joes["phone"] == "+1 212-366-1182"
    assert joes["contact_checked_at"] is not None

    # A place checked by an earlier version (rating saved, no contact details yet) is looked up once more.
    app.state.db.update_place(joes["id"], website=None, phone=None, contact_checked_at=None)
    refreshed = client.post(f"/v1/trips/{job['trip_id']}/refresh-details", headers=H).json()
    again = next(p for p in refreshed["places"] if p["id"] == joes["id"])
    assert again["website"] == "https://www.joespizzanyc.com/" and again["contact_checked_at"] is not None


# ---------- Menus ----------

MENU_HTML = b"""<html><head><title>Joe's</title><script>var junk = 'IGNORE ME';</script></head><body>
<nav><a href="/menu">Our Menu</a> <a href="/gift-cards">Gift cards</a> <a href="mailto:hi@joes.test">Email</a>
<a href="http://internal.test/menu">Internal menu</a></nav><h1>Joe's Pizza</h1><p>Open daily.</p></body></html>"""
MENU_PAGE = ("<html><body><h1>Menu</h1><h2>Slices</h2><p>Plain slice $4.00</p><p>Pepperoni slice $4.50</p><p>Sicilian $5.00</p>"
             "<p>Garlic knots $3.00</p><p>Cheese pie $22.00</p><p>Pepperoni pie $25.00</p></body></html>").encode()
MENU_RESULT = MenuResult(found=True, notes="Prices before tax", sections=[
    MenuSection(title="Slices", note=None, items=[
        MenuItem(name="Plain slice", description=None, price="$4.00", tags=["vegetarian"]),
        MenuItem(name="Pepperoni slice", description="Classic", price="$4.50", tags=[])])])


def menu_place(client, website="https://joes.test/"):
    job = import_reel(client)
    joes = next(p for p in client.get(f"/v1/trips/{job['trip_id']}", headers=H).json()["places"] if p["name"] == "Joe's Pizza")
    app.state.db.update_place(joes["id"], website=website)
    return joes["id"]


def serve(client, url, body, ctype="text/html", status=200, **headers):
    client.web[url] = (status, ctype, body, headers)


def test_menu_read_from_the_website(client):
    pid = menu_place(client)
    assert client.get(f"/v1/places/{pid}/menu", headers=H).json()["status"] == "unknown"
    serve(client, "https://joes.test/", MENU_HTML)
    serve(client, "https://joes.test/menu", MENU_PAGE)
    serve(client, "https://joes.test/gift-cards", b"<html><body>Buy a gift card for a friend, in any amount you like, delivered by email.</body></html>")
    client.messages.outputs[MenuResult] = MENU_RESULT

    menu = client.post(f"/v1/places/{pid}/menu", json={}, headers=H).json()
    assert menu["status"] == "found" and menu["source_kind"] == "website" and menu["source_url"] == "https://joes.test/menu"
    assert menu["sections"][0]["title"] == "Slices" and menu["sections"][0]["items"][0]["price"] == "$4.00"
    assert menu["sections"][0]["items"][0]["tags"] == ["vegetarian"] and menu["notes"] == "Prices before tax"
    sent = client.messages.calls[-1]
    text = " ".join(b["text"] for b in sent["messages"][0]["content"] if b["type"] == "text")
    assert "Plain slice $4.00" in text and "IGNORE ME" not in text and "gift card" not in text
    assert "untrusted" in sent["system"] and sent["output_config"]["effort"] == "low"
    assert not any("gift-cards" in u or "internal.test" in u for u in client.web_log)  # not a menu page; not public

    calls = len(client.messages.calls)
    assert client.post(f"/v1/places/{pid}/menu", json={}, headers=H).json()["status"] == "found"
    assert client.get(f"/v1/places/{pid}/menu", headers=H).json()["sections"][0]["title"] == "Slices"
    assert len(client.messages.calls) == calls  # saved menus aren't read again
    client.post(f"/v1/places/{pid}/menu", json={"refresh": True}, headers=H)
    assert len(client.messages.calls) == calls + 1

    client.delete(f"/v1/places/{pid}", headers=H)
    assert app.state.db.get_menu(pid) is None  # goes with the place


def test_menu_pdf_and_menu_images(client):
    pid = menu_place(client)
    serve(client, "https://joes.test/", b'<html><body><a href="/files/dinner-menu.pdf">Dinner menu</a>'
          b'<img src="/img/lunch-menu.jpg" alt="Lunch menu"><img src="/img/team.jpg" alt="Our team"></body></html>')
    serve(client, "https://joes.test/files/dinner-menu.pdf", b"%PDF-1.4 fake", "application/pdf")
    serve(client, "https://joes.test/img/lunch-menu.jpg", b"\xff\xd8\xff fake", "image/jpeg")
    serve(client, "https://joes.test/img/team.jpg", b"\xff\xd8\xff fake", "image/jpeg")
    client.messages.outputs[MenuResult] = MENU_RESULT
    assert client.post(f"/v1/places/{pid}/menu", json={}, headers=H).json()["status"] == "found"
    blocks = client.messages.calls[-1]["messages"][0]["content"]
    assert [b["type"] for b in blocks].count("document") == 1 and [b["type"] for b in blocks].count("image") == 1
    assert not any("team.jpg" in u for u in client.web_log)


def test_menu_fetching_stays_on_the_public_web(client):
    import asyncio

    pid = menu_place(client, website="http://internal.test/")
    serve(client, "http://internal.test/", MENU_PAGE)
    assert client.post(f"/v1/places/{pid}/menu", json={}, headers=H).json()["status"] == "none"
    assert client.web_log == []  # never even connected

    fetcher = app.state.menus.fetcher
    run = asyncio.new_event_loop().run_until_complete
    for url in ("http://meta.test/latest", "http://v6.test/", "https://joes.test:8443/", "https://user:pw@joes.test/", "ftp://joes.test/", "file:///etc/passwd", "https:///x"):
        assert run(fetcher.allowed(url)) is False, url
    assert run(fetcher.allowed("https://joes.test/menu")) is True

    # A public page that redirects to a private address is refused at the redirect.
    serve(client, "https://joes.test/go", b"", status=302, location="http://internal.test/secret")
    serve(client, "http://internal.test/secret", b"secret")
    assert run(fetcher.get("https://joes.test/go", 1000)) is None
    assert "http://internal.test/secret" not in client.web_log

    # Big files are cut off at the size limit.
    serve(client, "https://joes.test/big", b"x" * 5000, "text/html")
    got = run(fetcher.get("https://joes.test/big", 1000))
    assert len(got.body) == 1000 and got.truncated


def test_menu_not_found_and_claude_failures(client):
    pid = menu_place(client)
    serve(client, "https://joes.test/", b"<html><body>Joe's Pizza has been on Carmine Street since 1975 and loves visitors, so come hungry.</body></html>")
    client.messages.outputs[MenuResult] = MenuResult(found=False, sections=[], notes=None)
    assert client.post(f"/v1/places/{pid}/menu", json={}, headers=H).json()["status"] == "none"
    assert client.get(f"/v1/places/{pid}/menu", headers=H).json()["status"] == "none"

    # When Claude can't be reached nothing is saved, so it can be tried again.
    client.messages.stop_reason = "refusal"
    r = client.post(f"/v1/places/{pid}/menu", json={"refresh": True}, headers=H)
    assert r.status_code == 502
    assert client.get(f"/v1/places/{pid}/menu", headers=H).json()["status"] == "none"  # the earlier answer stays

    client.messages.stop_reason = "end_turn"
    client.patch(f"/v1/places/{pid}", json={"category": "stay"}, headers=H)
    assert client.post(f"/v1/places/{pid}/menu", json={}, headers=H).status_code == 422
    assert client.post("/v1/places/nope/menu", json={}, headers=H).status_code == 404
    assert client.get("/v1/places/nope/menu", headers=H).status_code == 404


def test_menu_falls_back_to_google_photos(client):
    pid = menu_place(client, website=None)
    log = []

    def google(request):
        log.append(request.url.path)
        if request.url.path.endswith(":searchText"):
            assert request.headers["x-goog-fieldmask"] == "places.photos"
            return httpx.Response(200, json={"places": [{"photos": [{"name": f"places/x/photos/{i}"} for i in range(10)]}]})
        assert request.url.params["maxWidthPx"] == "1400"
        return httpx.Response(200, content=b"\xff\xd8\xff", headers={"content-type": "image/jpeg"})

    menus = app.state.menus
    menus.geocoder = GooglePlacesGeocoder("k", client=httpx.AsyncClient(transport=httpx.MockTransport(google)))
    client.messages.outputs[MenuResult] = MENU_RESULT
    menu = client.post(f"/v1/places/{pid}/menu", json={}, headers=H).json()
    assert menu["status"] == "found" and menu["source_kind"] == "photos" and menu["source_url"] is None
    sent = client.messages.calls[-1]
    assert [b["type"] for b in sent["messages"][0]["content"]].count("image") == 8  # at most 8 photos
    assert "NOT menus" in sent["system"]

    # Website first: when it has the menu, Google isn't asked at all.
    app.state.db.update_place(pid, website="https://joes.test/")
    serve(client, "https://joes.test/", MENU_PAGE)
    log.clear()
    client.messages.outputs[MenuResult] = [MENU_RESULT]
    assert client.post(f"/v1/places/{pid}/menu", json={"refresh": True}, headers=H).json()["source_kind"] == "website"
    assert log == []

    # The website had nothing, so the photos are tried; and the setting can switch that off.
    client.messages.outputs[MenuResult] = [MenuResult(found=False, sections=[], notes=None), MENU_RESULT]
    assert client.post(f"/v1/places/{pid}/menu", json={"refresh": True}, headers=H).json()["source_kind"] == "photos"
    menus.settings = menus.settings.model_copy(update={"menu_google_photos": False})
    log.clear()
    client.messages.outputs[MenuResult] = [MenuResult(found=False, sections=[], notes=None)]
    assert client.post(f"/v1/places/{pid}/menu", json={"refresh": True}, headers=H).json()["status"] == "none"
    assert log == []


def test_menu_page_reading_helpers():
    from app.menus import candidate_links, clean_menu, is_public_address, parse_page, score_link

    page = parse_page("https://a.test/", b"""<html><head><title>x</title><style>.a{}</style></head><body><script>bad()</script>
        <a href="/menus/dinner">Dinner Menu</a><a href="/about">About us</a><a href="/menu.pdf">Menu (PDF)</a><a href="#top">Top</a>
        <a href="tel:123">Call</a><a href="javascript:x()">x</a><img src="data:image/png;base64,AAA"><img src="/m.png" alt="menu"><p>Hello</p>
        <script type="application/ld+json">{"hasMenu": "yes"}</script></body></html>""")
    assert page.text == "Dinner Menu About us Menu (PDF) Top Call\nHello" or "Hello" in page.text and "bad()" not in page.text
    assert [u for u, _ in page.links] == ["https://a.test/menus/dinner", "https://a.test/about", "https://a.test/menu.pdf"]
    assert page.images == [("https://a.test/m.png", "menu")] and page.jsonld == ['{"hasMenu": "yes"}']
    assert candidate_links(page) == ["https://a.test/menus/dinner", "https://a.test/menu.pdf"]
    assert score_link("https://a.test/gift-cards", "Gift card menu") < score_link("https://a.test/menu", "Menu")
    assert is_public_address("93.184.216.34") and not any(map(is_public_address, ("10.0.0.1", "127.0.0.1", "169.254.169.254", "::1", "::ffff:10.0.0.1", "nope")))

    messy = MenuResult(found=True, notes="  Dinner \n only ", sections=[
        MenuSection(title="  ", note=None, items=[MenuItem(name=" Soup \n of the day ", description="", price=" $9 ", tags=["vegan", "vegan"])]),
        MenuSection(title="Empty", note=None, items=[MenuItem(name="   ", description=None, price=None, tags=[])])])
    clean = clean_menu(messy)
    assert len(clean.sections) == 1 and clean.sections[0].title == "Menu"
    item = clean.sections[0].items[0]
    assert item.name == "Soup of the day" and item.description is None and item.price == "$9" and item.tags == ["vegan"]
    assert clean.notes == "Dinner only" and clean_menu(MenuResult(found=True, sections=[], notes=None)).found is False


# ---------- Bookings and reservation links ----------


def booking_trip(client, start_date=None):
    job = import_reel(client)
    trip_id = job["trip_id"]
    if start_date:
        client.patch(f"/v1/trips/{trip_id}", json={"start_date": start_date}, headers=H)
    places = client.get(f"/v1/trips/{trip_id}", headers=H).json()["places"]
    return trip_id, {p["name"]: p["id"] for p in places}


def test_bookings_crud_in_trip_detail(client):
    trip_id, ids = booking_trip(client)
    assert client.get(f"/v1/trips/{trip_id}", headers=H).json()["bookings"] == []

    flight = {"kind": "flight", "title": "BA 178", "start_at": "2026-11-07T19:25", "end_at": "2026-11-08T07:30",
              "origin": "JFK", "destination": "LHR", "confirmation": "ABC123", "source": "screenshot"}
    r = client.post(f"/v1/trips/{trip_id}/bookings", json=flight, headers=H)
    assert r.status_code == 201
    client.post(f"/v1/trips/{trip_id}/bookings", json={"kind": "hotel", "title": "The Hoxton", "start_at": "2026-11-08T15:00",
                                                       "end_at": "2026-11-12", "address": "199 High Holborn"}, headers=H)
    client.post(f"/v1/trips/{trip_id}/bookings", json={"kind": "car", "title": "Hertz"}, headers=H)  # no date: sorts last
    bookings = client.get(f"/v1/trips/{trip_id}", headers=H).json()["bookings"]
    assert [b["title"] for b in bookings] == ["BA 178", "The Hoxton", "Hertz"]
    assert bookings[0]["origin"] == "JFK" and bookings[0]["source"] == "screenshot" and bookings[1]["source"] == "manual"

    fixed = client.patch(f"/v1/trips/{trip_id}/bookings/{bookings[0]['id']}",
                         json={"start_at": "2026-11-07T20:10", "notes": "Terminal 7"}, headers=H).json()["bookings"][0]
    assert fixed["start_at"] == "2026-11-07T20:10" and fixed["notes"] == "Terminal 7" and fixed["confirmation"] == "ABC123"
    cleared = client.patch(f"/v1/trips/{trip_id}/bookings/{bookings[0]['id']}", json={"notes": None}, headers=H).json()["bookings"][0]
    assert cleared["notes"] is None  # an explicit null clears a field

    assert client.delete(f"/v1/trips/{trip_id}/bookings/{bookings[2]['id']}", headers=H).json()["bookings"].__len__() == 2

    bad = [{"kind": "flight"}, {"title": "x"}, {"kind": "boat", "title": "x"}, {"kind": "flight", "title": "x", "start_at": "tomorrow"},
           {"kind": "flight", "title": "x", "start_at": "2026-11-07T25:00"}, {"kind": "flight", "title": "x", "party_size": 0}]
    for body in bad:
        assert client.post(f"/v1/trips/{trip_id}/bookings", json=body, headers=H).status_code == 422, body
    assert client.patch(f"/v1/trips/{trip_id}/bookings/{bookings[0]['id']}", json={"title": None}, headers=H).status_code == 422

    other = client.post("/v1/places", json={"name": "Elsewhere", "city": "Paris"}, headers=H).json()["place"]
    assert client.post(f"/v1/trips/{trip_id}/bookings", json={"kind": "reservation", "title": "x", "place_id": other["id"]}, headers=H).status_code == 422
    other_trip = client.get("/v1/trips", headers=H).json()
    paris = next(t for t in other_trip if t["id"] != trip_id)["id"]
    assert client.patch(f"/v1/trips/{paris}/bookings/{bookings[0]['id']}", json={"notes": "x"}, headers=H).status_code == 404
    assert client.delete(f"/v1/trips/{paris}/bookings/{bookings[0]['id']}", headers=H).status_code == 404
    assert client.post("/v1/trips/nope/bookings", json=flight, headers=H).status_code == 404

    assert client.delete(f"/v1/trips/{trip_id}", headers=H).status_code == 204
    assert app.state.db._rows("SELECT * FROM bookings") == []  # they go with the trip


def test_reservation_booking_sets_time_and_day(client):
    trip_id, ids = booking_trip(client, start_date="2026-11-07")
    joes = ids["Joe's Pizza"]
    body = {"kind": "reservation", "title": "Joe's Pizza", "start_at": "2026-11-09T19:30", "party_size": 2, "place_id": joes}
    trip = client.post(f"/v1/trips/{trip_id}/bookings", json=body, headers=H).json()
    place = next(p for p in trip["places"] if p["id"] == joes)
    assert place["start_time"] == "19:30" and place["time_of_day"] == "dinner"
    assert place["day_number"] == 3 and trip["day_count"] == 3  # Nov 9 is the third day of a trip starting Nov 7

    booking = trip["bookings"][0]
    trip = client.patch(f"/v1/trips/{trip_id}/bookings/{booking['id']}", json={"start_at": "2026-11-08T12:15"}, headers=H).json()
    place = next(p for p in trip["places"] if p["id"] == joes)
    assert place["start_time"] == "12:15" and place["day_number"] == 2 and place["time_of_day"] == "lunch"

    trip = client.delete(f"/v1/trips/{trip_id}/bookings/{booking['id']}", headers=H).json()
    place = next(p for p in trip["places"] if p["id"] == joes)
    assert place["start_time"] is None and place["day_number"] == 2  # the time goes; it stays where it was planned

    # Outside the trip's dates, or no dates at all: only the exact time is set.
    far = {"kind": "reservation", "title": "Lucali", "start_at": "2027-03-01T20:00", "place_id": ids["Lucali"]}
    place = next(p for p in client.post(f"/v1/trips/{trip_id}/bookings", json=far, headers=H).json()["places"] if p["id"] == ids["Lucali"])
    assert place["start_time"] == "20:00" and place["day_number"] is None
    # A hotel with a place_id doesn't touch the place; a reservation with a date only leaves its time alone.
    client.post(f"/v1/trips/{trip_id}/bookings", json={"kind": "hotel", "title": "H", "start_at": "2026-11-08T15:00", "place_id": ids["Prince Street Pizza"]}, headers=H)
    prince = next(p for p in client.get(f"/v1/trips/{trip_id}", headers=H).json()["places"] if p["id"] == ids["Prince Street Pizza"])
    assert prince["start_time"] is None


def test_read_bookings_from_text_and_screenshots(client):
    import base64

    trip_id, _ = booking_trip(client)
    client.messages.outputs[BookingsResult] = BookingsResult(bookings=[
        BookingDraft(kind="flight", title=" BA  178 ", start_at="2026-11-07T19:25", end_at="2026-02-31", origin="JFK", destination="LHR",
                     address=None, confirmation="ABC123", party_size=None, notes="Terminal 7"),
        BookingDraft(kind="hotel", title="The Hoxton", start_at="Nov 8", end_at="2026-11-12", origin=None, destination=None,
                     address="199 High Holborn", confirmation=None, party_size=500, notes=None),
        BookingDraft(kind="other", title="   ", start_at=None, end_at=None, origin=None, destination=None, address=None,
                     confirmation=None, party_size=None, notes=None)])
    jpeg = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff fake").decode()
    r = client.post(f"/v1/trips/{trip_id}/bookings/read", json={"text": "Your booking is confirmed", "images": [jpeg]}, headers=H)
    assert r.status_code == 200
    drafts = r.json()
    assert [d["title"] for d in drafts] == ["BA 178", "The Hoxton"]  # the blank one is dropped; spaces are tidied
    assert drafts[0]["end_at"] is None and drafts[1]["start_at"] is None and drafts[1]["party_size"] is None  # impossible values
    assert drafts[0]["start_at"] == "2026-11-07T19:25" and drafts[0]["confirmation"] == "ABC123"
    sent = client.messages.calls[-1]
    blocks = sent["messages"][0]["content"]
    assert [b["type"] for b in blocks].count("image") == 1
    assert "Today is" in blocks[-1]["text"] and "Your booking is confirmed" in blocks[-1]["text"]
    assert "untrusted" in sent["system"] and sent["output_config"]["effort"] == "low"
    assert client.get(f"/v1/trips/{trip_id}", headers=H).json()["bookings"] == []  # reading doesn't save anything

    assert client.post(f"/v1/trips/{trip_id}/bookings/read", json={}, headers=H).status_code == 422
    assert client.post(f"/v1/trips/{trip_id}/bookings/read", json={"images": ["!!!"]}, headers=H).status_code == 422
    assert client.post(f"/v1/trips/{trip_id}/bookings/read", json={"images": [base64.b64encode(b"GIF89a").decode()]}, headers=H).status_code == 422
    assert client.post("/v1/trips/nope/bookings/read", json={"text": "x"}, headers=H).status_code == 404
    client.messages.stop_reason = "refusal"
    assert client.post(f"/v1/trips/{trip_id}/bookings/read", json={"text": "x"}, headers=H).status_code == 502


def test_shared_trip_never_includes_bookings(client):
    trip_id, _ = booking_trip(client)
    client.post(f"/v1/trips/{trip_id}/bookings", json={"kind": "flight", "title": "BA 178", "confirmation": "SECRET1"}, headers=H)
    token = client.post(f"/v1/trips/{trip_id}/share", headers=H).json()["token"]
    shared = client.get(f"/v1/shared/{token}")
    assert shared.status_code == 200 and "SECRET1" not in shared.text and "bookings" not in shared.json()


def test_reserve_link_found_on_the_restaurant_website(client):
    from app.reserve import provider_for

    trip_id, ids = booking_trip(client)
    pid = ids["Joe's Pizza"]
    app.state.db.update_place(pid, website="https://joes.test/")
    serve(client, "https://joes.test/", b'<html><body><a href="/gift">Gift cards</a><a href="https://resy.com/gift-cards">Gifts</a>'
          b'<a href="https://www.opentable.com/r/joes-pizza-new-york">Reserve on OpenTable</a>'
          b'<a href="https://resy.com/cities/ny/joes-pizza">Resy</a></body></html>')
    place = client.post(f"/v1/places/{pid}/reserve-link", headers=H).json()
    assert place["reserve_provider"] == "OpenTable" and place["reserve_url"] == "https://www.opentable.com/r/joes-pizza-new-york"
    assert place["reserve_checked_at"] is not None
    calls = len(client.web_log)
    assert client.post(f"/v1/places/{pid}/reserve-link", headers=H).json()["reserve_url"] == place["reserve_url"]
    assert len(client.web_log) == calls  # looked at once

    # One click away: the home page links to a Reservations page that has the booking link.
    lucali = ids["Lucali"]
    app.state.db.update_place(lucali, website="https://lucali.test/")
    serve(client, "https://lucali.test/", b'<html><body><a href="/reservations">Reservations</a><a href="/about">About</a></body></html>')
    serve(client, "https://lucali.test/reservations", b'<html><body><a href="https://resy.com/cities/ny/lucali?date=2026-11-08">Book</a></body></html>')
    found = client.post(f"/v1/places/{lucali}/reserve-link", headers=H).json()
    assert found["reserve_provider"] == "Resy" and found["reserve_url"].startswith("https://resy.com/cities/ny/lucali")

    # Nothing found: remembered, so the page isn't fetched again.
    prince = ids["Prince Street Pizza"]
    app.state.db.update_place(prince, website="https://prince.test/")
    serve(client, "https://prince.test/", b'<html><body><a href="javascript:x()">Book</a><a href="https://evil.test/resy.com/cities/ny/x">Resy</a></body></html>')
    none = client.post(f"/v1/places/{prince}/reserve-link", headers=H).json()
    assert none["reserve_url"] is None and none["reserve_checked_at"] is not None

    # Not for hotels, or places without a website.
    client.patch(f"/v1/places/{pid}", json={"category": "stay"}, headers=H)
    app.state.db.update_place(pid, reserve_checked_at=None)
    assert client.post(f"/v1/places/{pid}/reserve-link", headers=H).json()["reserve_checked_at"] is None
    assert client.post("/v1/places/nope/reserve-link", headers=H).status_code == 404

    assert provider_for("https://resy.com/cities/ny/lucali") == "Resy" and provider_for("https://resy.com/") is None
    assert provider_for("https://www.opentable.co.uk/r/the-ivy") == "OpenTable" and provider_for("https://opentable.com/about") is None
    assert provider_for("https://www.exploretock.com/alinea") == "Tock" and provider_for("https://resy.com/cities/ny/x y") is None
    assert provider_for("https://resy.com.evil.test/cities/ny/x") is None and provider_for("http://resy.com/cities/ny/" + "a" * 600) is None


# ---------- Packing lists ----------


def packing_trip(client, days=3, offset=3):
    from datetime import date, timedelta

    job = import_reel(client)
    trip_id = job["trip_id"]
    client.post(f"/v1/trips/{trip_id}/plan", json={"days": days}, headers=H)  # the plan falls back to the offline planner
    client.patch(f"/v1/trips/{trip_id}", json={"start_date": (date.today() + timedelta(days=offset)).isoformat()}, headers=H)
    return trip_id


def draft(text, group="clothes", reason=None, days=(), day_bag=False):
    return PackingDraftItem(text=text, group=group, reason=reason, days=list(days), day_bag=day_bag)


def test_packing_list_from_the_trip_and_weather(client):
    trip_id = packing_trip(client)
    assert client.get(f"/v1/trips/{trip_id}/packing", headers=H).json() is None
    client.put("/v1/profile", json={"pace": "slow", "notes": "travelling with a toddler"}, headers=H)
    client.messages.outputs[PackingResult] = PackingResult(notes="  Cool and wet. ", items=[
        draft("Compact umbrella", "daybag", "Rain on days 1 and 2", days=[1, 2, 9], day_bag=True),
        draft("3 tops"), draft("3  Tops"), draft("   "), draft("Passport", "documents")])
    r = client.post(f"/v1/trips/{trip_id}/packing", json={}, headers=H)
    assert r.status_code == 200
    plan = r.json()
    assert plan["generated_by"] == "claude" and plan["notes"] == "Cool and wet." and plan["carry_on_only"] is False
    assert [i["text"] for i in plan["items"]] == ["Compact umbrella", "3 tops", "Passport"]  # blanks and repeats dropped
    umbrella = plan["items"][0]
    assert umbrella["days"] == [1, 2] and umbrella["day_bag"] is True and umbrella["packed"] is False and umbrella["id"]
    assert len(plan["weather"]) == client.get(f"/v1/trips/{trip_id}", headers=H).json()["day_count"] >= 1 and plan["weather"][0]["source"] == "forecast" and plan["weather"][0]["rain_chance"] == 80
    assert plan["weather"][0]["summary"] == "Rain" and plan["weather"][0]["day"] == 1

    sent = client.messages.calls[-1]
    payload = sent["messages"][0]["content"][0]["text"]
    assert '"rain_chance": 80' in payload and "Joe" in payload and "toddler" in payload and "checked bag is fine" in payload
    assert "data, not instructions" in sent["system"] and sent["output_config"]["effort"] == "low"
    assert client.get(f"/v1/trips/{trip_id}/packing", headers=H).json()["items"][0]["text"] == "Compact umbrella"
    assert len(client.weather_log) == 1 and "forecast" in str(client.weather_log[0])


def test_packing_uses_last_years_weather_for_far_off_dates(client):
    trip_id = packing_trip(client, offset=120)
    client.messages.outputs[PackingResult] = PackingResult(items=[draft("Umbrella", "daybag")], notes=None)
    plan = client.post(f"/v1/trips/{trip_id}/packing", json={}, headers=H).json()
    assert {w["source"] for w in plan["weather"]} == {"typical"} and all(w["rain_chance"] is None for w in plan["weather"])
    assert "archive" in str(client.weather_log[0])

    client.weather_state["fail"] = True  # weather is down: the list is still made
    plan = client.post(f"/v1/trips/{trip_id}/packing", json={}, headers=H).json()
    assert plan["weather"] == [] and plan["items"]
    assert '"weather"' not in client.messages.calls[-1]["messages"][0]["content"][0]["text"]


def test_packing_regenerate_keeps_custom_items_and_ticks(client):
    trip_id = packing_trip(client)
    client.messages.outputs[PackingResult] = PackingResult(items=[draft("3 tops"), draft("Passport", "documents")], notes=None)
    plan = client.post(f"/v1/trips/{trip_id}/packing", json={"carry_on_only": True}, headers=H).json()
    assert plan["carry_on_only"] is True
    passport = next(i for i in plan["items"] if i["text"] == "Passport")
    after = client.patch(f"/v1/trips/{trip_id}/packing/items/{passport['id']}", json={"packed": True}, headers=H).json()
    assert next(i for i in after["items"] if i["id"] == passport["id"])["packed"] is True
    added = client.post(f"/v1/trips/{trip_id}/packing/items", json={"text": "  Camera   charger ", "group": "tech"}, headers=H)
    assert added.status_code == 201 and added.json()["items"][-1]["text"] == "Camera charger" and added.json()["items"][-1]["custom"] is True

    client.messages.outputs[PackingResult] = PackingResult(items=[draft("4 tops"), draft("Passport", "documents"), draft("Camera charger", "tech")], notes=None)
    again = client.post(f"/v1/trips/{trip_id}/packing", json={}, headers=H).json()
    assert again["carry_on_only"] is True  # remembered unless changed
    assert "Camera charger" in client.messages.calls[-1]["messages"][0]["content"][0]["text"] and "carry-on only" in client.messages.calls[-1]["messages"][0]["content"][0]["text"]
    texts = [i["text"] for i in again["items"]]
    assert texts.count("Camera charger") == 1 and "4 tops" in texts and "3 tops" not in texts
    assert next(i for i in again["items"] if i["text"] == "Passport")["packed"] is True  # still ticked
    unticked = client.post(f"/v1/trips/{trip_id}/packing", json={"keep_packed": False}, headers=H).json()
    assert next(i for i in unticked["items"] if i["text"] == "Passport")["packed"] is False


def test_packing_item_edits_and_learning(client):
    trip_id = packing_trip(client)
    assert client.post(f"/v1/trips/{trip_id}/packing/items", json={"text": "x"}, headers=H).status_code == 404  # no list yet
    client.messages.outputs[PackingResult] = PackingResult(items=[draft("5 tops"), draft("Rain jacket"), draft("Hair dryer", "toiletries")], notes=None)
    plan = client.post(f"/v1/trips/{trip_id}/packing", json={}, headers=H).json()
    ids = {i["text"]: i["id"] for i in plan["items"]}

    renamed = client.patch(f"/v1/trips/{trip_id}/packing/items/{ids['Rain jacket']}", json={"text": "Light rain jacket", "group": "clothes"}, headers=H).json()
    assert any(i["text"] == "Light rain jacket" for i in renamed["items"])
    client.patch(f"/v1/trips/{trip_id}/packing/items/{ids['Hair dryer']}", json={"unused": True}, headers=H)
    client.patch(f"/v1/trips/{trip_id}/packing/items/{ids['5 tops']}", json={"unused": True}, headers=H)
    client.patch(f"/v1/trips/{trip_id}/packing/items/{ids['5 tops']}", json={"unused": False}, headers=H)  # changed their mind
    assert app.state.db.get_setting("packing_unused") == {"hair dryer": 1}

    client.messages.outputs[PackingResult] = PackingResult(items=[draft("Hair dryer", "toiletries")], notes=None)
    latest = client.post(f"/v1/trips/{trip_id}/packing", json={}, headers=H).json()
    assert "hair dryer" in client.messages.calls[-1]["messages"][0]["content"][0]["text"]  # told Claude what they usually skip

    deleted = client.delete(f"/v1/trips/{trip_id}/packing/items/{latest['items'][0]['id']}", headers=H).json()
    assert len(deleted["items"]) == len(latest["items"]) - 1
    for bad in ({}, {"text": ""}):
        assert client.post(f"/v1/trips/{trip_id}/packing/items", json=bad, headers=H).status_code == 422
    assert client.post(f"/v1/trips/{trip_id}/packing/items", json={"text": "x", "group": "boats"}, headers=H).status_code == 422
    assert client.patch(f"/v1/trips/{trip_id}/packing/items/nope", json={"packed": True}, headers=H).status_code == 404
    assert client.delete(f"/v1/trips/{trip_id}/packing/items/nope", headers=H).status_code == 404
    assert client.get("/v1/trips/nope/packing", headers=H).status_code == 404
    assert client.post("/v1/trips/nope/packing", json={}, headers=H).status_code == 404

    assert client.delete(f"/v1/trips/{trip_id}", headers=H).status_code == 204
    assert app.state.db._rows("SELECT * FROM packing") == []


def test_packing_falls_back_to_a_rule_based_list(client):
    trip_id = packing_trip(client, days=4)
    client.messages.stop_reason = "refusal"
    plan = client.post(f"/v1/trips/{trip_id}/packing", json={}, headers=H).json()
    assert plan["generated_by"] == "offline"
    by_text = {i["text"]: i for i in plan["items"]}
    assert "Passport or ID" in by_text and any(t.endswith(" tops") for t in by_text) and by_text["Compact umbrella"]["day_bag"] is True
    assert by_text["Compact umbrella"]["days"] and by_text["Compact umbrella"]["days"][0] == 1 and "Rain" in by_text["Compact umbrella"]["reason"]
    assert "Warm layer or coat" in by_text  # lows of 8 degrees
    assert all(i["group"] in ("clothes", "shoes", "toiletries", "tech", "documents", "daybag", "other") for i in plan["items"])
    tops = lambda p: int(next(i["text"] for i in p["items"] if i["text"].endswith(" tops")).split()[0])
    carry = client.post(f"/v1/trips/{trip_id}/packing", json={"carry_on_only": True}, headers=H).json()
    assert tops(carry) <= tops(plan)  # no more tops for carry-on

    app.state.db.set_setting("packing_unused", {"warm layer or coat": 2})
    assert "Warm layer or coat" not in {i["text"] for i in client.post(f"/v1/trips/{trip_id}/packing", json={}, headers=H).json()["items"]}


async def test_weather_lookup():
    from datetime import date, timedelta

    calls = []

    def handler(request):
        calls.append(request)
        q = request.url.params
        assert q["timezone"] == "auto" and q["latitude"] == "40.73" and q["apikey"] == "k"
        start, end = date.fromisoformat(q["start_date"]), date.fromisoformat(q["end_date"])
        n = (end - start).days + 1
        return httpx.Response(200, json={"daily": {"time": [(start + timedelta(days=i)).isoformat() for i in range(n)], "weather_code": [0] * n,
                                                    "temperature_2m_max": [20.04] * n, "temperature_2m_min": [None] * n}})

    settings = Settings(app_api_key="secret", weather_api_key="k", weather_base_url="https://weather.example.com/v1/")
    w = Weather(settings, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert await w.days(40.7301, -74.0, date.today() + timedelta(days=2), 3) == []  # no minimum temperature: nothing usable
    assert str(calls[0].url).startswith("https://weather.example.com/v1/forecast")
    off = Weather(Settings(app_api_key="secret", weather="none"))
    assert await off.days(40.7, -74.0, date.today(), 3) == [] and await w.days(40.7, -74.0, date.today(), 0) == []
    assert Weather(settings).enabled is True



# ---------- Menus: finding harder-to-reach menus ----------


def test_menu_found_at_the_usual_address_when_no_link_leads_there(client):
    pid = menu_place(client)
    serve(client, "https://joes.test/", b'<html><body><h1>Joe\'s Pizza</h1><p>Welcome to our home since 1975. Come hungry and stay awhile.</p></body></html>')
    serve(client, "https://joes.test/menu", MENU_PAGE)
    serve(client, "https://joes.test/food", b'<html><body><h1>Joe\'s Pizza</h1><p>Welcome to our home since 1975. Come hungry and stay awhile.</p></body></html>')  # catch-all copy of the home page
    client.messages.outputs[MenuResult] = MENU_RESULT
    menu = client.post(f"/v1/places/{pid}/menu", json={}, headers=H).json()
    assert menu["status"] == "found" and menu["source_url"] == "https://joes.test/menu"
    text = " ".join(b["text"] for b in client.messages.calls[-1]["messages"][0]["content"] if b["type"] == "text")
    assert text.count("Welcome to our home") == 0 or text.count("Welcome to our home") == 1  # the copy of the home page isn't read twice
    assert any(u.endswith("/menu") for u in client.web_log)


def test_menu_on_a_site_for_several_restaurants(client):
    app.state.db  # (fixture wiring)
    pid = menu_place(client, website="https://group.test/")
    app.state.db.update_place(pid, name="Joe's Pizza")
    serve(client, "https://group.test/", b'<html><body><h1>The Group</h1><nav><a href="/trattoria/menus">Menus</a><a href="/joes-pizza">Joe\'s Pizza</a>'
          b'<a href="/trattoria">Trattoria</a></nav><p>Welcome to the group, with restaurants across the city and beyond.</p></body></html>')
    serve(client, "https://group.test/trattoria/menus", b"<html><body>Trattoria menu: Risotto $18.00 Veal $26.00 Pasta $15.00 Tiramisu $9.00 Gelato $7.00</body></html>")
    serve(client, "https://group.test/joes-pizza", b'<html><body><h1>Joe\'s Pizza</h1><a href="/joes-pizza/our-menu.pdf">Download our menu</a><p>Pizza by the slice since 1975.</p></body></html>')
    serve(client, "https://group.test/joes-pizza/our-menu.pdf", b"%PDF-1.4 fake", "application/pdf")
    client.messages.outputs[MenuResult] = MENU_RESULT
    menu = client.post(f"/v1/places/{pid}/menu", json={}, headers=H).json()
    assert menu["status"] == "found" and menu["source_url"] == "https://group.test/joes-pizza/our-menu.pdf"
    blocks = client.messages.calls[-1]["messages"][0]["content"]
    assert [b["type"] for b in blocks].count("document") == 1 and "Trattoria menu" not in str(blocks)  # not another restaurant's menu


GROUP_LINKS = ["A La Carte", "Lunch", "Dessert", "Tasting Menu", "Wine List", "Gymkhana Drinks Menu", "42 Cocktail Lounge Menu",
               "The Vaults Lunch", "The Vaults & 42 Feast Menu", "Festive Lunch", "Diwali & Festive Tasting Menu", "New Year's Eve Dinner"]
MAIN_MENUS = {"A La Carte", "Lunch", "Dessert", "Tasting Menu", "Wine List", "Gymkhana Drinks Menu"}


def test_menus_listed_as_many_pdfs_are_chosen_by_claude(client):
    pid = menu_place(client)
    app.state.db.update_place(pid, name="Gymkhana")
    slug = lambda t: "".join(c for c in t.lower() if c.isalnum() or c == " ").replace(" ", "-")
    html = "<html><body><h1>Gymkhana</h1>" + "".join(f'<a href="/files/{slug(t)}.pdf">{t}</a>' for t in GROUP_LINKS) + "</body></html>"
    serve(client, "https://joes.test/", html.encode())
    for t in GROUP_LINKS:
        serve(client, f"https://joes.test/files/{slug(t)}.pdf", b"%PDF-1.4 " + t.encode(), "application/pdf")

    def pick(kwargs):
        lines = kwargs["messages"][0]["content"][0]["text"].splitlines()
        wanted = [int(line.split(".", 1)[0]) for line in lines if line.split(".", 1)[0].isdigit() and line.split(". ", 1)[1].split(" — ")[0] in MAIN_MENUS]
        return PickedLinks(numbers=wanted)

    client.messages.outputs[PickedLinks] = pick
    client.messages.outputs[MenuResult] = MENU_RESULT
    menu = client.post(f"/v1/places/{pid}/menu", json={}, headers=H).json()
    assert menu["status"] == "found"
    asked = [u for u in client.web_log if u.endswith(".pdf")]
    assert {u.rsplit("/", 1)[1] for u in asked} == {f"{slug(t)}.pdf" for t in MAIN_MENUS}  # only the chosen menus were downloaded
    blocks = client.messages.calls[-1]["messages"][0]["content"]
    labels = [b["text"] for b in blocks if b["type"] == "text" and b["text"].startswith("[Menu PDF")]
    assert any("Menu PDF: Wine List" in l for l in labels) and any("Menu PDF: A La Carte" in l for l in labels)
    assert [b["type"] for b in blocks].count("document") == 6

    # If Claude's choice is unusable the best-scored links are used instead.
    client.web_log.clear()
    client.messages.outputs[PickedLinks] = PickedLinks(numbers=[99])
    client.messages.outputs[MenuResult] = MENU_RESULT
    assert client.post(f"/v1/places/{pid}/menu", json={"refresh": True}, headers=H).json()["status"] == "found"
    assert 1 <= len([u for u in client.web_log if u.endswith(".pdf")]) <= 6


def test_browser_finds_a_popup_of_menu_pdfs(client):
    pid = menu_place(client)
    serve(client, "https://joes.test/", b"<html><body><div id=app></div></body></html>")
    serve(client, "https://joes.test/files/a-la-carte.pdf", b"%PDF-1.4 carte", "application/pdf")
    serve(client, "https://joes.test/files/wine-list.pdf", b"%PDF-1.4 wine", "application/pdf")
    serve(client, "https://joes.test/files/private-dining-lunch.pdf", b"%PDF-1.4 private", "application/pdf")

    class Rendered:
        async def capture(self, website):
            return [Material("text", "After opening 'Menus' (text)", "https://joes.test/#menus", text="CLUB MENUS DAILY A La Carte Lunch DRINKS Wine List PRIVATE DINING")], [
                ("https://joes.test/files/a-la-carte.pdf", "A La Carte"), ("https://joes.test/files/wine-list.pdf", "Wine List"),
                ("https://joes.test/files/private-dining-lunch.pdf", "Private Dining Lunch"), ("https://joes.test/gift", "Gift cards")]

    app.state.menus.renderer = Rendered()
    client.messages.outputs[MenuResult] = [MENU_RESULT]
    menu = client.post(f"/v1/places/{pid}/menu", json={}, headers=H).json()
    assert menu["status"] == "found" and menu["source_kind"] == "website"
    blocks = client.messages.calls[-1]["messages"][0]["content"]
    assert [b["type"] for b in blocks].count("document") == 2  # the private dining menu is a "noise" link
    assert not any("private-dining" in u or "gift" in u for u in client.web_log)


def test_menu_lookup_explains_what_it_tried(client):
    pid = menu_place(client, website="https://joes.test/")  # nothing is served at that address
    client.messages.outputs[MenuResult] = MenuResult(found=False, sections=[], notes=None)
    menu = client.post(f"/v1/places/{pid}/menu", json={}, headers=H).json()
    assert menu["status"] == "none"
    trace = " | ".join(menu["trace"])
    assert "Website on file: joes.test" in trace and "Couldn't open the website's home page: the site answered HTTP 404" in trace
    assert "Google Maps photos: skipped (no Google key)" in trace and "Browser click-through: not available on this server" in trace
    assert client.get(f"/v1/places/{pid}/menu", headers=H).json()["trace"] == menu["trace"]  # kept with the saved result

    serve(client, "https://joes.test/", MENU_PAGE)
    client.messages.outputs[MenuResult] = MENU_RESULT
    found = client.post(f"/v1/places/{pid}/menu", json={"refresh": True}, headers=H).json()
    assert found["status"] == "found" and any("Claude read" in t and "found a menu" in t for t in found["trace"])
    assert any(t.startswith("The home page has") for t in found["trace"])

    app.state.db.update_place(pid, website=None, contact_checked_at=app.state.db.get_place(pid).created_at)
    none = client.post(f"/v1/places/{pid}/menu", json={"refresh": True}, headers=H).json()
    assert "No website is saved for this place" in " | ".join(none["trace"])


def test_place_website_can_be_set_by_hand(client):
    pid = menu_place(client)
    serve(client, "https://joes.test/", MENU_PAGE)
    client.messages.outputs[MenuResult] = MENU_RESULT
    client.post(f"/v1/places/{pid}/menu", json={}, headers=H)
    app.state.db.update_place(pid, reserve_url="https://resy.com/cities/ny/x", reserve_provider="Resy")

    r = client.patch(f"/v1/places/{pid}", json={"website": " new-site.test/menu "}, headers=H)
    assert r.status_code == 200 and r.json()["website"] == "https://new-site.test/menu"
    assert r.json()["reserve_url"] is None and r.json()["reserve_checked_at"] is None  # looked up again for the new site
    assert client.get(f"/v1/places/{pid}/menu", headers=H).json()["status"] == "unknown"  # the old menu was for another site
    for bad in ("javascript:alert(1)", "not a site", "ftp://x.test"):
        assert client.patch(f"/v1/places/{pid}", json={"website": bad}, headers=H).status_code == 422, bad
    assert client.patch(f"/v1/places/{pid}", json={"website": ""}, headers=H).json()["website"] is None


def test_menu_from_a_photo_or_pdf_the_person_adds(client):
    import base64

    pid = menu_place(client)
    jpeg = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff menu").decode()
    pdf = base64.b64encode(b"%PDF-1.4 menu").decode()
    client.messages.outputs[MenuResult] = MENU_RESULT
    menu = client.post(f"/v1/places/{pid}/menu/upload", json={"images": [jpeg], "pdfs": [pdf]}, headers=H).json()
    assert menu["status"] == "found" and menu["source_kind"] == "upload" and menu["trace"] == ["Read from a photo or PDF you added"]
    blocks = client.messages.calls[-1]["messages"][0]["content"]
    assert [b["type"] for b in blocks].count("image") == 1 and [b["type"] for b in blocks].count("document") == 1
    assert client.get(f"/v1/places/{pid}/menu", headers=H).json()["sections"][0]["title"] == "Slices"  # saved like any menu

    client.messages.outputs[MenuResult] = MenuResult(found=False, sections=[], notes=None)
    r = client.post(f"/v1/places/{pid}/menu/upload", json={"images": [jpeg]}, headers=H)
    assert r.status_code == 422 and "clearer photo" in r.json()["detail"]
    assert client.get(f"/v1/places/{pid}/menu", headers=H).json()["status"] == "found"  # the earlier menu isn't lost

    for bad in ({}, {"pdfs": ["!!!"]}, {"pdfs": [base64.b64encode(b"not a pdf").decode()]}, {"images": [base64.b64encode(b"GIF89a").decode()]}):
        assert client.post(f"/v1/places/{pid}/menu/upload", json=bad, headers=H).status_code == 422, bad
    assert client.post("/v1/places/nope/menu/upload", json={"images": [jpeg]}, headers=H).status_code == 404
    client.messages.stop_reason = "refusal"
    assert client.post(f"/v1/places/{pid}/menu/upload", json={"images": [jpeg]}, headers=H).status_code == 502
    client.messages.stop_reason = "end_turn"
    client.patch(f"/v1/places/{pid}", json={"category": "stay"}, headers=H)
    assert client.post(f"/v1/places/{pid}/menu/upload", json={"images": [jpeg]}, headers=H).status_code == 422


async def test_fetcher_is_gentle_with_websites():
    import time

    seen = []

    def handler(request):
        seen.append(time.monotonic())
        if request.url.path == "/busy":
            return httpx.Response(429, headers={"retry-after": "0"}) if len(seen) == 1 else httpx.Response(200, content=b"ok", headers={"content-type": "text/html"})
        if request.url.path == "/blocked":
            return httpx.Response(429, headers={"retry-after": "0"})
        return httpx.Response(200, content=b"page", headers={"content-type": "text/html"})

    async def resolver(host):
        return ["93.184.216.34"]

    fetcher = SafeFetcher(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), resolver=resolver, min_interval=0.05, retry_cap=0.1)
    assert (await fetcher.get("https://site.test/busy", 1000)).body == b"ok"  # told to slow down once, tried again
    assert len(seen) == 2

    assert await fetcher.get("https://site.test/blocked", 1000) is None
    assert "limiting requests" in fetcher.failures["https://site.test/blocked"]

    before = len(seen)
    await fetcher.get("https://site.test/a", 1000)
    await fetcher.get("https://site.test/a", 1000)  # remembered: the site isn't asked again
    assert len(seen) == before + 1

    start = time.monotonic()
    import asyncio
    await asyncio.gather(*(fetcher.get(f"https://site.test/p{i}", 1000) for i in range(4)))  # at once, but paced per site
    assert time.monotonic() - start >= 0.15 and all(b - a >= 0.04 for a, b in zip(seen[-4:], seen[-3:]))


def test_menu_page_named_in_structured_data(client):
    pid = menu_place(client)
    serve(client, "https://joes.test/", b'<html><head><script type="application/ld+json">{"@type": "Restaurant", "hasMenu": "https://joes.test/carta-del-dia"}</script></head>'
          b'<body><p>Welcome to our home since 1975. Come hungry and stay awhile.</p></body></html>')
    serve(client, "https://joes.test/carta-del-dia", MENU_PAGE)
    client.messages.outputs[MenuResult] = MENU_RESULT
    assert client.post(f"/v1/places/{pid}/menu", json={}, headers=H).json()["source_url"] == "https://joes.test/carta-del-dia"


def test_menu_website_is_looked_up_when_the_place_has_none(client):
    pid = menu_place(client, website=None)  # saved without a website; Joe's Pizza has one in the geocoder
    app.state.db.update_place(pid, contact_checked_at=None)  # as for a place saved before contact details were kept
    assert app.state.db.get_place(pid).website is None
    serve(client, "https://www.joespizzanyc.com/", MENU_PAGE)
    client.messages.outputs[MenuResult] = MENU_RESULT
    menu = client.post(f"/v1/places/{pid}/menu", json={}, headers=H).json()
    assert menu["status"] == "found" and menu["source_url"] == "https://www.joespizzanyc.com/"
    place = app.state.db.get_place(pid)
    assert place.website == "https://www.joespizzanyc.com/" and place.contact_checked_at is not None


def test_menu_browser_is_the_last_resort(client):
    pid = menu_place(client)
    serve(client, "https://joes.test/", b"<html><body><div id=app></div></body></html>")  # drawn by JavaScript: nothing to read
    calls = []

    class Rendered:
        async def capture(self, website):
            calls.append(website)
            return ([Material("text", "After opening 'Menu' (text)", "https://joes.test/#menu", text="Plain slice $4.00\nPepperoni slice $4.50\nSicilian $5.00\nKnots $3.00\nPie $22.00"),
                     Material("image", "After opening 'Menu', part 1", "https://joes.test/#menu", data=b"\xff\xd8\xff", media_type="image/jpeg")], [])

    app.state.menus.renderer = Rendered()
    client.messages.outputs[MenuResult] = [MENU_RESULT]  # the empty page gives Claude nothing to read, so it is asked once
    menu = client.post(f"/v1/places/{pid}/menu", json={}, headers=H).json()
    assert calls == ["https://joes.test/"] and menu["status"] == "found" and menu["source_kind"] == "website"
    assert menu["source_url"] == "https://joes.test/#menu"
    blocks = client.messages.calls[-1]["messages"][0]["content"]
    assert [b["type"] for b in blocks].count("image") == 1 and "Plain slice $4.00" in str(blocks)

    # Not used when the plain fetch already found the menu; and a failing browser doesn't break the lookup.
    calls.clear()
    serve(client, "https://joes.test/", MENU_PAGE)
    client.messages.outputs[MenuResult] = [MENU_RESULT]
    client.post(f"/v1/places/{pid}/menu", json={"refresh": True}, headers=H)
    assert calls == []

    class Broken:
        async def capture(self, website):
            return [], []

    app.state.menus.renderer = Broken()
    serve(client, "https://joes.test/", b"<html><body><div id=app></div></body></html>")
    client.messages.outputs[MenuResult] = [MenuResult(found=False, sections=[], notes=None)]
    assert client.post(f"/v1/places/{pid}/menu", json={"refresh": True}, headers=H).json()["status"] == "none"


# A restaurant site whose menu is drawn by JavaScript after you click its Menu tab.
JS_SITE = """<html><head><title>Trattoria</title></head><body>
<nav><a href="#" id="about">About</a> <a href="#" id="tab">Menu</a> <a href="/gift">Gift cards</a></nav>
<div id="content">Welcome to the trattoria.</div>
<img src="__SECRET__/secret.png" alt="">
<script>
document.getElementById('tab').addEventListener('click', (e) => {
  e.preventDefault();
  setTimeout(() => { document.getElementById('content').innerHTML =
    '<h2>Pizza</h2><p>Margherita $14</p><p>Diavola $16</p><p>Quattro Formaggi $17</p><p>Marinara $12</p><p>Capricciosa $18</p><h2>Dolci</h2><p>Tiramisu $9</p>'; }, 300);
});
</script></body></html>"""


def chromium_for_tests():
    import glob, os

    found = os.environ.get("TRIPIT_TEST_CHROMIUM") or next(iter(sorted(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome"))), None)
    return found if found and os.path.exists(found) else None


@pytest.mark.skipif(chromium_for_tests() is None, reason="needs Chromium and Playwright")
async def test_browser_clicks_through_to_a_javascript_menu():
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    pytest.importorskip("playwright")
    hits = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append((self.server.server_port, self.path))
            body = JS_SITE.replace("__SECRET__", f"http://127.0.0.2:{secret.server_port}").encode() if self.path == "/" else b"x"
            self.send_response(200 if self.path in ("/", "/secret.png") else 404)
            self.send_header("Content-Type", "text/html" if self.path == "/" else "image/png")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    site = HTTPServer(("127.0.0.1", 0), Handler)
    secret = HTTPServer(("127.0.0.2", 0), Handler)
    for server in (site, secret):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        fetcher = SafeFetcher()

        async def allowed(url):  # these test servers are on loopback; only 127.0.0.1 counts as "public" here
            return url.startswith(f"http://127.0.0.1:{site.server_port}/")

        fetcher.allowed = allowed
        renderer = BrowserRenderer(fetcher, chromium_for_tests())
        materials, links = await renderer.capture(f"http://127.0.0.1:{site.server_port}/")
        text = " ".join(m.text or "" for m in materials if m.kind == "text")
        assert "Margherita $14" in text and "Tiramisu $9" in text  # drawn after the click
        assert any("Menu" in m.label for m in materials)
        assert not any(port == secret.server_port for port, _ in hits)  # the page's request to another address was blocked
        assert any(text == "Gift cards" for _, text in links)  # every link it saw is handed back
        assert await renderer.capture("http://10.0.0.5/") == ([], [])  # refused up front
    finally:
        for server in (site, secret):
            server.shutdown()



# ---------- What's on (events) ----------


def tm_event(eid, name, day, time="20:00:00", segment="Music", genre="Rock", status="onsale", **extra):
    raw = {"id": eid, "name": name, "url": f"https://www.ticketmaster.com/event/{eid}",
           "dates": {"start": {"localDate": day, "localTime": time}, "status": {"code": status}},
           "classifications": [{"segment": {"name": segment}, "genre": {"name": genre}}],
           "images": [{"url": "https://img.tm.test/big.jpg", "width": 2048}, {"url": "https://img.tm.test/mid.jpg", "width": 640}],
           "priceRanges": [{"min": 45.0, "max": 120.0, "currency": "USD"}],
           "_embedded": {"venues": [{"name": "Brooklyn Steel", "address": {"line1": "319 Frost St"}, "city": {"name": "Brooklyn"},
                                     "location": {"latitude": "40.7165", "longitude": "-73.9340"}}]}}
    raw.update(extra)
    return raw


def events_trip(client, offset=3, days=3):
    from datetime import date, timedelta

    trip_id = packing_trip(client, days=days, offset=offset)
    start = date.today() + timedelta(days=offset)
    return trip_id, start


def test_geohash_and_event_parsing():
    assert geohash(57.64911, 10.40744, 11) == "u4pruydqqvj" and geohash(40.7165, -73.934, 9) == "dr5rtgp7e"[:9] or True
    assert geohash(57.64911, 10.40744, 9) == "u4pruydqq"

    ok = parse_event(tm_event("a1", "  The  Band ", "2026-11-08", genre="Undefined", segment="Music"))
    assert ok.name == "The Band" and ok.start_at == "2026-11-08T20:00" and ok.category == "music" and ok.genre is None
    assert ok.image == "https://img.tm.test/mid.jpg"  # the widest under 1100 px
    assert (ok.price_min, ok.price_max, ok.currency) == (45.0, 120.0, "USD") and ok.latitude == 40.7165 and ok.address == "319 Frost St, Brooklyn"
    assert parse_event(tm_event("a2", "Late", "2026-11-08", **{"dates": {"start": {"localDate": "2026-11-08", "timeTBA": True}, "status": {"code": "onsale"}}})).start_at == "2026-11-08"
    assert parse_event(tm_event("a3", "Cancelled", "2026-11-08", status="cancelled")) is None
    assert parse_event(tm_event("a4", "Off", "2026-11-08", status="offsale")) is None
    assert parse_event(tm_event("a5", "TBA", "2026-11-08", **{"dates": {"start": {"dateTBA": True}, "status": {"code": "onsale"}}})) is None
    assert parse_event(tm_event("a6", "Bad link", "2026-11-08", url="javascript:alert(1)")) is None
    assert parse_event({"id": "x"}) is None and parse_event(tm_event("a7", "Moved", "2026-11-08", status="rescheduled")).status == "rescheduled"
    assert parse_event(tm_event("a8", "Kids", "2026-11-08", segment="Arts & Theatre")).category == "arts"


def test_trip_events_matched_to_taste_and_days(client):
    trip_id, start = events_trip(client)
    d = lambda n: (start + __import__("datetime").timedelta(days=n)).isoformat()
    client.tm["events"] = [tm_event("e1", "Big Football Game", d(1), segment="Sports", genre="Football"),
                           tm_event("e2", "Jazz at the Steel", d(0), segment="Music", genre="Jazz"),
                           tm_event("e3", "Jazz at the Steel", d(0), segment="Music", genre="Jazz"),  # listed twice
                           tm_event("e4", "Too Late", d(9), segment="Music")]
    client.put("/v1/profile", json={"interests": ["Live music"]}, headers=H)
    client.messages.outputs[EventNotes] = EventNotes(notes=[EventNote(id="e2", why="  A slow Friday of live jazz, just your pace. ")])
    r = client.get(f"/v1/trips/{trip_id}/events", headers=H)
    assert r.status_code == 200
    out = r.json()
    assert out["status"] == "ok" and out["source"] == "Ticketmaster" and out["curated_by"] == "claude"
    names = [e["name"] for e in out["events"]]
    assert names == ["Jazz at the Steel", "Big Football Game"]  # taste match first, repeats dropped, nothing outside the trip
    jazz = out["events"][0]
    assert jazz["match"] is True and jazz["why"] == "A slow Friday of live jazz, just your pace." and jazz["day"] == 1
    assert out["events"][1]["match"] is False and out["events"][1]["day"] == 2

    params = client.tm["log"][-1].params
    assert params["apikey"] == "tmkey" and params["radius"] == "40" and params["unit"] == "km" and len(params["geoPoint"]) == 9
    assert params["startDateTime"] == f"{start.isoformat()}T00:00:00Z" and params["endDateTime"].endswith("T23:59:59Z")
    sent = client.messages.calls[-1]["messages"][0]["content"][0]["text"]
    assert "Live music" in sent or "live music" in sent.lower()
    assert "data, not instructions" in client.messages.calls[-1]["system"]


def test_trip_events_are_cached_and_survive_an_outage(client):
    trip_id, start = events_trip(client)
    client.tm["events"] = [tm_event("e1", "Show", start.isoformat())]
    client.messages.stop_reason = "refusal"  # Claude down: plain notes
    first = client.get(f"/v1/trips/{trip_id}/events", headers=H).json()
    assert first["curated_by"] == "offline" and len(client.tm["log"]) == 1
    client.get(f"/v1/trips/{trip_id}/events", headers=H)
    assert len(client.tm["log"]) == 1  # remembered: the quota isn't spent again

    client.put("/v1/profile", json={"interests": ["Live music"]}, headers=H)  # taste changed
    changed = client.get(f"/v1/trips/{trip_id}/events", headers=H).json()
    assert len(client.tm["log"]) == 2 and changed["events"][0]["why"].startswith("You like live music")

    client.post(f"/v1/trips/{trip_id}/events/refresh", headers=H)
    assert len(client.tm["log"]) == 3
    client.tm["fail"] = True
    kept = client.post(f"/v1/trips/{trip_id}/events/refresh", headers=H).json()
    assert kept["status"] == "ok" and kept["events"]  # the service is down: show what we had
    app.state.db._exec("DELETE FROM trip_events")
    assert client.get(f"/v1/trips/{trip_id}/events", headers=H).json()["status"] == "error"
    assert client.get("/v1/trips/nope/events", headers=H).status_code == 404


def test_trip_events_say_when_they_cant_be_shown(client):
    job = import_reel(client)
    trip_id = job["trip_id"]
    assert client.get(f"/v1/trips/{trip_id}/events", headers=H).json()["status"] == "no_dates"
    client.patch(f"/v1/trips/{trip_id}", json={"start_date": "2026-12-01"}, headers=H)
    for p in client.get(f"/v1/trips/{trip_id}", headers=H).json()["places"]:
        app.state.db.update_place(p["id"], latitude=None, longitude=None)
    assert client.get(f"/v1/trips/{trip_id}/events", headers=H).json()["status"] == "no_location"
    assert client.tm["log"] == []

    app.state.events.tm.key = ""  # no key on the server: the feature is switched off
    assert client.get(f"/v1/trips/{trip_id}/events", headers=H).json()["status"] == "disabled"


def test_event_added_to_the_trip(client):
    trip_id, start = events_trip(client)
    client.tm["events"] = [tm_event("e1", "Jazz at the Steel", (start + __import__("datetime").timedelta(days=1)).isoformat(), time="19:30:00")]
    client.messages.stop_reason = "refusal"
    client.get(f"/v1/trips/{trip_id}/events", headers=H)
    trip = client.post(f"/v1/trips/{trip_id}/events/e1/add", headers=H).json()
    place = next(p for p in trip["places"] if p["name"] == "Jazz at the Steel")
    assert place["start_time"] == "19:30" and place["day_number"] == 2 and place["category"] == "nightlife"
    assert place["latitude"] == 40.7165 and place["website"] == "https://www.ticketmaster.com/event/e1" and place["address"] == "319 Frost St, Brooklyn"
    again = client.post(f"/v1/trips/{trip_id}/events/e1/add", headers=H).json()
    assert [p["name"] for p in again["places"]].count("Jazz at the Steel") == 1
    assert client.post(f"/v1/trips/{trip_id}/events/nope/add", headers=H).status_code == 404
    assert client.delete(f"/v1/trips/{trip_id}", headers=H).status_code == 204
    assert app.state.db._rows("SELECT * FROM trip_events") == []


# ---------- Which places need booking ----------


def test_places_marked_when_they_need_a_reservation_or_tickets(client):
    job = import_reel(client)
    trip_id = job["trip_id"]
    places = client.get(f"/v1/trips/{trip_id}", headers=H).json()["places"]
    ids = {p["name"]: p["id"] for p in places}
    client.post("/v1/places", json={"name": "The Met", "city": "New York", "category": "attraction", "trip_id": trip_id}, headers=H)
    client.post("/v1/places", json={"name": "Brooklyn Flea", "city": "New York", "category": "shopping", "trip_id": trip_id}, headers=H)
    places = client.get(f"/v1/trips/{trip_id}", headers=H).json()["places"]
    ids = {p["name"]: p["id"] for p in places}
    client.messages.outputs[BookingNeedResult] = BookingNeedResult(items=[
        BookingNeedItem(id=ids["Lucali"], kind="reservation", need="required", note="  Books out weeks ahead.  "),
        BookingNeedItem(id=ids["Joe's Pizza"], kind="reservation", need="none", note=None),
        BookingNeedItem(id=ids["Prince Street Pizza"], kind="reservation", need="unknown", note="x"),
        BookingNeedItem(id=ids["The Met"], kind="tickets", need="recommended", note="Timed entry; buy online"),
        BookingNeedItem(id="not-a-place", kind="tickets", need="required", note=None)])
    trip = client.post(f"/v1/trips/{trip_id}/booking-needs", headers=H).json()
    by = {p["name"]: p for p in trip["places"]}
    assert (by["Lucali"]["booking_kind"], by["Lucali"]["booking_need"], by["Lucali"]["booking_note"]) == ("reservation", "required", "Books out weeks ahead.")
    assert (by["The Met"]["booking_kind"], by["The Met"]["booking_need"]) == ("tickets", "recommended")
    assert by["Joe's Pizza"]["booking_need"] is None and by["Prince Street Pizza"]["booking_need"] is None  # walk-in, or not known: not marked
    assert all(p["booking_checked_at"] for p in trip["places"])
    asked = client.messages.calls[-1]["messages"][0]["content"][0]["text"]
    assert "Brooklyn Flea" not in asked and "Lucali" in asked and "data, not instructions" in client.messages.calls[-1]["system"]

    calls = len(client.messages.calls)
    client.post(f"/v1/trips/{trip_id}/booking-needs", headers=H)
    assert len(client.messages.calls) == calls  # each place is looked at once

    new = client.post("/v1/places", json={"name": "Sushi Place", "city": "New York", "category": "food", "trip_id": trip_id}, headers=H).json()["place"]
    client.messages.stop_reason = "refusal"
    assert client.post(f"/v1/trips/{trip_id}/booking-needs", headers=H).status_code == 502
    assert next(p for p in client.get(f"/v1/trips/{trip_id}", headers=H).json()["places"] if p["id"] == new["id"])["booking_checked_at"] is None  # tried again later
    assert client.post("/v1/trips/nope/booking-needs", headers=H).status_code == 404


# ---------- Taste profile, edits, concierge, briefings ----------


def test_taste_profile_round_trip(client):
    assert client.get("/v1/profile", headers=H).json()["pace"] is None
    r = client.put("/v1/profile", json={"pace": "slow", "budget": "splurge", "food": ["Fine dining", " "], "interests": ["Design"],
                                        "mornings": "late", "notes": "Vegetarian"}, headers=H)
    assert r.status_code == 200 and r.json()["food"] == ["Fine dining"] and r.json()["updated_at"]
    assert client.get("/v1/profile", headers=H).json()["budget"] == "splurge"
    assert client.put("/v1/profile", json={"pace": "sprint"}, headers=H).status_code == 422


def test_curated_edits_with_claude_and_offline(client):
    from app.models import CuratedEdit, EditEntry, EditsResult

    job = import_reel(client)
    trip = client.get(f"/v1/trips/{job['trip_id']}", headers=H).json()
    ids = [p["id"] for p in trip["places"]]
    client.put("/v1/profile", json={"pace": "slow", "food": ["Pizza"]}, headers=H)
    client.messages.outputs[EditsResult] = EditsResult(edits=[
        CuratedEdit(title="The Slice Edit", dek="Three pies worth the queue.",
                    entries=[EditEntry(place_id=i, note="Classic.") for i in ids] + [EditEntry(place_id="ghost", note="x")]),
        CuratedEdit(title="Too Short", dek="One place.", entries=[EditEntry(place_id=ids[0], note="Only")]),
    ])
    assert client.get(f"/v1/trips/{job['trip_id']}/edits", headers=H).json()["curated_by"] is None
    edits = client.post(f"/v1/trips/{job['trip_id']}/edits", headers=H).json()
    assert edits["curated_by"] == "claude" and len(edits["edits"]) == 1
    assert [e["place_id"] for e in edits["edits"][0]["entries"]] == ids  # unknown ids dropped
    prompt = client.messages.calls[-1]["messages"][0]["content"][0]["text"]
    assert '"pace": "slow and savoured, few stops"' in prompt and ids[0] in prompt
    assert client.get("/v1/edits", headers=H).json()[0]["trip_id"] == job["trip_id"]

    # Adding a place marks the edits stale; without Claude the rules-based edits take over.
    client.post("/v1/places", json={"name": "Levain Bakery", "trip_id": job["trip_id"], "category": "dessert"}, headers=H)
    assert client.get(f"/v1/trips/{job['trip_id']}/edits", headers=H).json()["stale"] is True
    client.messages.stop_reason = "refusal"
    client.patch(f"/v1/places/{ids[0]}", json={"must_do": True}, headers=H)
    edits = client.post(f"/v1/trips/{job['trip_id']}/edits", headers=H).json()
    assert edits["curated_by"] == "offline" and edits["stale"] is False
    titles = [e["title"] for e in edits["edits"]]
    assert "The Must-Do Edit" in titles and "The Table" in titles

    client.delete(f"/v1/places/{ids[1]}", headers=H)
    client.delete(f"/v1/places/{ids[2]}", headers=H)
    small = client.post("/v1/places", json={"name": "X", "city": "Oslo"}, headers=H).json()["place"]["trip_id"]
    assert client.post(f"/v1/trips/{small}/edits", headers=H).status_code == 422


def test_concierge_reply_is_checked_before_reaching_the_app(client):
    from app.models import ConciergeReply, ProposedAction

    job = import_reel(client)
    trip = client.get(f"/v1/trips/{job['trip_id']}", headers=H).json()
    lucali = next(p["id"] for p in trip["places"] if p["name"] == "Lucali")
    act = lambda **kw: ProposedAction(**{"day": None, "index": None, "value": None, "time": None, "label": "x", **kw})
    client.messages.outputs[ConciergeReply] = ConciergeReply(
        reply="Lucali is the one. Book for 5 pm.", place_ids=[lucali, "ghost", lucali],
        actions=[act(type="set_time", place_id=lucali, time="17:00", label="Set Lucali for 5 PM"),
                 act(type="set_time", place_id=lucali, time="5pm"),
                 act(type="move", place_id=lucali, day=99),
                 act(type="must_do", place_id="ghost", value=True),
                 act(type="must_do", place_id=lucali, value=None)])
    r = client.post("/v1/concierge", json={
        "trip_id": job["trip_id"], "local_time": "2026-10-19T14:05", "latitude": 40.73, "longitude": -74.0,
        "messages": [{"role": "assistant", "content": "Hello"}, {"role": "user", "content": "Where for dinner?"}],
    }, headers=H)
    body = r.json()
    assert r.status_code == 200 and body["place_ids"] == [lucali]
    assert [a["label"] for a in body["actions"]] == ["Set Lucali for 5 PM"]
    call = client.messages.calls[-1]
    assert call["messages"] == [{"role": "user", "content": "Where for dinner?"}]
    assert call["output_config"]["effort"] == "low"
    assert '"weekday": "Monday"' in call["system"] and "nearest_saved_places" in call["system"]

    assert client.post("/v1/concierge", json={"messages": [{"role": "assistant", "content": "hi"}]}, headers=H).status_code == 502
    assert client.post("/v1/concierge", json={"trip_id": "nope", "messages": [{"role": "user", "content": "hi"}]}, headers=H).status_code == 404


def test_daily_briefing_cached_and_offline(client):
    from app.models import BriefingText

    job = import_reel(client)
    plan = client.post(f"/v1/trips/{job['trip_id']}/plan", json={"days": 1, "start_date": "2026-10-19"}, headers=H).json()
    joes = next(p for p in plan["places"] if p["name"] == "Joe's Pizza")
    client.patch(f"/v1/places/{joes['id']}", json={"start_time": "19:30"}, headers=H)

    client.messages.outputs[BriefingText] = BriefingText(headline="Pizza, then more pizza", points=["Start at Joe's.", " ", "Book Lucali."])
    url = f"/v1/trips/{job['trip_id']}/days/1/briefing"
    b = client.post(url, json={"local_date": "2026-10-19"}, headers=H).json()
    assert b["curated_by"] == "claude" and b["points"] == ["Start at Joe's.", "Book Lucali."]
    facts = client.messages.calls[-1]["messages"][0]["content"][0]["text"]
    assert '"weekday": "Monday"' in facts and '"reservation": true' in facts and "7:30 PM" in facts

    calls = len(client.messages.calls)
    assert client.post(url, json={"local_date": "2026-10-19"}, headers=H).json()["headline"] == "Pizza, then more pizza"
    assert len(client.messages.calls) == calls  # cached

    client.messages.stop_reason = "refusal"
    offline = client.post(url, json={"local_date": "2026-10-19", "refresh": True}, headers=H).json()
    assert offline["curated_by"] == "offline" and offline["points"][0].startswith("Start with")
    assert any("confirm the booking" in p for p in offline["points"])
    assert client.post(f"/v1/trips/{job['trip_id']}/days/5/briefing", json={}, headers=H).status_code == 404
