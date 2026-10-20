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
    must_do: bool = False
    mentions: int = 1  # how many saved reels recommend it
    start_time: Optional[str] = None  # a fixed time, e.g. a reservation ("HH:MM")
    current_day: Optional[int] = None  # the day the person already put it on, if any


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


# ---------- Menus ----------

MenuTag = Literal["vegetarian", "vegan", "gluten_free", "spicy"]


class MenuItem(BaseModel):
    name: str
    description: Optional[str] = Field(description="Ingredients or a short description as printed, or null.")
    price: Optional[str] = Field(description="The price exactly as printed, e.g. '$14' or '9 / 12', or null.")
    tags: list[MenuTag] = Field(description="Only dietary or spice marks the menu itself shows (e.g. a V or a chili symbol).")


class MenuSection(BaseModel):
    title: str = Field(description="Section heading as printed, e.g. 'Starters' or 'Cocktails'.")
    note: Optional[str] = Field(description="A line printed under the heading, e.g. 'Served with fries', or null.")
    items: list[MenuItem]


class MenuResult(BaseModel):
    found: bool = Field(description="False when the material has no menu of food or drinks.")
    sections: list[MenuSection]
    notes: Optional[str] = Field(description="Anything that applies to the whole menu, e.g. 'Dinner menu, Tue-Sun 5-10pm'.")


class PlaceMenu(BaseModel):
    status: Literal["unknown", "found", "none"] = "unknown"  # unknown = never looked for
    sections: list[MenuSection] = []
    notes: Optional[str] = None
    source_kind: Optional[Literal["website", "photos"]] = None
    source_url: Optional[str] = None  # the page or file the menu was read from
    fetched_at: Optional[datetime] = None


class MenuRequest(BaseModel):
    refresh: bool = False


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
    must_do: bool = False  # shown as a star: starred places rank first everywhere
    start_time: Optional[str] = None  # "HH:MM" local time, e.g. a reservation
    rating: Optional[float] = None  # Google's rating out of 5, when the place was found there
    rating_count: Optional[int] = None
    rating_checked_at: Optional[datetime] = None
    website: Optional[str] = None
    phone: Optional[str] = None
    contact_checked_at: Optional[datetime] = None
    # Every saved reel that recommends this place (reel_id is the first one).
    reel_ids: list[str] = []
    mention_count: int = 0
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
    cover_photo: Optional[PlacePhoto] = None
    share_token: Optional[str] = None  # set while a public link to the trip exists


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
    must_do: Optional[bool] = None
    start_time: Optional[str] = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    clear_start_time: bool = False


class PlanTripRequest(BaseModel):
    days: int = Field(ge=1, le=21)
    start_date: Optional[date] = None
    preferences: Optional[str] = Field(default=None, max_length=1000)


class ReorderRequest(BaseModel):
    place_ids: list[str]


class MoveRequest(BaseModel):
    place_id: str
    day: int = Field(ge=0, le=21)  # 0 = not scheduled
    index: int = Field(default=0, ge=0)


class AddToDayRequest(BaseModel):
    place_ids: list[str] = Field(min_length=1, max_length=100)
    day: Optional[int] = Field(default=None, ge=1, le=21)  # None = a new day at the end


class TidyRequest(BaseModel):
    instruction: Optional[str] = Field(default=None, max_length=500)  # e.g. "make day 2 more relaxed"


class SearchPlacesRequest(BaseModel):
    query: str = Field(min_length=1, max_length=300)
    trip_id: Optional[str] = None  # search near this trip's places


class PlaceCandidate(BaseModel):
    candidate_id: str  # pass back to POST /v1/places
    name: str
    address: Optional[str] = None
    category: PlaceCategory = PlaceCategory.other
    latitude: float
    longitude: float


class AddPlaceRequest(BaseModel):
    """Add a search result (candidate_id) or a place by name (name + trip_id or city)."""
    candidate_id: Optional[str] = Field(default=None, max_length=300)
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    city: Optional[str] = Field(default=None, max_length=120)
    category: PlaceCategory = PlaceCategory.other
    trip_id: Optional[str] = None


class AddFromLinkRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2000)
    trip_id: Optional[str] = None


