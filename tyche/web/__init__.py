"""Local web backend for Tyche: ``tyche ui``.

Serves the workspace (runs, stages, events, artifacts, papers) as a read side JSON API plus a
live SSE stream, and can start/resume/stop ``tyche run`` processes. See ``tyche.web.server`` for
``create_app``/``serve``, ``tyche.web.runs`` for the pure read-side functions over one workspace,
``tyche.web.processes`` for the run launcher/registry, and ``tyche.web.settings`` for ``.env``
handling. Never let any endpoint here import from ``tyche.paper``, ``tyche.review``,
``tyche.gates``, ``tyche.evolution``, ``tyche.analysis``, ``tyche.experiments``,
``tyche.literature``, ``tyche.pipeline``, ``tyche.workspace``, or ``tyche.llm`` except read-only
(module-level import and calling their pure helpers): those modules may still be imported lazily
by a running pipeline process and are not otherwise modified for this feature.
"""

from __future__ import annotations
