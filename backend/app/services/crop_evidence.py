"""Curated crop evidence matching and historical regional context."""
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from app.schemas.features import CropEvidenceAttribution, CropRecommendation, CropRequest, CropResponse
from app.services.language import crop_names, text as localized


CATALOG_VERSION = "1"


@dataclass(frozen=True)
class CropRecommendationEvidence:
    evidence_id: str
    crop_id: str
    crop_names: dict[str, str]
    explanations: dict[str, str]
    state: str
    geography: str
    geography_level: Literal["district", "zone", "state"]
    districts: tuple[str, ...]
    season: str
    source_title: str
    publisher: str
    source_url: str
    publication_year: int | None
    evidence_type: Literal["current_recommendation", "historical_research"]
    decision: Literal["recommend", "do_not_recommend"] = "recommend"
    required_soil_types: tuple[str, ...] | None = None
    required_water_availability: tuple[str, ...] | None = None
    conditions_by_language: dict[str, tuple[str, ...]] = field(default_factory=dict)
    reviewed_on: date | None = None
    publication_date: date | None = None
    valid_from: date | None = None
    valid_until: date | None = None


@dataclass(frozen=True)
class CropEvidenceCatalog:
    version: str
    recommendations: tuple[CropRecommendationEvidence, ...] = ()


PRODUCTION_CROP_EVIDENCE_CATALOG = CropEvidenceCatalog(version=CATALOG_VERSION)


def _normalized(value: str | None) -> str:
    return " ".join((value or "").casefold().split())


def _season_key(value: str | None) -> str:
    normalized = _normalized(value)
    aliases = {
        "monsoon": "kharif", "vanakalam": "kharif", "వానాకాలం": "kharif",
        "winter": "rabi", "yasangi": "rabi", "యాసంగి": "rabi",
        "summer": "zaid", "zaid": "zaid",
    }
    return aliases.get(normalized, normalized)


def _soil_key(value: str | None) -> str:
    normalized = _normalized(value)
    return normalized.removesuffix(" soil").strip()


def _matches_geography(record: CropRecommendationEvidence, request: CropRequest) -> bool:
    if _normalized(record.state) != _normalized(request.state):
        return False
    if record.geography_level == "state":
        return True
    return any(_normalized(district) == _normalized(request.district) for district in record.districts)


def _attribution(record: CropRecommendationEvidence, language: str) -> CropEvidenceAttribution:
    return CropEvidenceAttribution(
        evidence_id=record.evidence_id, source_title=record.source_title,
        publisher=record.publisher, source_url=record.source_url,
        evidence_type=record.evidence_type, publication_year=record.publication_year,
        publication_date=record.publication_date, reviewed_on=record.reviewed_on,
        valid_from=record.valid_from, valid_until=record.valid_until, geography=record.geography,
        season=_season_key(record.season).title(),
        conditions=list(record.conditions_by_language.get(language, ())),
    )


def evaluate_crop_evidence(request: CropRequest, catalog: CropEvidenceCatalog,
                           *, today: date | None = None) -> CropResponse:
    """Return only explicitly matching, current, localized evidence; never rank crops."""
    today = today or date.today()
    language = request.language.replace("_", "-").split("-", 1)[0].lower()
    geography_matches = [record for record in catalog.recommendations if _matches_geography(record, request)]
    season_matches = [record for record in geography_matches if _season_key(record.season) == _season_key(request.season)]
    stale = [record for record in season_matches if record.evidence_type != "current_recommendation"
             or (record.valid_from is not None and today < record.valid_from)
             or (record.valid_until is not None and today > record.valid_until)]
    active = [record for record in season_matches if record not in stale]
    if stale and not active:
        return CropResponse(
            recommendations=[], disclaimer=localized("crop_stale_evidence", language),
            source="; ".join(sorted({record.publisher for record in stale})), is_mock=False,
            outcome="no_applicable_evidence", evidence_issue="stale",
            evidence=[_attribution(record, language) for record in stale], catalog_version=catalog.version,
        )

    missing_conditions: set[str] = set()
    condition_matches: list[CropRecommendationEvidence] = []
    for record in active:
        soil_key = _soil_key(request.soil_type)
        soil_missing = bool(record.required_soil_types) and not soil_key
        soil_matches = (not record.required_soil_types or soil_missing
                        or soil_key in {_soil_key(value) for value in record.required_soil_types})
        water = _normalized(request.water_availability)
        water_missing = bool(record.required_water_availability) and not water
        water_matches = (not record.required_water_availability or water_missing
                         or water in {_normalized(value) for value in record.required_water_availability})
        if not soil_matches or not water_matches:
            continue
        if soil_missing:
            missing_conditions.add("soil_type")
        if water_missing:
            missing_conditions.add("water_availability")
        if soil_missing or water_missing:
            continue
        if not record.crop_names.get(language) or not record.explanations.get(language):
            missing_conditions.add("language_review")
            continue
        if ((record.required_soil_types or record.required_water_availability)
            and not record.conditions_by_language.get(language)):
            missing_conditions.add("language_review")
            continue
        condition_matches.append(record)

    if missing_conditions:
        keys = frozenset(missing_conditions)
        prompt = "crop_missing_soil_water" if {"soil_type", "water_availability"} <= keys else (
            "crop_missing_soil" if "soil_type" in keys else "crop_missing_water" if "water_availability" in keys
            else "crop_language_evidence_unavailable"
        )
        return CropResponse(
            recommendations=[], disclaimer=localized(prompt, language),
            source="Verified crop guidance requires additional information.", is_mock=False,
            outcome="no_applicable_evidence", missing_conditions=sorted(missing_conditions),
            evidence=[_attribution(record, language) for record in active], catalog_version=catalog.version,
        )

    decisions: dict[str, set[str]] = {}
    for record in condition_matches:
        decisions.setdefault(record.crop_id, set()).add(record.decision)
    conflicted_crops = {crop for crop, outcomes in decisions.items() if len(outcomes) > 1}
    if conflicted_crops:
        conflicting_records = [record for record in condition_matches if record.crop_id in conflicted_crops]
        return CropResponse(
            recommendations=[], disclaimer=localized("crop_conflicting_evidence", language),
            source="Conflicting verified crop guidance.", is_mock=False,
            outcome="no_applicable_evidence", evidence_issue="conflict",
            evidence=[_attribution(record, language) for record in conflicting_records], catalog_version=catalog.version,
        )

    supported = [record for record in condition_matches if record.decision == "recommend"]
    if supported:
        if len(supported) > 3:
            return CropResponse(
                recommendations=[], disclaimer=localized("crop_many_matches", language),
                source="More verified crop guidance applies than can be shown safely.", is_mock=False,
                outcome="no_applicable_evidence", evidence_issue="multiple_matches",
                evidence=[_attribution(record, language) for record in supported], catalog_version=catalog.version,
            )
        recommendations = [CropRecommendation(
            crop=record.crop_names[language], reasons=[record.explanations[language]],
            cultivation_notes=[], confidence=None,
        ) for record in supported]
        return CropResponse(
            recommendations=recommendations, disclaimer=localized("crop_verified", language),
            source="; ".join(sorted({record.publisher for record in supported})), is_mock=False,
            outcome="verified_recommendation", evidence=[_attribution(record, language) for record in supported],
            catalog_version=catalog.version, recommendation_ready=True,
        )

    return CropResponse(
        recommendations=[], disclaimer=localized("crop_no_evidence", language),
        source="No current crop guidance matches this location and season.", is_mock=False,
        outcome="no_applicable_evidence", evidence=[_attribution(record, language) for record in season_matches],
        catalog_version=catalog.version,
    )


