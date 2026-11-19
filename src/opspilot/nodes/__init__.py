"""Graph nodes: pure functions `(OpsState, Deps) -> state update`."""

from opspilot.nodes.classify import classify
from opspilot.nodes.common import Deps
from opspilot.nodes.extract import extract
from opspilot.nodes.ingest import ingest
from opspilot.nodes.priority import assess_priority
from opspilot.nodes.sanitize import sanitize
from opspilot.nodes.validate import validate

__all__ = ["Deps", "assess_priority", "classify", "extract", "ingest", "sanitize", "validate"]
