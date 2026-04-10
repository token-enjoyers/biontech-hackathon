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
            "Several tools overlap and you need the canonical choice before calling anything else.",
        ],
        "avoid_when": [
            "You already know the exact tool to call.",
            "You need biomedical evidence rather than metadata about the tool surface itself.",
        ],
        "decision_boundary": "Use this as the router when the question could fit multiple tools. Do not use it as a substitute for trials, literature, conference, safety, or burden evidence.",
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
            "You want conference-stage evidence rather than peer-reviewed journal records.",
            "You want one bundled asset-centric brief across trials, publications, conferences, and approvals.",
        ],
        "decision_boundary": "Use this for PubMed records only. If the user wants preprints call search_preprints; for congress evidence call search_conference_abstracts; for a one-trial bundle call link_trial_evidence; for an asset-wide bundle call asset_dossier.",
        "choose_instead_of": ["search_preprints", "search_conference_abstracts", "link_trial_evidence", "asset_dossier"],
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
            "You want an asset-wide multi-source brief rather than preprint records only.",
        ],
        "decision_boundary": "Use this for emerging, non-peer-reviewed evidence. If the user needs journal evidence first call search_publications; for congress evidence call search_conference_abstracts; for a bundled asset brief call asset_dossier.",
        "choose_instead_of": ["search_publications", "search_conference_abstracts", "asset_dossier"],
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
            "You want a full cross-source asset brief rather than conference evidence only.",
        ],
        "decision_boundary": "Use this only for conference-stage evidence. The tool now returns both strong and related conference matches, so downstream summaries should distinguish clearly supported abstracts from broader query-adjacent signals. If the user wants journal records call search_publications; for preprints call search_preprints; for an asset-centric bundle call asset_dossier.",
        "choose_instead_of": ["search_publications", "search_preprints", "asset_dossier"],
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
            "You want a disease-level strategy proxy rather than raw approved-drug records.",
        ],
        "decision_boundary": "Use this for raw approved-drug or label context only. If the user wants a strategic opportunity proxy that mixes burden, visible competition, and treatment scarcity, use estimate_commercial_opportunity_proxy instead.",
        "choose_instead_of": ["estimate_commercial_opportunity_proxy"],
        "typical_next_tools": [
            "summarize_safety_signals",
            "watch_indication_signals",
        ],
    },
    "search_oncology_burden": {
        "category": "discovery",
        "family": "oncology_burden",
        "output_kind": "raw",
        "stability": "stable",
        "workflow_position": "primary",
        "canonical_parameters": [
            "site",
            "country",
            "sex",
            "indicator",
            "year",
            "age_min",
            "age_max",
            "max_results",
        ],
        "parameter_aliases": {"indication": "site"},
        "requires_identifiers": [],
        "use_when": [
            "You need oncology burden rows such as cases or deaths by cancer entity, country, sex, year, or age band.",
            "You want epidemiology-style burden data rather than trials, publications, or approved drugs.",
        ],
        "avoid_when": [
            "You need trial, publication, or approved-drug evidence instead of burden records.",
            "You want burden compared directly against clinical-trial geography or site footprint.",
            "You want a composite commercial-style proxy rather than raw burden rows.",
        ],
        "decision_boundary": "Use this for raw epidemiology rows only. If the question is about where burden is high relative to visible trial activity, call burden_vs_trial_footprint instead. If the question asks for a commercial-style prioritization proxy, call estimate_commercial_opportunity_proxy instead.",
        "choose_instead_of": ["burden_vs_trial_footprint", "estimate_commercial_opportunity_proxy"],
        "typical_next_tools": [
            "search_trials",
            "search_publications",
            "search_approved_drugs",
        ],
    },
    "burden_vs_trial_footprint": {
        "category": "analysis",
        "family": "cross_source",
        "output_kind": "derived",
        "stability": "stable",
        "workflow_position": "secondary",
        "canonical_parameters": ["indication", "indicator", "year", "phase", "sponsor", "status", "max_results"],
        "parameter_aliases": {},
        "requires_identifiers": [],
        "use_when": [
            "You want countries ranked by high burden and low visible trial-site footprint.",
            "You need an indication-level opportunity scan that combines epidemiology with visible clinical-operations presence.",
        ],
        "avoid_when": [
            "You only need raw burden rows with no trial comparison.",
            "You only need raw site geography from trials with no epidemiology layer.",
            "You want a composite strategic proxy that also includes approved-treatment scarcity.",
        ],
        "decision_boundary": "Use this when the question is explicitly about epidemiology versus visible study footprint. For raw burden rows use search_oncology_burden; for raw site or investigator geography use investigator_site_landscape; for a broader commercial-style prioritization proxy use estimate_commercial_opportunity_proxy.",
        "choose_instead_of": ["search_oncology_burden", "investigator_site_landscape", "estimate_commercial_opportunity_proxy"],
        "typical_next_tools": [
            "search_oncology_burden",
            "investigator_site_landscape",
            "search_trials",
        ],
    },
    "estimate_commercial_opportunity_proxy": {
        "category": "analysis",
        "family": "commercial_proxy",
        "output_kind": "heuristic",
        "stability": "stable",
        "workflow_position": "optional",
        "canonical_parameters": ["indication", "indicator", "year", "max_results"],
        "parameter_aliases": {},
        "requires_identifiers": [],
        "use_when": [
            "You want a rough strategy proxy for commercial attractiveness using disease burden, treatment scarcity, and visible competition.",
            "You need a prioritization aid when true pricing, reimbursement, sales, or access data are not available.",
        ],
        "avoid_when": [
            "You need real revenue estimates, market size, pricing, or reimbursement analysis.",
            "You only need raw burden, trial, or approved-drug records without a composite score.",
        ],
        "decision_boundary": "Use this only for heuristic strategic prioritization. For raw epidemiology use search_oncology_burden; for burden versus site footprint use burden_vs_trial_footprint; for actual commercial modeling you need new sources beyond the current MCP.",
        "choose_instead_of": ["search_oncology_burden", "burden_vs_trial_footprint", "search_approved_drugs"],
        "typical_next_tools": [
            "burden_vs_trial_footprint",
            "search_approved_drugs",
            "competitive_landscape",
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
    "screen_trial_candidates": {
        "category": "analysis",
        "family": "trials",
        "output_kind": "derived",
        "stability": "stable",
        "workflow_position": "secondary",
        "canonical_parameters": [
            "indication",
            "phase",
            "mechanism",
            "sponsor",
            "patient_segment",
            "include_terminated",
            "allow_combination_phases",
            "max_results",
        ],
        "parameter_aliases": {},
        "requires_identifiers": [],
        "use_when": [
            "You need a narrow, high-precision trial set such as all phase 3 bispecific trials in an indication.",
            "Hallucination risk matters more than broad recall.",
            "You want explicit inclusion and exclusion reasons before writing prose.",
        ],
        "avoid_when": [
            "You are still exploring broadly and do not yet know the exact filters that matter.",
            "You need a lightweight landscape summary rather than an auditable include/exclude screen.",
        ],
        "decision_boundary": "Use this instead of free-form trial synthesis when the final answer should come from deterministic screening against verified detail records. Treat `included_trials` as the primary answer set, noting from `decision_reasons` whether an item is an exact text-confirmed match or a strong detail-verified candidate; `related_trials` still need more follow-up.",
        "choose_instead_of": ["search_trials", "competitive_landscape", "track_competitor_assets"],
        "typical_next_tools": [
            "get_trial_details",
            "verify_claim_evidence",
            "link_trial_evidence",
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
            "You want an asset- or sponsor-level brief spanning multiple trials rather than one known trial.",
        ],
        "decision_boundary": "Use this for one known NCT ID. If the user cares about a named asset, therapy, or sponsor across multiple studies, call asset_dossier instead.",
        "choose_instead_of": ["asset_dossier"],
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
            "You want publications, conference signals, or approved-drug context in the same answer.",
        ],
        "decision_boundary": "Use this for trial-derived sponsor/asset grouping only. If the user wants one richer, cross-source asset brief, use asset_dossier instead.",
        "choose_instead_of": ["asset_dossier", "search_trials"],
        "typical_next_tools": [
            "competitive_landscape",
            "search_trials",
        ],
    },
    "asset_dossier": {
        "category": "analysis",
        "family": "portfolio",
        "output_kind": "derived",
        "stability": "stable",
        "workflow_position": "secondary",
        "canonical_parameters": ["asset", "indication", "sponsor", "year_from", "include_preprints", "include_conference_signals", "include_approvals"],
        "parameter_aliases": {},
        "requires_identifiers": [],
        "use_when": [
            "You want one asset-centric brief that bundles trials, publications, preprints, conference signals, and optional approved-drug context.",
            "The user is asking about one named therapy, program, or asset rather than a broad indication.",
        ],
        "avoid_when": [
            "You only need raw records from one source family.",
            "You only have one specific NCT ID and want a trial-level evidence bundle.",
        ],
        "decision_boundary": "Use this for asset- or program-level synthesis across multiple sources. For one known trial use link_trial_evidence; for indication-wide watchlists use watch_indication_signals; for sponsor/asset grouping without literature use track_competitor_assets.",
        "choose_instead_of": ["link_trial_evidence", "watch_indication_signals", "track_competitor_assets"],
        "typical_next_tools": [
            "search_trials",
            "search_publications",
            "search_conference_abstracts",
            "search_approved_drugs",
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
            "The user is asking about one named asset or sponsor program rather than the whole indication.",
        ],
        "decision_boundary": "Use this for indication-level monitoring across sources. If the ask is centered on one asset or therapy name, use asset_dossier instead.",
        "choose_instead_of": ["asset_dossier", "track_indication_changes"],
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
    "raw": "This tool returns source-aligned records. Prefer these when precision, source review, or custom LLM synthesis matters most.",
    "derived": "This tool returns server-side aggregations over source records. Use it for faster orientation, then verify with raw tools for high-stakes use.",
    "heuristic": "This tool includes server-side heuristics or recommendations. Treat the output as a draft starting point, not ground truth.",
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
