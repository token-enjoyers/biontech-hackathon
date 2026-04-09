import asyncio
import csv

from Medical_Wizard_MCP.sources.openfda import OpenFDASource

CSV_PATH = "temp-result.csv"
CSV_FIELDS = [
    "query_condition", "query_sponsor", "query_intervention",
    "approval_id", "brand_name", "generic_name", "indication", "sponsor",
    "substance_names", "route", "product_type",
    "mechanism_of_action", "pharmacodynamics", "pharmacokinetics",
    "clinical_pharmacology", "clinical_studies_summary",
    "dosage_and_administration", "dosage_forms_and_strengths",
    "warnings", "adverse_reactions", "contraindications", "drug_interactions",
]


async def main():
    source = OpenFDASource()
    await source.initialize()

    queries = [
        {"indication": "cancer"},
        {"indication": "oncology"},
        {"indication": "cancer", "intervention": "pembrolizumab"},
        {"indication": "cancer", "sponsor": "Genentech"},
    ]

    all_rows: list[dict] = []

    for q in queries:
        print(f"\n{'='*60}")
        print(f"Query: {q}")
        print("="*60)
        results = await source.search_approved_drugs(**q, max_results=3)
        if not results:
            print("  No results.")
        for r in results:
            display_name = r.brand_name or r.generic_name or r.approval_id
            print(f"\n  [{r.approval_id}] {display_name}")
            print(f"  Indication:  {r.indication or 'N/A'}")
            print(f"  Sponsor:     {r.sponsor or 'N/A'}")
            print(f"  Route:       {', '.join(r.route) or 'N/A'}")
            print(f"  MoA:         {(r.mechanism_of_action or 'N/A')[:120]}...")
            all_rows.append({
                "query_condition": q.get("indication", ""),
                "query_sponsor": q.get("sponsor", ""),
                "query_intervention": q.get("intervention", ""),
                "approval_id": r.approval_id,
                "brand_name": r.brand_name or "",
                "generic_name": r.generic_name or "",
                "indication": r.indication or "",
                "sponsor": r.sponsor or "",
                "substance_names": "; ".join(r.substance_names),
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
