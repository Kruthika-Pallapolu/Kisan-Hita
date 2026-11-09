from app.providers.interfaces import WeatherProvider
from app.schemas.features import FarmTodayRequest, FarmTodayResponse


class WeatherService:
    """Weather use-case logic depends on the provider protocol, not an adapter."""

    def __init__(self, provider: WeatherProvider):
        self._provider = provider

    def get_today(self, request: FarmTodayRequest) -> FarmTodayResponse:
        return self._provider.get_forecast(request)
