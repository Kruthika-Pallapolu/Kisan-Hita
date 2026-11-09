"""Backend adapter for the official data.gov.in AGMARKNET daily-price resource."""
from datetime import datetime, timezone
from collections.abc import Callable
from typing import Any

import httpx

from app.schemas.features import MarketPriceRequest, MarketPriceResponse


class DataGovMarketProvider:
    ENDPOINT = "https://api.data.gov.in/resource/9ef84268-d588-465a-a308-a864a43d0070"
    SOURCE = "AGMARKNET, Directorate of Marketing and Inspection via data.gov.in (Government Open Data License – India)"
    def __init__(self, api_key: str, *, client_factory: Callable[..., Any] = httpx.Client):
        if not api_key.strip():
            raise ValueError("DATA_GOV_IN_API_KEY is required when MARKET_PROVIDER=datagov.")
        self.__api_key = api_key.strip()
        self._client_factory = client_factory

    @staticmethod
    def _date(value: object) -> datetime | None:
        if not isinstance(value, str):
            return None
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
            try:
                return datetime.strptime(value.strip(), fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        return None

    def lookup(self, request: MarketPriceRequest) -> list[MarketPriceResponse]:
        params: dict[str, str | int] = {"api-key": self.__api_key, "format": "json", "limit": 100, "offset": 0}
        filters = {"commodity": request.crop.strip(), "market": request.market.strip()}
        if request.state:
            filters["state"] = request.state.strip()
        if request.district:
            filters["district"] = request.district.strip()
        if request.variety:
            filters["variety"] = request.variety.strip()
        params.update({f"filters[{key}]": value for key, value in filters.items()})
        try:
            with self._client_factory(timeout=httpx.Timeout(8.0, connect=3.0)) as client:
                response = client.get(self.ENDPOINT, params=params)
            if not 200 <= response.status_code < 300:
                return []
            body = response.json()
            records = body.get("records", []) if isinstance(body, dict) else []
        except (httpx.HTTPError, ValueError, TypeError):
            return []
        output: list[MarketPriceResponse] = []
        for row in records if isinstance(records, list) else []:
            if not isinstance(row, dict):
                continue
            observed = self._date(row.get("arrival_date"))
            try:
                modal = float(row.get("modal_price"))
                minimum = float(row["min_price"]) if row.get("min_price") not in (None, "", "NA") else None
                maximum = float(row["max_price"]) if row.get("max_price") not in (None, "", "NA") else None
            except (TypeError, ValueError):
                continue
            if not observed or modal <= 0:
                continue
            commodity = str(row.get("commodity", "")).strip()
            market = str(row.get("market", "")).strip()
            if not commodity or not market:
                continue
            output.append(MarketPriceResponse(
                crop=commodity, market=market, variety=str(row.get("variety", "")).strip() or None,
                price=modal, minimum_price=minimum, maximum_price=maximum, modal_price=modal,
                unit="INR per quintal", observed_at=observed, source=self.SOURCE, is_mock=False,
            ))
        return output
