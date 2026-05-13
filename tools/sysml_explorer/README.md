# SysML v2 Explorer

A lightweight local tool that renders an interactive diagram from a folder of
SysML v2 text files (`.sysml`) and lets you arrange the elements manually by
dragging. You curate as many named **Views** as you like — SysML v2's term
for a purpose-built presentation of model content — each holding its own
element membership, positions, and pan/zoom. Every View is its own plain
JSON file next to the model source, so it's versionable in git independently
of every other View.

Built as an alternative to auto-layout-only viewers (SysML v2 pilot Jupyter
implementation, SysIDE) and heavyweight commercial modelers (Cameo/MagicDraw).

## Installation

This tool is a standalone pip package (no dependencies beyond the stdlib),
so it can be installed once and pointed at a SysML model folder in *any*
repository — it doesn't need to live next to the model.

```
pip install -e tools/sysml_explorer
```

installs the `sysml-explorer` command on PATH for the current environment.
To use it from a different repo/machine without a local checkout of this
one, install straight from git:

```
pip install "git+https://github.com/PatrykPrezyna/SE_assistant.git#subdirectory=tools/sysml_explorer"
```

## Usage

```
sysml-explorer <folder> [--port 8199] [--no-open]
```

Opens the diagram in your browser at `http://127.0.0.1:<port>/`. Each View is
saved to `<folder>/views/<id>.json`; everything else (documentation links,
the element tree panel, IBD/UCD drilldown state) is saved to
`<folder>/layout.json`.

Every `.sysml` file directly inside `<folder>` (not recursive — subfolders are
ignored) is merged into one model, so cross-file references resolve — e.g.
point it at a folder holding both the architecture and the requirements
package to see `satisfy` connections:

```
sysml-explorer examples/RoboticArm/1_SystemModel
```

Debugging aid — dump the parsed model as JSON without starting the server:

```
sysml-explorer <folder> --print
```

Without installing, from a checkout of this tool (e.g. while developing it
in place inside SE_assistant):

```
python -m sysml_explorer <folder>   # run from tools/sysml_explorer/src, or
                                     # with tools/sysml_explorer/src on PYTHONPATH
```

## Features

### Parsing (`src/sysml_explorer/app.py`)
Pragmatic regex/brace-based parser (not a full KerML grammar). Supported:

- `package` (incl. nested packages; nested package path shown in node header,
  and every node carries its full `packagePath`, used to group the element
  tree below)
- `part def` / `requirement def` / `item def` / `action def` / `port def` /
  `actor def` / `use case def`, including `abstract` (name rendered italic)
  and specialization `:> Super`
- attributes: type, `default` value, and `:>>` redefinitions with `= value`
- nested part usages (`part servo : ServoDrive`), including `:>>` redefinitions
  and attribute redefinitions inside them (e.g. `mechanics` length overrides).
  Each part entry is `{"text": "name : Type", "attrs": [nested redefs]}` so the
  viewer can filter nested attribute lines independently.
- top-level usages (`part robotArm : RobotArmSystem`, requirements with
  `<'REQ-123'>` short names) and their `doc /* ... */` text
- comments (`//`, `/* */`) are stripped; `doc` bodies are preserved
- `ibd def IbdName of Owner { connection role : a.b to c.d; }` — an internal
  block diagram definition contributes no node of its own; its connections
  are attached to `Owner` (resolved after all files are parsed, same as
  `satisfy`; an unresolved `of` target drops the connections silently). The
  shorthand `connect a.b to c.d;` directly inside a `part def` body is also
  recognized, without a wrapping `ibd def`.
- `use case useDiagram Name for Subject { actor a : ActorDef; use case u :
  UseCaseDef; connection n from a to u; }` — a use case diagram, handled the
  same way as `ibd def`: contributes no node of its own, and its role usages
  + named associations attach to `Subject` (resolved after all files are
  parsed; an unresolved `for` target, or a connection missing the mandatory
  `from` clause, drops silently — see Use case diagrams below).

Relationships extracted as edges:

- **specialization** (`:>`) — solid line, hollow triangle at the parent
- **composition** (nested part usage) — filled diamond at the owner, edge
  labeled with the role name
