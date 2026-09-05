"""Pure mapping from canonical Performance/repository reads to Repo Intelligent inputs.

No new business logic lives here: :mod:`repo_intelligence.signals`,
:mod:`repo_intelligence.evidence_join`, and :mod:`repo_intelligence.entity_resolution`
already define exactly what they need (``ObservationEnvelope`` tuples exactly
as ``EvidenceLedger.replay()``/``PerformanceQueryAPI`` yield them, and a
path-keyed ``ProjectEntityRef`` map). This module only reshapes already-owned
Performance/repository reads into those shapes -- Performance remains the
canonical owner of the observation, the repository remains the canonical
owner of structure truth.

Known scaling limitation (documented, not fixed this pass): ``PerformanceQueryAPI.query_evidence``
returns at most 100 matching envelopes from the start of its scan, the same
limitation ``desktop_bridge.py`` documents for the same reason (see that
module's Execution 03 note). A busy project's window can exceed 100 evidence
envelopes; the honest fix is a paginated, project-scoped replay comparable to
what ``projection_store`` gives the desktop bridge, out of scope for this
integration pass.
"""

from __future__ import annotations

from datetime import datetime

from .contracts import Identity
from .repo_intelligence.contracts import ProjectEntityRef
from .repo_intelligence.entity_resolution import bootstrap_entity_refs, index_refs_by_path
from .repository_capture import RepositorySnapshot


def resolve_entity_refs_by_path(
    project: Identity,
    repository_key: str,
    snapshot: RepositorySnapshot,
    *,
    now: datetime,
) -> dict[str, ProjectEntityRef]:
    """Bootstrap the file/package/repository entity hierarchy, indexed by path.

    Symbol/code-region level refs (``symbol_refs_from_resolved``) require
    Performance's per-changeset resolver output and are not wired here this
    pass -- file/module-level entity refs are sufficient for
    ``scan_signals``'s path-keyed lookups.
    """
    refs = bootstrap_entity_refs(project, repository_key, snapshot, now=now)
    return index_refs_by_path(refs.values())


__all__ = ["resolve_entity_refs_by_path"]
