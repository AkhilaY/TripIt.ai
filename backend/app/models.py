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
    event = "event"
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
    category: PlaceCategory = Field(description="event is for a dated happening (a concert, show, festival, match, pop-up or limited exhibition); a venue itself takes its usual category.")
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
    event_date: Optional[date] = Field(default=None, description="For an event: the date it happens (or starts), resolving words like 'this Saturday' from the post date. Null when no date is given or for a regular place.")
    event_end_date: Optional[date] = Field(default=None, description="For a multi-day event (a pop-up running all week): the last day. Null otherwise.")
    event_time: Optional[str] = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$", description="For an event: its start time as 'HH:MM' (24 hour), or null.")
    venue: Optional[str] = Field(default=None, description="For an event: the venue or address where it happens, as you'd search for it on a map. Null otherwise.")
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
    posted_on: Optional[date] = None  # when the post went up, to resolve 'this Saturday'


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
    reel_id: Optional[str] = None  # the saved post, whose places are those with it in reel_ids
    user_id: Optional[str] = Field(default=None, exclude=True)  # whose import it is (not sent to the app)
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
    city: Optional[str] = None


class PlanCity(BaseModel):
    """One city of a multi-city trip and the days spent there."""
    city: str
    first_day: int
    last_day: int


class PlanRequest(BaseModel):
    city: str
    days: int = Field(ge=1, le=21)
    start_date: Optional[date] = None
    preferences: Optional[str] = None
    places: list[PlanPlace] = Field(min_length=1, max_length=200)
    route: list[PlanCity] = []  # filled in for multi-city trips


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


# ---------- Bookings ----------

BookingKind = Literal["flight", "hotel", "reservation", "tour", "car", "other"]
# Local wall-clock time as printed on the booking, with no time zone: a flight leaves and lands in different ones.
BOOKING_TIME = r"^\d{4}-\d{2}-\d{2}(T([01]\d|2[0-3]):[0-5]\d)?$"


class Booking(BaseModel):
    id: str
    trip_id: str
    kind: BookingKind
    title: str  # flight number, hotel, restaurant or rental company
    start_at: Optional[str] = None  # "YYYY-MM-DD" or "YYYY-MM-DDTHH:MM": departure, check-in, table time, pick-up
    end_at: Optional[str] = None  # arrival, check-out, drop-off
    origin: Optional[str] = None
    destination: Optional[str] = None
    address: Optional[str] = None
    confirmation: Optional[str] = None
    party_size: Optional[int] = None
    notes: Optional[str] = None
    place_id: Optional[str] = None  # the saved place a table reservation is for
    source: Literal["manual", "screenshot", "text", "reserve"] = "manual"
    created_at: datetime


class BookingListItem(Booking):
    """A booking with the trip it belongs to, for the Bookings tab."""
    trip_name: str
    trip_kind: Literal["trip", "local"] = "trip"


class BookingInput(BaseModel):
    kind: Optional[BookingKind] = None
    title: Optional[str] = Field(default=None, min_length=1, max_length=160)
    start_at: Optional[str] = Field(default=None, pattern=BOOKING_TIME)
    end_at: Optional[str] = Field(default=None, pattern=BOOKING_TIME)
    origin: Optional[str] = Field(default=None, max_length=80)
    destination: Optional[str] = Field(default=None, max_length=80)
    address: Optional[str] = Field(default=None, max_length=300)
    confirmation: Optional[str] = Field(default=None, max_length=60)
    party_size: Optional[int] = Field(default=None, ge=1, le=100)
    notes: Optional[str] = Field(default=None, max_length=2000)
    place_id: Optional[str] = Field(default=None, max_length=40)
    source: Optional[Literal["manual", "screenshot", "text", "reserve"]] = None


