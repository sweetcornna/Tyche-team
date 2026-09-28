#!/usr/bin/env python3
"""Build the CCF BDCI 2026 submission directory from one verified paper package.

    python scripts/tyche/make_submission.py --team <队伍名称> \
        --package workspace/runs/<run-id>/package --out dist/submission \
        [--review-token-file token.txt] [--zip]

The package must pass ``tyche verify``; the Tyche files must be committed (the code snapshot is
taken from HEAD). See docs/tyche/SUBMISSION.md for the layout and what to check before uploading.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tyche.submission import SubmissionError, build_bundle  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--team", required=True, help="team name; becomes the top-level directory")
    parser.add_argument("--package", required=True, type=Path, help="a package directory or a run directory")
    parser.add_argument("--out", type=Path, default=ROOT / "dist" / "submission", help="where to create <team>/")
    parser.add_argument("--review-token-file", type=Path, help="file holding the paperreview.ai access token")
    parser.add_argument("--repo-url", default="https://github.com/sweetcornna/Tyche")
    parser.add_argument("--replace", action="store_true", help="rebuild <out>/<team> if it exists")
    parser.add_argument("--zip", action="store_true", help="also write <out>/<team>.zip")
    args = parser.parse_args(argv)
    try:
        result = build_bundle(
            repo=ROOT,
            package=args.package,
            out_dir=args.out,
            team=args.team,
            token_file=args.review_token_file,
            repo_url=args.repo_url,
            replace=args.replace,
        )
    except SubmissionError as exc:
        print(f"[tyche] submission not built: {exc}", file=sys.stderr)
        return 1
    print(f"[tyche] submission: {result.root}")
    print(f"[tyche] paper run {result.run_id}; code snapshot {result.commit[:12]}")
    if result.redacted_hosts:
        print(f"[tyche] model endpoint redacted in evidence/: {len(result.redacted_hosts)} host(s)")
    if args.zip:
        archive = shutil.make_archive(str(result.root), "zip", root_dir=result.root.parent, base_dir=result.root.name)
        print(f"[tyche] archive: {archive}")
    for item in result.todo:
        print(f"[tyche] TODO: {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
