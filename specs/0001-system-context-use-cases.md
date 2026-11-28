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

- [ ] Parser recognizes `activity` definitions with:
  - `action` declarations
  - `first`, `then` succession
  - `fork`, `join` concurrency (**gap: not yet supported**)
  - `flow of` item flows (**gap: not yet supported**)
  - `perform <action> by <part>;` allocations (**gap: not yet supported, but custom `perform action` exists**)
- [ ] Parser **stops accepting** the custom `perform action { ... }` dialect (breaking change)
- [ ] Viewer derives swimlanes from `perform` relationships (which part owns which action)
- [ ] Viewer renders actions in vertical lanes grouped by owning part
- [ ] Viewer renders `fork` and `join` as split/merge markers across lanes
- [ ] Viewer renders `flow of` as dashed arrows between actions
- [ ] Actions with no `perform` allocation go in an "unassigned" lane
- [ ] User can manually position actions within lanes
- [ ] Positions saved to `views/<id>.json` with lane metadata

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

**Purpose**: Demonstrates activity flow with actions allocated to actor roles, fork/join concurrency, and item flows.

```sysml
package SurgicalSystem {
    // Actor part definitions
    part def Surgeon;
    part def Nurse;
    part def Anesthesiologist;
    part def Patient;
    
    // Activity definition
    activity PerformSurgeryActivity {
        doc /* Detailed flow of the surgical procedure with role assignments. */
        
        // Action declarations
        action preparePatient {
            doc /* Prepare patient for surgery. */
        }
        
        action administerAnesthesia {
            doc /* Administer anesthesia to patient. */
        }
        
        action makeSurgicalIncision {
            doc /* Make initial surgical incision. */
        }
        
        action performSurgery {
            doc /* Execute the main surgical procedure. */
        }
        
        action monitorVitalSigns {
            doc /* Continuously monitor patient vital signs during surgery. */
        }
        
        action closeIncision {
            doc /* Close surgical incision and apply dressing. */
        }
        
        action recoverPatient {
            doc /* Monitor patient recovery in post-op. */
        }
        
        // Actor part instances (for allocation)
        part nurse : Nurse;
        part surgeon : Surgeon;
        part anesthesiologist : Anesthesiologist;
        
        // Succession flow
        first preparePatient;
        then administerAnesthesia;
        then makeSurgicalIncision;
        
        // Fork into parallel actions
        fork makeSurgicalIncision;
        then performSurgery;
        then monitorVitalSigns;
        
        // Join after parallel section
        join;
        then closeIncision;
        then recoverPatient;
        
        // Actor allocations (who performs what)
        perform preparePatient by nurse;
        perform administerAnesthesia by anesthesiologist;
        perform makeSurgicalIncision by surgeon;
        perform performSurgery by surgeon;
        perform monitorVitalSigns by nurse;
        perform closeIncision by surgeon;
        perform recoverPatient by nurse;
        
        // Item flow (patient moves through the procedure)
        flow of patient : Patient from preparePatient to administerAnesthesia;
        flow of patient from administerAnesthesia to makeSurgicalIncision;
        flow of patient from makeSurgicalIncision to performSurgery;
        flow of patient from performSurgery to closeIncision;
        flow of patient from closeIncision to recoverPatient;
    }
}
```

**Expected behavior**:
- Parser extracts activity with 7 actions
- Parser extracts succession: `first` → `then` chain with `fork`/`join`
- Parser extracts `perform ... by ...` allocations (swimlane assignments)
- Parser extracts `flow of` item flows
- Viewer renders:
  - 3 swimlanes: Surgeon, Nurse, Anesthesiologist
  - Actions positioned vertically within their owning lane
  - Fork marker after `makeSurgicalIncision` (splits into 2 parallel branches)
  - Join marker before `closeIncision` (merges branches)
  - Dashed arrows showing Patient item flowing through actions
  - `monitorVitalSigns` and `performSurgery` on the same vertical level (parallel)

**Validation**: This fixture uses standard SysML v2 and should pass both official and JamieD parsers.

## Parser Requirements

### Already Supported (per FEATURES.md)