class BookingDraft(BaseModel):
    """What Claude read from a confirmation; the person checks it before it is saved."""
    kind: BookingKind
    title: str = Field(description="Flight number like 'BA 178', the hotel's or restaurant's name, or the rental company.")
    start_at: Optional[str] = Field(description="Departure, check-in, table time or pick-up as 'YYYY-MM-DDTHH:MM' (local time, 24 hour), or 'YYYY-MM-DD' when there is no time. Null if not shown.")
    end_at: Optional[str] = Field(description="Arrival, check-out or drop-off in the same format, or null.")
    origin: Optional[str] = Field(description="Departure airport (IATA code if shown) or pick-up location, or null.")
    destination: Optional[str] = Field(description="Arrival airport or drop-off location, or null.")
    address: Optional[str] = Field(description="Street address of the hotel, restaurant or rental office, or null.")
    confirmation: Optional[str] = Field(description="Confirmation or booking reference exactly as printed, or null.")
    party_size: Optional[int] = Field(description="Guests for a restaurant table, or null.")
    notes: Optional[str] = Field(description="Terminal, seat, room type, check-in instructions or similar, briefly, or null.")


class BookingsResult(BaseModel):
    bookings: list[BookingDraft]


class ReadBookingsRequest(BaseModel):
    text: Optional[str] = Field(default=None, max_length=20000)
    images: list[str] = Field(default=[], max_length=6, description="Base64 JPEG images (data: URLs are fine).")


# ---------- Home city and discovering ----------


class HomeSetting(BaseModel):
    city: str
    country: str = ""
    latitude: float
    longitude: float


class HomeRequest(BaseModel):
    city: str = Field(min_length=1, max_length=120)


DiscoverKind = Literal["restaurants", "coffee", "bars", "dessert", "things"]


class DiscoverItem(BaseModel):
    id: str  # "google:<place id>": the same id the add-a-place search uses
    name: str
    kind_label: Optional[str] = None  # "Italian restaurant"
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    rating: Optional[float] = None
    rating_count: Optional[int] = None
    price_level: Optional[int] = None  # 1 to 4
    maps_url: Optional[str] = None
    photo: Optional[str] = None  # a signed link served by this server
    distance_m: Optional[int] = None
    award: Optional[str] = None  # e.g. "Michelin star": from Claude's knowledge, to be checked
    why: Optional[str] = None
    saved: bool = False


class DiscoverArea(BaseModel):
    name: str
    latitude: float
    longitude: float


class DiscoverResult(BaseModel):
    status: Literal["ok", "disabled", "no_area", "error"]
    area: Optional[DiscoverArea] = None
    kind: DiscoverKind = "restaurants"
    items: list[DiscoverItem] = []
    curated_by: Optional[Literal["claude", "offline"]] = None
    fetched_at: Optional[datetime] = None


class DiscoverNote(BaseModel):
    id: str
    award: Optional[str] = Field(description="Only when you are confident this exact venue holds it: 'Michelin 1 star', 'Michelin 2 stars', 'Bib Gourmand', 'Michelin Guide', 'James Beard', '50 Best Bars'. Otherwise null. Never guess.")
    why: str = Field(description="One line, under 16 words, on why it suits this traveller, naming the taste or habit it fits.")


class DiscoverNotes(BaseModel):
    notes: list[DiscoverNote]


# ---------- Booking needs ----------


class Lounge(BaseModel):
    name: str = Field(description="The lounge's name as travellers know it, e.g. 'The Centurion Lounge'.")
    terminal: Optional[str] = Field(description="Terminal or concourse, e.g. 'Terminal 4', or null if not sure.")
    location: Optional[str] = Field(description="Where in the terminal, e.g. 'Airside, near gate B22, level 2', under 14 words, or null.")
    access: list[str] = Field(description="Ways in, each under 12 words: 'Priority Pass', 'Amex Platinum card holders', 'Business class on Delta', 'Day pass about $50', 'Oneworld Emerald/Sapphire'. Only ones you are confident of.")
    hours: Optional[str] = Field(description="Typical opening hours like '5:00-22:00', or null if not sure.")


Day = date  # the field below is called "date"


class CalendarItem(BaseModel):
    """One dated thing on the calendar: a saved event, a booking, a planned stop, or a trip's span of days."""
    id: str  # "event:<place id>", "booking:<id>", "stop:<place id>", "trip:<id>"
    kind: Literal["event", "booking", "stop", "trip"]
    title: str
    date: Optional[Day] = None  # None for an event with no date yet
    end_date: Optional[Day] = None  # last day, for multi-day items
    time: Optional[str] = None  # "HH:MM" local
    end_time: Optional[str] = None
    part_of_day: Optional[str] = None  # a planned stop's time of day when it has no exact time
    subtitle: Optional[str] = None
    category: Optional[str] = None  # the place's category, or the booking's kind
    place_id: Optional[str] = None
    trip_id: Optional[str] = None
    booking_id: Optional[str] = None
    google_url: Optional[str] = None  # opens Google Calendar with this item filled in
    ics_url: Optional[str] = None  # a signed .ics link for Apple Calendar and others


