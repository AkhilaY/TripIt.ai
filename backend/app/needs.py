"""Whether a place needs a reservation or tickets, so the places list can say so up front.

Claude judges from what it knows of the place, its type, and any tip from the video that mentioned it. It's a
guide, not a promise: places it can't place are left unmarked rather than guessed at.
"""

import logging
from datetime import datetime, timezone

from .db import Database
from .llm import ClaudeError, ClaudeService
from .models import TripDetail

log = logging.getLogger(__name__)

BATCH = 40
# Types that never need booking, so they're marked as checked without asking.
NO_BOOKING = {"stay", "shopping", "dessert"}


class NeedsService:
    def __init__(self, db: Database, claude: ClaudeService):
        self.db = db
        self.claude = claude

    async def check(self, trip: TripDetail) -> int:
        """Fills in booking_need for places in the trip that haven't been looked at. Returns how many were checked."""
        now = datetime.now(timezone.utc)
        pending = [p for p in trip.places if p.booking_checked_at is None]
        for p in [p for p in pending if p.category.value in NO_BOOKING]:
            self.db.update_place(p.id, booking_checked_at=now)
        asked = [p for p in pending if p.category.value not in NO_BOOKING][:BATCH]
        if not asked:
            return len(pending)
        payload = [{k: v for k, v in {"id": p.id, "name": p.name, "type": p.category.value, "city": p.city, "area": p.neighborhood,
                                      "tip_from_video": (p.tips or p.summary or "")[:200] or None}.items() if v} for p in asked]
        result = await self.claude.booking_needs(payload)  # a ClaudeError leaves them unchecked, to try again later
        by_id = {i.id: i for i in result.items}
        for p in asked:
            item = by_id.get(p.id)
            if item is None or item.need == "unknown":
                self.db.update_place(p.id, booking_checked_at=now)
                continue
            need = item.need if item.need in ("required", "recommended") and item.kind != "none" else None
            self.db.update_place(
                p.id, booking_kind=item.kind if need else None, booking_need=need,
                booking_note=" ".join((item.note or "").split())[:100] or None if need else None, booking_checked_at=now,
            )
        return len(pending)
