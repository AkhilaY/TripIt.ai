import asyncio
import logging
import secrets
from contextlib import asynccontextmanager
from typing import Annotated, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request

from .config import Settings, get_settings
from .jobs import JobStore
from .llm import ClaudeError, ClaudeService
from .media import UnsupportedURLError, find_url, platform_for
from .models import CreateJobRequest, Job, PlanRequest, PlanResult
from .pipeline import Pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if not hasattr(app.state, "pipeline"):
        store = JobStore(ttl_hours=settings.job_ttl_hours)
        app.state.store = store
        app.state.claude = ClaudeService(settings)
        app.state.pipeline = Pipeline(settings, store, app.state.claude)
    app.state.tasks = set()
    yield


app = FastAPI(title="TripIt.ai", lifespan=lifespan)


def require_api_key(
    settings: Annotated[Settings, Depends(get_settings)],
    x_api_key: Annotated[Optional[str], Header()] = None,
) -> None:
    if settings.app_api_key and not secrets.compare_digest(x_api_key or "", settings.app_api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")


Auth = Depends(require_api_key)


@app.get("/health")
async def health() -> dict:
    return {"ok": True}


@app.post("/v1/jobs", response_model=Job, status_code=202, dependencies=[Auth])
async def create_job(body: CreateJobRequest, request: Request) -> Job:
    url = find_url(body.url) or body.url.strip()
    try:
        platform_for(url)
    except UnsupportedURLError as e:
        raise HTTPException(status_code=422, detail=str(e))

    state = request.app.state
    job, created = await state.store.create(url)
    if created:
        task = asyncio.create_task(state.pipeline.run(job.id, url, body.shared_text))
        state.tasks.add(task)
        task.add_done_callback(state.tasks.discard)
    return job


@app.get("/v1/jobs/{job_id}", response_model=Job, dependencies=[Auth])
async def get_job(job_id: str, request: Request) -> Job:
    job = request.app.state.store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found or expired")
    return job


@app.post("/v1/itineraries", response_model=PlanResult, dependencies=[Auth])
async def plan_itinerary(body: PlanRequest, request: Request) -> PlanResult:
    try:
        return await request.app.state.claude.plan_itinerary(body)
    except ClaudeError as e:
        raise HTTPException(status_code=502, detail=str(e))