class CalendarFeed(BaseModel):
    url: str  # https link to the .ics feed
    webcal_url: str  # opens Apple Calendar's subscribe prompt
    google_url: str  # opens Google Calendar's "add by URL"


class CalendarResult(BaseModel):
    items: list[CalendarItem]
    undated: list[CalendarItem]  # saved events with no date yet
    feed: Optional[CalendarFeed] = None


class LoungeList(BaseModel):
    airport_name: Optional[str] = Field(description="Full name of the airport, or null if the code or name is not a real airport.")
    lounges: list[Lounge] = Field(description="Up to 8 lounges at this airport that you are confident exist. Empty when unsure; never invent one.")


class LoungeResult(BaseModel):
    status: Literal["ok", "no_airport", "error"]
    airport: Optional[str] = None
    airport_name: Optional[str] = None
    lounges: list[Lounge] = []
    checked_at: Optional[str] = None


class BookingNeedItem(BaseModel):
    id: str
    kind: Literal["reservation", "tickets", "none"] = Field(description="reservation for a table at a restaurant, bar or cafe; tickets for entry to an attraction, show or activity; none when you can simply walk in or enter free.")
    need: Literal["required", "recommended", "none", "unknown"] = Field(description="required: you usually can't get in without booking ahead; recommended: booking ahead is wise; none: walk-ins are normal; unknown: you can't tell.")
    note: Optional[str] = Field(description="Under 12 words, e.g. 'Books out weeks ahead' or 'Timed tickets; buy online'. Null when there is nothing useful to add.")


class BookingNeedResult(BaseModel):
    items: list[BookingNeedItem]


# ---------- Events ----------

EventCategory = Literal["music", "arts", "sports", "family", "other"]


class EventItem(BaseModel):
    id: str
    name: str
    url: str  # the event's page on Ticketmaster, where tickets are bought
    image: Optional[str] = None
    start_at: str  # local "YYYY-MM-DDTHH:MM", or "YYYY-MM-DD" when the time isn't set
    status: Literal["onsale", "postponed", "rescheduled", "unknown"] = "unknown"
    venue: Optional[str] = None
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    category: EventCategory = "other"
    genre: Optional[str] = None
    price_min: Optional[float] = None
    price_max: Optional[float] = None
    currency: Optional[str] = None
    day: Optional[int] = None  # trip day, when the trip has dates
    match: bool = False  # fits the person's taste
    why: Optional[str] = None


class TripEvents(BaseModel):
    status: Literal["ok", "disabled", "no_dates", "no_location", "error"]
    events: list[EventItem] = []
    fetched_at: Optional[datetime] = None
    source: str = "Ticketmaster"
    curated_by: Optional[Literal["claude", "offline"]] = None


class EventNote(BaseModel):
    id: str
    why: str = Field(description="One line, under 16 words, on why this event suits this traveller, in a warm, polished voice. Mention the taste it matches.")


class EventNotes(BaseModel):
    notes: list[EventNote]


# ---------- Packing ----------

PackingGroup = Literal["clothes", "shoes", "toiletries", "tech", "documents", "daybag", "other"]


class WeatherDay(BaseModel):
    day: int  # trip day, from 1
    date: str  # YYYY-MM-DD
    summary: str  # "Light rain", "Sunny", ...
    temp_min: float  # degrees Celsius
    temp_max: float
    rain_chance: Optional[int] = None  # percent; known for forecasts only
    source: Literal["forecast", "typical"]  # typical = the same dates last year


