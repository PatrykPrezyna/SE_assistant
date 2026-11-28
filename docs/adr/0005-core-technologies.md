# ADR 0005: Core Technology Stack

## Status

Accepted

## Context

SE_assistant's technology choices need to balance openness, maintainability, deployability, and thesis requirements. This ADR consolidates decisions on license, core dependencies, and static site generation.

## Decision

Establish and maintain these technology constraints:

1. **License**: MIT
2. **Core (parser/server)**: Python standard library only, no pip dependencies
3. **Viewer**: Vanilla JavaScript, no frameworks or build step
4. **Static site generator**: Evolve from existing `publish.py`

## Rationale

### License: MIT

**Choice**: MIT License (copyright Patryk Prezyna)

**Reasoning**:

- Aligns with "no lock-in" positioning: users can fork, modify, and redistribute without restriction
- Thesis context: Academic research benefits from permissive licensing
- Compatibility: Can be integrated into commercial or GPL projects
- Simplicity: Shorter and clearer than Apache 2.0, no patent clause complexity
- Community: Most SysML v2 community tools are MIT (SysIDE extensions, PySysML2)

**Alternatives considered**:

- Apache 2.0: More explicit patent protection, but overkill for a thesis project
- GPL-3.0: Forces derivatives to be open source, conflicts with "no lock-in" claim
- AGPL-3.0: Would enable dual-licensing business model (Obeo style), but premature for thesis stage

### Core: Python Standard Library Only

**Choice**: Parser, server, and validation tools use only Python's standard library

**Reasoning**:

- **Deployment simplicity**: `pip install` works everywhere with no compiler dependencies, no Postgres, no Java runtime for the core tool
- **Thesis requirements**: Demonstrates that MBSE doesn't require heavyweight infrastructure
- **Market differentiation**: Beats Capella (Eclipse), Cameo (server), SysON (Postgres) on ease of setup (R1: fast start)
- **Maintenance**: No dependency updates, no security patches for third-party libraries, no breaking changes
- **Transparency**: Thesis reviewers can audit all code without learning external frameworks

**Boundaries**:

- ✅ Core tool: `app.py`, `cloud.py`, `publish.py` → stdlib only
- ⚠️ Assistant: `src/assistant/` uses OpenAI API (not stdlib) → acceptable, it's a separate optional component
- ⚠️ Validation: Conda env + Jupyter kernel for official parser → acceptable, opt-in validation path
- ⚠️ Testing: `unittest` only (stdlib), but DOM tests need Microsoft Edge → acceptable, tests can depend on external tools

**Acknowledged costs**:

- No FastAPI/Flask (use `http.server.ThreadingHTTPServer` instead)
- No SQLAlchemy (store Views as JSON files)
- No Click/Typer (use `argparse`)
- No Jinja2 (use string templates or f-strings)

These constraints are **features, not bugs**. Simplicity is the goal.

### Viewer: Vanilla JavaScript

**Choice**: `viewer.html` uses no frameworks (React, Vue, Svelte), no build tools (Webpack, Vite), no npm dependencies

**Reasoning**:

- **Phone access**: The published viewer (`--publish docs`) must work on any device with a browser, no build artifacts to serve
- **Transparency**: Thesis reviewers can open `viewer.html` and understand it without React/JSX knowledge
- **Deployment**: No `npm install`, no `node_modules`, no supply chain attacks
- **Longevity**: Vanilla JS will work in browsers 20 years from now; framework code may not

**Current state**: `viewer.html` is 2,545 lines of global-state JS ([architecture review](../../uploads/report_4d53.md) Section 3.5), nearing maintainability limits.

**Future evolution** (post-thesis):

- Phase 4 of the roadmap splits it into modules (`diagram.js`, `tree.js`, `views.js`)
- Lightweight framework (Preact, Alpine.js) might be justified at ~4,000+ lines
- But **not for thesis**: the current viewer works, and simplicity matters more than perfect architecture

### Static Site Generator: Evolve `publish.py`

**Choice**: Continue using the existing `publish.py` script rather than adopting Astro/Eleventy/Sphinx

**Reasoning**:

- **Stdlib-only principle**: `publish.py` uses only standard library (templates as f-strings, JSON output)
- **Specific output**: The published viewer is one HTML file with embedded JSON, not a multi-page site—static site generators are designed for blogs/docs, not interactive apps
- **Control**: Full control over output structure, no fighting framework conventions
- **Thesis scope**: The published viewer is a demo feature (R6: no-install read), not the core contribution

**Current gaps** (from [architecture review](../../uploads/report_4d53.md) Section 4.2):

- Static site lacks search, filter, zoom persistence
- No "embed a View in Confluence" `<iframe>` snippet

These are **enhancements to `publish.py`**, not reasons to adopt a framework. The script already proves the pattern works; just extend it.

**Future evolution** (post-thesis):

- Phase 4: Add search (client-side JS over `model.json`)
- Add filter and zoom persistence to `publish_viewer.html`
- Generate embeddable `<iframe>` snippet in the output directory

All achievable by enhancing `publish.py`, no framework needed.

## Consequences

### Positive

- Clear technology boundaries for contributors
- Thesis reviewers understand the full stack without prerequisites
- Deployment remains trivial (no dependency hell)
- Code longevity: stdlib and vanilla JS age well
- Market differentiation: "no-install, no-dependency MBSE" is a unique positioning

### Negative

- Viewer complexity ceiling: 2,545-line `viewer.html` is approaching unmaintainability (mitigation: modularize in Phase 4, consider lightweight framework only if >4,000 lines)
- Some features harder without frameworks: interactive search, reactive state, component reuse (mitigation: acceptable trade-off for simplicity)
- Potential contributor friction: "Why not React?" (mitigation: document rationale clearly, as we're doing here)

### Boundaries for Future Extensions

If new features require dependencies, isolate them:

✅ **Acceptable**:
- Optional assistant enhancements (document parsing, vector search) → dependencies in `src/assistant/`, not in core
- CI/CD tooling (GitHub Actions, pre-commit hooks) → dev dependencies, not runtime
- Validation tools (conda env, LSP server) → opt-in, not required for core usage

❌ **Not acceptable**:
- Parser depending on a third-party library
- Viewer requiring a build step for basic usage
- Core server needing Postgres or Redis

The rule: **if it's required to run `system-explorer <folder>`, it must be stdlib**.

## Notes

This ADR consolidates decisions about the technology foundation. It does **not** cover:

- Methodology framework (`product-development.yaml`, Activity Repository) → separate concern
- SysML v2 conformance (dialect migration) → see ADRs 0001, 0004
- Deployment modes (local, hosted, published) → see `FEATURES.md`

These constraints are **thesis requirements**, not arbitrary preferences. Post-thesis, a maintainer team could revisit them, but that would be a major architectural shift (and would weaken the "no-install, no-dependency" market positioning).
