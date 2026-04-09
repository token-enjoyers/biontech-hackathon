from __future__ import annotations

from copy import deepcopy
from typing import Any


TOOL_CATALOG: dict[str, dict[str, Any]] = {
    "describe_tools": {
        "category": "meta",
        "family": "meta",
        "output_kind": "raw",
        "stability": "stable",
        "workflow_position": "primary",
        "canonical_parameters": ["tool_names", "category", "output_kind"],
        "parameter_aliases": {},
        "requires_identifiers": [],
        "use_when": [
            "You are unsure which MCP tool to call next.",
            "You need a machine-readable tool routing guide.",
        ],
        "avoid_when": [
            "You already know the exact tool to call.",
        ],
        "typical_next_tools": [
            "search_trials",
            "search_publications",
            "search_preprints",
            "search_approved_drugs",
        ],
    },
    "search_trials": {
        "category": "discovery",
        "family": "trials",
        "output_kind": "raw",
        "stability": "stable",
        "workflow_position": "primary",
        "canonical_parameters": ["query", "term", "indication", "phase", "status", "sponsor", "intervention", "max_results"],
        "parameter_aliases": {"condition": "indication", "term": "query"},
        "requires_identifiers": [],
        "use_when": [
            "You need candidate clinical trials for a disease area.",
            "You need to resolve a named clinical trial, study alias, or acronym into trial records.",
            "You want to discover competitors before deeper analysis.",
        ],
        "avoid_when": [
            "You already have an NCT ID and need full study details.",
            "The user asks for latest publications or preprints and you have not called literature tools yet.",
        ],
        "typical_next_tools": [
            "get_trial_details",
            "get_trial_timelines",
            "compare_trials",
            "link_trial_evidence",
        ],
    },
    "get_trial_details": {
        "category": "evidence",
        "family": "trials",
        "output_kind": "raw",
        "stability": "stable",
        "workflow_position": "secondary",
        "canonical_parameters": ["nct_id"],
        "parameter_aliases": {},
        "requires_identifiers": ["nct_id"],
        "use_when": [
            "You already know the trial NCT ID.",
            "You need eligibility, arms, conditions, or other detailed fields.",
            "You need comparator or control arm labels from one specific study.",
        ],
        "avoid_when": [
            "You are still searching broadly and do not have a trial identifier yet.",
        ],
        "typical_next_tools": [
            "compare_trials",
            "benchmark_trial_design",
            "benchmark_eligibility_criteria",
            "link_trial_evidence",
        ],
    },
    "get_trial_timelines": {
        "category": "analysis",
        "family": "trials",
        "output_kind": "derived",
        "stability": "stable",
        "workflow_position": "secondary",
        "canonical_parameters": ["indication", "sponsor", "phase", "status", "max_results"],
        "parameter_aliases": {"condition": "indication"},
        "requires_identifiers": [],
        "use_when": [
            "You need start dates, completion dates, or enrollment timing.",
            "You want to compare development pace across studies.",
        ],
        "avoid_when": [
            "You need eligibility or arm-level design detail.",
        ],
        "typical_next_tools": [
            "get_recruitment_velocity",
            "forecast_readouts",
        ],
    },
    "search_publications": {
        "category": "evidence",
        "family": "publications",
        "output_kind": "raw",
        "stability": "stable",
        "workflow_position": "primary",
        "canonical_parameters": ["query", "indication", "intervention", "term", "nct_id", "year_from", "max_results"],
        "parameter_aliases": {"term": "query"},
        "requires_identifiers": [],
        "use_when": [
            "You need peer-reviewed literature or PubMed evidence.",
            "You want publications linked to a mechanism, indication, or trial.",
            "The user asks for the latest publications on a named clinical trial after you have resolved the trial identity.",
        ],
        "avoid_when": [
            "You want unpublished or early-stage evidence only.",
        ],
        "typical_next_tools": [
            "search_preprints",
            "summarize_safety_signals",
            "link_trial_evidence",
        ],
    },
    "search_preprints": {
        "category": "evidence",
        "family": "publications",
        "output_kind": "raw",
        "stability": "stable",
        "workflow_position": "secondary",
        "canonical_parameters": ["query", "indication", "intervention", "term", "nct_id", "year_from", "max_results"],
        "parameter_aliases": {"term": "query"},
        "requires_identifiers": [],
        "use_when": [
            "You need emerging evidence before peer review.",
            "You want early competitive or translational signals.",
            "The user asks for newer preprints tied to a named clinical trial after you have resolved the trial identity.",
        ],
        "avoid_when": [
            "You need established peer-reviewed evidence first.",
        ],
        "typical_next_tools": [
            "search_publications",
            "summarize_safety_signals",
            "watch_indication_signals",
        ],
    },
    "search_conference_abstracts": {
        "category": "evidence",
        "family": "conferences",
        "output_kind": "raw",
        "stability": "stable",
        "workflow_position": "primary",
        "canonical_parameters": [
            "query",
            "indication",
            "intervention",
            "term",
            "nct_id",
            "conference_series",
            "year_from",
            "max_results",
        ],
        "parameter_aliases": {"term": "query"},
        "requires_identifiers": [],
        "use_when": [
            "You need early congress signals before journal publication.",
            "You want ASCO, AACR, ESMO, or SITC abstract-like evidence for a mechanism, indication, or trial.",
        ],
        "avoid_when": [
            "You only need peer-reviewed literature and do not want conference-stage evidence.",
        ],
        "typical_next_tools": [
            "search_publications",
            "get_document_passages",
            "verify_claim_evidence",
        ],
    },
    "search_approved_drugs": {
        "category": "evidence",
        "family": "drugs",
        "output_kind": "raw",
        "stability": "stable",
        "workflow_position": "primary",
        "canonical_parameters": ["indication", "sponsor", "intervention", "max_results"],
        "parameter_aliases": {},
        "requires_identifiers": [],
        "use_when": [
            "You need approved standard-of-care or label information.",
            "You want sponsor, mechanism, pharmacology, or safety fields from marketed products.",
        ],
        "avoid_when": [
            "You are searching investigational trials rather than approved products.",
        ],
        "typical_next_tools": [
            "summarize_safety_signals",
            "watch_indication_signals",
        ],
    },
    "compare_trials": {
        "category": "analysis",
        "family": "trials",
        "output_kind": "derived",
        "stability": "stable",
        "workflow_position": "secondary",
        "canonical_parameters": ["nct_ids"],
        "parameter_aliases": {},
        "requires_identifiers": ["nct_ids"],
        "use_when": [
            "You already have 2-5 NCT IDs and want a side-by-side comparison.",
        ],
        "avoid_when": [
            "You still need to discover candidate trials first.",
        ],
        "typical_next_tools": [
            "get_trial_details",
            "benchmark_trial_design",
        ],
    },
    "get_trial_density": {
        "category": "analysis",
        "family": "trials",
        "output_kind": "derived",
        "stability": "stable",
        "workflow_position": "secondary",
        "canonical_parameters": ["indication", "group_by", "status"],
        "parameter_aliases": {},
        "requires_identifiers": [],
        "use_when": [
            "You need a quick count distribution by phase, sponsor, or intervention type.",
        ],
        "avoid_when": [
            "You need detailed evidence records rather than counts.",
        ],
        "typical_next_tools": [
            "competitive_landscape",
            "analyze_competition_gaps",
        ],
    },
    "find_whitespaces": {
        "category": "analysis",
        "family": "trials",
        "output_kind": "heuristic",
        "stability": "deprecated",
        "workflow_position": "optional",
        "canonical_parameters": ["indication", "include_terminated"],
        "parameter_aliases": {},
        "requires_identifiers": [],
        "use_when": [
            "Backward-compatibility alias for analyze_competition_gaps.",
        ],
        "avoid_when": [
            "Use analyze_competition_gaps for new integrations.",
        ],
        "typical_next_tools": [
            "analyze_competition_gaps",
        ],
        "deprecated": True,
        "replacement_tool": "analyze_competition_gaps",
    },
    "analyze_competition_gaps": {
        "category": "analysis",
        "family": "trials",
        "output_kind": "heuristic",
        "stability": "stable",
        "workflow_position": "optional",
        "canonical_parameters": ["indication", "include_terminated"],
        "parameter_aliases": {},
        "requires_identifiers": [],
        "use_when": [
            "You want a gap analysis that mixes density and terminated-trial heuristics.",
        ],
        "avoid_when": [
            "You need raw evidence without server-side gap scoring.",
        ],
        "typical_next_tools": [
            "search_trials",
            "get_trial_details",
            "benchmark_trial_design",
        ],
    },
    "competitive_landscape": {
        "category": "analysis",
        "family": "trials",
        "output_kind": "derived",
        "stability": "stable",
        "workflow_position": "secondary",
        "canonical_parameters": ["indication", "phase", "status"],
        "parameter_aliases": {},
        "requires_identifiers": [],
        "use_when": [
            "You need sponsor and mechanism concentration in one indication.",
        ],
        "avoid_when": [
            "You need raw trial rows rather than an aggregated market snapshot.",
        ],
        "typical_next_tools": [
            "track_competitor_assets",
            "analyze_competition_gaps",
        ],
    },
    "get_recruitment_velocity": {
        "category": "analysis",
        "family": "trials",
        "output_kind": "derived",
        "stability": "stable",
        "workflow_position": "secondary",
        "canonical_parameters": ["indication", "phase", "sponsor"],
        "parameter_aliases": {},
        "requires_identifiers": [],
        "use_when": [
            "You need an enrollment-per-month estimate from available timelines.",
        ],
        "avoid_when": [
            "You need raw dates only without server-side rate calculations.",
        ],
        "typical_next_tools": [
            "get_trial_timelines",
            "forecast_readouts",
        ],
    },
    "suggest_trial_design": {
        "category": "recommendation",
        "family": "trials",
        "output_kind": "heuristic",
        "stability": "stable",
        "workflow_position": "optional",
        "canonical_parameters": ["indication", "mechanism"],
        "parameter_aliases": {},
        "requires_identifiers": [],
        "use_when": [
            "The user explicitly wants a draft design recommendation.",
        ],
        "avoid_when": [
            "You need raw evidence or want the LLM to do the synthesis itself.",
        ],
        "typical_next_tools": [
            "search_trials",
            "search_publications",
            "benchmark_trial_design",
        ],
    },
    "suggest_patient_profile": {
        "category": "recommendation",
        "family": "trials",
        "output_kind": "heuristic",
        "stability": "stable",
        "workflow_position": "optional",
        "canonical_parameters": ["indication", "mechanism", "biomarker"],
        "parameter_aliases": {},
        "requires_identifiers": [],
        "use_when": [
            "The user explicitly wants a draft target patient profile.",
        ],
        "avoid_when": [
            "You need source evidence rather than a server-side recommendation.",
        ],
        "typical_next_tools": [
            "benchmark_eligibility_criteria",
            "analyze_patient_segments",
            "search_publications",
        ],
    },
    "benchmark_trial_design": {
        "category": "analysis",
        "family": "trials",
        "output_kind": "derived",
        "stability": "stable",
        "workflow_position": "secondary",
        "canonical_parameters": ["indication", "phase", "mechanism", "sponsor"],
        "parameter_aliases": {},
        "requires_identifiers": [],
        "use_when": [
            "You want common design patterns across comparable trials.",
        ],
        "avoid_when": [
            "You need raw detail records instead of a benchmark summary.",
        ],
        "typical_next_tools": [
            "benchmark_eligibility_criteria",
            "benchmark_endpoints",
        ],
    },
    "benchmark_eligibility_criteria": {
        "category": "analysis",
        "family": "trials",
        "output_kind": "derived",
        "stability": "stable",
        "workflow_position": "secondary",
        "canonical_parameters": ["indication", "phase", "mechanism"],
        "parameter_aliases": {},
        "requires_identifiers": [],
        "use_when": [
            "You want recurring inclusion or exclusion patterns across similar trials.",
        ],
        "avoid_when": [
            "You need full criteria text for individual studies.",
        ],
        "typical_next_tools": [
            "get_trial_details",
            "suggest_patient_profile",
        ],
    },
    "benchmark_endpoints": {
        "category": "analysis",
        "family": "trials",
        "output_kind": "derived",
        "stability": "stable",
        "workflow_position": "secondary",
        "canonical_parameters": ["indication", "phase", "mechanism"],
        "parameter_aliases": {},
        "requires_identifiers": [],
        "use_when": [
            "You want endpoint categories and examples across similar studies.",
        ],
        "avoid_when": [
            "You need the exact endpoint text from one specific trial.",
        ],
        "typical_next_tools": [
            "get_trial_details",
            "benchmark_trial_design",
        ],
    },
    "link_trial_evidence": {
        "category": "analysis",
        "family": "cross_source",
        "output_kind": "derived",
        "stability": "stable",
        "workflow_position": "secondary",
        "canonical_parameters": ["nct_id", "include_preprints", "include_approvals"],
        "parameter_aliases": {},
        "requires_identifiers": ["nct_id"],
        "use_when": [
            "You want a quick cross-source bundle for one known trial.",
            "You already resolved a named study to an NCT ID and need latest publications or preprints connected to that trial.",
        ],
        "avoid_when": [
            "You need exact citation matching rather than query-based associations.",
            "You have not resolved the trial identity to an NCT ID yet.",
        ],
        "typical_next_tools": [
            "search_publications",
            "search_preprints",
            "search_approved_drugs",
        ],
    },
    "analyze_patient_segments": {
        "category": "analysis",
        "family": "trials",
        "output_kind": "derived",
        "stability": "stable",
        "workflow_position": "secondary",
        "canonical_parameters": ["indication", "phase", "mechanism"],
        "parameter_aliases": {},
        "requires_identifiers": [],
        "use_when": [
            "You need biomarker, line-of-therapy, or disease-stage segment patterns.",
        ],
        "avoid_when": [
            "You need raw trial rows instead of segment counts.",
        ],
        "typical_next_tools": [
            "benchmark_eligibility_criteria",
            "suggest_patient_profile",
        ],
    },
    "forecast_readouts": {
        "category": "analysis",
        "family": "trials",
        "output_kind": "heuristic",
        "stability": "stable",
        "workflow_position": "optional",
        "canonical_parameters": ["indication", "phase", "sponsor", "months_ahead"],
        "parameter_aliases": {},
        "requires_identifiers": [],
        "use_when": [
            "You need an estimate of upcoming readouts based on known or inferred dates.",
        ],
        "avoid_when": [
            "You need only registered dates with no forecast logic.",
        ],
        "typical_next_tools": [
            "get_trial_timelines",
            "watch_indication_signals",
        ],
    },
    "track_competitor_assets": {
        "category": "analysis",
        "family": "portfolio",
        "output_kind": "derived",
        "stability": "stable",
        "workflow_position": "secondary",
        "canonical_parameters": ["indication", "sponsors", "mechanism"],
        "parameter_aliases": {},
        "requires_identifiers": [],
        "use_when": [
            "You want sponsor-asset groupings within one indication.",
        ],
        "avoid_when": [
            "You need trial-level detail rather than sponsor-level grouping.",
        ],
        "typical_next_tools": [
            "competitive_landscape",
            "search_trials",
        ],
    },
    "summarize_safety_signals": {
        "category": "analysis",
        "family": "cross_source",
        "output_kind": "derived",
        "stability": "stable",
        "workflow_position": "secondary",
        "canonical_parameters": ["indication", "mechanism", "year_from"],
        "parameter_aliases": {},
        "requires_identifiers": [],
        "use_when": [
            "You want recurring safety themes aggregated across sources.",
        ],
        "avoid_when": [
            "You need source-by-source safety evidence without server-side summarization.",
        ],
        "typical_next_tools": [
            "search_publications",
            "search_preprints",
            "search_approved_drugs",
        ],
    },
    "investigator_site_landscape": {
        "category": "analysis",
        "family": "trials",
        "output_kind": "derived",
        "stability": "stable",
        "workflow_position": "secondary",
        "canonical_parameters": ["indication", "phase", "sponsor"],
        "parameter_aliases": {},
        "requires_identifiers": [],
        "use_when": [
            "You want visible site geography or study-official patterns.",
        ],
        "avoid_when": [
            "You need one specific trial's location data only.",
        ],
        "typical_next_tools": [
            "get_trial_details",
        ],
    },
    "watch_indication_signals": {
        "category": "analysis",
        "family": "cross_source",
        "output_kind": "derived",
        "stability": "stable",
        "workflow_position": "secondary",
        "canonical_parameters": ["indication", "mechanism", "sponsor", "recent_years", "months_ahead"],
        "parameter_aliases": {},
        "requires_identifiers": [],
        "use_when": [
            "You want a compact multi-source watchlist snapshot for an indication.",
        ],
        "avoid_when": [
            "You want raw source records and full LLM-driven synthesis instead of a packaged snapshot.",
        ],
        "typical_next_tools": [
            "search_trials",
            "search_publications",
            "search_preprints",
            "search_approved_drugs",
            "forecast_readouts",
        ],
    },
    "track_indication_changes": {
        "category": "monitoring",
        "family": "cross_source",
        "output_kind": "derived",
        "stability": "stable",
        "workflow_position": "secondary",
        "canonical_parameters": ["indication", "intervention", "sponsor", "since", "recent_years", "include_preprints", "max_results"],
        "parameter_aliases": {},
        "requires_identifiers": [],
        "use_when": [
            "The user asks what changed, what is new, or what appeared since a date.",
            "You need a date-filtered delta view over the currently retrievable records.",
        ],
        "avoid_when": [
            "You only need a current snapshot with no time comparison.",
            "You need a true historical state diff that the current sources cannot reconstruct.",
        ],
        "typical_next_tools": [
            "search_trials",
            "search_publications",
            "search_preprints",
            "verify_claim_evidence",
        ],
    },
    "get_document_passages": {
        "category": "audit",
        "family": "cross_source",
        "output_kind": "derived",
        "stability": "stable",
        "workflow_position": "optional",
        "canonical_parameters": ["query", "indication", "intervention", "nct_id", "include_preprints", "include_approvals", "max_documents", "max_passages"],
        "parameter_aliases": {},
        "requires_identifiers": [],
        "use_when": [
            "The user explicitly asks where a statement is supported or wants the relevant passage text.",
            "You want a passage-level audit trail instead of only document-level links.",
        ],
        "avoid_when": [
            "You only need high-level source discovery with no passage drilldown.",
        ],
        "typical_next_tools": [
            "verify_claim_evidence",
            "extract_structured_evidence",
        ],
    },
    "extract_structured_evidence": {
        "category": "audit",
        "family": "cross_source",
        "output_kind": "derived",
        "stability": "stable",
        "workflow_position": "optional",
        "canonical_parameters": ["query", "indication", "intervention", "nct_id", "include_preprints", "include_approvals", "max_documents"],
        "parameter_aliases": {},
        "requires_identifiers": [],
        "use_when": [
            "The user explicitly wants atomic findings such as endpoints, percentages, durations, hazard ratios, or biomarker mentions.",
            "You want a structured evidence layer before doing LLM-side synthesis.",
        ],
        "avoid_when": [
            "You only need raw documents or links without server-side extraction.",
        ],
        "typical_next_tools": [
            "get_document_passages",
            "verify_claim_evidence",
        ],
    },
    "verify_claim_evidence": {
        "category": "audit",
        "family": "cross_source",
        "output_kind": "derived",
        "stability": "stable",
        "workflow_position": "optional",
        "canonical_parameters": ["claim", "indication", "intervention", "nct_id", "include_preprints", "include_approvals", "max_documents", "max_passages"],
        "parameter_aliases": {},
        "requires_identifiers": [],
        "use_when": [
            "The user explicitly asks whether a claim is supported, contradicted, or where the evidence lies.",
            "You want a claim-to-passage binding over the currently available evidence.",
        ],
        "avoid_when": [
            "You only need source discovery or a generic overview with no claim audit.",
        ],
        "typical_next_tools": [
            "get_document_passages",
            "extract_structured_evidence",
        ],
    },
}


