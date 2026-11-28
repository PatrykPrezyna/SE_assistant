# Spec 0003: Trace highlight, interview quick-add, undo

**Status:** Implemented  
**Author:** System  
**Date:** 2026-11-28

## Summary

Three small additions for someone reading a model with a stakeholder, or
capturing one live in an interview. The traceability view shows the thread
on the diagram instead of opening a second panel. The context and use-case
views can add a person, a use case, and an actor link without leaving the
page. Edits can be undone, and the toolbar says whether the last save
worked.

Depends on the embedded-chat fix (spec 0001, PR #6) and the activity
diagram (spec 0002, PR #8). Merge order is #6, then #8, then this work.
Swimlane layout is unchanged. Activity-bar edits use the same undo stack
and the same save-status word.

## User stories

1. **As a reader of the traceability view**, I want a click to light up the
   whole chain (need, requirement, use case, stakeholder, and the
   satisfy / derive / verify links) and dim the rest, so I can see the
   thread without a details panel repeating what is already drawn.

2. **As a facilitator in a stakeholder interview**, I want to add a
   stakeholder or a use case by typing a name and an optional short
   description, and connect that person to a use case as an actor, so the
   model is updated before the conversation moves on.

3. **As an editor**, I want Ctrl+Z / Ctrl+Shift+Z and toolbar buttons to
   undo and redo those edits, and a status that stays on screen
   (Saving… / Saved / Error), so a mis-click is recoverable and a failed
   save is obvious.

## Acceptance criteria

### Traceability view

- [x] A view is the traceability view when its name or id contains
      "trace" and it is not an activity view.
- [x] Clicking an element does not open the detail sheet.
- [x] The selected element, every element reachable from it by trace
      links in either direction, and those links, stay fully visible.
      Trace links are satisfy, verify, derive, stakeholder, and
      association (use case ↔ actor/subject).
- [x] Everything else on the canvas is dimmed.
- [x] Clicking empty canvas, or pressing Esc, clears the selection and
      the dimming.
- [x] Other views keep the existing one-hop highlight and the detail sheet.
- [x] Activity views are unchanged.

### Quick-add (context and use-case views)

- [x] A view is an interview view when its name or id contains "context"
      or "use case" and it is not an activity view.
- [x] The bar offers: stakeholder name + optional description, use case
      name + optional description, and a pick list that links a
      stakeholder to a use case as an actor.
- [x] A stakeholder is a `part def` in the existing `*Context.sysml` file
      (or a new `SystemContext.sysml`). Not an `actor def`.
- [x] A use case is a `use case def` in the existing use-case file (or a
      new `UseCases.sysml`), with a `doc` comment when a description was
      given.
- [x] Linking writes `actor <lowerCamel> : <Stakeholder>;` inside that
      use case, and a `private import` of the stakeholder's package when
      the two definitions are not already in the same package.
- [x] Names typed in plain words ("the nurse") are stored as
      UpperCamelCase (`TheNurse`). Duplicates and empty names are refused.
- [x] The new element is added to the open view and the file is saved
      through the existing path: written locally, and committed with the
      signed-in user when the explorer is hosted.
- [x] The generated files pass `system-explorer --check`.

### Undo and save status

- [x] Undo and Redo buttons are always on the toolbar. Shortcuts are
      Ctrl+Z and Ctrl+Shift+Z (Command on a Mac). They do not fire while
      typing in a field.
- [x] One step is one edit: a move, a view-membership change, a display
      option, a documentation link, hiding a connection, one quick-add, or
      one activity-bar edit.
- [x] Undoing a quick-add or an activity edit restores the `.sysml` text
      as well as the view.
- [x] The status stays visible: Saving…, Saved, Error. Unsaved means the
      diagram has edits that Save has not written yet.
- [x] Revert (back to the last Save) still works.

## Design

### Why a pick list, not a drag

Dragging a node already moves it (Edit on) or pans the diagram (Edit off).
A second meaning for the same gesture would be easy to do by accident
during an interview. Two dropdowns and Connect is one deliberate step.

### SysML v2 constructs

Written text uses only standard notation:

- `part def Name { doc /* … */ }` for a stakeholder. In this model's
  convention a person is a part definition, later referenced as an actor.
  The tool does not write `actor def` (that keyword is not standard SysML
  v2, and the explorer's own dialect notes say so).
- `use case def Name { doc /* … */ actor role : Type; }` for a use case
  and its participants. `actor` here is a usage typed by the stakeholder's
  part def, which is the standard way to say who takes part.
- `private import Package::*;` so a use case in another package can name
  that part def. The explorer already resolves simple names across files;
  the import is there for a conforming parser.
- Parsed, not written by quick-add: `stakeholder role : Type;` inside a
  requirement (a stakeholder feature), and
  `#derivation dependency <name> from <derived> to <source>;`
  (a derivation dependency). Both become edges so the traceability view
  can follow them. `satisfy` and `verify` were already parsed.

### Trace walk

Undirected breadth-first search over the edges currently drawn, limited to
the five trace kinds. A requirement between a need and a use case lights
both directions. Composition, typing, specialization, and connectors are
not trace links, so a decomposition view does not dim itself.

### Save path

`POST /api/model/edit` with `action` of `add_stakeholder`, `add_use_case`,
`link_actor`, or `restore_files`. The handler writes the file and, in
hosted mode, calls the same `commit_and_push` used for view saves. A write
that introduces new parser warnings is rolled back. `restore_files` accepts
only a bare `*.sysml` name in the model folder.

## Non-goals

- No changes to activity-diagram layout, swimlanes, or how a step is selected.
- The interview bar and the activity bar are different controls. Only one
  is on screen: the interview bar on a context or use-case view, the
  activity bar on an activity view with Edit on.
- No drag-to-connect.
- Undo does not cover creating, renaming, or deleting a view.
- The published phone viewer is unchanged.

## Risks

- A view whose name happens to contain "trace" or "context" picks up the
  new behavior. That matches how these views are named in the CoolSpine
  model; a decomposition view does not match.
- Undo history is in the browser tab. A reload clears it. The files and
  the last Save remain.
