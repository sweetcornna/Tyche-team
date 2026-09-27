#!/usr/bin/env python3
"""Tyche: an evidence-bound ICLR short-paper agent built on openJiuwen (entry point).

Given a research topic about LLM agents, Tyche produces a compiled ICLR 2027 short paper in
eight resumable stages (``tyche/pipeline.py``). Language models propose plans, prose, and
critiques; deterministic code owns retrieval, citation verification, statistics, compilation,
the gates that decide whether a draft may advance, and the AI use statement.

    S0 plan         tyche/planning.py            falsifiable research plan (pydantic-validated JSON)
    S1 survey       tyche/literature/            arXiv, Semantic Scholar, OpenAlex; metadata verified
                                                 against arXiv/Crossref (verify.py); evidence cards whose
                                                 quotes must appear verbatim in the abstract
    S2 experiments  tyche/experiments/bridge.py  openJiuwen auto_research ManagerRuntime:
                                                 design -> code -> execute -> reflect, real execution
    S3 analysis     tyche/analysis/              bootstrap CIs, paired permutation tests, the
                                                 allowed-numbers registry, tables, figures (no model)
    S4 write        tyche/paper/                 section by section within context budgets
                                                 (tyche/memory/context_pack.py), LaTeX compile
    S5 review       tyche/review/                seven-dimension panel + fidelity auditor, findings
                                                 ledger, gated acceptance of each revision
    S6 evolve       tyche/evolution/             cross-run writing lessons, promoted only when they
                                                 recur and help; exported as JiuwenSwarm evolutions.json
    S7 package      tyche/pipeline.py            PDF, sources, provenance, claim-evidence map,
                                                 environment snapshot; refused while a gate blocks

Every stage writes immutable artifact versions with SHA-256 provenance under
``workspace/runs/<run-id>/``; ``--resume`` continues from the first unfinished stage.

Usage (after ./setup_env.sh and ``source .venv/bin/activate``):

    python main.py selftest                     offline end-to-end check: fictional fixtures, real LaTeX
    python main.py verify ../evidence/<run-id>  offline audit of the submitted paper's package
    python main.py doctor                       toolchain, credentials (presence only), APIs, endpoint
    python main.py run --config config.yaml --run-id <id> --topic "<topic>" --direction memory_engine
    python main.py run --resume --run-id <id>   continue a run
    python main.py ui                           local research workbench (http://127.0.0.1:8765)

Credentials come only from environment variables or a git-ignored ``.env`` (API_KEY, API_BASE,
MODEL_NAME, MODEL_PROVIDER, MODEL_CONTEXT_WINDOW); see run_guide.md.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> int:
    # Run from this snapshot without installing it. Processes that Tyche starts itself (the
    # workbench's `python -m tyche run`, openJiuwen's experiment programs) find the same code
    # through PYTHONPATH.
    sys.path.insert(0, str(HERE))
    os.environ["PYTHONPATH"] = os.pathsep.join(p for p in (str(HERE), os.environ.get("PYTHONPATH", "")) if p)

    from tyche.cli import main as tyche_main

    return tyche_main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