- **typing** (usage `: Def`) — dashed line, open arrow at the definition
- **satisfy** (`satisfy REQ-123;` inside a def) — dashed line, open arrow at
  the requirement, «satisfy» label. The reference is resolved by element name
  or requirement short name (`<'REQ-123'>`), including across files when
  several models are loaded; unresolved references are dropped silently. An
  edge only renders when both endpoints are members of the active View (see
  Views below).
- **association** (an actor ↔ use case link declared in a `useDiagram`
  block) — plain purple line, no arrowhead. A `useDiagram`'s connections are
  between local role usages (e.g. `operator : Operator`), but the
  relationship is really between the actor/use-case *defs* they're typed by,
  so it's resolved to those defs and surfaced as an ordinary edge — it
  renders in the block definition diagram too, not just inside UCD mode,
  whenever both the actor and use case happen to be in the same View. A def
  reused across several roles/diagrams gets one edge per distinct pair, not
  a duplicate for each connection.

### Viewer (`viewer.html`)
- drag elements to arrange them; drag the background to pan; mouse wheel zooms
- **Click to highlight**: left-clicking an element outlines it (red) and
  outlines every connection touching it plus the elements on the other end
  (blue) — a quick way to trace what's wired to what. Left-clicking a
  connection instead outlines that connection and its two endpoint elements.
  Click the background, or press Esc, to clear the highlight. It's a
  transient view aid, not saved to the layout file.
- **Save layout** (or Ctrl+S) persists the active View (membership,
  positions, pan/zoom, filters) and the global state (docs, tree panel,
  drilldown) in one action; unsaved changes are flagged and warned on close
- auto-layout for elements without a saved position (layered: parents above
  children, wholes above parts); **Auto-layout** button re-runs it for all
- **Fit view** zooms to the whole diagram
- **Reload model** re-parses the folder's `.sysml` files without losing the
  arrangement (positions are keyed by qualified element name)
- **attributes** / **parts** checkboxes hide the respective compartments.
  Attribute redefinitions nested under a part (e.g. `.length = 120.0`) follow
  the *attributes* checkbox, and are also hidden when *parts* is off.
- parse errors are shown in a banner instead of a broken page
- element kind keywords («part def», «requirement», …) are **not** shown in
  node headers by default; flip the `SHOW_KEYWORDS` constant at the top of
  the `viewer.html` script to bring them back
- connection labels (composition role names, «satisfy») are **not** shown by
  default either — `SHOW_EDGE_LABELS` constant brings them back. Instead a
  **legend** (bottom-left, `SHOW_LEGEND` constant) explains the arrow styles,
  listing only the edge kinds currently visible in the diagram. To keep
  satisfy distinguishable from typing without labels, satisfy edges are
  drawn in dark yellow.

### Views (`viewer.html`)
A **View** is a curated, named presentation of model content — SysML v2's
own term for this (`view def`/`viewpoint def`). Unlike the block definition
diagram's element list (which is just "everything the parser found"), a
View's membership is entirely up to you: nothing is in it until you add it,
typically from the element tree.

