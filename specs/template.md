# Spec Template

**Status**: Draft | Ready | In Progress | Complete | Deprecated

**Feature ID**: `FEAT-NNNN`

**Related ADRs**: ADR-XXXX

## Overview

One-paragraph summary: what is this feature, and why do we need it?

## User Stories

Who needs this, and what do they achieve?

```
As a [role],
I want [capability],
So that [benefit].
```

## Acceptance Criteria

- [ ] Criterion 1
- [ ] Criterion 2
- [ ] Criterion 3

## Example Fixtures

### Fixture 1: [Name]

```sysml
// SysML v2 example demonstrating the feature
package Example {
    part def Widget;
}
```

**Expected behavior**: What should the parser extract, and what should the viewer show?

### Fixture 2: [Name]

```sysml
// Another example showing edge cases or variations
```

## Parser Requirements

What must `app.py` recognize and extract?

- [ ] Parse construct X
- [ ] Extract attributes Y
- [ ] Emit edges Z

## Viewer Requirements

What must `viewer.html` render?

- [ ] Display nodes/edges in mode M
- [ ] Support interaction I
- [ ] Save positions to `views/<id>.json`

## Known Gaps

What doesn't work yet?

- **Gap 1**: Parser doesn't support `<construct>` (would need: regex pattern, extraction logic)
- **Gap 2**: Viewer doesn't render `<aspect>` (would need: canvas drawing code, layout logic)

## Validation Status

- [ ] Fixtures validate with official parser (`python -m system_explorer.official_check`)
- [ ] Fixtures validate with JamieD parser (`python -m system_explorer.jamied_check`)
- [ ] Tool's `--check` flag passes

## Testing Notes

What tests are needed in `test_system_explorer.py`?

- [ ] Parser test: fixture → model JSON assertion
- [ ] HTTP test: API endpoint behavior
- [ ] DOM test: viewer rendering (requires Edge)

## Implementation Notes

Any constraints, design decisions, or gotchas?

## References

- [FEATURES.md](../FEATURES.md) — existing capabilities
- [ADR-XXXX](../docs/adr/XXXX-title.md) — related decision
- [SysML v2 spec section](https://link) — standard reference
