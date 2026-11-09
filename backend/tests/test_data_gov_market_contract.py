"""Offline contract checks for the data.gov.in AGMARKNET adapter."""
import httpx

from app.providers.data_gov_market import DataGovMarketProvider
from app.schemas.features import MarketPriceRequest


def provider(handler):
    transport = httpx.MockTransport(handler)
    return DataGovMarketProvider("local-contract-key", client_factory=lambda **kw: httpx.Client(transport=transport, **kw))


def test_datagov_market_maps_source_record_and_keeps_credentials_server_side():
    def handler(request):
        assert request.url.host == "api.data.gov.in"
        assert request.url.path.endswith("9ef84268-d588-465a-a308-a864a43d0070")
        assert request.url.params["api-key"] == "local-contract-key"
        assert request.url.params["filters[commodity]"] == "Tomato"
        assert request.url.params["filters[market]"] == "Warangal"
        assert request.url.params["filters[state]"] == "Telangana"
        assert request.url.params["filters[district]"] == "Warangal"
        return httpx.Response(200, json={"records": [{
            "state": "Telangana", "district": "Warangal", "market": "Warangal",
            "commodity": "Tomato", "variety": "Local", "arrival_date": "03/11/2026",
            "min_price": "1800", "max_price": "2400", "modal_price": "2100",
        }]})
    result = provider(handler).lookup(MarketPriceRequest(crop="Tomato", market="Warangal", state="Telangana", district="Warangal"))
    assert len(result) == 1
    assert result[0].price == 2100 and result[0].unit == "INR per quintal"
    assert result[0].observed_at.date().isoformat() == "2026-11-03"
    assert result[0].is_mock is False


def test_datagov_market_drops_incomplete_rows_and_fails_closed_on_upstream_errors():
    malformed = provider(lambda _request: httpx.Response(200, json={"records": [{"commodity": "Potato"}, {"arrival_date": "bad", "modal_price": "3", "commodity": "Potato", "market": "Warangal"}]}))
    assert malformed.lookup(MarketPriceRequest(crop="Potato", market="Warangal")) == []
    unavailable = provider(lambda _request: httpx.Response(503, text="unavailable"))
    assert unavailable.lookup(MarketPriceRequest(crop="Potato", market="Warangal")) == []
