from datetime import date, datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class PlaceCategory(str, Enum):
    food = "food"
    cafe = "cafe"
    dessert = "dessert"
    drinks = "drinks"
    nightlife = "nightlife"
    attraction = "attraction"
    activity = "activity"
    nature = "nature"
    shopping = "shopping"
    stay = "stay"
    other = "other"


class PlacePhoto(BaseModel):
    source: Literal["reel", "google", "wikimedia"]
    url: str
    attribution: Optional[str] = None


class TimeRange(BaseModel):
    open: str  # "HH:MM", local time at the place
    close: str  # "HH:MM"; earlier than open means after midnight; "24:00" = midnight


class OpeningHours(BaseModel):
    weekly: Optional[list[list[TimeRange]]] = None  # 7 lists, Monday first; None if not machine-readable
    text: list[str] = []
    source: str = ""
    raw: Optional[str] = None


# ---------- Claude extraction output ----------


class ExtractedPlace(BaseModel):
    name: str = Field(description="Official business or landmark name, as you'd type it into a maps search.")
    category: PlaceCategory
    city: str
    country: str
    neighborhood: Optional[str] = Field(description="Neighborhood or district, if known.")
    address: Optional[str] = Field(description="Street address only if stated or shown in the video.")
    description: str = Field(description="One or two sentences on why the creator recommends it.")
    recommended_items: list[str] = Field(description="Specific dishes, drinks or things to do mentioned.")
    price_hint: Optional[str] = Field(description="Price info if mentioned, e.g. '$', '$18 pizza', 'free'.")
    tips: Optional[str] = Field(description="Practical tips: reservations, best time, lines, cash only.")
    source: Literal["caption", "speech", "on_screen", "multiple"] = Field(
        description="Where in the reel the place was identified."
    )
    confidence: Literal["high", "medium", "low"]
    image_labels: list[str] = Field(
        description="Labels of up to 3 frames or slides, copied exactly (e.g. 'Slide 2', 'Frame at 12s'), that "
        "clearly show this place itself: storefront, sign, interior, view or its food. Empty if none do."
    )


class ExtractionResult(BaseModel):
    title: str = Field(description="Short title for this reel, e.g. 'Best pizza in NYC'.")
    destination_city: Optional[str]
    destination_country: Optional[str]
    summary: str
    places: list[ExtractedPlace]


# ---------- Jobs API ----------


class JobStatus(str, Enum):
    queued = "queued"
    downloading = "downloading"
    transcribing = "transcribing"
    analyzing = "analyzing"
    done = "done"
    failed = "failed"


class CreateJobRequest(BaseModel):
    url: str = ""
    # Text the share sheet passed along (TikTok/IG often include the caption with the link).
    shared_text: Optional[str] = None


class ReelMetadata(BaseModel):
    platform: str
    url: str
    title: Optional[str] = None
    caption: Optional[str] = None
    uploader: Optional[str] = None
    thumbnail_url: Optional[str] = None
    duration_seconds: Optional[float] = None


class Job(BaseModel):
    id: str
    url: str
    status: JobStatus
    message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    reel: Optional[ReelMetadata] = None
    result: Optional[ExtractionResult] = None
    warnings: list[str] = []
    # Set once the places are saved to the library.
    trip_id: Optional[str] = None
    added_places: int = 0


# ---------- Itinerary planning ----------


class PlanPlace(BaseModel):
    id: str
    name: str
    category: PlaceCategory
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    neighborhood: Optional[str] = None
    notes: Optional[str] = None
    opening_hours: Optional[str] = None


class PlanRequest(BaseModel):
    city: str
    days: int = Field(ge=1, le=21)
    start_date: Optional[date] = None
    preferences: Optional[str] = None
    places: list[PlanPlace] = Field(min_length=1, max_length=200)


class TimeOfDay(str, Enum):
    morning = "morning"
    lunch = "lunch"
    afternoon = "afternoon"
    dinner = "dinner"
    evening = "evening"