class PackingDraftItem(BaseModel):
    text: str = Field(description="The thing to pack, with a quantity when it matters: '5 tops', 'Compact umbrella'.")
    group: PackingGroup
    reason: Optional[str] = Field(description="Why it's on this trip's list, under 14 words, tied to the weather, a stop or a day. Null for obvious basics.")
    days: list[int] = Field(description="Trip days (from 1) when it matters, for rain gear or an outfit for one evening. Empty when it applies to the whole trip.")
    day_bag: bool = Field(description="True when it goes in the bag carried out each day (umbrella, sunscreen, scarf for a temple, charger).")


class PackingResult(BaseModel):
    items: list[PackingDraftItem]
    notes: Optional[str] = Field(description="One short line on the trip's conditions and what they mean for packing, or null.")


class PackingItem(BaseModel):
    id: str
    text: str
    group: PackingGroup = "other"
    reason: Optional[str] = None
    days: list[int] = []
    day_bag: bool = False
    packed: bool = False
    unused: bool = False  # marked after the trip: left out of future lists
    custom: bool = False  # added by the person, kept when the list is made again


class PackingList(BaseModel):
    trip_id: str
    items: list[PackingItem]
    weather: list[WeatherDay] = []
    notes: Optional[str] = None
    carry_on_only: bool = False
    generated_by: Literal["claude", "offline", "manual"] = "offline"
    generated_at: datetime


class PackingStart(BaseModel):
    """Start a list without AI: empty, from pasted text (one item per line), or copied from another trip."""
    text: Optional[str] = Field(default=None, max_length=20000)
    copy_from: Optional[str] = None  # another trip's id


class PackingRequest(BaseModel):
    carry_on_only: Optional[bool] = None
    keep_packed: bool = True


class PackingItemInput(BaseModel):
    text: Optional[str] = Field(default=None, min_length=1, max_length=120)
    group: Optional[PackingGroup] = None
    packed: Optional[bool] = None
    unused: Optional[bool] = None


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
    source_kind: Optional[Literal["website", "photos", "upload"]] = None
    source_url: Optional[str] = None  # the page or file the menu was read from
    fetched_at: Optional[datetime] = None
    trace: list[str] = []  # what the last lookup tried, so a miss can be understood


class PickedLinks(BaseModel):
    numbers: list[int] = Field(description="The numbers of the links to open, best first, at most 6.")


class MenuUploadRequest(BaseModel):
    images: list[str] = Field(default=[], max_length=6, description="Base64 JPEGs (data: URLs are fine).")
    pdfs: list[str] = Field(default=[], max_length=2, description="Base64 PDF files.")


class MenuRequest(BaseModel):
    refresh: bool = False


# ---------- Library (what the web app shows) ----------


class Place(BaseModel):
    id: str
    trip_id: Optional[str] = None  # the trip it is shown in, when read as a trip stop
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
    trip_ids: list[str] = []  # trips this place is a stop on
    folder_ids: list[str] = []  # folders it is filed in
    saved: bool = True  # False for a place an AI plan suggested that you haven't kept
    suggested: bool = False  # on this trip: added by the planner to fill a quiet day
    suggestion_note: Optional[str] = None
    must_do: bool = False  # shown as a star: starred places rank first everywhere
    start_time: Optional[str] = None  # "HH:MM" local time, e.g. a reservation or an event's start
    event_date: Optional[date] = None  # for an event: the day it happens (or starts)
    event_end_date: Optional[date] = None  # for a multi-day event: the last day
    venue: Optional[str] = None  # for an event: where it happens
    rating: Optional[float] = None  # Google's rating out of 5, when the place was found there
    rating_count: Optional[int] = None
    rating_checked_at: Optional[datetime] = None
    booking_kind: Optional[Literal["reservation", "tickets"]] = None  # what a visit needs booking: a table or entry tickets
    booking_need: Optional[Literal["required", "recommended"]] = None  # None = no booking needed, or not known
    booking_note: Optional[str] = None
    booking_checked_at: Optional[datetime] = None
    reserve_url: Optional[str] = None  # the restaurant's own page on Resy, OpenTable, Tock or SevenRooms
    reserve_provider: Optional[str] = None
    reserve_checked_at: Optional[datetime] = None
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


TravelMode = Literal["train", "flight", "drive", "bus", "ferry", "walk", "other"]


