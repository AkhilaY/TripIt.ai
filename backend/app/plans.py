"""Free and Plus plans: the free plan has a few video saves a month, Plus (and the owner) has no limit."""
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel

from .db import Database

PLANS = ("free", "plus")


class PlanOut(BaseModel):
    plan: str  # "free" or "plus"
    video_saves_used: int
    video_saves_limit: Optional[int] = None  # None: no limit
    resets_at: str  # when the month's count starts again (ISO, UTC)


def _month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _next_month(now: datetime) -> datetime:
    start = _month_start(now)
    return start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)


def plan_for(db: Database, user_id: str, is_admin: bool, free_limit: int, now: Optional[datetime] = None) -> PlanOut:
    now = now or datetime.now(timezone.utc)
    plan = "plus" if is_admin else db.user_plan(user_id)
    unlimited = plan == "plus" or free_limit <= 0
    return PlanOut(
        plan=plan,
        video_saves_used=db.video_saves_since(user_id, _month_start(now).isoformat()),
        video_saves_limit=None if unlimited else free_limit,
        resets_at=_next_month(now).isoformat(),
    )


def out_of_saves(plan: PlanOut) -> bool:
    return plan.video_saves_limit is not None and plan.video_saves_used >= plan.video_saves_limit


def upgrade_message(plan: PlanOut) -> str:
    reset = datetime.fromisoformat(plan.resets_at).strftime("%B %-d")
    return (f"You've used your {plan.video_saves_limit} free video saves this month. "
            f"Upgrade to Plus for unlimited saves, or wait until {reset}.")
