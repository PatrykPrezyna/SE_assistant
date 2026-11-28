# Agent Development Guide for SE_assistant

This file provides instructions for AI coding agents (Cursor, Claude, Copilot) working on the SE_assistant tool. If you are an agent implementing a feature or fixing a bug, read this first.

## Core Principles

### 1. Standard Library Only

The **core tool** (`src/system_explorer/app.py`, `cloud.py`, `publish.py`) uses **only Python's standard library**. No pip dependencies.

✅ Allowed:
- `http.server`, `json`, `re`, `pathlib`, `threading`, `argparse`, `tempfile`, etc.

❌ Not allowed in core:
- `requests`, `flask`, `fastapi`, `click`, `jinja2`, `sqlalchemy`, etc.

**Why**: Thesis requirement (R8: no investment). Deployment is `pip install <git-url>`, not "install Java + Postgres + npm".

**Exception**: `src/assistant/` may use external dependencies (OpenAI API, etc.). Testing tools may use external dependencies (Edge for DOM tests).

### 2. Standard SysML v2 Textual Notation

Models use **standard SysML v2** as defined by the OMG specification. The official pilot parser (Jupyter kernel) is the arbiter.

**Parser gaps** are acceptable (pragmatic regex parser, not full grammar), but:
- Document gaps in the spec or `FEATURES.md`
- Never invent custom dialect unless absolutely necessary
- Migrate away from custom dialect toward standard (see ADRs 0001, 0004)

**Validation order**:
1. Official parser (`python -m system_explorer.official_check <folder>`) — slow, spec-grade
2. JamieD parser (`python -m system_explorer.jamied_check <folder>`) — fast, community grammar
3. Tool's `--check` flag — sanity check only, not a grammar

Always run validation before claiming a feature is done. Exit code **must** be 0.

### 3. Viewer: Vanilla JavaScript

`src/system_explorer/viewer.html` and `src/system_explorer/publish_viewer.html` are **vanilla JS**, no frameworks, no build step.

- Use standard DOM APIs
- No React, Vue, Svelte, jQuery
- No npm, no webpack, no vite

**Why**: Phone compatibility, longevity, simplicity (thesis requirement).

**Current state**: `viewer.html` is 2,545 lines of global-state JS. It's approaching maintainability limits, but framework adoption is **post-thesis** (see ADR 0005).

## Development Workflow

### Spec-Driven Process (ADR 0006)

Every new feature follows:

```
Spec → Plan → Tasks → Tests → Implementation → PR → CI → Merge
```

1. **Read the spec** in `specs/<feature>.md` before writing code
2. **Write tests first** covering acceptance criteria
3. **Implement** to pass the tests
4. **Update the spec** if you discover parser gaps, fixture issues, or requirement changes
5. **Update `FEATURES.md`** with the new capability
6. **Run the full test suite**: `python tests/test_system_explorer.py -v`
7. **Create a PR** with:
   - Spec updates (if any)
   - Implementation
   - Tests
   - `FEATURES.md` update

### Testing Requirements (CLAUDE.md)

**Rule**: Every new feature must have a test in `tests/test_system_explorer.py`.

Test types:
- **Parser tests**: `parse_sysml()` on fixture text, assert expected nodes/edges
- **HTTP tests**: `ServerFixture` to test API endpoints
- **DOM tests**: Headless Edge tests for viewer behavior (auto-skip if Edge unavailable)

**Run before finishing**:

```bash
python tests/test_system_explorer.py -v
```

Do **not** kill the test run early. Some tests take 60+ seconds (DOM tests with Edge). If every DOM test fails with an empty page, Edge isn't available—that's not a bug, just a skip condition.

### Small PRs

Target **200-500 lines per PR** (excluding tests and fixtures). One logical change per PR.

