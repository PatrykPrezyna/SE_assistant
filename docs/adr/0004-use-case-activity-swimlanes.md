# ADR 0004: Use Case Activity Views with Swimlanes

## Status

Accepted

## Context

Use case definitions (ADR 0003) capture **what** interactions exist, but not **how** they unfold. Users need to drill down into a use case to see:

- The sequence of actions (first this, then that)
- Which actor performs each action (surgeon cuts, nurse monitors)
- Parallel activities (surgery and vital sign monitoring happen concurrently)
- Item flows between actions (patient moves through the procedure)

SysML v2 provides **action** and **activity** constructs for behavior modeling, but swimlane diagrams (actions grouped by performer role) are not explicitly covered by the standard's graphical notation.

## Decision

Implement **use case activity views** where:

1. Opening a use case in the viewer shows an **activity diagram** of its internal flow
2. Actions are grouped into **swimlanes** derived from their `perform` relationships
3. Swimlanes represent actor roles (Surgeon, Nurse, Anesthesiologist)
4. Actions with no `perform` go in an "unassigned" lane
5. The viewer uses **standard SysML v2 `perform` semantics**, not the custom `perform action` dialect

## Rationale

### User Need

Operational scenarios (medical procedures, manufacturing processes, service workflows) are naturally understood as **who does what, when**:

- Surgeon: makes incision, performs surgery, closes incision
- Nurse: prepares patient, monitors vitals, assists with instruments
- Anesthesiologist: administers anesthesia, monitors patient state

A flat list of actions loses this structure. Swimlanes make roles explicit.

### Standard SysML v2 Approach

The current `FEATURES.md` documents a **non-standard `perform action` construct**:

```sysml
// CUSTOM DIALECT (deprecated)
action PrepareSurgery {
    perform action PreparePatient by Nurse;
    perform action SetupEquipment by Nurse;
}
```

This is not in the SysML v2 spec and fails official parser validation.

**Standard SysML v2 uses `perform` inside part definitions**:

```sysml
// STANDARD SysML v2
action def PerformSurgeryActivity {
    // Actions
    action preparePatient;
    first preparePatient;
    
    action administerAnesthesia;
    then administerAnesthesia;
    
    action makeSurgicalIncision;
    then makeSurgicalIncision;
    
    action performSurgicalProcedure;
    then performSurgicalProcedure;
    
    action closeIncision;
    then closeIncision;
    
    action recoverPatient;
    then recoverPatient;
    
    // Actor part definitions with perform statements (allocations)
    part nurse : Nurse {
        perform preparePatient;
        perform recoverPatient;
    }
    
    part surgeon : Surgeon {
        perform makeSurgicalIncision;
        perform performSurgicalProcedure;
        perform closeIncision;
    }
    
    part anesthesiologist : Anesthesiologist {
        perform administerAnesthesia;
    }
    
    // Item flows
    flow preparePatient.prepared to administerAnesthesia.patient;
}
```

The viewer **derives swimlanes from `perform` statements in nested parts**:

- Find all `part <name> : <Type> { perform <action>; }` patterns
- Group actions by the `<part>` that performs them
- Render each part's actions in a vertical lane
- Actions with no `perform` go in "unassigned"

**Note**: `fork`/`join` keywords shown in the original example do not exist in standard SysML v2 (confirmed via official parser validation). Concurrency is implicit when multiple parts perform actions.

### Migration from Custom Dialect

Existing models using `perform action by` need migration:

1. Extract inline `perform action` blocks into separate `action` definitions
2. Add `perform <action> by <part>;` allocations at the activity level
3. Update the parser to **stop accepting** the custom `perform action` syntax

The migration will be documented in a separate guide: `docs/migrations/perform-action-to-action-def.md`

### Rendering Approach

Swimlane layout is a **viewer concern**, not a model structure:

- The `.sysml` file contains standard actions, `perform` relationships, and succession (`first`/`then`/`fork`/`join`)
- The viewer's **activity diagram mode** lays out actions in swimlanes based on `perform` edges
- The user arranges action positions within lanes (manual layout, like block diagrams)
- Positions are saved to `views/<id>.json` with lane metadata

### Concurrency Semantics

**Important**: Standard SysML v2 does not have `fork`/`join` keywords (confirmed via official parser validation).

Concurrency is implicit when multiple parts perform actions in parallel. The viewer may choose to visually represent this through layout (e.g., actions at the same vertical level across different lanes) or leave it implicit.

### Item Flows

Objects moving between actions use `flow of`:

```sysml
flow of patient : Patient from preparePatient to administerAnesthesia;
flow of patient from administerAnesthesia to makeSurgicalIncision;
```

The viewer renders these as dashed arrows crossing swimlane boundaries.

## Implementation

### Parser Requirements

The parser must recognize (already supported, per `FEATURES.md`):

- `action` definitions
- `first`, `then` succession
- `fork`, `join` concurrency
- `flow of` item flows
- `perform <action> by <part>;` allocations

**New requirement**: Stop accepting `perform action <name> by <part>;` (custom dialect).

### Viewer Requirements

The viewer must:

1. Detect when a use case has an associated activity (naming convention: `PerformSurgeryActivity` for `PerformSurgery` use case, or explicit link)
2. Enter "activity view" mode when drilling into a use case
3. Parse `perform` edges to determine which part owns which action
4. Render actions in swimlanes grouped by owning part
5. Support `first`/`then` layout (vertical flow within lane)
6. Support `fork`/`join` markers (split/merge across lanes)
7. Render `flow of` as item flow arrows

### Example Fixture

A complete surgical procedure model serves as the reference fixture for testing:

- 3 actors (Surgeon, Nurse, Anesthesiologist)
- 7 actions with succession
- 1 fork (surgery + monitoring in parallel)
- 1 join (before recovery)
- Item flow (Patient through the procedure)

This fixture must validate with the official SysML v2 parser.

## Consequences

### Positive

- Uses **standard SysML v2 semantics** (`perform` allocations, not custom `perform action`)
- Models validate with official parser (no dialect gap)
- Swimlanes provide intuitive role-based organization
- Supports realistic operational scenarios (medical, manufacturing, service)
- Enables traceability from actors to actions to requirements

### Negative

- **Parser must reject the old `perform action` syntax** (breaking change for existing models using it)
- Swimlane layout is viewer-specific (other tools may not render lanes the same way)
- Manual positioning within lanes required (no auto-layout)
- More verbose than the custom dialect (allocations separate from action definitions)

### Migration Impact

**CoolSpine model** uses the custom `perform action` dialect ([architecture review](../../uploads/report_4d53.md) Section 3.1). Migration steps:

1. Update `FEATURES.md` to document the deprecation
2. Write a migration script or manual guide
3. Update CoolSpine to use standard `perform` allocations
4. Remove parser support for the old syntax

This aligns with the broader goal of **100% standard SysML v2** (Phase 2 in the architecture review roadmap).

### Testing

The test suite (`tests/test_system_explorer.py`) must include:

- Parser tests for `perform`, `fork`, `join`, `flow of`
- Swimlane derivation logic (action → owning part via `perform` edge)
- DOM tests for activity view rendering (when Edge is available)

## Notes

This decision eliminates one of the three remaining dialect gaps ([architecture review](../../uploads/report_4d53.md) Section 3.1):

- ~~`ibd def`~~ (removed previously)
- ~~`actor def`~~ (migration planned, Phase 2)
- **`perform action by`** (this ADR removes it)

After this change, only `actor def` remains as a non-standard construct, and it has a clear migration path to standard SysML v2.
