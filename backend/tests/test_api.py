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
from app.main import app
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

H = {"X-API-Key": "secret"}


def extracted(name, city="New York", hood="Greenwich Village", category="food"):
    return {
        "name": name, "category": category, "city": city, "country": "USA", "neighborhood": hood,
        "address": None, "description": f"{name} is great", "recommended_items": ["slice"], "price_hint": "$",
        "tips": None, "source": "on_screen", "confidence": "high",
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

    async def locate(self, name, neighborhood, city, country, query=None):
        self.queries.append(query or name)
        if query:
            return GeoMatch(name=name, latitude=40.6818, longitude=-74.0003, address="575 Henry St")
        if name in self.COORDS:
            lat, lon = self.COORDS[name]
            return GeoMatch(name=name, latitude=lat, longitude=lon, address="Somewhere St")
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
    library = Library(db, geocoder)
    store = JobStore(db)
    app.state.db = db
    app.state.store = store
    app.state.claude = claude
    app.state.library = library
    app.state.pipeline = pipeline_module.Pipeline(settings, store, claude, library)

    with TestClient(app) as c:
        c.messages = messages
        c.geocoder = geocoder
        yield c
    app.dependency_overrides.clear()
    for attr in ("db", "store", "claude", "library", "pipeline"):
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

    for model in (ExtractionResult, PlanResult):
        schema = transform_schema(TypeAdapter(model).json_schema())
        assert schema["additionalProperties"] is False


async def test_google_geocoder_parses_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Goog-Api-Key"] == "k"
        assert "places.location" in request.headers["X-Goog-FieldMask"]
        return httpx.Response(200, json={"places": [{
            "displayName": {"text": "Joe's Pizza"}, "formattedAddress": "7 Carmine St, New York",
            "location": {"latitude": 40.73, "longitude": -74.0}, "googleMapsUri": "https://maps.google.com/?cid=1",
        }]})

    geo = GooglePlacesGeocoder("k", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    match = await geo.locate("Joe's Pizza", "Greenwich Village", "New York", "USA")
    assert match.latitude == 40.73 and match.maps_url.startswith("https://maps.google.com")


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