def catalog_crop_response(request: CropRequest) -> CropResponse:
    return evaluate_crop_evidence(request, PRODUCTION_CROP_EVIDENCE_CATALOG)


class EvidenceCatalogCropRecommendationProvider:
    """Crop provider backed only by curated records; the production catalog is empty until reviewed evidence is approved."""

    def recommend(self, request: CropRequest) -> CropResponse:
        return catalog_crop_response(request)


@dataclass(frozen=True)
class RegionalCropContext:
    region: str
    crops: tuple[str, ...]
    rainfall_range_mm: str
    soil_summary: str
    period: str
    source_name: str
    source_url: str
    limitation: str
    publication_year: int

    def as_dict(self) -> dict[str, object]:
        return {
            "region": self.region, "crops_reported": list(self.crops),
            "annual_rainfall_range_mm": self.rainfall_range_mm,
            "zone_soil_summary": self.soil_summary, "source_period": self.period,
            "source": self.source_name, "source_url": self.source_url,
            "limitation": self.limitation, "publication_year": self.publication_year,
            "evidence_type": "regional_context",
        }


CENTRAL_TELANGANA = RegionalCropContext(
    region="Central Telangana Zone",
    crops=("cotton", "rice", "maize", "greengram", "mango", "sugarcane", "chillies"),
    rainfall_range_mm="779–1,213", soil_summary="red soils (zone-level summary)",
    period="Telangana Statistical Abstract 2021; crop pattern reference year 2020–21",
    source_name="Government of Telangana, Telangana State Statistical Abstract 2021; source credited in the report to ACRC, PJTSAU",
    source_url="https://telangana.gov.in/wp-content/uploads/2023/05/Telangana-Statistical-Abstract-2021.pdf",
    limitation="Historical zone-level context only. It does not establish suitability for this farm, current season, soil test, irrigation, variety, pest pressure, prices, yield, or profit.",
    publication_year=2021,
)


def warangal_context(state: str | None, district: str | None) -> RegionalCropContext | None:
    place = (district or "").strip().casefold()
    state_key = (state or "").strip().casefold()
    warangal_places = {"warangal", "warangal urban", "warangal rural", "hanamkonda"}
    if place not in warangal_places or state_key not in {"telangana", "telangana state"}:
        return None
    return CENTRAL_TELANGANA


def attach_regional_context(response: CropResponse, request: CropRequest) -> CropResponse:
    regional = warangal_context(request.state, request.district)
    if regional is None:
        return response
    response.regional_context = regional.as_dict()
    if not any(item.evidence_id == "telangana-statistical-abstract-2021" for item in response.evidence):
        response.evidence.append(CropEvidenceAttribution(
            evidence_id="telangana-statistical-abstract-2021",
            source_title="Telangana Statistical Abstract 2021",
            publisher="Government of Telangana; crop-pattern reference credited to ACRC, PJTSAU",
            source_url=regional.source_url, evidence_type="regional_context",
            publication_year=regional.publication_year, geography=regional.region,
            reference_period="Crop-pattern reference year 2020–21",
        ))
    if (response.outcome == "no_applicable_evidence" and response.evidence_issue is None
            and not response.missing_conditions):
        crops = crop_names(regional.crops, request.language)
        response.outcome = "regional_context_only"
        response.disclaimer = " ".join((
            localized("crop_unavailable", request.language),
            localized("crop_profile_intro", request.language), crops + ".",
            localized("crop_profile_limit", request.language),
            localized("crop_profile_next", request.language),
        ))
    return response
