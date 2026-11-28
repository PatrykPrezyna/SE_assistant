# ADR 0001: Spec-Driven Development Process

## Status

Accepted

## Context

SE_assistant needs a lightweight spec-driven development process to guide future feature implementation with AI coding agents. The process should support versioned specs, test-backed implementation, and small PRs while remaining accessible for a solo developer working on a master's thesis.

Two options were evaluated:

1. **GitHub Spec Kit** (`github/spec-kit`): Full-featured toolkit with `specify` CLI, constitution/spec/plan/tasks flow, extensions, presets, workflows, and integration support for multiple AI coding agents.

2. **Plain `specs/` folder + AGENTS.md**: Lightweight approach using plain Markdown files in a `specs/` directory with agent instructions in `AGENTS.md`, following existing patterns in the codebase.

## Decision

Use a **plain `specs/` folder + AGENTS.md** approach rather than GitHub Spec Kit.

## Rationale

### Alignment with Project Principles

- **Stdlib-only philosophy**: SE_assistant's core design principle is zero dependencies beyond Python's standard library. Spec Kit requires Python 3.11+, uv, and the `specify-cli` package, adding significant dependency overhead.

- **Simplicity**: The thesis context values transparency and understandability. Plain Markdown files are immediately comprehensible to thesis readers and reviewers without learning Spec Kit's abstractions.

- **Solo developer context**: Spec Kit's extension system, presets, workflows, and catalogs are designed for teams and organizations. A solo thesis project gains minimal benefit from this infrastructure while bearing the full learning and maintenance cost.

### Practical Considerations

- **Thesis traceability**: The thesis needs to demonstrate decision-making. Plain ADRs and spec files serve this purpose directly without wrapping them in Spec Kit's templating layer.

- **Lock-in avoidance**: Consistent with the "no lock-in" positioning (standard SysML v2, text files, git), keeping specs as plain Markdown avoids tool-specific formats.

- **Working with Cursor agents**: Both approaches work with Cursor agents. Plain files require no special integration setup—agents read Markdown naturally.

- **Maintenance burden**: Spec Kit evolves independently and may introduce breaking changes. Plain files are stable and self-contained.

### Trade-offs Acknowledged

Spec Kit provides valuable features we're forgoing:

- Structured command flow (`constitution` → `specify` → `plan` → `tasks` → `implement` → `converge`)
- Template consistency across features
- Quality gates and validation hooks
- Community extensions and presets

However, these benefits are primarily valuable for:
- Teams coordinating multiple developers
- Organizations enforcing standards
- Projects with complex regulatory requirements
- Repeated application of the same process across many features

A thesis project building 3–5 features with one developer gains more from simplicity than from Spec Kit's sophisticated tooling.

## Consequences

### Positive

- Zero new dependencies maintain stdlib-only principle
- Thesis readers understand the process without external documentation
- Full control over spec format and evolution
- Lower cognitive overhead for the developer
- Specs remain readable decades from now without tool archaeology

### Negative

- No automated consistency checks between specs
- Must manually maintain spec structure conventions
- No pre-built templates or quality gates
- Future contributors must learn project-specific conventions rather than industry-standard Spec Kit patterns

### Mitigation

- Document spec format conventions in `AGENTS.md`
- Provide a spec template as a reference
- Use GitHub PR templates to enforce process adherence
- Consider Spec Kit adoption later if the project scales to a team

## Notes

This decision applies to the SE_assistant tool repository. Model repositories (like cool-spine-model) may make different choices based on their own needs.

The methodology framework in `methodology/product-development.yaml` is complementary—it guides the SE activities (stakeholder analysis, requirements, etc.), while specs guide tool feature development. Both remain.
