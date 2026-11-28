# Spec 0001: System Context and Use Cases Activity + Use Case Activity View with Swimlanes

**Status**: Ready

**Feature ID**: `FEAT-0001`

**Related ADRs**: 
- [ADR-0003: System Context and Use Cases Activity](../docs/adr/0003-system-context-use-cases.md)
- [ADR-0004: Use Case Activity Views with Swimlanes](../docs/adr/0004-use-case-activity-swimlanes.md)

## Overview

Implement the second Activity Repository step: **system context and use cases**. Users define the system boundary, actors (derived from stakeholders), and use case interactions. Each use case can drill down into an **activity view** showing the internal flow of actions grouped into swimlanes by actor role, using **standard SysML v2 semantics** (not custom dialect).

## User Stories

### Story 1: Define System Context

```
As a systems engineer,
I want to define which actors interact with my system and what use cases exist,
So that the system boundary and external interfaces are clear before I write detailed requirements.
```

### Story 2: Drill Down into Use Case Flow

```
As a systems engineer,
I want to open a use case and see the sequence of actions (who does what, when),
So that I understand the operational scenario and can trace requirements to specific action steps.
```

### Story 3: Visualize Parallel Activities

```
As a medical device engineer,
I want to show that "monitoring vital signs" and "performing surgery" happen concurrently,
So that the operational flow accurately represents real-world parallelism.
```

## Acceptance Criteria

### Use Case Definitions

- [x] Parser recognizes `use case def` with name, `doc`, `subject`, and `actor` usages (already supported per FEATURES.md)
- [ ] Viewer renders use cases as pale green nodes with associations to actors
- [ ] Use cases can `satisfy` requirements (already supported)

### Activity Views with Swimlanes

- [ ] Parser recognizes `action def` as activity definitions with:
  - nested `action` declarations
  - `first`, `then` succession
  - `flow <source> to <target>;` item flows (**gap: not yet supported**)
  - `perform <action>;` statements inside `part` definitions for allocation (**gap: custom `perform action` exists instead**)
- [ ] Parser **stops accepting** the custom `perform action { ... }` dialect (breaking change)
- [ ] Viewer derives swimlanes from `perform` statements in nested parts (which part performs which action)
- [ ] Viewer renders actions in vertical lanes grouped by performing part
- [ ] Viewer renders `flow` statements as dashed arrows between actions
- [ ] Actions with no `perform` allocation go in an "unassigned" lane
- [ ] User can manually position actions within lanes
- [ ] Positions saved to `views/<id>.json` with lane metadata

**Note on fork/join**: Standard SysML v2 does not have `fork` and `join` keywords (confirmed via official parser validation). Concurrency must be represented through other means (e.g., multiple succession paths, decision/merge nodes).

### Traceability

- [ ] Actors in use cases link back to stakeholder definitions
- [ ] Use case activities reference the use case definition
- [ ] Actions in activity views can be traced to requirements (future: via `satisfy` on actions)

## Example Fixtures

### Fixture 1: Surgical Procedure Use Case

**Purpose**: Demonstrates use case definition with actors, subject, and objective.

```sysml
package SurgicalSystem {
    // Actor definitions (derived from stakeholders)
    part def Surgeon {
        doc /* Medical professional performing the surgery. */
    }
    
    part def Nurse {
        doc /* Medical professional assisting with the procedure. */
    }
    
    part def Anesthesiologist {
        doc /* Medical professional managing anesthesia. */
    }
    
    part def Patient {
        doc /* Individual undergoing the surgical procedure. */
    }
    
    // System definition
    part def SurgicalSystem {
        doc /* Integrated system supporting surgical procedures. */
    }
    
    // Use case definition
    use case def PerformSurgery {
        doc /* Surgeon performs a surgical procedure on a patient with support from the surgical team. */
        
        subject system : SurgicalSystem;
        
        actor surgeon : Surgeon;
        actor patient : Patient;
        actor nurse : Nurse;
        actor anesthesiologist : Anesthesiologist;
        
        objective {
            doc /* Complete the surgical procedure safely and effectively. */
        }
    }
}
```

**Expected behavior**:
- Parser extracts `use case def PerformSurgery` as a node
- Parser extracts `actor` and `subject` usages as association edges (already supported)
- Viewer renders:
  - Pale green `PerformSurgery` node
  - Purple association lines to `Surgeon`, `Nurse`, `Anesthesiologist`, `Patient` actor nodes
  - Association line to `SurgicalSystem` subject

**Validation**: This fixture uses standard SysML v2 and should pass both official and JamieD parsers.

### Fixture 2: Surgical Procedure Activity with Swimlanes (Standard SysML v2)

**Purpose**: Demonstrates activity flow with actions allocated to actor roles and item flows.

