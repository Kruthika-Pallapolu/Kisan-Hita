"""Open-Meteo adapter. Uses public forecast and geocoding APIs; no credentials."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from threading import Lock
from time import monotonic

import httpx

from app.schemas.features import CurrentConditions, FarmTodayRequest, FarmTodayResponse, ForecastDay

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
SOURCE = "Open-Meteo forecast model (not an official observation or warning)"


class WeatherUnavailableError(Exception):
    """No usable forecast could be obtained."""


class WeatherLocationNotFoundError(Exception):
    """The selected location could not be resolved by the geocoder."""


class OpenMeteoWeatherProvider:
    """Backend-only Open-Meteo client with short-lived and stale cache handling."""

    cache_ttl_seconds = 900
    max_stale_seconds = 86_400

    def __init__(self, client_factory=httpx.Client):
        self._client_factory = client_factory
        self._cache: dict[tuple[float, float], tuple[float, FarmTodayResponse]] = {}
        self._lock = Lock()

    def get_forecast(self, request: FarmTodayRequest) -> FarmTodayResponse:
        lat, lon, place = self._resolve_location(request)
        key = (round(lat, 3), round(lon, 3))
        now = monotonic()
        with self._lock:
            cached = self._cache.get(key)
        if cached and now - cached[0] < self.cache_ttl_seconds:
            return self._for_request(cached[1], request, place)

        try:
            payload = self._fetch_forecast(lat, lon)
            response = self._parse_forecast(payload, request, place)
            with self._lock:
                self._cache[key] = (monotonic(), response)
            return response
        except (WeatherLocationNotFoundError,):
            raise
        except Exception as exc:
            if cached and now - cached[0] < self.max_stale_seconds:
                stale = cached[1].model_copy(update={
                    "is_stale": True,
                    "notice": "Showing a cached forecast because the weather service is unavailable. This data may be up to 24 hours old; check local conditions.",
                })
                return self._for_request(stale, request, place)
            if isinstance(exc, WeatherUnavailableError):
                raise
            raise WeatherUnavailableError("Weather data is temporarily unavailable.") from exc

    def _resolve_location(self, request: FarmTodayRequest) -> tuple[float, float, str]:
        if request.latitude is not None and request.longitude is not None:
            label = request.location or ", ".join(value for value in (request.district, request.state) if value)
            return request.latitude, request.longitude, label
        query = request.location or ", ".join(value for value in (request.district, request.state, "India") if value)
        try:
            with self._client_factory(timeout=httpx.Timeout(8.0, connect=3.0)) as client:
                response = client.get(GEOCODING_URL, params={"name": query, "count": 5, "language": "en", "countryCode": "IN"})
                response.raise_for_status()
                payload = response.json()
            results = payload.get("results", []) if isinstance(payload, dict) else []
            if not isinstance(results, list) or not results:
                raise WeatherLocationNotFoundError("No matching Indian place was found. Try a nearby town or use the optional farm-location button.")
            requested_state = _normalized(request.state or "")
            result = next((candidate for candidate in results if not requested_state or _normalized(str(candidate.get("admin1", ""))) == requested_state), None)
            if result is None:
                raise WeatherLocationNotFoundError("No matching place was found in the selected state. Try your district's nearby town or the optional farm-location button.")
            lat, lon = float(result["latitude"]), float(result["longitude"])
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError("Invalid geocoding coordinates")
            components = [result.get("name"), result.get("admin2"), result.get("admin1"), result.get("country")]
            return lat, lon, ", ".join(dict.fromkeys(str(part) for part in components if part))
        except WeatherLocationNotFoundError:
            raise
        except Exception as exc:
            raise WeatherUnavailableError("The selected place could not be checked right now.") from exc

    def _fetch_forecast(self, latitude: float, longitude: float) -> dict:
        params = {
            "latitude": latitude, "longitude": longitude,
            "current": "temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum,rain_sum,weather_code",
            "forecast_days": 7, "timezone": "Asia/Kolkata",
        }
        with self._client_factory(timeout=httpx.Timeout(10.0, connect=3.0)) as client:
            response = client.get(FORECAST_URL, params=params)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Forecast payload was not an object")
        return payload

    def _parse_forecast(self, payload: dict, request: FarmTodayRequest, place: str) -> FarmTodayResponse:
        current = payload.get("current")
        daily = payload.get("daily")
        if not isinstance(current, dict) or not isinstance(daily, dict):
            raise ValueError("Missing current or daily weather data")
        dates = daily.get("time")
        highs = daily.get("temperature_2m_max")
        lows = daily.get("temperature_2m_min")
        rain = daily.get("precipitation_sum")
        rain_probability = daily.get("precipitation_probability_max")
        codes = daily.get("weather_code")
        if not isinstance(dates, list) or not dates or not isinstance(highs, list) or len(highs) != len(dates):
            raise ValueError("Forecast dates or temperatures are missing")
        def value(items, index):
            return items[index] if isinstance(items, list) and index < len(items) else None
        forecasts = []
        for index, day in enumerate(dates):
            # Validate each date and numeric field instead of returning malformed provider data.
            summary = _weather_summary(value(codes, index))
            forecasts.append(ForecastDay(
                date=day,
                summary=summary,
                temperature_c=_number(value(highs, index)),
                temperature_min_c=_number(value(lows, index)),
                precipitation_mm=_number(value(rain, index)),
                precipitation_probability=_integer(value(rain_probability, index), 0, 100),
            ))
        fetched = datetime.now(UTC)
        current_time = current.get("time")
        current_data = CurrentConditions(
            time=current_time,
            temperature_c=_number(current.get("temperature_2m")),
            relative_humidity_percent=_integer(current.get("relative_humidity_2m"), 0, 100),
            precipitation_mm=_number(current.get("precipitation")),
            wind_speed_kmh=_number(current.get("wind_speed_10m")),
        )
        if current_data.temperature_c is None:
            raise ValueError("Current temperature is missing")
        advice = _farm_notes(current_data, forecasts, request)
        start, end = forecasts[0].date, forecasts[-1].date
        return FarmTodayResponse(
            location=place, state=request.state, district=request.district, resolved_place=place,
            geographic_resolution="Open-Meteo model grid point near the selected place; not a district-wide forecast",
            observed_at=None, current=current_data, forecast=forecasts, advice=advice, alerts=[],
            warnings_available=False,
            warnings_notice="Official IMD warnings and district agromet advisories were not available from this data source.",
            source=SOURCE, is_mock=False,
            notice="Forecast model estimates can differ from conditions at your farm. Check local observations and official IMD alerts before acting.",
            fetched_at=fetched, forecast_period=f"{start} to {end}",
        )

    def _for_request(self, response: FarmTodayResponse, request: FarmTodayRequest, place: str) -> FarmTodayResponse:
        return response.model_copy(update={
            "location": place, "resolved_place": place, "state": request.state,
            "district": request.district,
            "advice": _farm_notes(response.current, response.forecast, request) if response.current else [],
        })


def _number(value):
    if value is None:
        return None
    number = float(value)
    if number != number or abs(number) == float("inf"):
        raise ValueError("Non-finite weather value")
    return number


def _normalized(value: str) -> str:
    return " ".join(value.casefold().replace("&", "and").split())


def _integer(value, minimum, maximum):
    number = _number(value)
    if number is None:
        return None
    return max(minimum, min(maximum, round(number)))


def _weather_summary(code):
    code = int(code) if code is not None else -1
    if code == 0: return "Clear"
    if code in (1, 2): return "Mostly clear to partly cloudy"
    if code == 3: return "Overcast"
    if code in (45, 48): return "Fog"
    if 51 <= code <= 57: return "Drizzle"
    if 61 <= code <= 67: return "Rain"
    if 71 <= code <= 77: return "Snow"
    if 80 <= code <= 82: return "Rain showers"
    if 85 <= code <= 86: return "Snow showers"
    if code >= 95: return "Thunderstorm"
    return "Weather summary unavailable"


def _farm_notes(current, forecast, request):
    if request.question and any(word in request.question.lower() for word in ("spray", "pesticide", "pesticides", "spraying")):
        if not (request.crop and request.growth_stage and request.spray_product):
            return ["A weather forecast alone cannot establish whether spraying is safe. Check the product label and local guidance."]
        return ["The forecast cannot confirm product-specific spray safety. Check the label’s wind and rain restrictions and consult a local agricultural adviser."]
    notes = []
    if forecast and any((day.precipitation_probability or 0) >= 60 or (day.precipitation_mm or 0) >= 10 for day in forecast[:3]):
        notes.append("Rain is possible in the next few days. Check drainage and local field conditions; consider this forecast before irrigation or field work.")
    if current and current.wind_speed_kmh is not None and current.wind_speed_kmh >= 25:
        notes.append("Wind may be strong. Check conditions at the field before work that can be affected by wind.")
    if not notes:
        notes.append("No major rain signal appears in this model forecast. Verify conditions locally before making irrigation or field-work decisions.")
    return notes