OUTPUT_KIND_NOTES = {
    "raw": "This tool returns source-aligned records. Prefer doing synthesis in the LLM layer.",
    "derived": "This tool returns server-side aggregations over source records. Verify with raw tools for high-stakes use.",
    "heuristic": "This tool includes server-side heuristics or recommendations. Treat the result as a draft, not ground truth.",
}


def get_tool_metadata(tool_name: str) -> dict[str, Any]:
    return deepcopy(TOOL_CATALOG.get(tool_name, {}))


def list_tool_metadata(
    *,
    tool_names: list[str] | None = None,
    category: str | None = None,
    output_kind: str | None = None,
) -> list[dict[str, Any]]:
    requested = set(tool_names or [])
    rows: list[dict[str, Any]] = []
    for name, metadata in TOOL_CATALOG.items():
        if requested and name not in requested:
            continue
        if category and metadata.get("category") != category:
            continue
        if output_kind and metadata.get("output_kind") != output_kind:
            continue

        row = get_tool_metadata(name)
        row["tool_name"] = name
        row["source"] = "server_catalog"
        row["interpretation_note"] = OUTPUT_KIND_NOTES.get(metadata.get("output_kind", ""), "")
        rows.append(row)

    rows.sort(key=lambda item: item["tool_name"])
    return rows
