from fastapi import APIRouter, Request
from app.schemas.features import ContractInfo

router = APIRouter(prefix="/contracts", tags=["contracts"])

CONTRACTS = [
    ("My Farm Today", "POST", "/farm/today", "FarmTodayRequest", "FarmTodayResponse", True),
    ("Choose My Crop", "POST", "/crops/recommendations", "CropRequest", "CropResponse", False),
    ("Check My Crop", "POST", "/crop-health/analyze", "CropHealthRequest", "CropHealthResponse", False),
    ("Market Prices", "POST", "/market/prices", "MarketPriceRequest", "list[MarketPriceResponse]", False),
    ("Ask Kisan Hita", "POST", "/assistant/messages", "ChatRequest", "ChatResponse", False),
]


@router.get("", response_model=list[ContractInfo])
def list_contracts(request: Request):
    """List current API shapes using the active configured version prefix."""
    prefix = request.app.state.settings.api_v1_prefix
    return [
        ContractInfo(feature=name, method=method, path=f"{prefix}{path}", request_schema=req, response_schema=resp, implemented=implemented)
        for name, method, path, req, resp, implemented in CONTRACTS
    ]