```sysml
package SurgicalSystem {
    part def Surgeon {
        doc /* Medical professional performing the surgery. */
    }
    
    part def Nurse {
        doc /* Medical professional assisting with the procedure. */
    }
    
    part def Anesthesiologist {
        doc /* Medical professional managing anesthesia. */
    }
    
    item def Patient {
        doc /* Individual undergoing the surgical procedure. */
    }
    
    part def SurgicalSystem {
        doc /* Integrated system supporting surgical procedures. */
    }
    
    use case def PerformSurgery {
        doc /* Surgeon performs a surgical procedure on a patient with support from the surgical team. */
        
        subject system : SurgicalSystem;
        
        actor surgeon : Surgeon;
        actor patient : Patient;
        actor nurse : Nurse;
        actor anesthesiologist : Anesthesiologist;
        
        objective {
            doc /* Complete the surgical procedure safely and effectively. */
        }
    }
    
    // Activity as action definition (not "activity def")
    action def PerformSurgeryActivity {
        doc /* Detailed flow of the surgical procedure with role assignments. */
        
        in item patientIn : Patient;
        out item patientOut : Patient;
        
        // Action declarations
        action preparePatient {
            in item patient : Patient;
            out item prepared : Patient;
        }
        
        action administerAnesthesia {
            in item patient : Patient;
            out item anesthetized : Patient;
        }
        
        action makeSurgicalIncision {
            in item patient : Patient;
            out item incised : Patient;
        }
        
        action performSurgicalProcedure {
            in item patient : Patient;
            out item operated : Patient;
        }
        
        action closeIncision {
            in item patient : Patient;
            out item closed : Patient;
        }
        
        action recoverPatient {
            in item patient : Patient;
            out item recovered : Patient;
        }
        
        // Succession flow
        first preparePatient;
        then administerAnesthesia;
        then makeSurgicalIncision;
        then performSurgicalProcedure;
        then closeIncision;
        then recoverPatient;
        
        // Actor part instances with perform allocations (swimlanes)
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
        
        // Item flows between actions
        flow preparePatient.prepared to administerAnesthesia.patient;
        flow administerAnesthesia.anesthetized to makeSurgicalIncision.patient;
        flow makeSurgicalIncision.incised to performSurgicalProcedure.patient;
        flow performSurgicalProcedure.operated to closeIncision.patient;
        flow closeIncision.closed to recoverPatient.patient;
    }
}
```

**Expected behavior**:
- Parser extracts `action def PerformSurgeryActivity` as the activity
- Parser extracts 6 nested actions
- Parser extracts succession: `first` → `then` chain
- Parser extracts `perform` statements from nested parts (swimlane assignments)
- Parser extracts `flow` statements for item flows
- Viewer renders:
  - 3 swimlanes: Surgeon, Nurse, Anesthesiologist
  - Actions positioned vertically within their performing part's lane
  - Dashed arrows showing Patient item flowing through actions

**Validation**: ✅ **VALIDATED** with official SysML v2 Pilot Implementation parser (exit code 0, no errors)

**Note**: Concurrency (e.g., parallel monitoring) is implicit in the allocation—multiple parts can perform actions simultaneously. Standard SysML v2 does not have explicit `fork`/`join` keywords.

## Parser Requirements

### Already Supported (per FEATURES.md)

- [x] `use case def` with `actor` and `subject` usages
- [x] `action` declarations
- [x] `first`, `then` succession
- [x] `decide`, `if ... then`, `else` branching

### New Requirements (Gaps)

- [ ] **`flow` item flows**: Parse `flow <source> to <target>;` statements, emit item-flow edges (kind: `item-flow`, dashed rendering)
- [ ] **Standard `perform` allocations in parts**: Parse `part <name> : <Type> { perform <action>; }` patterns, build a map of action → performing part for swimlane derivation
- [ ] **Deprecate custom `perform action` dialect**: Remove or warn on `RE_PERFORM_ACTION` and `RE_PERFORM_LANE` patterns (breaking change for existing models)

**Note**: `fork`/`join` keywords do not exist in standard SysML v2 (confirmed via official parser). Concurrency is represented through other means in the standard.

### Implementation Plan

1. Add `RE_FLOW` regex pattern for `flow <source> to <target>;` statements
2. Update parsing to recognize `perform <action>;` statements inside `part <name> : <Type> { ... }` blocks within action definitions
3. Build `{"swimlanes": {"action_id": "part_id"}}` map from `perform` statements in nested parts
4. Update model JSON to include `{"activities": [{"name", "actions", "edges", "itemFlows", "swimlanes"}]}`
5. Viewer consumes swimlane map to group actions into lanes