class TripStop(BaseModel):
    """One city on a trip's route, in order. Stops cover the trip's days back to back."""
    city: str
    country: str = ""
    days: int = 1
    start_day: int = 1
    end_day: int = 1
    travel_mode: Optional[TravelMode] = None  # how you get here from the stop before
    travel_minutes: Optional[int] = None
    travel_note: Optional[str] = None  # e.g. "Eurostar from St Pancras"


class TripStopIn(BaseModel):
    city: str = Field(min_length=1, max_length=120)
    country: Optional[str] = Field(default=None, max_length=80)
    days: int = Field(ge=1, le=21)
    travel_mode: Optional[TravelMode] = None
    travel_minutes: Optional[int] = Field(default=None, ge=0, le=3000)
    travel_note: Optional[str] = Field(default=None, max_length=120)


class TripStopsRequest(BaseModel):
    stops: list[TripStopIn] = Field(min_length=1, max_length=12)


class Trip(BaseModel):
    id: str
    name: str
    city: str
    country: str = ""
    kind: Literal["trip", "local"] = "trip"  # local = places in your home city: no dates, itinerary or packing
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
    stops: list[TripStop] = []  # the route; one stop (the trip's city) until you add more
    role: Literal["owner", "editor"] = "owner"  # yours, or one you were invited to plan
    member_count: int = 0  # people planning it with the owner


class TripMember(BaseModel):
    user_id: str
    name: str
    role: Literal["owner", "editor"]
    you: bool = False


class JoinPreview(BaseModel):
    """What an invite link shows before you join: whose trip, where and when."""
    trip_name: str
    city: str
    start_date: Optional[date] = None
    day_count: int = 0
    owner_name: str
    people: int = 1


class TripClosure(BaseModel):
    """A place planned on a day it's closed, and the nearest day in the same city it's open."""
    place_id: str
    day: int
    message: str  # "Closed on Sundays"
    move_to_day: Optional[int] = None
    move_to_label: Optional[str] = None  # "Mon"


class ScheduledStop(BaseModel):
    """When a stop happens on its day: its exact time, or an estimate from the stops before it."""
    place_id: str
    day: int
    time: str  # "HH:MM"
    estimated: bool = True


class TripDetail(Trip):
    places: list[Place] = []
    reels: list[Reel] = []
    bookings: list[Booking] = []
    closures: list[TripClosure] = []  # filled in when the trip has a start date
    schedule: list[ScheduledStop] = []  # a realistic time for each planned stop
    members: list[TripMember] = []  # everyone planning it, the owner first (only once someone's been invited)

    def day_places(self, day: int) -> list[Place]:
        return sorted((p for p in self.places if p.day_number == day), key=lambda p: p.day_order)


class TripUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    kind: Optional[Literal["trip", "local"]] = None
    start_date: Optional[date] = None


class PlaceSuggestion(BaseModel):
    name: str = Field(description="The place's real name as you'd type it into a maps search.")
    category: PlaceCategory
    neighborhood: Optional[str] = Field(description="Neighbourhood, to help find it on the map, or null.")
    day: int = Field(description="Which quiet day it goes on.")
    time_of_day: Optional[TimeOfDay] = Field(description="When in the day it fits best, or null.")
    why: str = Field(description="Under 14 words on why it fits this person and this day.")


class SuggestionResult(BaseModel):
    suggestions: list[PlaceSuggestion]


class PlaceDetail(BaseModel):
    place: Place
    reels: list["Reel"] = []  # the posts that recommended it


class Folder(BaseModel):
    id: str
    name: str
    created_at: datetime
    place_count: int = 0
    covers: list[PlacePhoto] = []  # up to four photos from its places


class FolderInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    place_ids: list[str] = Field(default=[], max_length=500)


