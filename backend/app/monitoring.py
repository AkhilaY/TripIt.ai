"""Error reporting with Sentry (optional: set SENTRY_DSN).

The server reports its own crashes and logged errors. The web app and the iOS app's web screens send their
JavaScript errors to POST /v1/client-errors, and feedback from the app arrives at POST /v1/feedback; both are
forwarded here. Only an account's id is attached, never emails, request bodies or cookies.
"""

import logging
import time
from collections import defaultdict, deque
from typing import Optional

log = logging.getLogger(__name__)

try:  # the app runs without the package too (it's only needed when a DSN is set)
    import sentry_sdk
except ImportError:  # pragma: no cover
    sentry_sdk = None

_enabled = False


def init_monitoring(settings) -> bool:
    global _enabled
    if not settings.sentry_dsn or sentry_sdk is None:
        return False
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.sentry_environment,
        release=settings.sentry_release or None,
        send_default_pii=False,  # no IP addresses, cookies or auth headers
        max_request_body_size="never",  # bodies hold passwords and people's places
        traces_sample_rate=settings.sentry_traces_sample_rate,
        before_send=_scrub,
    )
    _enabled = True
    log.info("Error reporting is on (%s)", settings.sentry_environment)
    return True


def enabled() -> bool:
    return _enabled


SENSITIVE = ("authorization", "cookie", "x-api-key", "password", "token", "secret", "invite")


def _scrub(event: dict, hint: dict) -> dict:
    """Belt and braces on top of send_default_pii=False: drop anything that looks like a credential."""
    request = event.get("request") or {}
    headers = request.get("headers")
    if isinstance(headers, dict):
        request["headers"] = {k: ("[filtered]" if any(s in k.lower() for s in SENSITIVE) else v) for k, v in headers.items()}
    request.pop("cookies", None)
    request.pop("data", None)
    if "query_string" in request and any(s in str(request["query_string"]).lower() for s in ("sig=", "token=")):
        request["query_string"] = "[filtered]"
    return event


def set_user(user_id: Optional[str]) -> None:
    if _enabled:
        sentry_sdk.set_user({"id": user_id} if user_id else None)


class RateLimit:
    """At most `limit` reports per key (an IP address) per minute, so a broken page can't flood the logs."""

    def __init__(self, limit: int = 20, window: float = 60.0):
        self.limit, self.window = limit, window
        self.hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        hits = self.hits[key]
        while hits and now - hits[0] > self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        if len(self.hits) > 5000:  # forget idle keys
            for k in [k for k, v in self.hits.items() if not v]:
                del self.hits[k]
        return True


def report_client_error(source: str, message: str, *, stack: str = "", url: str = "", version: str = "",
                        user_id: Optional[str] = None, extra: Optional[dict] = None) -> None:
    log.warning("Client error from %s at %s: %s", source, url or "?", message[:300])
    if not _enabled:
        return
    with sentry_sdk.new_scope() as scope:
        scope.set_tag("source", source)
        if version:
            scope.set_tag("app_version", version)
        if user_id:
            scope.set_user({"id": user_id})
        scope.set_context("client", {"url": url, "stack": stack[:8000], **(extra or {})})
        scope.fingerprint = [source, message[:200]]
        sentry_sdk.capture_message(f"[{source}] {message[:300]}", level="error")


def report_feedback(message: str, *, user_id: Optional[str], email: str = "", context: Optional[dict] = None) -> None:
    log.info("Feedback from %s: %s", user_id or "someone", message[:300])
    if not _enabled:
        return
    with sentry_sdk.new_scope() as scope:
        scope.set_tag("kind", "feedback")
        if user_id:
            scope.set_user({"id": user_id})
        scope.set_context("feedback", {"message": message, "reply_to": email, **(context or {})})
        sentry_sdk.capture_message(f"Feedback: {message[:120]}", level="info")