### Migration from Custom Dialect

**Breaking change**: The existing `perform action Name { ... }` syntax (documented as non-standard in FEATURES.md) must be removed or deprecated with a clear warning:

```
Warning: 'perform action { ... }' is deprecated. Use standard SysML v2 'activity <name> { ... }' 
with 'perform <action> by <part>;' allocations. See docs/migrations/perform-action-to-activity.md.
```

Existing models (e.g., CoolSpine if it uses this syntax) need migration before this feature lands.

## Viewer Requirements

### Activity View Mode

- [ ] Detect when a use case has an associated activity (naming convention: `PerformSurgeryActivity` for `PerformSurgery` use case)
- [ ] Add context menu option on use case nodes: "Open Activity View"
- [ ] Enter "activity view" mode showing swimlanes instead of block diagram

### Swimlane Rendering

- [ ] Derive lanes from `swimlanes` map (group actions by owning part)
- [ ] Render vertical lane dividers (pale background tint per lane, header with part name)
- [ ] Position actions within their lane (manual drag-and-drop)
- [ ] Render actions with no allocation in an "Unassigned" lane
- [ ] Support `first` → `then` vertical flow within/across lanes

### Concurrency Rendering

**Note**: Standard SysML v2 does not have `fork`/`join` keywords. Concurrency is implicit when multiple parts perform actions in parallel. The viewer may choose to visually indicate parallel execution through layout (e.g., actions at the same vertical level) or leave it implicit.

### Item Flow Rendering

- [ ] Render `flow of` as dashed arrows (blue or distinct color)
- [ ] Arrow label shows item name and type (e.g., "patient : Patient")
- [ ] Arrows cross swimlane boundaries when actions are in different lanes

### View Persistence

- [ ] Save action positions within lanes to `views/<id>.json`:
  ```json
  {
    "version": 1,
    "name": "Perform Surgery Activity",
    "kind": "activity",
    "elements": ["PerformSurgeryActivity::preparePatient", ...],
    "nodes": {
      "PerformSurgeryActivity::preparePatient": {"x": 150, "y": 100},
      ...
    },
    "lanes": {
      "Surgeon": ["PerformSurgeryActivity::makeSurgicalIncision", ...],
      "Nurse": ["PerformSurgeryActivity::preparePatient", ...],
      ...
    }
  }
  ```

## Known Gaps

### Parser Gaps

| Gap | Description | Effort |
|-----|-------------|--------|
| **`flow` item flows** | Not currently parsed; no item-flow edges in model JSON | Medium — parse `flow <source> to <target>;` statements, emit edge |
| **Standard `perform` in parts** | Parser uses custom `perform action` / `perform Name.action;` dialect instead of `part { perform <action>; }` | Medium — parse nested perform statements, build allocation map, **breaking change** |

**Removed gap**: `fork`/`join` keywords (not in standard SysML v2 per official parser validation)

### Viewer Gaps

| Gap | Description | Effort |
|-----|-------------|--------|
| **Swimlane layout** | No swimlane rendering; activities render as flat lists or simple flows | Large — lane grouping, dividers, manual positioning |
| **Item flow arrows** | No dashed arrows for item flows | Medium — edge rendering, label placement |
| **Activity ↔ use case linking** | No automatic detection of which activity belongs to which use case | Small — naming convention or explicit link |

**Removed gap**: Fork/join markers (not in standard SysML v2)

## Validation Status

### Official Parser (OMG SysML v2 Pilot)

**Test environment**: Miniconda 26.9.4, jupyter-sysml-kernel from conda-forge, Python 3.11

**Fixture 1 (use case def)**: ✅ **PASS**
```bash
$ python -m system_explorer.official_check /tmp/sysml_test
surgical.sysml: OK
OK - official parser reports no problems in 1 file(s)
```

**Fixture 2 (action def activity with swimlanes)**: ✅ **PASS**
```bash
$ python -m system_explorer.official_check /tmp/sysml_test
surgical_final.sysml: OK
OK - official parser reports no problems in 1 file(s)
```

