# Notice

## Project base

This repository is a fork of **JiuwenSwarm** by the openJiuwen community
(<https://github.com/openJiuwen-ai/jiuwenswarm>), imported verbatim at commit
`b7a7c32564a98eb2033271ed93b7ad0124fc92c8` and licensed under the Apache License 2.0 (see `LICENSE`).
The import omits the six Git LFS demo videos under `docs/assets/videos/`; the documentation links to the
upstream copies instead. Third-party components bundled by JiuwenSwarm are listed in
`OPEN_SOURCE_SOFTWARE_NOTICE.md`.

JiuwenSwarm depends on the openJiuwen **agent-core** SDK (`openjiuwen`), pinned by upstream to commit
`9e3390195a9ea15235b2b5f7412cb2aa440622cc`. Tyche calls its public modules and does not modify them.

## Tyche additions

Files under `tyche/`, `tests/tyche/`, `scripts/tyche/`, `docs/tyche/`, and the skills
`jiuwenswarm/resources/agent/workspace/skills/tyche-iclr-paper/` and `.../skills/tyche-paper/` are original
work for the CCF BDCI 2026 openJiuwen track, released under the Apache License 2.0.

Upstream files are changed only where Tyche's packaging requires it: `pyproject.toml` declares the `tyche`
package, its console script, and its package data (including the built web UI). Each such change is called out
in its commit message.

## Web UI dependencies

The research workbench (`tyche/web/frontend/`) is original code. Its built bundle (`tyche/web/frontend/dist/`)
includes third-party JavaScript packages, chiefly React and React DOM (MIT), Radix UI primitives (MIT),
lucide-react (ISC), react-markdown and remark-gfm with their unified/micromark dependencies (MIT), highlight.js
(BSD-3-Clause), and clsx (MIT). The build writes the full list with each package's license text to
`dist/THIRD_PARTY_NOTICES.txt`.

## ICLR style files

`tyche/paper/template/` contains the unmodified ICLR 2027 style files from the official ICLR template
repository (<https://github.com/ICLR/Master-Template>); see `tyche/paper/template/SOURCE.md`. They remain under
the terms stated in their own headers.

## Design references

During design the team consulted public descriptions of research-agent workflows, including the Stanford Agentic
Reviewer's published evaluation dimensions and the owner-authored analysis documents of the
`sweetcornna/claude_science_opensource` repository. Only general concepts were used: fresh-context review, a
findings ledger, provenance-tagged memory, immutable artifact versions, a claim-to-evidence map, a plan approval
step, per-round revision diffs, artifact lineage with an environment snapshot, and worked example runs. No code,
prompts, skill text, or other expression from that repository or from any proprietary product was copied into
this project.

The workbench follows the familiar layout of desktop chat applications (a conversation column, a run sidebar,
and a side panel). Its components, styles, icons (from lucide), and copy were written for this project; no code,
assets, or trade dress were taken from any commercial application.
