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
from app.llm import ClaudeService, _sanitize_plan
from app.concierge import Curator
from app.main import app, notify_import
from app.media import DownloadedReel, UnsupportedURLError, find_url, platform_for
from app.models import (
    ExtractionResult,
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

    with TestClient(app) as c:
        c.messages = messages
        c.geocoder = geocoder
        c.push_log = push_log
        c.push_status = push_status
        c.uploads = tmp_path / "uploads"
        yield c
    app.dependency_overrides.clear()
    for attr in ("db", "store", "claude", "library", "pipeline", "router", "photos", "push", "curator"):
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

    for model in (ExtractionResult, PlanResult, EditsResult, ConciergeReply, BriefingText):
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