class FolderRename(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class PlaceIds(BaseModel):
    place_ids: list[str] = Field(min_length=1, max_length=500)


class NewTripRequest(BaseModel):
    """A trip made on purpose: a city, a length, the saved places to go to, and who plans it."""
    city: str = Field(min_length=1, max_length=120)
    name: Optional[str] = Field(default=None, max_length=120)
    country: Optional[str] = Field(default=None, max_length=80)
    days: int = Field(default=3, ge=1, le=21)
    start_date: Optional[date] = None
    place_ids: list[str] = Field(default=[], max_length=500)
    plan: Literal["ai", "manual"] = "manual"
    fill_gaps: bool = False  # AI only: suggest a few well-rated places for quiet days
    preferences: Optional[str] = Field(default=None, max_length=1000)


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
    website: Optional[str] = Field(default=None, max_length=500)  # "" clears it
    trip_id: Optional[str] = None  # which trip day_number / time_of_day / start_time refer to
    event_date: Optional[date] = None
    event_end_date: Optional[date] = None
    clear_event_date: bool = False


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
    city: Optional[str] = Field(default=None, max_length=120)  # or in this city (a city page)


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
    trip_id: Optional[str] = None  # also add it to this trip
    folder_id: Optional[str] = None  # also file it in this folder


class AddFromLinkRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2000)
    trip_id: Optional[str] = None
    folder_id: Optional[str] = None


class AddPlaceResult(BaseModel):
    place: Place
    created: bool  # False when you'd already saved a place with that name


class ScreenshotJobRequest(BaseModel):
    images: list[str] = Field(min_length=1, max_length=10, description="Base64 JPEG images (data: URLs are fine).")
    note: Optional[str] = Field(default=None, max_length=2000)


class PushSubscriptionRequest(BaseModel):
    endpoint: str = Field(max_length=2000)
    keys: dict[str, str] = {}


class InviteLink(BaseModel):
    token: str
    path: str  # "/join/<token>", relative to the app's address


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
    place_id: Optional[str] = Field(default=None, description="The id of one of the traveler's saved places, or null for a place from the articles.")
    name: Optional[str] = Field(default=None, description="For a place from the articles: its name as the article gives it. Null for a saved place.")
    category: Optional[PlaceCategory] = Field(default=None, description="For a place from the articles: its kind. Null for a saved place.")
    neighborhood: Optional[str] = Field(default=None, description="For a place from the articles: its neighbourhood, if known. Null otherwise.")
    source: Optional[int] = Field(default=None, description="For a place from the articles: the number of the article that recommends it. Null for a saved place.")
    note: str = Field(description="One line, under 20 words, on why it belongs in this edit, in a polished editorial voice.")


class CuratedEdit(BaseModel):
    title: str = Field(description="Magazine-style title, e.g. 'The Date Night Edit' or 'One Perfect Afternoon in Soho'.")
    dek: str = Field(description="A one-sentence standfirst under the title, like a magazine subheading.")
    entries: list[EditEntry] = Field(description="4 to 8 places, in the order to read or visit them.")


class EditsResult(BaseModel):
    edits: list[CuratedEdit] = Field(description="3 to 6 edits.")


class EditSource(BaseModel):
    name: str  # "Eater", "Time Out", "@eatsbyjune on TikTok", "Your saved places"
    title: Optional[str] = None  # the article or post
    url: Optional[str] = None


class EditItem(BaseModel):
    """One place in an edit: one of your saved places, or one a publication recommends that you can save."""
    id: str
    place_id: Optional[str] = None  # set when it's in your saved places
    saved: bool = False
    name: str
    category: PlaceCategory = PlaceCategory.other
    neighborhood: Optional[str] = None
    city: Optional[str] = None
    note: str = ""
    source: Optional[EditSource] = None
    photo: Optional[PlacePhoto] = None
    rating: Optional[float] = None
    rating_count: Optional[int] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    maps_url: Optional[str] = None


class TripEdit(BaseModel):
    id: str
    title: str
    dek: str
    entries: list[EditItem] = []
    cover_photo: Optional[PlacePhoto] = None
    folder_id: Optional[str] = None  # set once the whole edit is saved to the Library
    new_count: int = 0  # places in it that aren't in your saved places yet


class CoverPick(BaseModel):
    number: int = Field(description="The number of the photo that makes the best cover.")
    reason: str = Field(description="Under 12 words on why.")


class TripEdits(BaseModel):
    trip_id: str
    trip_name: str = ""
    edits: list[TripEdit] = []
    curated_by: Optional[str] = None  # "claude", "claude+web" or "offline"; None until first curated
    created_at: Optional[datetime] = None
    stale: bool = False  # a day old, or your places changed since
    refreshing: bool = False  # a new set is being made in the background


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


PlaceDetail.model_rebuild()
