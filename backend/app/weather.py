"""Weather for a trip's dates, from Open-Meteo (https://open-meteo.com).

- Dates within the next two weeks: the daily forecast.
- Later dates (or past ones): the same dates last year, shown as "typical" rather than as a forecast.

Open-Meteo's free service is for non-commercial use. A public or paid app needs its commercial plan
(WEATHER_API_KEY and WEATHER_BASE_URL) or another provider. When the lookup fails, packing lists are made
without weather.
"""

import logging
from datetime import date, timedelta
from typing import Optional

import httpx

from .config import Settings
from .models import WeatherDay

log = logging.getLogger(__name__)

FORECAST_DAYS = 15  # Open-Meteo forecasts up to about 16 days ahead
WMO = {
    0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle", 56: "Freezing drizzle", 57: "Freezing drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain", 66: "Freezing rain", 67: "Freezing rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains", 80: "Light showers", 81: "Showers",
    82: "Heavy showers", 85: "Snow showers", 86: "Snow showers", 95: "Thunderstorms", 96: "Thunderstorms with hail",
    99: "Thunderstorms with hail",
}


def wmo_summary(code: Optional[int]) -> str:
    return WMO.get(int(code), "Mixed") if code is not None else "Mixed"


class Weather:
    FORECAST = "https://api.open-meteo.com/v1/forecast"
    ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"

    def __init__(self, settings: Settings, client: Optional[httpx.AsyncClient] = None):
        self.enabled = settings.weather != "none"
        self.key = settings.weather_api_key
        self.base = settings.weather_base_url.rstrip("/")
        self.client = client or httpx.AsyncClient(timeout=10)

    def _url(self, kind: str) -> str:
        if self.base:
            return f"{self.base}/{'archive' if kind == 'archive' else 'forecast'}"
        return self.ARCHIVE if kind == "archive" else self.FORECAST

    async def _daily(self, kind: str, lat: float, lon: float, start: date, end: date) -> dict:
        fields = "weather_code,temperature_2m_max,temperature_2m_min" + (",precipitation_probability_max" if kind == "forecast" else "")
        params = {"latitude": round(lat, 3), "longitude": round(lon, 3), "daily": fields, "timezone": "auto",
                  "start_date": start.isoformat(), "end_date": end.isoformat()}
        if self.key:
            params["apikey"] = self.key
        response = await self.client.get(self._url(kind), params=params)
        response.raise_for_status()
        return response.json().get("daily") or {}

    async def days(self, lat: float, lon: float, start: date, count: int) -> list[WeatherDay]:
        """One entry per trip day, or an empty list when weather isn't available."""
        if not self.enabled or count < 1:
            return []
        count = min(count, 21)
        today = date.today()
        result: list[WeatherDay] = []
        try:
            wanted = [start + timedelta(days=i) for i in range(count)]
            ahead = [d for d in wanted if today <= d <= today + timedelta(days=FORECAST_DAYS)]
            by_date: dict[date, tuple[str, dict, int]] = {}
            if ahead:
                daily = await self._daily("forecast", lat, lon, ahead[0], ahead[-1])
                for i, iso in enumerate(daily.get("time") or []):
                    by_date[date.fromisoformat(iso)] = ("forecast", daily, i)
            rest = [d for d in wanted if d not in by_date]
            if rest:
                shift = lambda d: d.replace(year=d.year - 1) if not (d.month == 2 and d.day == 29) else d.replace(year=d.year - 1, day=28)
                daily = await self._daily("archive", lat, lon, shift(min(rest)), shift(max(rest)))
                lookup = {date.fromisoformat(iso): i for i, iso in enumerate(daily.get("time") or [])}
                for d in rest:
                    i = lookup.get(shift(d))
                    if i is not None:
                        by_date[d] = ("typical", daily, i)
            for number, d in enumerate(wanted, start=1):
                if d not in by_date:
                    continue
                source, daily, i = by_date[d]
                lo, hi = daily["temperature_2m_min"][i], daily["temperature_2m_max"][i]
                if lo is None or hi is None:
                    continue
                chance = (daily.get("precipitation_probability_max") or [None] * (i + 1))[i] if source == "forecast" else None
                result.append(WeatherDay(day=number, date=d.isoformat(), summary=wmo_summary((daily.get("weather_code") or [None] * (i + 1))[i]),
                                         temp_min=round(lo, 1), temp_max=round(hi, 1), rain_chance=int(chance) if chance is not None else None,
                                         source=source))
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as e:
            log.warning("Weather lookup failed: %s", e)
            return []
        return result