class AddPlaceResult(BaseModel):
    place: Place
    created: bool  # False when the trip already had a place with that name


class ScreenshotJobRequest(BaseModel):
    images: list[str] = Field(min_length=1, max_length=10, description="Base64 JPEG images (data: URLs are fine).")
    note: Optional[str] = Field(default=None, max_length=2000)


class PushSubscriptionRequest(BaseModel):
    endpoint: str = Field(max_length=2000)
    keys: dict[str, str] = {}


class ShareLink(BaseModel):
    token: str
    path: str  # "/s/<token>", relative to the app's address


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


# ---------- Taste profile, curated edits, concierge, briefings ----------


class TasteProfile(BaseModel):
    pace: Optional[Literal["slow", "balanced", "packed"]] = None
    budget: Optional[Literal["value", "mix", "splurge"]] = None
    food: list[str] = Field(default=[], max_length=12)
    interests: list[str] = Field(default=[], max_length=12)
    mornings: Optional[Literal["early", "late"]] = None
    notes: Optional[str] = Field(default=None, max_length=500)  # "vegetarian, travelling with a toddler"
    updated_at: Optional[datetime] = None


class EditEntry(BaseModel):
    place_id: str
    note: str = Field(description="One line, under 20 words, on why it belongs in this edit, in a polished editorial voice.")


class CuratedEdit(BaseModel):
    title: str = Field(description="Magazine-style title, e.g. 'The Date Night Edit' or 'One Perfect Afternoon in Soho'.")
    dek: str = Field(description="A one-sentence standfirst under the title, like a magazine subheading.")
    entries: list[EditEntry] = Field(description="3 to 8 saved places, in the order to read or visit them.")


class EditsResult(BaseModel):
    edits: list[CuratedEdit] = Field(description="3 to 6 edits.")


class TripEdit(CuratedEdit):
    id: str
    cover_photo: Optional[PlacePhoto] = None


class TripEdits(BaseModel):
    trip_id: str
    trip_name: str = ""
    edits: list[TripEdit] = []
    curated_by: Optional[str] = None  # "claude" or "offline"; None until first curated
    created_at: Optional[datetime] = None
    stale: bool = False  # places were added or removed since


class ConciergeMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ConciergeRequest(BaseModel):
    trip_id: Optional[str] = None
    messages: list[ConciergeMessage] = Field(min_length=1, max_length=40)
    local_time: Optional[str] = Field(default=None, max_length=40)  # the phone's clock, e.g. "2026-10-19T14:05"
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)


class ProposedAction(BaseModel):
    type: Literal["move", "must_do", "set_time", "visited"]
    place_id: str
    day: Optional[int] = Field(description="For move: the day number, or 0 to take it off the plan. Otherwise null.")
    index: Optional[int] = Field(description="For move: 0-based position within the day, or null for the end.")
    value: Optional[bool] = Field(description="For must_do and visited: true or false. Otherwise null.")
    time: Optional[str] = Field(description="For set_time: 'HH:MM' (24h), or '' to clear. Otherwise null.")
    label: str = Field(description="Short description shown on the confirm button, e.g. 'Move Lucali to Day 2'.")


class ConciergeReply(BaseModel):
    reply: str = Field(description="Your answer: warm, polished and concise (under 120 words unless asked for more). Plain text, short paragraphs, no markdown.")
    place_ids: list[str] = Field(description="Saved places to show as cards under the answer, most relevant first. Empty if none apply.")
    actions: list[ProposedAction] = Field(description="Changes to propose. The traveler confirms before anything changes. Empty unless they asked for a change.")


class BriefingRequest(BaseModel):
    local_date: Optional[date] = None  # the phone's date; defaults to the trip day's date
    refresh: bool = False


class BriefingText(BaseModel):
    headline: str = Field(description="Under 8 words, e.g. 'Slow morning, then Williamsburg'.")
    points: list[str] = Field(description="2 to 4 short lines: how the day starts, anything closed or closing early, what to book or bring, one insider tip from the notes.")


class DayBriefing(BriefingText):
    trip_id: str
    day: int
    curated_by: str  # "claude" or "offline"
    created_at: datetime
