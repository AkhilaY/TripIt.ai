"""Airport lounges for the airport a flight departs from.

There is no free, reliable lounge feed, so this is Claude's knowledge: names, terminals and access rules it is
confident of. Lounges change often, so the app labels the result as a guide to check with the airport or the
card or programme before relying on it. Results are cached for three days.
"""

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from .db import Database
from .llm import ClaudeError, ClaudeService
from .models import LoungeResult

log = logging.getLogger(__name__)

FRESH_DAYS = 3
IATA = re.compile(r"\b([A-Z]{3})\b")


def airport_key(origin: Optional[str]) -> Optional[str]:
    """The airport as written on the booking: an IATA code when there is one, else the cleaned name."""
    text = " ".join((origin or "").split())[:80]
    if not text:
        return None
    code = IATA.search(text)
    return code.group(1) if code else text


class LoungeService:
    def __init__(self, db: Database, claude: Optional[ClaudeService]):
        self.db = db
        self.claude = claude

    async def lookup(self, origin: Optional[str], refresh: bool = False) -> LoungeResult:
        airport = airport_key(origin)
        if airport is None:
            return LoungeResult(status="no_airport")
        key = f"lounges:{airport.lower()}"
        row = self.db.get_discover(key)
        if row and not refresh and datetime.now(timezone.utc) - datetime.fromisoformat(row["created_at"]) < timedelta(days=FRESH_DAYS):
            return LoungeResult(**json.loads(row["data"]))
        if self.claude is None:
            return LoungeResult(status="error", airport=airport)
        try:
            found = await self.claude.lounges(airport)
        except ClaudeError as e:
            log.warning("Lounge lookup failed: %s", e)
            return LoungeResult(**json.loads(row["data"])) if row else LoungeResult(status="error", airport=airport)
        if not found.airport_name:
            return LoungeResult(status="no_airport", airport=airport)
        result = LoungeResult(status="ok", airport=airport, airport_name=found.airport_name[:100], checked_at=datetime.now(timezone.utc).isoformat(),
                              lounges=[l.model_copy(update={"access": [a[:80] for a in l.access][:6]}) for l in found.lounges[:8]])
        self.db.save_discover(key, result.model_dump())
        return result
