# Spec 0002: Use-case activity diagram

**Status:** Implemented
**Depends on:** Spec 0001 (embedded assistant chat) and the open chat fix (PR #6)
**Related decisions:** system context and use cases; swimlanes. This spec corrects the swimlane syntax those notes guessed.

## Why

The owner opens a use case while interviewing someone and models the process on the spot. The diagram has to stay readable as steps are added, and every edit has to land in the `.sysml` files as standard SysML v2.

## Language (plain words)

SysML v2 has no `activity` keyword. A process is an **action**. There is also no `perform … by`. Who does a step is written by putting `perform <step>;` **inside that person's part**.

| Idea | What you write | What it means |
| --- | --- | --- |
| The process | `use case def PerformSurgery { … }` | The use case owns the steps |
| A step | `action 'Prepare OR';` | One rounded box |
| Who does it | `actor nurse : Nurse { perform 'Prepare OR'; }` | The step sits in the Nurse lane |
| Order | `first start then 'Prepare OR';` | An arrow. `start` and `done` are the beginning and the end |
| A choice | `decide decide1;` then `if stable then …;` `else …;` | A diamond. The guard is the label on the arrow |
| Paths join again | `merge merge1;` | A diamond that waits for one of the alternatives |
| Do both | `fork fork1;` with two `first fork1 then …;` | A bar. Both paths start |
| Wait for both | `join join1;` | A bar. Continue only when both paths arrive |
| Something handed over | `flow 'Request Instrument'.payload to 'Provide Instrument'.payload;` | A dashed arrow. This is "the output of one step into the input of the next" (`flow source.out to target.in`) |

`fork`, `join`, `decide`, and `merge` are ordinary SysML v2 control nodes. An earlier note dropped fork and join after trying a syntax the parser does not accept (`fork <action>;`). The forms above are the ones in the language's own training examples.

A step whose body contains further steps is a sub-activity. Opening it shows those steps.

## Editing

On the activity view, with Edit on:

- **Add stakeholder** adds a lane and, if needed, a `part def` for that person.
- **Click a lane** and type a name to add a step in that lane. A selected step becomes the one it follows.
- **Connect** draws a succession.
- **Decision** asks for the guard and the two outcomes, and adds a merge so the paths can meet.
- **Fork** asks for the parallel steps and adds the matching join.
- **Rename** and **Delete** update the text.
- **New activity** adds a use case. **Sub-activity** adds a step you can open.

The embedded chat uses the same edits. If the person, the place in the flow, or a decision's two outcomes were not said, it asks one question and does not write. A complete request such as "add a decision after Assess Patient: if stable, administer anesthesia, else stabilise patient" is written immediately and the diagram refreshes.

## Reference picture

Surgeon, Nurse, and Anesthesiologist lanes. Prepare OR, Assess Patient, Administer Anesthesia, then a fork into Perform Surgery and Monitor Vital Signs, with Request Instrument and Provide Instrument on the surgery path, a join, Close Incision, Recover Patient, and the end. An item flow runs from the request to the instrument that is provided.

## Acceptance

- The parser reads this syntax, including fork, join, decide, merge, guards, and item flows. The older `perform action { … }` blocks still read, so existing models keep their diagrams.
- The view draws lanes, rounded steps, a filled start, a bullseye end, diamonds, bars, and arrows that stay readable as the graph grows.
- Edits round-trip through the parser and `system-explorer --check` reports no warnings.
- The chat tool writes the same text and the open diagram updates without a reload.
