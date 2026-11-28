# ADR 0006: Spec-Driven Development Workflow

## Status

Accepted

## Context

Future SE_assistant features need a consistent development process that works well with AI coding agents (Cursor, Claude, etc.) and maintains quality. The workflow must specify:

- When specs are written
- How specs connect to implementation
- PR size and testing requirements
- How specs stay synchronized with code

## Decision

Adopt this spec-driven workflow for all new features:

```
Spec → Plan → Tasks → Tests → Implementation → PR → CI → Merge
```

### Process Steps

1. **Spec** (`specs/<feature>.md`): Define the feature with user stories, acceptance criteria, and example `.sysml` fixtures
2. **Plan**: Identify parser gaps, viewer changes, test requirements (recorded in the spec)
3. **Tasks**: Break the plan into small, testable chunks (one chunk = one PR when possible)
4. **Tests**: Write tests for acceptance criteria *before* implementation
5. **Implementation**: Build the feature to pass the tests
6. **PR**: One PR per task, small and focused (~200-500 lines when feasible)
7. **CI**: Automated tests must pass before merge
8. **Merge**: Squash or preserve commits based on logical coherence

### Spec Updates

- Specs are **living documents**: when decisions change during implementation, update the spec *before* changing code
- Spec diffs in PRs show what was learned
- Deprecated features are marked `~~strikethrough~~` with a note, not deleted

## Rationale

### Alignment with AI Agents

AI coding agents (Cursor, Claude, Copilot) work best with:

- **Clear written specifications**: Models trained on GitHub understand Markdown specs better than verbal instructions
- **Explicit acceptance criteria**: "passes these tests" is more precise than "works well"
- **Small PRs**: Agents can implement, test, and verify 200-500 lines more reliably than 2,000-line changes
- **Updated specs**: When an agent learns "the fixture won't work because the parser doesn't support X", capturing that in the spec helps future agents (and humans)

### Quality Gates

Each step is a gate:

| Gate | Question | Evidence |
|------|----------|----------|
| **Spec** | Do we know what to build? | User stories, acceptance criteria, fixtures |
| **Plan** | Do we know how to build it? | Parser/viewer changes identified, gaps listed |
| **Tests** | How do we know it works? | Test cases covering acceptance criteria |
| **Implementation** | Does it pass the tests? | Test suite green |
| **CI** | Does it integrate with the rest? | Full suite green on PR |

### Small PRs

**Target**: 200-500 lines per PR (excluding test code and fixtures)

**Rationale**:

- Easier to review (human or agent)
- Faster to merge (less risk of conflicts)
- Easier to revert if needed
- Clear single-purpose changes

**When to exceed**: 

- Large refactorings (e.g., splitting `viewer.html` into modules)
- Multiple tightly coupled changes (parser + viewer + tests for one feature)

**Principle**: One logical change per PR, even if it touches many files. Split by feature, not by file type (don't do "add parser support" then "add viewer support" in separate PRs if they're one feature).

### Spec Evolution

Specs are **not frozen requirements**. During implementation:

- Parser limitations discovered → update spec to note gaps
- Better fixture found → replace the example
- Acceptance criteria clarified → revise the spec

The PR includes the spec diff, showing what was learned. This creates **implementation traceability**:

```
Commit: "Implement use case activity views"
Files changed:
  specs/use-case-activity-views.md  (noted fork/join rendering limitation)
  src/system_explorer/app.py        (parse perform allocations)
  src/system_explorer/viewer.html   (swimlane rendering)
  tests/test_system_explorer.py     (activity view tests)
```

The spec diff documents "we thought X, learned Y, built Z."

### CI as the Gate

**Requirement**: All tests must pass before merge

**CI runs**:

1. Full test suite (`python tests/test_system_explorer.py`)
2. Example model validation (CoolSpine or test fixtures)
3. (Future) Official parser check on fixtures (nightly, not on every PR)

**No merge exceptions**: If a test fails, either:

- Fix the implementation, or
- Fix the test (if it was wrong), or
- Remove the test (if the requirement changed, with spec update)

### AGENTS.md Integration

The spec-driven workflow is **enforced by agent instructions** in `AGENTS.md`:

- Agents read specs before implementation
- Agents check tests pass before claiming done
- Agents update specs when discoveries are made

This makes the process work for both human and AI developers.

## Implementation

### Directory Structure

```
SE_assistant/
├── specs/
│   ├── 0001-system-context-use-cases.md
│   ├── 0002-use-case-activity-views.md
│   └── template.md
├── docs/
│   └── adr/
│       ├── 0001-spec-driven-process.md
│       └── ...
├── src/
│   └── system_explorer/
│       ├── app.py
│       └── viewer.html
├── tests/
│   └── test_system_explorer.py
├── AGENTS.md
└── .github/
    └── workflows/
        └── test.yml
```

### Spec Template

A template (`specs/template.md`) provides structure:

- Feature name and status
- User stories
- Acceptance criteria
- Example fixtures
- Known gaps
- Testing notes

### PR Template

GitHub PR template (`.github/pull_request_template.md`) enforces:

- [ ] Spec updated or created
- [ ] Tests added/updated
- [ ] `FEATURES.md` updated
- [ ] Tests pass locally

## Consequences

### Positive

- Clear process for AI agents and human contributors
- Specs document **what** and **why**, code documents **how**
- Small PRs make review faster and reverting safer
- CI catches regressions automatically
- Spec evolution captures implementation learning

### Negative

- Upfront spec writing slows initial velocity
- Discipline required to update specs (not just code)
- More files to maintain (specs + ADRs + docs)
- Risk of spec drift if not enforced (mitigation: PR template checklist, CI could check spec exists for new features)

### Trade-offs

**Compared to ad-hoc development**:

- Slower to start (spec + plan before code)
- Faster to finish (fewer rework cycles, clearer acceptance)
- Higher quality (tests written first, CI gated)

**Compared to GitHub Spec Kit**:

- More manual (no `specify plan`, `specify converge` commands)
- More flexible (no prescribed template structure)
- Simpler (no tool to learn, just Markdown conventions)

### Validation

Success metrics:

- Every new feature has a spec in `specs/`
- PRs reference the spec they implement
- CI passes on all PRs
- Test coverage stays >80% (future, once coverage tooling added)

## Notes

This workflow applies to **new features**. Bug fixes and refactorings follow a lighter process (no spec required, but tests are mandatory).

The spec-driven workflow is **complementary to the Activity Repository**: 

- Activity Repository: Guides **model creation** (stakeholder analysis, requirements, etc.)
- Spec-driven workflow: Guides **tool development** (adding features to System Explorer)

Both are part of the broader thesis contribution: demonstrating structured, repeatable processes for MBSE.