If a feature requires more (e.g., large refactoring), that's acceptable, but:
- Keep related changes together (parser + viewer for one feature)
- Split unrelated changes (don't do "feature X + refactor Y" in one PR)

### Git Workflow

- Branch: `cursor/<descriptive-name>-2d7a` (lowercase only)
- Commit messages: Clear, descriptive (e.g., "Add use case activity view with swimlanes")
- One commit per logical change (or squash before merge)

## Model Files vs. Tool Files

**SE_assistant repository** = the tool (`system-explorer` package)
**Model repositories** (e.g., `cool-spine-model`) = SysML v2 models

**You are working on the tool, not a model**. Do not:
- Create `.sysml` files in this repo (models live elsewhere)
- Modify user model files (the tool is read-only on models)

**Exception**: Test fixtures in `tests/test_system_explorer.py` are inline SysML strings, not files. That's fine.

## SysML v2 Constructs the Parser Handles

From `FEATURES.md` (always check the latest version):

**Supported**:
- Packages
- Part definitions (abstract, with attributes, parts, connections)
- Usages (typed, nested, singleton)
- Requirements (with short names, `satisfy` edges)
- Action definitions (`action def`) with nested actions, `first`, `then` succession
- Attributes (typed, with defaults, redefinitions)
- Specialization (`:>`) and typing (`:`)
- Enumerations
- Ports, connections
- Comments (`// ...`, `/* ... */`) and `doc /* ... */`

**Parser gaps** (pragmatic parser, not full grammar):
- No `import` resolution (all files merged before resolving)
- Name resolution by simple name only (no qualified paths)
- String literals inside blocks can corrupt brace nesting (don't use `{` in strings)
- Item flows (`flow <source> to <target>;`) not yet parsed
- Many edge cases in the full SysML v2 grammar

**Custom dialect** (deprecated, being migrated):
- `actor def` (use `part def` + `actor` usages instead)
- `perform action` syntax (use standard `action def` with nested parts containing `perform <action>;` statements)

## Common Pitfalls

### Gotcha 1: Parser Re-runs on Every `/api/model` Request

The server parses all `.sysml` files on **every** request to `/api/model`. This is intentional (file edits appear without server restart), but it means:

- Parsing must be fast (it is—regex-based, not full grammar)
- Parser errors show up on page refresh
- Changes to `.sysml` files are immediately visible (just reload the page)

### Gotcha 2: Validation is Opt-In

`system-explorer --check` is a sanity check, not a grammar. For real validation:

1. Official parser (conda env, slow): `python -m system_explorer.official_check <folder>`
2. JamieD parser (fast): `python -m system_explorer.jamied_check <folder>`

Always validate fixtures with one of these before claiming "standard SysML v2."

### Gotcha 3: DOM Tests Need Edge

If **every** DOM test fails with an empty page, headless Edge isn't available in your environment. This is not a bug—just run tests in a normal terminal or skip DOM tests for this session.

Do **not** "fix" the viewer based on DOM test failures if Edge isn't running.

### Gotcha 4: Views Are Sidecars, Models Are Truth

The model (`.sysml` files) is the **single source of truth**. Everything else is regenerable:

- `views/*.json` = element positions, filters (can be deleted, repositioned from scratch)
- `layout.json` = global state (can be deleted, defaults to empty)
- `process/*.yaml` = methodology state (can be deleted, activity restarts)

**Never edit `.sysml` files in the tool**. The explorer is read-only. Models are edited:
- By hand (in a text editor)
- By the assistant (chat writes `.sysml` files)
- By methodology tools (`methodology/stakeholder_analysis.py` writes `.sysml`)

The tool **reads and visualizes**, it doesn't write models.

### Gotcha 5: Hosted Mode Commits on Every Save

In hosted mode (`system-explorer-cloud`), every View or layout save triggers:
- `git commit` (authored as the signed-in GitHub user)
- `git push` to `main` after ~1s debounce

This is intentional (R7: live collaboration). But it means:

- **Never run hosted mode on a local dev repo** without `GITHUB_BRANCH=scratch-branch`
- Commits are real, not ephemeral
- `ALLOW_ANONYMOUS=1` for local Docker testing only

## Specific Instructions for Common Tasks

### Adding a New Parser Construct

1. Add regex pattern to `app.py` (e.g., `RE_USE_CASE`)
2. Parse and extract attributes in `_parse_blocks()` or `_parse_statements()`
3. Add nodes/edges to the model JSON
4. Add a test in `test_system_explorer.py` with fixture and assertions
5. Document the construct in `FEATURES.md`

### Adding a New Viewer Feature

1. Modify `viewer.html` (or `publish_viewer.html` if static-only)
2. Update rendering logic (canvas draw, element positioning, filters)
3. Add DOM test in `test_system_explorer.py` (requires Edge)
4. Update `FEATURES.md`

### Adding a New Validation Warning

1. Detect the condition in `app.py` during parsing
2. Append to `model["warnings"]` with file, line, message
3. The viewer renders warnings in the banner automatically
4. Add a test asserting the warning appears
5. Document the warning in `FEATURES.md`

### Migrating from Custom Dialect

1. Identify the non-standard construct (e.g., `actor def`, `perform action`)
2. Write a migration guide in `docs/migrations/`
3. Update the parser to **reject** the old syntax (with helpful error message)
4. Update test fixtures to use standard syntax
5. Update CoolSpine model (in its own repo)
6. Update `FEATURES.md` to remove the dialect note

## References

- `FEATURES.md` — Feature reference (what the tool parses, renders, validates)
- `README.md` — Setup, hosting, usage
- `ARCHITECTURE.md` — Design direction
- `NOTATION.md` — Graphical notation simplification rules
- `CLAUDE.md` — Testing rules (every feature gets a test)
- `docs/adr/` — Architecture Decision Records
- `specs/` — Feature specifications

## Questions?

If the instructions conflict:
1. ADRs override this file (decisions trump instructions)
2. This file overrides `FEATURES.md` (instructions trump reference)
3. `FEATURES.md` overrides code comments (documentation trumps implementation)

If something is unclear, check the architecture review report at `uploads/report_4d53.md` (latest comprehensive analysis of the codebase).

---

**Remember**: You are building a **thesis project** demonstrating that MBSE can be democratized. Simplicity, transparency, and standard compliance are **features**, not constraints. When in doubt, choose the simpler, more standard option.
