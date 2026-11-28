# Spec 0004: A new project on login, and an insulin-pump example

Spec 0001 on this branch is the embedded assistant. Spec 0002 is the
activity diagram on PR #8 (`specs/0002-activity-diagram.md`). Spec 0003
is trace highlighting, interview quick-add, and undo on PR #9
(`specs/0003-trace-quickadd-undo.md`). This spec is 0004 so those
numbers stay unique. PR #2 uses a different
`specs/0001-system-context-use-cases.md` and does not take 0002, 0003,
or 0004.

**Status:** Implemented
**Author:** System
**Date:** 2026-11-28

There is no `AGENTS.md` in this repo. This spec follows the same shape as
`specs/0001-embedded-assistant.md`: write the spec before the code, record
the persistence choice in `docs/adr/`, and add tests in the same change.

## Summary

Signing in today opens the spine-cooling model that lives at the root of
`GITHUB_REPO`. After this change, signing in opens a fresh empty project.
Earlier projects stay in the same git repo and can be opened again from a
Projects menu. An Example button opens a small insulin-pump model that
ships inside the `system-explorer` package.

The spine-cooling files are not the landing project, and this feature
never deletes or rewrites them.

## User stories

1. **As a signed-in user**, I want a new empty project when I log in, so I
   am not dropped into the spine-cooling example.
2. **As a returning user**, I want my earlier projects still there, so a
   new login does not throw away what I already modeled.
3. **As a learner**, I want an Example button that opens a small medical
   device, so I can see stakeholders, needs, requirements, use cases, and
   one activity without touching my project.
4. **As someone running the tool locally**, I want the same new-project
   behavior, so hosted mode is not a special case.

## Acceptance criteria

- [x] Each successful GitHub login creates one new project and opens it.
- [x] A refresh in the same session stays on that project. A later login
      creates another project; it does not replace the previous one.
- [x] The new project is a valid SysML v2 skeleton: a package file and an
      empty context file, following the `*Context.sysml` convention.
- [x] Projects are listed in a Projects menu (newest first) and can be
      opened. The menu is a separate toolbar control from the view switcher.
- [x] Example opens the bundled insulin pump. The package original is not
      modified. In a workspace, the first edit copies it into a new project.
- [x] The example includes Patient, Caregiver, Endocrinologist, Regulator
      (FDA), and Manufacturer; a few user needs; requirements traced with
      the relationships the explorer already draws (`satisfy`, `verify`);
      use cases Deliver Basal Insulin, Deliver Bolus, and Handle Occlusion
      Alarm; and one swimlane activity in standard SysML v2: actions owned
      by the use case, `perform 'Step';` inside each `actor`, `first`/`then`
      successions, a `decide` with `if`/`else`, and a `merge`.
- [x] `system-explorer --check` reports no warnings for the skeleton and
      for the example.
- [x] The example files are package data and are present after
      `pip install` (the install does not depend on the source checkout).
- [x] Hosted mode stores projects in the cloned git repo (see the ADR).
      Render's disk is not the store.
- [x] No code path writes, deletes, or stages a file that sits in the
      workspace root beside `projects/`. The repository model, when one
      exists, can be opened read-only from the menu.
- [x] Local `system-explorer <folder>` still opens that folder when it
      already contains `.sysml` files. `--workspace`, and a folder with no
      `.sysml` files, start a new project the same way hosted mode does.
- [x] Tests cover creation, the project list, example loading, and package
      data. The UI change is the two toolbar controls and their menu.

## Design

### Persistence

See `docs/adr/0007-git-backed-projects.md`. Short version: one folder per
project at `<workspace>/projects/<id>/`, committed with the existing
`GitSync`. The workspace is `MODEL_PATH` (`.` in the Render deployment).

### Session

The active project id is a `sx_project` cookie.

- Login creates a project, commits it, and sets the cookie.
- Opening a project or the example sets the cookie and reloads the page.
- The signed-in GitHub session is unchanged. The project cookie only
  chooses which folder the server reads.

### What the server reads

`make_handler` gains an optional project library. With no library (the
existing tests, and `system-explorer <folder>` on a model), behavior is
unchanged except for the Example button, which serves the packaged model
read-only.

With a library, each request resolves the cookie:

| Cookie | Folder | Writes |
|---|---|---|
| a project id | `projects/<id>/` | committed as that project |
| `example` | package data | copy into `projects/<new id>/` on the first write, when a library exists; otherwise rejected |
| `repository` | workspace root | rejected |
| missing, local workspace | the project created at startup | committed only in hosted mode |
| missing, hosted | a new project is created | committed |

### Example model

Five files, name-sorted so a later official-parser run sees dependencies
first. Stakeholders are `part def`s in the context file (the same convention
as Patient and Surgeon in spine-cooling, and as spec 0001). Use cases name
them with `actor` / `subject`. The occlusion use case carries the only
activity.

The explorer draws `satisfy` and `verify`. It does not draw a separate
`derive` edge, so a system requirement that comes from a user need
`satisfy`s that need. The wording in the requirement `doc` says "derived
from". This spec does not add a new relationship type; another change is
working on traceability views.

The occlusion activity is standard SysML v2, in the spelling the
swimlane view reads (PR #8, spec 0002): the use case owns the
`action` steps, each `actor` body says `perform 'Step';`, order is
`first`/`then`, and the choice is `decide` with `if`/`else` joining
again at `merge`. The Occlusion alarm view is an activity view of
`InsulinPumpUseCases::HandleOcclusionAlarm`, so that view draws the
lanes. The example does not use the `perform action { … }` dialect.

### Toolbar

One toolbar. After the flexible space, and before Chat: the project
name, **Projects**, **Example**, **Undo**, **Redo**, and the save-status
word. **Save** stays with the edit controls, before the flexible space.
The view dropdown stays at the left.

- **Projects** opens a menu: New project, then the saved projects, then
  the read-only repository model when the workspace root has `.sysml` files.
- **Example** opens the insulin pump.

The current project name is a label next to those buttons. Opening
another project, creating one, or copying the example reloads the page
and clears the undo history first. Undo steps name files in the project
that was open, so they are not replayed after the switch. A write that
copies the example includes `switchedProject` (the new project id) in
the JSON response.

## Non-goals

- Deleting a project.
- Per-user access control inside the repo. Collaborators who can sign in
  can open every project, which is the same rule as today's single model.
- A new `derive` edge kind, or any change to activity or trace rendering.
- Rewriting `PatrykPrezyna/spine-cooling-model` history or moving its files.

## Risks

- A write that used the workspace root would rewrite the spine-cooling
  files. Writes go through `ProjectLibrary.assert_project_file`, which
  refuses any path outside `projects/<id>/`.
- Package data has been left out of the wheel before. The test builds a
  wheel the same way `pip install` does and checks the example files are
  inside it.
