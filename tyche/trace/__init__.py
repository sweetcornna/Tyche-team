"""Traceability: which evidence supports each claim, how review changed the paper, and what produced it.

All four views are computed deterministically from a run directory's
artifacts; none of them calls a model or the network.
"""

from tyche.trace.claims import build_claim_map, claim_map_for_run, plain_text, split_sentences
from tyche.trace.environment import capture_environment
from tyche.trace.lineage import lineage_graph, read_provenance, upstream
from tyche.trace.revisions import revision_history

__all__ = [
    "build_claim_map",
    "capture_environment",
    "claim_map_for_run",
    "lineage_graph",
    "plain_text",
    "read_provenance",
    "revision_history",
    "split_sentences",
    "upstream",
]
