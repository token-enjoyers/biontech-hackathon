from __future__ import annotations

import httpx
import pytest

from Medical_Wizard_MCP.models import TrialSummary
from Medical_Wizard_MCP.sources.openfda import BASE_URL, OpenFDASource


def test_trial_summary_does_not_include_openfda_only_fields() -> None:
    summary = TrialSummary(
        source="clinicaltrials_gov",
        nct_id="NCT12345678",
        brief_title="Example trial",
        phase="Phase 2",
        overall_status="RECRUITING",
        lead_sponsor="BioNTech",
        interventions=["BNT111"],
        primary_outcomes=["ORR"],
        enrollment_count=42,
    )

    payload = summary.model_dump()

    assert "route" not in payload
    assert "product_type" not in payload
    assert "mechanism_of_action" not in payload
    assert "warnings" not in payload


@pytest.mark.asyncio
async def test_openfda_returns_approved_drug_model() -> None:
    label_payload = {
        "results": [
            {
                "openfda": {
                    "application_number": ["BLA123456"],
                    "brand_name": ["ExampleDrug"],
                    "generic_name": ["example-generic"],
                    "manufacturer_name": ["Example Pharma"],
                    "substance_name": ["example-substance"],
                    "route": ["INTRAVENOUS"],
                    "product_type": ["HUMAN PRESCRIPTION DRUG"],
                },
                "mechanism_of_action": ["Blocks example target."],
                "warnings_and_cautions": ["Example warning."],
            }
        ]
    }

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=label_payload)

    source = OpenFDASource()
    source._client = httpx.AsyncClient(
        base_url=BASE_URL,
        transport=httpx.MockTransport(handler),
    )

    results = await source.search_approved_drugs("lung cancer", max_results=3)
    await source.close()

    assert len(results) == 1
    result = results[0]
    assert result.approval_id == "BLA123456"
    assert result.brand_name == "ExampleDrug"
    assert result.generic_name == "example-generic"
    assert result.indication == "lung cancer"
    assert result.sponsor == "Example Pharma"
    assert result.substance_names == ["example-substance"]
    assert result.route == ["INTRAVENOUS"]
    assert result.mechanism_of_action == "Blocks example target."
    assert result.warnings == "Example warning."
