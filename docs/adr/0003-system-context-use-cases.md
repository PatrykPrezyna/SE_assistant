# ADR 0003: System Context and Use Cases Activity

## Status

Accepted

## Context

After stakeholder analysis (Activity 1), the next methodology step needs definition. Options considered:

1. **Requirements capture** (jump straight to functional/non-functional requirements)
2. **System context and use cases** (define system boundary, actors, interactions)
3. **System decomposition** (start breaking the system into subsystems)

## Decision

Implement **system context and use cases** as Activity 2, capturing:

- System boundary (what's in scope, what's external)
- Actors (who/what interacts with the system)
- Use cases (interactions between actors and the system)

## Rationale

### Methodological Ordering

Standard SE methodologies (INCOSE, ISO 15288, Arcadia) establish context before detailed requirements:

1. Stakeholders → understand who cares
2. **System context → understand the boundary**
3. Requirements → understand what it must do
4. Architecture → understand how it's structured

Skipping context leads to scope creep (unclear what's in/out of system) and missed external interfaces.

### Use of Existing Model Elements

Stakeholder analysis already produced:
- `stakeholders.sysml` with categorized stakeholders
- `user_needs.sysml` with high-level needs

Use cases naturally **connect stakeholders to system interactions**:
- Stakeholders become actors (the roles interacting with the system)
- Needs inform which use cases matter (what interactions address which needs)
- Use cases scope the requirements that follow (requirements trace to use cases)

### SysML v2 Support

SysML v2 provides first-class support for use cases:

```sysml
use case def PerformSurgery {
    doc /* Surgeon performs a surgical procedure on a patient. */
    
    subject system : SurgicalSystem;
    
    actor surgeon : Surgeon;
    actor patient : Patient;
    actor nurse : Nurse;
    
    objective {
        doc /* Complete the surgical procedure safely and effectively. */
    }
}
```

This is standard notation, not a custom dialect, so it validates with the official parser.

### Traceability to Later Activities

Use cases serve as anchors for:
- **Requirements**: "The system shall [requirement] to support [use case]"
- **Architecture**: Design decisions traced to use case scenarios
- **Verification**: Test cases derived from use case flows

Establishing use cases early makes later activities more concrete.

## Structure

### Use Case Elements

Each use case captures:

| Field | Description | SysML v2 Construct |
|-------|-------------|-------------------|
| **Name** | Brief identifier (e.g., "Perform Surgery") | `use case def PerformSurgery` |
| **Description** | Textual summary of the interaction | `doc /* ... */` |
| **Subject** | The system being used | `subject system : SurgicalSystem;` |
| **Actors** | External entities participating | `actor surgeon : Surgeon;` |
| **Objective** (optional) | Goal of the interaction | `objective { doc /* ... */ }` |

### Actor Derivation

Actors are **roles**, not individual people. They map to stakeholder categories:

- **Customer stakeholders** → primary actors (initiate use cases to achieve goals)
- **Internal stakeholders** → supporting actors (assist in use cases)
- **Regulatory stakeholders** → oversight actors (audit or approve)

The tool generates actor definitions from the existing `stakeholders.sysml`, creating part definitions typed as actors.

### Register Format

Similar to `process/stakeholders.yaml`, use cases live in `process/use_cases.yaml`:

```yaml
system: SurgicalSystem

use_cases:
  - id: UC-01
    name: Perform Surgery
    description: Surgeon performs a surgical procedure on a patient.
    subject: SurgicalSystem
    actors:
      - Surgeon
      - Patient
      - Nurse
    objective: Complete the surgical procedure safely and effectively.
```

The `apply` tool writes standard SysML v2 to `use_cases.sysml`.

## Consequences

### Positive

- Establishes clear system boundary before requirements
- Reuses stakeholders as actors (traceability)
- Standard SysML v2 constructs (use case definitions, actors, subjects)
- Natural progression: stakeholders → context → requirements
- Use cases anchor requirements and verification

### Negative

- Adds an extra activity before requirements (more upfront work)
- Use cases alone don't specify behavior (need activity diagrams for flows—addressed in ADR 0004)
- Risk of use case proliferation (need discipline to keep them high-level)

### Next Steps

1. Implement `methodology/system_context.py` with `check`/`apply` commands
2. Create `process/use_cases.yaml` register format
3. Write `use_cases.sysml` and `actors.sysml` from the register
4. Update `product-development.yaml` with the new activity

## Notes

This decision focuses on **static context** (what use cases exist, who the actors are). **Dynamic behavior** within a use case (the flow of actions) is deferred to ADR 0004 (use case activity views).