- The **view** dropdown switches between Views. Alongside it: **+ View**
  (prompts for a name, creates it empty, and switches to it), **Rename**
  (updates the name, keeps the same underlying file), **Delete** (with a
  confirmation; if it was the last View, a fresh empty one is created so
  there's always something to look at).
- A brand-new folder (no `views/` yet) gets one View auto-created on first
  launch, named "Default" and seeded with every element the parser found —
  so the first launch isn't a blank canvas. Every View you create by hand
  after that starts empty.
- **Add elements** by checking them in the element tree (see below); an edge
  between two elements renders automatically once both are members.
  **Remove from view** (right-click an element) drops just that element —
  its saved position goes with it, so re-adding it later re-runs auto-layout
  for it rather than remembering the old spot.
- **Right-click context menu** (designed to grow — new entries are added in
  `nodeMenuItems()` in `viewer.html`):
  - on an *element*: **Open internal block diagram** / **Open use case
    diagram** (only offered when the element has one — see below),
    **Remove from view**.
  - on a *connection*: **Hide connection** (removes only the line, without
    removing either endpoint — for decluttering a busy View).
  - on the *background*: **Unhide connections (n)**, **Fit view**,
    **Auto-layout**.
  - close with Esc or by clicking elsewhere.
- **Documentation links**: right-click an element → **Add documentation
  link…** and enter a file path (e.g. a PDF; relative paths resolve from the
  model folder) or an http(s) URL. Linked elements show a 📄
  marker, and the menu gains **Open documentation (file.pdf)**, which opens
  the file in a new browser tab (local files are served via `/api/doc`).
  Links are global (not per-View) and stored in the layout file (`docs`) —
  remember to **Save layout**. Enter an empty value in **Edit documentation
  link…** to remove a link.
- Each View's membership, positions, hidden connections, pan/zoom, and
  attributes/parts filters are saved in its own file
  (`<folder>/views/<id>.json`) — see Server below. The id is a filesystem-safe
  slug derived from the name when the View is created and never changes,
  even if you rename it afterwards.

### Element tree (`viewer.html`)
- A left-side panel lists every element in the *model* (not just the active
  View), grouped into a collapsible tree by `packagePath` (click a package
  header to expand/collapse its branch) — this is how you build up a View.
  Toggle the panel itself with the **☰ Tree** toolbar button; its open/
  closed state is saved in the layout file (`treeOpen`, default open).
- Each element row has a checkbox reflecting whether it's a **member of the
  active View** (and thus on the canvas right now); checking it adds the
  element to the View, unchecking it removes it — the same add/remove
  mechanism as the tree checkbox and right-click **Remove from view** are
  interchangeable, both with an immediate rebuild.
- Rows for elements not currently in the View are dimmed, with a tooltip.
- **Package headers get a checkbox too**, for adding/removing a whole
  package (including nested subpackages) at once: checked when every
  element under it is a View member, unchecked when none are, and
  indeterminate (a dash) when it's a mix. Toggling it adds or removes every
  descendant element in one go — clicking elsewhere on the header still
  just expands/collapses the branch.
- Clicking an element's name (not its checkbox) selects it (same highlight
  as clicking it on the canvas) and, if it's a View member, centers the view
  on it — a quick way to locate an element without hunting across a large
  diagram.
- Each row gets a small color dot matching its kind (yellow = requirement,
  purple = actor, green = use case, blue = any other usage; def-level
  elements are uncolored).
- Disabled (greyed out, non-interactive) while in IBD or UCD mode, since
  View membership only applies to the block definition diagram.

### Internal block diagrams (viewer.html)
- Elements that own an `ibd def`/`connect` block, or usages typed by such a
  def, carry a 🧩 marker (top-left corner of the node, next to the 📄
  documentation marker) and gain **Open internal block diagram** in their
  right-click menu.
- Opening it switches the whole canvas to **IBD mode**: the owner's parts
  become role boxes (named after the role, e.g. `drive`, typed by whatever
  they were declared as) connected by green ball-tipped **connector** edges
  — the diagram's normal nodes/edges are replaced, not overlaid.
  - a role box whose own type has an internal block diagram gets the same 🧩
    marker and menu entry, so you can drill down (**◀ Back to parent IBD**)
    into nested structure.
  - the **◀ Back** toolbar button (and the same entry in the background
    menu, worded **Close internal block diagram**) returns to the block
    definition diagram, or to the parent IBD when nested.
  - the **view** controls and **Unhide** are disabled while in IBD mode —
    both concepts belong to the block definition diagram.
  - the legend gains a **connector (IBD)** row whenever connector edges are
    visible.
  - the current mode and owner are saved in the layout file (`mode`,
    `ibdOwner`); an owner that no longer resolves (e.g. after editing the
    model) falls back to the block definition diagram.

### Use case diagrams (viewer.html)
- Actors (`actor def`) and use cases (`use case def`) render as ordinary
  block-definition nodes too — actors tinted pale purple, use cases pale
  green — so they show up in the normal BDD view and can be added to any
  View like any other element, including `satisfy` edges from a use case to
  the requirements it addresses, and **association** edges to whichever
  actors/use cases they're linked to in a `useDiagram` (see the association
  bullet under Parsing above) — add both ends to a View to see it.
