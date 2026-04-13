from __future__ import annotations

import re
from typing import Any

from ._evidence_quality import evidence_quality_fields
from ._evidence_refs import document_ref_from_payload
from ._intelligence import extract_biomarkers

CLAIM_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "into",
    "about",
    "show",
    "shows",
    "showed",
    "patients",
    "patient",
    "study",
    "trial",
    "data",
    "evidence",
    "where",
    "what",
    "which",
    "after",
    "before",
    "than",
    "have",
    "has",
    "were",
    "was",
    "are",
    "is",
    "can",
    "may",
}

POSITIVE_CUES = ("improved", "improvement", "promising", "benefit", "respond", "response", "longer", "manageable")
NEGATIVE_CUES = ("worse", "terminated", "insufficient efficacy", "toxicity", "adverse", "warning", "risk", "colitis", "pneumonitis")

RESULT_PATTERNS = (
    ("ORR", "efficacy", "response_rate", re.compile(r"\b(?:ORR|objective response rate)\b[^.]{0,80}?(\d{1,3}(?:\.\d+)?)\s*%", re.I), "%"),
    ("PFS", "efficacy", "median_duration", re.compile(r"\b(?:PFS|progression[- ]free survival)\b[^.]{0,80}?(\d{1,3}(?:\.\d+)?)\s*(months?|mos?)", re.I), "months"),
    ("OS", "efficacy", "median_duration", re.compile(r"\b(?:OS|overall survival)\b[^.]{0,80}?(\d{1,3}(?:\.\d+)?)\s*(months?|mos?)", re.I), "months"),
    ("DOR", "efficacy", "median_duration", re.compile(r"\b(?:DOR|duration of response)\b[^.]{0,80}?(\d{1,3}(?:\.\d+)?)\s*(months?|mos?)", re.I), "months"),
    ("Grade 3+ AEs", "safety", "adverse_event_rate", re.compile(r"\bgrade\s*3\+?.{0,40}?(?:AEs?|adverse events?)\b[^.]{0,60}?(\d{1,3}(?:\.\d+)?)\s*%", re.I), "%"),
    ("Hazard ratio", "efficacy", "hazard_ratio", re.compile(r"\b(?:hazard ratio|HR)\b[^0-9]{0,20}(\d(?:\.\d+)?)", re.I), "ratio"),
    ("P value", "statistics", "p_value", re.compile(r"\bp\s*[=<]\s*(0?\.\d+)\b", re.I), "p"),
    ("Sample size", "design", "sample_size", re.compile(r"\bn\s*=\s*(\d{1,4})\b", re.I), "patients"),
)


def tokenize_query(text: str) -> list[str]:
    tokens = re.findall(r"[a-zA-Z0-9\-+]{3,}", text.lower())
    return [token for token in tokens if token not in CLAIM_STOPWORDS]


