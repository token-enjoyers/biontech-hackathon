import logging

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

from .server import mcp  # noqa: E402
from .sources.clinicaltrials import ClinicalTrialsSource  # noqa: E402
from .sources.europepmc import EuropePMCSource  # noqa: E402
from .sources.medrxiv import MedRxivSource  # noqa: E402
from .sources.openfda import OpenFDASource  # noqa: E402
from .sources.pubmed import PubMedSource  # noqa: E402
from .sources.registry import registry  # noqa: E402

from . import tools  # noqa: E402, F401 — triggers tool registration

# Register data sources
registry.register(ClinicalTrialsSource())
registry.register(OpenFDASource())
registry.register(PubMedSource())
registry.register(MedRxivSource())
registry.register(EuropePMCSource())

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
