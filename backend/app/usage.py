"""What the AI features cost, and the limits that keep that in check.

Every Claude call is recorded per person, feature and day (UTC) with its tokens, web searches and an estimated
dollar cost. Before a call, three checks:
- the app-wide monthly budget: once it's used up, AI pauses for everyone until the 1st;
- a per-person daily spend cap;
- per-person daily counts for the features someone can repeat on demand (imports, plans, Concierge…).
A blocked call raises a ClaudeError like any other failure, so features with an offline fallback keep working.
The owner skips the per-person checks but not the monthly budget. Google Maps calls are counted too, with list
prices before Google's free monthly allowance; they're billed by Google separately and don't count toward the budget.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from .config import Settings
from .db import CURRENT_USER, Database
from .llm import ClaudeError

log = logging.getLogger(__name__)

# Per-person daily limits: which Claude features count toward each, and how the limit is named to people.
LIMITS = {
    "imports": (("import",), "imports"),
    "plans": (("plan", "tidy", "suggest"), "AI plans"),
    "concierge": (("concierge",), "Concierge messages"),
    "menus": (("menu",), "menu lookups"),
    "bookings": (("bookings",), "booking reads"),
    "packing": (("packing",), "packing lists"),
    "edits": (("edits",), "edits refreshes"),
}
# Estimated Google Maps Platform list prices per call (per route element for travel times), before the free
# monthly allowance, for the fields this app asks for.
GOOGLE_PRICES = {
    "locate": 0.035, "search": 0.032, "nearby": 0.035, "details": 0.020, "menu_photos": 0.032,
    "photo": 0.007, "routes": 0.005,
}
ALERT_LEVELS = (50, 80, 100)


class BudgetExceeded(ClaudeError):
    """AI was skipped because a budget or daily limit is used up."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def until_midnight() -> str:
    now = _now()
    left = (now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)) - now
    hours = int(left.total_seconds() // 3600)
    return f"in {hours} hour{'s' if hours != 1 else ''}" if hours else "within the hour"


class Usage:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings

    # ---------- Settings ----------

    def config(self) -> dict[str, float]:
        """The budgets and limits: the server settings, with any the owner changed on the Usage page."""
        s = self.settings
        values: dict[str, float] = {"monthly_budget_usd": s.monthly_budget_usd, "user_daily_budget_usd": s.user_daily_budget_usd}
        values.update({f"limit_{name}": getattr(s, f"limit_{name}_per_day") for name in LIMITS})
        for key, value in (self.db.get_setting("cost_limits") or {}).items():
            if key in values and isinstance(value, (int, float)) and value >= 0:
                values[key] = value
        return values

    def set_config(self, changes: dict[str, Any]) -> dict[str, float]:
        current = self.config()
        saved = dict(self.db.get_setting("cost_limits") or {})
        for key, value in changes.items():
            if key not in current:
                continue
            if value is None:
                saved.pop(key, None)  # back to the server setting
            elif isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 100000:
                saved[key] = int(value) if key.startswith("limit_") else round(float(value), 2)
        self.db.set_setting("cost_limits", saved)
        return self.config()

    # ---------- Checks ----------

    def _exempt(self, uid: Optional[str]) -> bool:
        return not uid or self.db.is_admin(uid)

    def check(self, feature: str) -> None:
        """Raises BudgetExceeded when a Claude call for this feature isn't allowed right now."""
        config = self.config()
        today, month = _now().date().isoformat(), _now().strftime("%Y-%m")
        budget = config["monthly_budget_usd"]
        if budget and self.db.usage_cost(f"{month}-01") >= budget:
            raise BudgetExceeded("AI features are paused until next month: this month's AI budget is used up.")
        uid = CURRENT_USER.get()
        if self._exempt(uid):
            return
        for name, (features, label) in LIMITS.items():
            limit = int(config[f"limit_{name}"])
            if feature in features and limit and self.db.usage_calls(today, uid, features) >= limit:
                raise BudgetExceeded(f"You've reached today's limit of {limit} {label}. It resets {until_midnight()}.")
        cap = config["user_daily_budget_usd"]
        if cap and self.db.usage_cost(today, uid) >= cap:
            raise BudgetExceeded(f"You've used today's AI allowance. It resets {until_midnight()}.")

    # ---------- Recording ----------

    def price(self, usage: Any) -> tuple[dict[str, int], float]:
        s = self.settings
        tokens = {
            "input_tokens": getattr(usage, "input_tokens", 0) or 0,
            "output_tokens": getattr(usage, "output_tokens", 0) or 0,
            "cache_read": getattr(usage, "cache_read_input_tokens", 0) or 0,
            "cache_write": getattr(usage, "cache_creation_input_tokens", 0) or 0,
            "searches": getattr(getattr(usage, "server_tool_use", None), "web_search_requests", 0) or 0,
        }
        cost = (tokens["input_tokens"] * s.price_input_mtok + tokens["output_tokens"] * s.price_output_mtok
                + tokens["cache_read"] * s.price_cache_read_mtok + tokens["cache_write"] * s.price_cache_write_mtok) / 1e6
        cost += tokens["searches"] * s.price_web_search_k / 1000
        return tokens, cost

    def record(self, feature: str, usage: Any) -> None:
        """Adds one Claude response (its .usage) to today's totals."""
        try:
            tokens, cost = self.price(usage)
            self.db.add_usage(_now().date().isoformat(), CURRENT_USER.get() or "", feature, cost=cost, **tokens)
            self._alert()
        except Exception:
            log.exception("Couldn't record AI usage")

    def record_google(self, kind: str, count: int = 1) -> None:
        try:
            self.db.add_usage(_now().date().isoformat(), CURRENT_USER.get() or "", f"google:{kind}", calls=count,
                              cost=GOOGLE_PRICES.get(kind, 0.0) * count)
        except Exception:
            log.exception("Couldn't record Google usage")

    def _alert(self) -> None:
        """An error-level log (which Sentry emails) the first time spend passes 50%, 80% and 100% of the month's budget."""
        budget = self.config()["monthly_budget_usd"]
        if not budget:
            return
        month = _now().strftime("%Y-%m")
        spent = self.db.usage_cost(f"{month}-01")
        level = max((lvl for lvl in ALERT_LEVELS if spent >= budget * lvl / 100), default=0)
        sent = self.db.get_setting("budget_alert") or {}
        already = sent.get("level", 0) if sent.get("month") == month else 0
        if level > already:
            self.db.set_setting("budget_alert", {"month": month, "level": level})
            if level >= 100:
                log.error("AI budget used up for %s: $%.2f of $%.2f. AI features are paused until next month.", month, spent, budget)
            else:
                log.error("AI spend for %s passed %d%% of the budget: $%.2f of $%.2f", month, level, spent, budget)

    # ---------- Report ----------

    def report(self, days: int = 30) -> dict:
        now = _now()
        today, month_start = now.date().isoformat(), now.strftime("%Y-%m-01")
        since = min(month_start, (now.date() - timedelta(days=days - 1)).isoformat())
        rows = self.db.usage_rows(since)
        emails = self.db.user_emails()
        ai = [r for r in rows if not r["feature"].startswith("google:")]
        google = [r for r in rows if r["feature"].startswith("google:")]

        def total(items, key="cost_usd"):
            return round(sum(r[key] for r in items), 4)

        by_day: dict[str, dict] = {}
        for r in ai:
            d = by_day.setdefault(r["day"], {"day": r["day"], "cost": 0.0, "calls": 0})
            d["cost"] += r["cost_usd"]
            d["calls"] += r["calls"]
        month_ai = [r for r in ai if r["day"] >= month_start]
        features: dict[str, dict] = {}
        for r in month_ai:
            f = features.setdefault(r["feature"], {"feature": r["feature"], "calls": 0, "cost": 0.0, "input_tokens": 0,
                                                   "output_tokens": 0, "searches": 0})
            for key in ("calls", "input_tokens", "output_tokens", "searches"):
                f[key] += r[key]
            f["cost"] += r["cost_usd"]
        people: dict[str, dict] = {}
        for r in month_ai:
            p = people.setdefault(r["user_id"], {"user_id": r["user_id"], "email": emails.get(r["user_id"]) or ("(no account)" if not r["user_id"] else "(deleted)"),
                                                 "calls": 0, "cost_month": 0.0, "cost_today": 0.0})
            p["calls"] += r["calls"]
            p["cost_month"] += r["cost_usd"]
            if r["day"] == today:
                p["cost_today"] += r["cost_usd"]
        kinds: dict[str, dict] = {}
        for r in google:
            if r["day"] >= month_start:
                k = kinds.setdefault(r["feature"][7:], {"kind": r["feature"][7:], "calls": 0, "cost": 0.0})
                k["calls"] += r["calls"]
                k["cost"] += r["cost_usd"]
        config = self.config()
        return {
            "today": today, "month": month_start[:7],
            "month_cost": total(month_ai), "today_cost": total([r for r in ai if r["day"] == today]),
            "monthly_budget": config["monthly_budget_usd"], "paused": bool(config["monthly_budget_usd"]) and total(month_ai) >= config["monthly_budget_usd"],
            "config": config, "limit_labels": {name: label for name, (_, label) in LIMITS.items()},
            "days": sorted(by_day.values(), key=lambda d: d["day"], reverse=True)[:days],
            "features": sorted(features.values(), key=lambda f: f["cost"], reverse=True),
            "people": sorted(people.values(), key=lambda p: p["cost_month"], reverse=True),
            "google": sorted(kinds.values(), key=lambda k: k["cost"], reverse=True),
            "google_cost": round(sum(k["cost"] for k in kinds.values()), 4),
        }