class PlannedStop(BaseModel):
    place_id: str
    time_of_day: TimeOfDay
    note: Optional[str] = Field(description="Short tip for this stop, e.g. 'Go early to beat the line'.")


class PlannedDay(BaseModel):
    day_number: int
    title: str = Field(description="Theme for the day, e.g. 'West Village & SoHo'.")
    stops: list[PlannedStop]


class PlanResult(BaseModel):
    days: list[PlannedDay]
    unscheduled_place_ids: list[str] = Field(
        description="Places that didn't fit, e.g. too many for the number of days."
    )
    notes: Optional[str] = None


# ---------- Library (what the web app shows) ----------


class Place(BaseModel):
    id: str
    trip_id: str
    reel_id: Optional[str] = None
    name: str
    category: PlaceCategory
    summary: str = ""
    recommended_items: list[str] = []
    price_hint: Optional[str] = None
    tips: Optional[str] = None
    user_notes: str = ""
    confidence: str = "high"
    visited: bool = False
    neighborhood: Optional[str] = None
    address: Optional[str] = None
    city: str = ""
    country: str = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    maps_url: Optional[str] = None
    resolved_name: Optional[str] = None
    day_number: Optional[int] = None
    day_order: int = 0
    time_of_day: Optional[TimeOfDay] = None
    day_note: Optional[str] = None
    opening_hours: Optional[OpeningHours] = None
    hours_checked_at: Optional[datetime] = None
    photos: list[PlacePhoto] = []
    photos_checked_at: Optional[datetime] = None
    created_at: datetime


class Reel(BaseModel):
    id: str
    url: str
    platform: str
    title: str
    summary: str = ""
    caption: Optional[str] = None
    creator: Optional[str] = None
    thumbnail_url: Optional[str] = None
    trip_id: Optional[str] = None
    imported_at: datetime
    place_count: int = 0


class Trip(BaseModel):
    id: str
    name: str
    city: str
    country: str = ""
    created_at: datetime
    start_date: Optional[date] = None
    day_count: int = 0
    day_titles: list[str] = []
    plan_notes: Optional[str] = None
    planned_by: Optional[str] = None
    place_count: int = 0
    mapped_count: int = 0
    categories: list[PlaceCategory] = []


class TripDetail(Trip):
    places: list[Place] = []
    reels: list[Reel] = []


class TripUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    start_date: Optional[date] = None


class PlaceUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    category: Optional[PlaceCategory] = None
    visited: Optional[bool] = None
    user_notes: Optional[str] = Field(default=None, max_length=5000)
    # Use 0 to unschedule.
    day_number: Optional[int] = Field(default=None, ge=0, le=21)
    time_of_day: Optional[TimeOfDay] = None
    clear_time_of_day: bool = False


class PlanTripRequest(BaseModel):
    days: int = Field(ge=1, le=21)
    start_date: Optional[date] = None
    preferences: Optional[str] = Field(default=None, max_length=1000)


class ReorderRequest(BaseModel):
    place_ids: list[str]


class LocateRequest(BaseModel):
    # Optional better search text, e.g. "Joe's Pizza Carmine St".
    query: Optional[str] = Field(default=None, max_length=300)


# ---------- Travel times ----------


class TravelMode(str, Enum):
    walk = "walk"
    transit = "transit"
    drive = "drive"
    bike = "bike"


class TravelTime(BaseModel):
    duration_s: int
    distance_m: int
    # True when computed from straight-line distance instead of a real route.
    estimated: bool = False


class Leg(BaseModel):
    from_place_id: Optional[str] = None  # None = your current location
    to_place_id: str
    times: dict[TravelMode, Optional[TravelTime]]


class DayLegs(BaseModel):
    day: int
    provider: str  # "google" or "estimate"
    legs: list[Leg]


class Coordinates(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class RoutesFromRequest(Coordinates):
    place_ids: list[str] = Field(min_length=1, max_length=50)


class RoutesFromResponse(BaseModel):
    provider: str
    legs: list[Leg]