- A `use case useDiagram Name for Subject { ... }` block turns `Subject`
  into an entry point: it carries a 🎭 marker (next to any 🧩/📄 markers) and
  gains **Open use case diagram** in its right-click menu (only offered from
  the block definition diagram, not from inside another drilldown).
- Opening it switches the whole canvas to **UCD mode**: the actor/use-case
  roles declared in the `useDiagram` block become nodes (named after the
  role, e.g. `operator`), connected by plain purple **association** edges
  for each `connection n from a to b;` — the diagram's normal nodes/edges are
  replaced, not overlaid. A connection without the mandatory `from` clause
  (e.g. a bare system-level trigger with only a `to`) is ambiguous and is
  dropped at parse time rather than guessed.
- Shares the same drilldown chrome as IBD mode: the **◀ Back to BDD**
  toolbar button, **Close use case diagram** in the background menu, and the
  **view** controls/**Unhide** disabled while active.
- The legend gains an **association (actor ↔ use case)** row whenever
  association edges are visible — in UCD mode or in the block definition
  diagram, wherever they end up rendering.
- The current mode and owner are saved in the layout file (`mode`,
  `ucdOwner`); an owner that no longer resolves falls back to the block
  definition diagram.
- Not yet supported: `activity def` (activity/behavior diagrams) — a
  different diagram type from use case diagrams, still unparsed.

### Server (`src/sysml_explorer/app.py`)
- `GET /` — the viewer page
- `GET /api/model` — the folder is re-globbed for `.sysml` files and
  re-parsed on every request, so a file added, edited, or removed in the
  folder shows up on refresh/**Reload model** without restarting the server
- `GET /api/layout` / `POST /api/layout` — global state persistence, always
  at `<folder>/layout.json`
- `GET /api/views` — list of `{id, name}` for every View
  (`<folder>/views/*.json`)
- `GET /api/views/<id>` — one View's full content
- `POST /api/views` — create a View; body `{"name": "..."}`, response
  `{"id": "...", "name": "..."}`. The id is a slug derived from the name
  (lowercased, non-alphanumerics collapsed to `-`; a colliding slug gets a
  `-2`, `-3`, … suffix) and is fixed for the View's lifetime
- `PUT /api/views/<id>` — replace a View's content (also used for renames —
  the id/filename never changes, only the `name` field inside); an
  idempotent create-or-replace, not update-only
- `DELETE /api/views/<id>` — remove a View

## Troubleshooting

**PDFs download instead of opening in the tab**: the server serves
documentation with `Content-Type: application/pdf` and
`Content-Disposition: inline` (and answers HEAD probes), which is everything
a browser needs to render the PDF in the tab. If your browser downloads a
copy instead, it is a browser setting: in Edge open
`edge://settings/content/pdfDocuments` and switch **off** "Always download
PDF files"; in Chrome open `chrome://settings/content/pdf` and choose
"Open PDFs in Chrome". A PDF-reader browser extension (e.g. Adobe Acrobat)
taking over PDF handling can cause the same behavior.

Antivirus loopback filters (observed with AVG Web Shield) can intercept
`127.0.0.1` HTTP traffic and nondeterministically swallow the tail of large,
fast responses — even from Python's stock `http.server`. The server therefore
sends payloads in paced ~32 KB chunks (`_write_all`), which delivers reliably.
If large documentation files ever hang again, add an antivirus exception for
local Python web servers before debugging the tool.

## Tests

```
python tools/sysml_explorer/test_sysml_explorer.py -v
```

Plain `unittest`, no dependencies. Covers the parser (nodes, attributes,
parts structure, edges, requirements/docs), the HTTP API (model serving,
layout round-trip), and — when Microsoft Edge is available — end-to-end
rendering: the page is loaded headless and the DOM is checked for each
attribute/parts filter combination.

## Development conventions

Every new feature gets:
1. a bullet (or section) in **Features** above, and
2. a test in `test_sysml_explorer.py` proving it works.
