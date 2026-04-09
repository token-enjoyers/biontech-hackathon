from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

from Medical_Wizard_MCP.__main__ import registry
from Medical_Wizard_MCP.tools.drugs import search_approved_drugs
from Medical_Wizard_MCP.tools.publications import search_preprints, search_publications
from Medical_Wizard_MCP.tools.search import get_trial_details, search_trials
from Medical_Wizard_MCP.tools.timelines import get_trial_timelines


def _pretty_json(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True)


def _describe_payload(payload: Any) -> list[str]:
    lines: list[str] = [f"type={type(payload).__name__}"]

    if isinstance(payload, dict):
        lines.append(f"keys={list(payload.keys())}")

        meta = payload.get("_meta")
        if isinstance(meta, dict):
            lines.append(f"_meta_keys={list(meta.keys())}")
            if "source" in meta:
                lines.append(f"meta.source={meta['source']}")
            if "sources" in meta:
                lines.append(f"meta.sources={meta['sources']}")

        results = payload.get("results")
        if isinstance(results, list):
            lines.append(f"results.length={len(results)}")
            if results:
                first = results[0]
                lines.append(f"results.first_item_type={type(first).__name__}")
                if isinstance(first, dict):
                    lines.append(f"results.first_item_keys={list(first.keys())}")

        result = payload.get("result")
        if isinstance(result, dict):
            lines.append(f"result.keys={list(result.keys())}")
        elif result is None and "result" in payload:
            lines.append("result=None")
    elif isinstance(payload, list):
        lines.append(f"length={len(payload)}")
        if payload:
            first = payload[0]
            lines.append(f"first_item_type={type(first).__name__}")
            if isinstance(first, dict):
                lines.append(f"first_item_keys={list(first.keys())}")
    elif isinstance(payload, str):
        lines.append("string_response=True")

    return lines


async def _run_case(
    name: str,
    fn: Callable[..., Awaitable[Any]],
    /,
    **kwargs: Any,
) -> Any:
    print(f"\n{'=' * 80}")
    print(name)
    print(f"args={kwargs}")
    print("=" * 80)

    result = await fn(**kwargs)

    for line in _describe_payload(result):
        print(line)

    print("\nJSON payload:")
    print(_pretty_json(result))
    return result


async def main() -> None:
    try:
        trials = await _run_case(
            "search_trials",
            search_trials,
            condition="lung cancer",
            sponsor="BioNTech",
            max_results=2,
        )

        nct_id = None
        trial_results = trials.get("results") if isinstance(trials, dict) else None
        if isinstance(trial_results, list) and trial_results:
            for item in trial_results:
                if (
                    isinstance(item, dict)
                    and item.get("source") == "clinicaltrials_gov"
                    and isinstance(item.get("nct_id"), str)
                    and item["nct_id"].startswith("NCT")
                ):
                    nct_id = item["nct_id"]
                    break

        if nct_id:
            await _run_case(
                "get_trial_details",
                get_trial_details,
                nct_id=nct_id,
            )
        else:
            print("\nSkipping get_trial_details because search_trials returned no NCT ID.")

        await _run_case(
            "get_trial_timelines",
            get_trial_timelines,
            condition="NSCLC",
            sponsor="Merck",
            max_results=2,
        )

        await _run_case(
            "search_publications",
            search_publications,
            query="mRNA cancer vaccine NSCLC",
            year_from=2023,
            max_results=2,
        )

        await _run_case(
            "search_preprints",
            search_preprints,
            query="mRNA cancer vaccine GBM",
            year_from=2024,
            max_results=2,
        )

        await _run_case(
            "search_approved_drugs",
            search_approved_drugs,
            indication="NSCLC",
            sponsor="Merck",
            max_results=2,
        )
    finally:
        await registry.close_all()


if __name__ == "__main__":
    asyncio.run(main())