**Validation findings**:
1. ✅ `action def` works for activity definitions (NOT `activity def` - that keyword doesn't exist)
2. ✅ `first`/`then` succession works
3. ✅ `perform <action>;` inside `part <name> : <Type> { ... }` works for allocation
4. ✅ `flow <source> to <target>;` works for item flows (NOT `flow of` - requires simpler syntax)
5. ❌ `fork`/`join` keywords **do not exist** in standard SysML v2 (official parser rejects them)
6. ❌ `perform <action> by <part>;` syntax **does not exist** (official parser rejects it)

**Repository example model**: `methodology/example`
- `stakeholders.sysml`: ✅ PASS
- `user_needs.sysml`: ⚠️ 4 warnings (subject must be first parameter in requirement defs)

### JamieD Parser

Not tested (official parser is authoritative and validates fixtures pass).

### Tool's `--check` Flag

- Both fixtures should pass once parser gaps are closed (no unresolved references, no unrecognized statements).

## Testing Notes

### Parser Tests (`test_system_explorer.py`)

1. **Use case definition parsing**:
   ```python
   def test_use_case_with_actors(self):
       model = parse_sysml("""
           package Test {
               part def Surgeon;
               use case def PerformSurgery {
                   subject sys : System;
                   actor surgeon : Surgeon;
               }
           }
       """)
       uc = node(model, "PerformSurgery")
       self.assertEqual(uc["kind"], "use case def")
       # Assert association edges exist
   ```

2. **Activity with swimlanes parsing**:
   ```python
   def test_activity_with_swimlanes(self):
       model = parse_sysml(SURGICAL_FIXTURE)  # Fixture 2 above
       activity = model["activities"][0]
       self.assertEqual(activity["name"], "PerformSurgeryActivity")
       self.assertEqual(len(activity["actions"]), 7)
       self.assertIn("fork", activity)
       self.assertIn("join", activity)
       self.assertEqual(len(activity["itemFlows"]), 5)
       # Assert swimlane allocations
       self.assertEqual(activity["swimlanes"]["preparePatient"], "nurse")
   ```

3. **Fork/join succession**:
   ```python
   def test_fork_join_concurrency(self):
       # Assert fork edge exists, join edge exists, parallel actions identified
   ```

### HTTP Tests

- No new API endpoints (activities are part of model JSON)
- Verify `GET /api/model` includes `activities` with swimlane data

### DOM Tests (Requires Edge)

1. **Swimlane rendering**:
   - Load activity view, assert lane dividers exist
   - Assert actions grouped by lane
   - Assert "Unassigned" lane appears for unallocated actions

2. **Fork/join markers**:
   - Assert fork marker rendered after `makeSurgicalIncision`
   - Assert join marker rendered before `closeIncision`

3. **Item flow arrows**:
   - Assert dashed arrows rendered between actions
   - Assert arrow labels show "patient : Patient"

## Implementation Notes

### Breaking Change: Deprecate Custom Dialect

The current `perform action` dialect (FEATURES.md lines 174-180, 199-200) **must be removed** to implement standard SysML v2 swimlanes. Migration path:

1. Update parser to **reject** `perform action` with error:
   ```
   Error: 'perform action' is not standard SysML v2. Use 'activity <name> { action ...; perform <action> by <part>; }'.
   ```
2. Write migration guide: `docs/migrations/perform-action-to-activity.md`
3. Update CoolSpine model (in its own repo) to use standard syntax
4. Update `FEATURES.md` to remove dialect notes

### Standard SysML v2 Verification

Before implementation, **validate that Fixture 2 passes the official parser**. If `fork`, `join`, or `perform ... by ...` are rejected, they are **not standard SysML v2**, and the spec must be revised.

Command to run:

```bash
# Create test directory with fixture
mkdir -p /tmp/sysml-test
cat > /tmp/sysml-test/surgical.sysml <<'EOF'
<Fixture 2 contents>
EOF

# Validate (requires conda env)
python -m system_explorer.official_check /tmp/sysml-test
```

If the official parser rejects constructs, document the gap and determine if:
- We misunderstood the syntax (revise fixture)
- The feature is SysML v2 but not supported by pilot parser (note limitation)
- The feature is **not in SysML v2** (this would be a critical blocker—ADR 0004 assumes standard conformance)

### Viewer Architecture

Swimlane rendering is **viewer-specific**. The `.sysml` model contains only:
- Activity definition
- Actions
- Succession (`first` / `then` / `fork` / `join`)
- Allocations (`perform ... by ...`)
- Item flows (`flow of`)

The **viewer derives lanes** from allocations and **lays out actions** within lanes. Other tools (Cameo, SysON) may render the same model differently (no swimlanes, different layout). This is acceptable—the **model is portable**, the visualization is tool-specific.

## References

- [FEATURES.md](../FEATURES.md) — lines 71-73 (use cases), lines 174-180 (perform action dialect), lines 494-532 (use cases and actors, activity diagrams)
- [ADR-0003: System Context and Use Cases](../docs/adr/0003-system-context-use-cases.md)
- [ADR-0004: Use Case Activity Views with Swimlanes](../docs/adr/0004-use-case-activity-swimlanes.md)
- [SysML v2 Specification](https://www.omg.org/spec/SysML/) — Chapter on Actions and Activities
- [CoolSpine Model](https://github.com/PatrykPrezyna/cool-spine-model) — reference example
