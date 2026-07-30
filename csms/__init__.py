"""CSMS — sponsorship contract → Asana automation.

The parser is the source of structure: it reads a completed contract PDF and
produces the sections and tasks to build in Asana. See csms.parser.
"""

from .parser import parse_contract, to_csv_rows, validate_pdf, InvalidPDFError
from .engine import build_project, BuildPlan, BuildResult, plan_to_dict
from .asana_client import AsanaClient, AsanaError

__all__ = [
    "parse_contract", "to_csv_rows", "validate_pdf", "InvalidPDFError",
    "build_project", "BuildPlan", "BuildResult", "plan_to_dict",
    "AsanaClient", "AsanaError",
]
__version__ = "0.1.0"
