from __future__ import annotations

from collections import Counter
from typing import Any


def _clean_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def _combined_text(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in (
        "title",
        "brief_title",
        "official_title",
        "abstract",
        "conference_name",
        "conference_series",
        "indication",
        "mechanism_of_action",
        "clinical_studies_summary",
        "warnings",
        "adverse_reactions",
        "eligibility_criteria",
    ):
        text = _clean_text(payload.get(key))
        if text:
            parts.append(text)
    for key in ("primary_outcomes", "secondary_outcomes", "conditions", "interventions", "substance_names"):
        value = payload.get(key)
        if isinstance(value, list):
            parts.extend(_clean_text(item) for item in value if _clean_text(item))
    return " ".join(parts).lower()


def _clamp_score(value: float) -> float:
    return round(min(max(value, 0.05), 0.99), 2)


def _score_pubmed(payload: dict[str, Any]) -> tuple[float, list[str]]:
    score = 0.76
    reasons = ["PubMed-indexed peer-reviewed literature."]
    text = _combined_text(payload)
    if payload.get("abstract"):
        score += 0.05
        reasons.append("Abstract text is available for direct inspection.")
    if payload.get("mesh_terms"):
        score += 0.03
        reasons.append("Controlled vocabulary terms are available.")
    if any(token in text for token in ("phase", "randomized", "trial", "overall survival", "progression-free survival", "objective response rate")):
        score += 0.05
        reasons.append("The record looks like direct clinical-result reporting.")
    return _clamp_score(score), reasons


def _score_medrxiv(payload: dict[str, Any]) -> tuple[float, list[str]]:
    score = 0.46
    reasons = ["Preprint evidence is available before peer review."]
    text = _combined_text(payload)
    if payload.get("abstract"):
        score += 0.05
        reasons.append("Abstract text is available for direct inspection.")
    if any(token in text for token in ("phase", "trial", "overall survival", "progression-free survival", "objective response rate")):
        score += 0.04
        reasons.append("The preprint contains direct clinical-result language.")
    return _clamp_score(score), reasons


def _score_openfda(payload: dict[str, Any]) -> tuple[float, list[str]]:
    score = 0.9
    reasons = ["Approved product label or regulatory text from OpenFDA."]
    if payload.get("clinical_studies_summary"):
        score += 0.03
        reasons.append("Clinical studies summary text is available.")
    if payload.get("warnings") or payload.get("adverse_reactions"):
        score += 0.02
        reasons.append("Safety language is directly available from the label.")
    return _clamp_score(score), reasons


def _score_clinicaltrials(payload: dict[str, Any]) -> tuple[float, list[str]]:
    score = 0.61
    reasons = ["Registered clinical trial evidence from ClinicalTrials.gov."]
    if payload.get("eligibility_criteria"):
        score += 0.03
        reasons.append("Detailed eligibility text is available.")
    if payload.get("primary_outcomes") or payload.get("secondary_outcomes"):
        score += 0.03
        reasons.append("Endpoint fields are available in the registry record.")
    if payload.get("overall_status") in {"COMPLETED", "ACTIVE_NOT_RECRUITING"}:
        score += 0.03
        reasons.append("The trial status suggests a mature registry record.")
    return _clamp_score(score), reasons


def _score_conference_abstract(payload: dict[str, Any]) -> tuple[float, list[str]]:
    score = 0.58
    reasons = ["Conference abstract or proceedings evidence from a scholarly index."]
    if payload.get("conference_series"):
        score += 0.04
        reasons.append("A target conference series was identified explicitly.")
    if payload.get("abstract"):
        score += 0.05
        reasons.append("Abstract text is available for direct inspection.")
    if payload.get("doi"):
        score += 0.03
        reasons.append("A DOI is available for citation or follow-up.")
    if payload.get("presentation_type"):
        score += 0.02
        reasons.append("Presentation format metadata is available.")
    if str(payload.get("source") or "").lower() == "europe_pmc":
        score += 0.02
        reasons.append("The record is available through a biomedical literature index.")
    return _clamp_score(score), reasons


def evidence_quality_fields(payload: dict[str, Any]) -> dict[str, Any]:
    source = str(payload.get("source") or "").lower()
    if source == "pubmed":
        score, reasons = _score_pubmed(payload)
    elif source == "medrxiv":
        score, reasons = _score_medrxiv(payload)
    elif source == "openfda":
        score, reasons = _score_openfda(payload)
    elif source == "clinicaltrials_gov":
        score, reasons = _score_clinicaltrials(payload)
    elif source == "europe_pmc":
        score, reasons = _score_conference_abstract(payload)
    else:
        score, reasons = 0.5, ["Evidence source type is not explicitly ranked, so a neutral baseline was used."]

    if score >= 0.85:
        tier = "high"
    elif score >= 0.7:
        tier = "medium_high"
    elif score >= 0.55:
        tier = "medium"
    else:
        tier = "low"

    return {
        "evidence_quality_tier": tier,
        "evidence_quality_score": score,
        "evidence_quality_reason": " ".join(reasons),
    }


def annotate_evidence_quality(items: list[dict[str, Any]], *, sort_desc: bool = True) -> list[dict[str, Any]]:
    annotated: list[tuple[int, dict[str, Any]]] = []
    for index, item in enumerate(items):
        enriched = dict(item)
        enriched.update(evidence_quality_fields(enriched))
        annotated.append((index, enriched))

    if sort_desc:
        annotated.sort(
            key=lambda pair: (
                -float(pair[1].get("evidence_quality_score", 0)),
                pair[0],
            )
        )
    return [item for _, item in annotated]


def summarize_evidence_quality(items: list[dict[str, Any]]) -> dict[str, Any]:
    if not items:
        return {
            "document_count": 0,
            "average_score": None,
            "highest_tier": None,
            "counts_by_tier": {},
        }

    counter = Counter(str(item.get("evidence_quality_tier") or "unknown") for item in items)
    scores = [float(item["evidence_quality_score"]) for item in items if isinstance(item.get("evidence_quality_score"), (float, int))]
    ordered_tiers = ["high", "medium_high", "medium", "low", "unknown"]
    highest_tier = next((tier for tier in ordered_tiers if counter.get(tier)), None)
    return {
        "document_count": len(items),
        "average_score": round(sum(scores) / len(scores), 2) if scores else None,
        "highest_tier": highest_tier,
        "counts_by_tier": {tier: counter[tier] for tier in ordered_tiers if counter.get(tier)},
    }
