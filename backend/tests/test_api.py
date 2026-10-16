import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import pipeline as pipeline_module
from app.config import Settings, get_settings
from app.jobs import JobStore
from app.llm import ClaudeService, _sanitize_plan
from app.main import app
from app.media import DownloadedReel, UnsupportedURLError, find_url, platform_for
from app.models import (
    ExtractionResult,
    PlannedDay,
    PlannedStop,
    PlanRequest,
    PlanResult,
    ReelMetadata,
)

EXTRACTION = ExtractionResult(
    title="Best pizza in NYC",
    destination_city="New York",
    destination_country="USA",
    summary="Three pizza spots",
    places=[
        {
            "name": "Joe's Pizza",
            "category": "food",
            "city": "New York",
            "country": "USA",
            "neighborhood": "Greenwich Village",
            "address": None,
            "description": "Classic NY slice",
            "recommended_items": ["plain slice"],
            "price_hint": "$",
            "tips": None,
            "source": "on_screen",
            "confidence": "high",
        }
    ],
)


class FakeMessages:
    def __init__(self, parsed, stop_reason="end_turn"):
        self.parsed = parsed
        self.stop_reason = stop_reason
        self.calls = []

    async def parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(parsed_output=self.parsed, stop_reason=self.stop_reason)


def fake_client(parsed, stop_reason="end_turn"):
    messages = FakeMessages(parsed, stop_reason)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages)), messages


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
            metadata=ReelMetadata(platform="tiktok", url=url, caption="pizza!"), video_path=video
        ),
    )
    monkeypatch.setattr(pipeline_module, "extract_audio", lambda v, w: tmp_path / "a.wav")
    monkeypatch.setattr(pipeline_module, "transcribe", lambda a, s: "[0.0s] go to Joe's Pizza")
    monkeypatch.setattr(pipeline_module, "extract_frames", lambda v, w, s: [(0.0, frame)])

    anthropic_client, messages = fake_client(EXTRACTION)
    store = JobStore()
    claude = ClaudeService(settings, client=anthropic_client)
    app.state.store = store
    app.state.claude = claude
    app.state.pipeline = pipeline_module.Pipeline(settings, store, claude)

    with TestClient(app) as c:
        c.messages = messages
        yield c
    app.dependency_overrides.clear()
    for attr in ("store", "claude", "pipeline"):
        delattr(app.state, attr)


def wait_for(c, job_id, headers):
    for _ in range(100):
        job = c.get(f"/v1/jobs/{job_id}", headers=headers).json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def test_requires_api_key(client):
    assert client.post("/v1/jobs", json={"url": "https://www.tiktok.com/@a/video/1"}).status_code == 401


def test_rejects_unsupported_hosts(client):
    r = client.post("/v1/jobs", json={"url": "http://169.254.169.254/latest"}, headers={"X-API-Key": "secret"})
    assert r.status_code == 422


def test_job_end_to_end(client):
    headers = {"X-API-Key": "secret"}
    r = client.post(
        "/v1/jobs",
        json={"url": "Look at this! https://vm.tiktok.com/ZMabc/ via TikTok", "shared_text": "best pizza"},
        headers=headers,
    )
    assert r.status_code == 202
    job = wait_for(client, r.json()["id"], headers)
    assert job["status"] == "done", job
    assert job["result"]["places"][0]["name"] == "Joe's Pizza"
    assert job["reel"]["caption"] == "pizza!"

    call = client.messages.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["fallbacks"] == "default"
    assert call["output_format"] is ExtractionResult
    blocks = call["messages"][0]["content"]
    assert any(b["type"] == "image" for b in blocks)
    assert "Joe's Pizza" in blocks[-1]["text"]

    # Same URL again reuses the existing job instead of paying for another run.
    again = client.post("/v1/jobs", json={"url": "https://vm.tiktok.com/ZMabc/"}, headers=headers).json()
    assert again["id"] == job["id"]


def test_refusal_fails_job(client):
    client.messages.stop_reason = "refusal"
    headers = {"X-API-Key": "secret"}
    r = client.post("/v1/jobs", json={"url": "https://www.instagram.com/reel/xyz/"}, headers=headers)
    job = wait_for(client, r.json()["id"], headers)
    assert job["status"] == "failed"


def test_download_failure_without_text_fails(client, monkeypatch):
    def boom(*a):
        raise RuntimeError("private video")

    monkeypatch.setattr(pipeline_module, "download_reel", boom)
    headers = {"X-API-Key": "secret"}
    r = client.post("/v1/jobs", json={"url": "https://www.instagram.com/reel/private/"}, headers=headers)
    job = wait_for(client, r.json()["id"], headers)
    assert job["status"] == "failed"
    assert "download" in job["message"]


def test_url_helpers():
    assert find_url("watch https://vm.tiktok.com/ZMabc/).") == "https://vm.tiktok.com/ZMabc/"
    assert platform_for("https://www.instagram.com/reel/abc/") == "instagram"
    with pytest.raises(UnsupportedURLError):
        platform_for("https://evil-tiktok.com/x")
    with pytest.raises(UnsupportedURLError):
        platform_for("file:///etc/passwd")


def test_sanitize_plan_drops_unknown_and_duplicate_ids():
    request = PlanRequest(
        city="NYC",
        days=2,
        places=[{"id": "a", "name": "A", "category": "food"}, {"id": "b", "name": "B", "category": "cafe"}],
    )
    result = PlanResult(
        days=[
            PlannedDay(day_number=5, title="x", stops=[PlannedStop(place_id="a", time_of_day="lunch", note=None)]),
            PlannedDay(
                day_number=6,
                title="y",
                stops=[
                    PlannedStop(place_id="a", time_of_day="dinner", note=None),
                    PlannedStop(place_id="zzz", time_of_day="dinner", note=None),
                ],
            ),
        ],
        unscheduled_place_ids=[],
    )
    clean = _sanitize_plan(result, request)
    assert [d.day_number for d in clean.days] == [1]
    assert clean.unscheduled_place_ids == ["b"]


def test_output_schemas_are_accepted_by_sdk():
    from anthropic.lib._parse._transform import transform_schema
    from pydantic import TypeAdapter

    for model in (ExtractionResult, PlanResult):
        schema = transform_schema(TypeAdapter(model).json_schema())
        assert schema["additionalProperties"] is False