def split_sentences(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", text or "").strip()
    if not normalized:
        return []
    parts = re.split(r"(?<=[.;?!])\s+", normalized)
    return [part.strip() for part in parts if part and len(part.strip()) >= 20]


def document_sections(payload: dict[str, Any]) -> list[dict[str, str]]:
    sections: list[dict[str, str]] = []

    def add_section(name: str, value: Any) -> None:
        if isinstance(value, str) and value.strip():
            sections.append({"section": name, "text": value.strip()})
        elif isinstance(value, list):
            joined = " ".join(item.strip() for item in value if isinstance(item, str) and item.strip())
            if joined:
                sections.append({"section": name, "text": joined})

    add_section("title", payload.get("title") or payload.get("brief_title"))
    add_section("official_title", payload.get("official_title"))
    add_section("abstract", payload.get("abstract"))
    add_section("primary_outcomes", payload.get("primary_outcomes"))
    add_section("secondary_outcomes", payload.get("secondary_outcomes"))
    add_section("eligibility_criteria", payload.get("eligibility_criteria"))
    add_section("mechanism_of_action", payload.get("mechanism_of_action"))
    add_section("clinical_studies_summary", payload.get("clinical_studies_summary"))
    add_section("warnings", payload.get("warnings"))
    add_section("adverse_reactions", payload.get("adverse_reactions"))
    add_section("indication", payload.get("indication"))
    return sections


def build_document(payload: dict[str, Any]) -> dict[str, Any]:
    ref = document_ref_from_payload(payload)
    identifier = None
    label = None
    url = None
    if ref is not None:
        identifier = ref["id"]
        label = ref["label"]
        url = ref["url"]
    else:
        identifier = str(payload.get("id") or payload.get("title") or payload.get("brief_title") or "unknown")
        label = str(payload.get("title") or payload.get("brief_title") or identifier)

    document = {
        "source": payload.get("source"),
        "document_id": identifier,
        "document_label": label,
        "document_url": url,
        "sections": document_sections(payload),
        "payload": payload,
    }
    document.update(evidence_quality_fields(payload))
    return document


def passage_relevance(passage: str, query: str) -> float:
    passage_lower = passage.lower()
    query_lower = query.lower().strip()
    if not query_lower:
        return 0.0
    terms = tokenize_query(query_lower)
    if not terms:
        return 0.0
    overlap = sum(1 for term in terms if term in passage_lower)
    score = overlap / len(terms)
    if query_lower in passage_lower:
        score += 0.6
    if any(cue in passage_lower for cue in POSITIVE_CUES + NEGATIVE_CUES):
        score += 0.1
    return round(score, 3)


def find_matching_passages(
    document: dict[str, Any],
    *,
    query: str,
    max_passages: int = 3,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for section in document.get("sections", []):
        section_name = section.get("section") or "text"
        for sentence in split_sentences(section.get("text", "")):
            score = passage_relevance(sentence, query)
            if score <= 0:
                continue
            matches.append(
                {
                    "source": document.get("source"),
                    "document_id": document.get("document_id"),
                    "document_label": document.get("document_label"),
                    "document_url": document.get("document_url"),
                    "section": section_name,
                    "passage": sentence,
                    "relevance_score": score,
                    "evidence_quality_tier": document.get("evidence_quality_tier"),
                    "evidence_quality_score": document.get("evidence_quality_score"),
                }
            )

    matches.sort(key=lambda item: (-item["relevance_score"], -(item.get("evidence_quality_score") or 0), item["document_id"]))
    return matches[:max_passages]


def _claim_overlap(claim: str, passage: str) -> tuple[int, float]:
    claim_terms = list(dict.fromkeys(tokenize_query(claim)))
    if not claim_terms:
        return 0, 0.0

    passage_lower = passage.lower()
    matched_terms = [term for term in claim_terms if term in passage_lower]
    overlap_count = len(matched_terms)
    return overlap_count, overlap_count / len(claim_terms)


def classify_claim_passage(claim: str, passage: str) -> str:
    claim_lower = claim.lower()
    passage_lower = passage.lower()
    claim_positive = any(token in claim_lower for token in POSITIVE_CUES)
    claim_negative = any(token in claim_lower for token in NEGATIVE_CUES)
    passage_positive = any(token in passage_lower for token in POSITIVE_CUES)
    passage_negative = any(token in passage_lower for token in NEGATIVE_CUES)
    overlap_count, overlap_ratio = _claim_overlap(claim, passage)

    if overlap_count == 0:
        return "unclear"

    if claim_positive and passage_negative:
        return "conflicting"
    if claim_negative and passage_positive:
        return "conflicting"
    if claim_positive:
        return "supporting" if passage_positive and overlap_ratio >= 0.4 else "unclear"
    if claim_negative:
        return "supporting" if passage_negative and overlap_ratio >= 0.4 else "unclear"
    if overlap_ratio >= 0.6 and (passage_positive or passage_negative or re.search(r"\d", passage)):
        return "supporting"
    return "unclear"


def extract_structured_findings(document: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    biomarker_seen: set[tuple[str, str]] = set()
    for section in document.get("sections", []):
        section_name = section.get("section") or "text"
        for sentence in split_sentences(section.get("text", "")):
            for endpoint_name, endpoint_type, metric_name, pattern, unit in RESULT_PATTERNS:
                match = pattern.search(sentence)
                if match is None:
                    continue
                value = match.group(1)
                confidence = "high" if re.search(r"\d", sentence) else "medium"
                findings.append(
                    {
                        "source": document.get("source"),
                        "document_id": document.get("document_id"),
                        "document_label": document.get("document_label"),
                        "document_url": document.get("document_url"),
                        "section": section_name,
                        "endpoint_name": endpoint_name,
                        "endpoint_type": endpoint_type,
                        "metric_name": metric_name,
                        "value": value,
                        "unit": unit,
                        "population": ", ".join(extract_biomarkers(sentence)) or None,
                        "direction": "positive" if any(cue in sentence.lower() for cue in POSITIVE_CUES) else "neutral",
                        "confidence": confidence,
                        "evidence_passage": sentence,
                        "evidence_quality_tier": document.get("evidence_quality_tier"),
                        "evidence_quality_score": document.get("evidence_quality_score"),
                    }
                )
            for biomarker in extract_biomarkers(sentence):
                key = (document.get("document_id") or "", biomarker)
                if key in biomarker_seen:
                    continue
                biomarker_seen.add(key)
                findings.append(
                    {
                        "source": document.get("source"),
                        "document_id": document.get("document_id"),
                        "document_label": document.get("document_label"),
                        "document_url": document.get("document_url"),
                        "section": section_name,
                        "endpoint_name": biomarker,
                        "endpoint_type": "biomarker",
                        "metric_name": "mention",
                        "value": biomarker,
                        "unit": None,
                        "population": biomarker,
                        "direction": "neutral",
                        "confidence": "medium",
                        "evidence_passage": sentence,
                        "evidence_quality_tier": document.get("evidence_quality_tier"),
                        "evidence_quality_score": document.get("evidence_quality_score"),
                    }
                )

    findings.sort(
        key=lambda item: (
            -(item.get("evidence_quality_score") or 0),
            item.get("document_id") or "",
            item.get("endpoint_type") or "",
        )
    )
    return findings
