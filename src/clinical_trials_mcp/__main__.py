import logging

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

from clinical_trials_mcp.server import mcp  # noqa: E402
from clinical_trials_mcp.sources.clinicaltrials import ClinicalTrialsSource  # noqa: E402
from clinical_trials_mcp.sources.pubmed import PubMedSource  # noqa: E402
from clinical_trials_mcp.sources.registry import registry  # noqa: E402

import clinical_trials_mcp.tools  # noqa: E402, F401 — triggers tool registration

# Register data sources
registry.register(ClinicalTrialsSource())
registry.register(PubMedSource())

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000, mount_path="/mcp")
