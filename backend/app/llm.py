"""Claude calls: pull places out of a reel, and turn saved places into a day-by-day plan."""

import base64
import json
import logging
from pathlib import Path
from typing import Optional, TypeVar

import anthropic
from pydantic import BaseModel

from .config import Settings
from .models import ExtractionResult, PlanRequest, PlanResult, ReelMetadata

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

FALLBACK_BETA = "server-side-fallback-2026-07-01"

EXTRACT_SYSTEM = """You turn short travel posts (TikTok videos and photo slideshows, Instagram Reels and carousels, YouTube Shorts) into a structured list of places.

You get the post caption, a timestamped speech transcript when there is speech, and images: frames sampled from a video, or the slides of a photo post. Creators usually name each place in the voiceover or as text written over the frames or slides, so read the images carefully.

Rules:
- Include only real, specific places a person could visit or search for in a maps app: restaurants, bars, cafes, shops, landmarks, parks, hotels, tours. Skip generic advice ("try a bagel") unless it names a specific place.
- Use the place's proper name, fixing obvious transcription misspellings when you are confident of the real name.
- city/country: where the place actually is. Use the reel's destination when the place's location isn't stated otherwise.
- Never invent addresses, prices or dishes that weren't mentioned or shown. Use null when unknown.
- confidence: high when the name is clearly stated or shown; low when you had to infer it from partial or garbled text.
- List places in the order they appear in the video. If the reel has no identifiable places, return an empty list."""

PLAN_SYSTEM = """You are a travel planner. Arrange the given saved places into a realistic day-by-day itinerary.

- Group places that are geographically close into the same day to minimise travel (use latitude/longitude and neighborhood).
- Put meals at sensible times: cafes and bakeries in the morning, restaurants at lunch or dinner, bars and nightlife in the evening.
- Don't overload days: roughly 3-6 stops per day, fewer if they are big attractions.
- Respect opening_hours when given (local times, Mon–Sun). Don't schedule a place on a day or at a time it's closed. If a start_date is given, day 1 falls on that date's weekday; otherwise prefer slots when the place is open on most days.
- Use each place at most once, and only use place_ids from the input. Put places that don't fit in unscheduled_place_ids.
- Day titles should name the area or theme."""


class ClaudeError(RuntimeError):
    pass


class ClaudeService:
    def __init__(self, settings: Settings, client: Optional[anthropic.AsyncAnthropic] = None):
        self.settings = settings
        self.client = client or anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key or None)

    async def extract_places(
        self,
        reel: ReelMetadata,
        shared_text: Optional[str],
        transcript: Optional[str],
        frames: list[tuple[str, Path]],
    ) -> ExtractionResult:
        """frames: (label, image) pairs, e.g. ("Frame at 12s", …) or ("Slide 3", …)."""
        content: list[dict] = []
        for label, path in frames:
            content.append({"type": "text", "text": f"{label}:"})
            content.append(_image_block(path))

        text_parts = [
            f"Platform: {reel.platform}",
            f"Creator: {reel.uploader or 'unknown'}",
            f"Title: {reel.title or '(none)'}",
            f"Caption:\n{reel.caption or '(none)'}",
        ]
        if shared_text and shared_text.strip() != (reel.caption or "").strip():
            text_parts.append(f"Text shared with the link:\n{shared_text}")
        text_parts.append(f"Speech transcript:\n{transcript or '(no speech detected)'}")
        if not frames:
            text_parts.append("(No video frames or images were available for this post.)")
        text_parts.append("Extract every place recommended in this post.")
        content.append({"type": "text", "text": "\n\n".join(text_parts)})

        return await self._parse(EXTRACT_SYSTEM, content, ExtractionResult)

    async def plan_itinerary(self, request: PlanRequest) -> PlanResult:
        payload = {
            "city": request.city,
            "days": request.days,
            "start_date": request.start_date.isoformat() if request.start_date else None,
            "start_weekday": request.start_date.strftime("%A") if request.start_date else None,
            "preferences": request.preferences,
            "places": [p.model_dump(mode="json", exclude_none=True) for p in request.places],
        }
        content = [
            {
                "type": "text",
                "text": f"Plan a {request.days}-day itinerary from these saved places:\n\n"
                + json.dumps(payload, indent=2),
            }
        ]
        result = await self._parse(PLAN_SYSTEM, content, PlanResult)
        return _sanitize_plan(result, request)

    async def _parse(self, system: str, content: list[dict], output_type: type[T]) -> T:
        try:
            response = await self.client.beta.messages.parse(
                model=self.settings.claude_model,
                max_tokens=16000,
                system=system,
                messages=[{"role": "user", "content": content}],
                thinking={"type": "adaptive"},
                output_config={"effort": self.settings.claude_effort},
                output_format=output_type,
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
        except anthropic.RateLimitError as e:
            raise ClaudeError("Claude is rate limited, try again in a minute") from e
        except anthropic.APIStatusError as e:
            log.error("Claude API error %s (request %s): %s", e.status_code, e.request_id, e.message)
            raise ClaudeError(f"Claude API error ({e.status_code})") from e
        except anthropic.APIConnectionError as e:
            raise ClaudeError("Couldn't reach Claude") from e
        except anthropic.AnthropicError as e:  # e.g. no API key configured
            log.error("Claude client error: %s", e)
            raise ClaudeError("Claude isn't configured on the server") from e

        if response.stop_reason == "refusal":
            raise ClaudeError("Claude declined to process this post")
        if response.stop_reason == "max_tokens" or response.parsed_output is None:
            raise ClaudeError("Claude's response was incomplete")
        return response.parsed_output


def _image_block(path: Path) -> dict:
    media_type = {".png": "image/png", ".webp": "image/webp"}.get(path.suffix.lower(), "image/jpeg")
    data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}


def _sanitize_plan(result: PlanResult, request: PlanRequest) -> PlanResult:
    """Drop unknown or repeated place IDs, and make sure every input place lands somewhere."""
    valid = {p.id for p in request.places}
    seen: set[str] = set()
    for day in result.days:
        stops = []
        for stop in day.stops:
            if stop.place_id in valid and stop.place_id not in seen:
                seen.add(stop.place_id)
                stops.append(stop)
        day.stops = stops
    result.days = [d for d in result.days if d.stops]
    for i, day in enumerate(result.days, start=1):
        day.day_number = i
    result.unscheduled_place_ids = [p.id for p in request.places if p.id not in seen]
    return result