- [x] `use case def` with `actor` and `subject` usages
- [x] `action` declarations
- [x] `first`, `then` succession
- [x] `decide`, `if ... then`, `else` branching

### New Requirements (Gaps)

- [ ] **`fork` / `join` keywords**: Add regex patterns `RE_FORK` and `RE_JOIN`, emit control-flow markers in activity edges
- [ ] **`flow of` item flows**: Parse `flow of <item> : <Type> from <action> to <action>;`, emit item-flow edges (kind: `item-flow`, dashed rendering)
- [ ] **Standard `perform ... by ...` allocations**: Parse `perform <action> by <part>;` at activity level (not nested in actions), build a map of action → owning part for swimlane derivation
- [ ] **Deprecate custom `perform action` dialect**: Remove or warn on `RE_PERFORM_ACTION` and `RE_PERFORM_LANE` patterns (breaking change for existing models)

### Implementation Plan

1. Add `RE_FORK`, `RE_JOIN`, `RE_FLOW_OF`, `RE_PERFORM_BY` regex patterns
2. Update `_interpret_activity()` to:
   - Recognize `fork` / `join` keywords, add to `{"forks": [...], "joins": [...]}`
   - Parse `flow of` statements, emit item-flow edges
3. Add a new parsing phase for `perform ... by ...` (at `activity` body level, not inside `perform action`)
4. Build `{"swimlanes": {"action_id": "part_id"}}` map from `perform` statements
5. Update model JSON to include `{"activities": [{"name", "actions", "edges", "forks", "joins", "itemFlows", "swimlanes"}]}`
6. Viewer consumes swimlane map to group actions into lanes

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

### Fork/Join Rendering

- [ ] Render `fork` as a split marker (horizontal bar across lanes with outgoing arrows)
- [ ] Render `join` as a merge marker (horizontal bar across lanes with incoming arrows)
- [ ] Actions between `fork` and `join` are on the same vertical level (parallel)

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
| **`fork` / `join` keywords** | Not currently parsed; activities use only `first` / `then` succession | Small — add 2 regex patterns, emit markers |
| **`flow of` item flows** | Not currently parsed; no item-flow edges in model JSON | Medium — parse statement, emit edge with type |
| **Standard `perform ... by ...`** | Parser uses custom `perform action` / `perform Name.action;` dialect | Medium — add regex, build allocation map, **breaking change** |

### Viewer Gaps

| Gap | Description | Effort |
|-----|-------------|--------|
| **Swimlane layout** | No swimlane rendering; activities render as flat lists or simple flows | Large — lane grouping, dividers, manual positioning |
| **Fork/join markers** | No visual representation of concurrency | Medium — horizontal bars, parallel positioning |
| **Item flow arrows** | No dashed arrows for item flows | Medium — edge rendering, label placement |
| **Activity ↔ use case linking** | No automatic detection of which activity belongs to which use case | Small — naming convention or explicit link |

## Validation Status

### Official Parser (OMG SysML v2 Pilot)

- **Fixture 1 (use case def)**: ✅ Should pass (standard SysML v2 syntax, already supported)
- **Fixture 2 (activity with swimlanes)**: ⚠️ **Validation pending** — requires conda env with `jupyter-sysml-kernel`:
  ```bash
  # Save fixture to test.sysml, then:
  python -m system_explorer.official_check .
  ```

**Expected result**: Pass if SysML v2 supports `fork`, `join`, `flow of`, and `perform ... by ...` as documented. 

**Critical validation note**: The spec assumes these constructs are standard SysML v2 based on the language specification. If the official parser rejects any construct:
- Consult SysML v2 specification to verify syntax
- If syntax is correct but parser doesn't support it yet → document as pilot limitation
- If construct is **not in SysML v2** → **this is a blocker** requiring spec revision (ADR 0004 depends on standard conformance)

### JamieD Parser

- **Fixture 1**: ✅ Should pass (standard `use case def` syntax)
- **Fixture 2**: ⚠️ **Validation pending** — requires Node.js and JamieD.sysml-v2-support extension:
  ```bash
  python -m system_explorer.jamied_check test.sysml
  ```

**Note**: JamieD parser is a community grammar, so discrepancies with official parser are possible. Official parser is authoritative.

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
