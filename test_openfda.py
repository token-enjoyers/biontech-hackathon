import asyncio
import csv

from Medical_Wizard_MCP.sources.openfda import OpenFDASource

CSV_PATH = "temp-result.csv"
CSV_FIELDS = [
    "query_condition", "query_sponsor", "query_intervention",
    "nct_id", "brief_title", "overall_status", "lead_sponsor",
    "interventions", "route", "product_type",
    "mechanism_of_action", "pharmacodynamics", "pharmacokinetics",
    "clinical_pharmacology", "clinical_studies_summary",
    "dosage_and_administration", "dosage_forms_and_strengths",
    "warnings", "adverse_reactions", "contraindications", "drug_interactions",
]


async def main():
    source = OpenFDASource()
    await source.initialize()

    queries = [
        {"condition": "cancer"},
        {"condition": "oncology"},
        {"condition": "cancer", "intervention": "pembrolizumab"},
        {"condition": "cancer", "sponsor": "Genentech"},
    ]

    all_rows: list[dict] = []

    for q in queries:
        print(f"\n{'='*60}")
        print(f"Query: {q}")
        print("="*60)
        results = await source.search_trials(**q, max_results=3)
        if not results:
            print("  No results.")
        for r in results:
            print(f"\n  [{r.nct_id}] {r.brief_title}")
            print(f"  Status:      {r.overall_status}")
            print(f"  Sponsor:     {r.lead_sponsor}")
            print(f"  Route:       {', '.join(r.route) or 'N/A'}")
            print(f"  MoA:         {(r.mechanism_of_action or 'N/A')[:120]}...")
            all_rows.append({
                "query_condition": q.get("condition", ""),
                "query_sponsor": q.get("sponsor", ""),
                "query_intervention": q.get("intervention", ""),
                "nct_id": r.nct_id,
                "brief_title": r.brief_title,
                "overall_status": r.overall_status,
                "lead_sponsor": r.lead_sponsor,
                "interventions": "; ".join(r.interventions),
                "route": "; ".join(r.route),
                "product_type": r.product_type or "",
                "mechanism_of_action": r.mechanism_of_action or "",
                "pharmacodynamics": r.pharmacodynamics or "",
                "pharmacokinetics": r.pharmacokinetics or "",
                "clinical_pharmacology": r.clinical_pharmacology or "",
                "clinical_studies_summary": r.clinical_studies_summary or "",
                "dosage_and_administration": r.dosage_and_administration or "",
                "dosage_forms_and_strengths": r.dosage_forms_and_strengths or "",
                "warnings": r.warnings or "",
                "adverse_reactions": r.adverse_reactions or "",
                "contraindications": r.contraindications or "",
                "drug_interactions": r.drug_interactions or "",
            })

    await source.close()

    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"\nWrote {len(all_rows)} rows to {CSV_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
