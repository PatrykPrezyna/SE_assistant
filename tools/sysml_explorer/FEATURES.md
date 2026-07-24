# SysML v2 Explorer — feature reference

Complete, always-up-to-date reference of what the explorer parses, renders,
validates, and serves. Written to be loaded as context by an LLM coding
agent working on this tool or on a model viewed with it (humans welcome
too). Setup, troubleshooting, and developer workflow live in
[README.md](README.md).

## CLI

```
sysml-explorer <folder> [--port 8199] [--no-open]
```

- `<folder>` — every `.sysml` file directly inside it (not recursive —
  subfolders are ignored) is merged into one model, so cross-file
  references (e.g. `satisfy`) resolve.
- `--port` — HTTP port, default 8199. `--no-open` — don't open the browser.
- `--print` — dump the parsed model as JSON and exit (debugging aid).
- `--check` — run only the validation: print every warning (see
  **Validation**) and exit nonzero if there are any, usable as a
  pre-commit/CI gate.

Each View is saved to `<folder>/views/<id>.json`; everything else
(documentation links, the element tree panel, UCD/activity drilldown state)
is saved to `<folder>/layout.json`. Both formats carry a `version` field
(currently `1`); older files without it are treated as version 1 on load,
and stale keys (e.g. `ibdOwner`) are dropped on save.

## Parsing (`src/sysml_explorer/app.py`)

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
  Multiplicity after the type is kept (`part csfDrain : CsfDrain [0..1]` →
  compartment text `csfDrain : CsfDrain [0..1]` and a composition edge).
  Each part entry is `{"text": "name : Type", "attrs": [nested redefs]}` so the
  viewer can filter nested attribute lines independently.
- top-level usages (`part robotArm : RobotArmSystem`, requirements with
  `<'REQ-123'>` short names) and their `doc /* ... */` text
- comments (`//`, `/* */`) are stripped; `doc` bodies are preserved
- `connect a.b to c.d;` / `connection name : a.b to c.d;` inside a `part def`
  body (standard SysML v2, plus the shorthand `connection` spelling) —
  wires two part usages together; the connection's owner is the enclosing
  `part def`, and it surfaces as a **connector** edge (see below).
- `use case useDiagram Name for Subject { actor a : ActorDef; use case u :
  UseCaseDef; connection n from a to u; }` — a use case diagram contributes
  no node of its own, and its role usages + named associations attach to
  `Subject` (resolved after all files are parsed; an unresolved `for`
  target, or a connection missing the mandatory `from` clause, is dropped
  with a validation warning — see Use case diagrams below).
- `perform action Name { action a { doc /*…*/ } first start; then a; then done; }`
  nested inside a `part def` or `use case def` — declares an activity for that
  def (swimlane drilldown; see Activity diagrams). Role usages elsewhere in
  the same def may assign actions to lanes with `perform Name.action;` on
  `part`, `ref part`, `actor`, or `subject` (all but plain `part` are
  reference usages — swimlane-only, no usage node and no composition
  edge; see Reference usages). Branching uses SysML v2 `then decide;`
  followed by `if <guard> then <target>;` / `else <target>;` (and `then`
  right after an `action` declaration continues that action's path). The
  parser emits `edges: [{from,to,label}]` plus `decisions` for diamond
  nodes; a linear `first`/`then` chain still works (edges inferred).

Relationships extracted as edges:

- **specialization** (`:>`) — solid line, hollow triangle at the parent
- **composition** (nested `part x : Def` usage) — filled diamond at the
  owner, edge labeled with the role name
- **typing** (usage `: Def`, including a nested `port x : Iface` — a port is
  typed by its interface def, not "contained" the way a part is, so it does
  not get a composition diamond) — dashed line, open arrow at the definition
- **satisfy** (`satisfy REQ-123;` or the spec-compliant quoted form
  `satisfy 'REQ-123';` inside a def — the quoted spelling is the only one
  the official SysML v2 parser accepts for hyphenated names) — dashed
  line, open arrow at
  the requirement, «satisfy» label. The reference is resolved by element name
  or requirement short name (`<'REQ-123'>`), including across files when
  several models are loaded; an unresolved reference drops the edge and
  emits a validation warning. An edge only renders when both endpoints are
  members of the active View (see Views below).
- **association** (an actor ↔ use case link declared in a `useDiagram`
  block) — plain purple line, no arrowhead. A `useDiagram`'s connections are
  between local role usages (e.g. `operator : Operator`), but the
  relationship is really between the actor/use-case *defs* they're typed by,
  so it's resolved to those defs and surfaced as an ordinary edge — it
  renders in the block definition diagram too, not just inside UCD mode,
  whenever both the actor and use case happen to be in the same View. A def
  reused across several roles/diagrams gets one edge per distinct pair, not
  a duplicate for each connection.
- **connector** (a `connect`/`connection` statement inside a `part def`
  body) — green line, ball at both ends, labeled with the connection name
  and the two port names (`name · fromPort · toPort`). The statement wires
  two *usages* together (e.g. `pump.out to valve.in`), but that's really a
  relationship between the part defs those usages are typed by, so it's
  resolved to those defs and surfaced as an edge between them — it renders
  in the block definition diagram whenever both defs are members of the
  active View, same as any other edge — build a View containing the
  connected part defs to see them, and use **Hide connection** to declutter
  it if it gets busy; no separate diagram type is needed.

### Usage nodes — one element per part usage

A nested `part x : Def` is an element in its own right, not just a
reference to `Def`: `part inputTempSensor : Thermistor` and `part
outputTempSensor : Thermistor` are two distinct parts of their owner. So
besides the owner→def composition edge, every part usage also gets:

- a **node** of its own, id `Owner::role` (e.g.
  `CoolSpineSystem::FluidReservoir::inputTempSensor`), header showing
  only the role name (not `role : Type` — type is on the typing edge;
  see README "What the viewer simplifies"), carrying that usage's own
  `doc` and its `:>>` attribute redefinitions. It reports `usageOwner`
  (the def that declares it) and `usageType` (the type name as written).
  Canvas fill and tree-dot color match `part def` (no usage tint).
- a **composition** edge owner → usage node (unlabeled — the node itself
  carries the role name) and a **typing** edge usage node → def.
- for a `connect`/`connection` between two roles of the same owner, a
  second **connector** edge between the two usage nodes, alongside the
  def-level one. This is the only way to tell the ends apart when both
  roles have the same type (a def-level self-loop otherwise).

Both levels coexist, and a View picks whichever it wants:

- Def level (the default) is unchanged — auto-seeded Views and **Show
  decomposition** contain defs only, so existing Views keep working and
  nothing appears twice.
- Usage nodes are opt-in: check them in the element tree, or right-click a
  def and use **Show usages**.
- **Singleton collapse (viewer only):** if a part def has exactly one
  usage in the model, that usage is omitted from the element tree and
  **Show usages**; if both are View members, only the def box is drawn
  (see README "What the viewer simplifies"). Multi-usage types still
  show each member usage in the tree and on the canvas.
- A type-level edge is dropped from the canvas as soon as the usage node it
  stands for is **drawn** (not merely a View member), since
  `Reservoir ◆── inputTempSensor ▷ Thermistor` already says what
  `Reservoir ◆──(inputTempSensor)── Thermistor` said. The same applies to
  a connector whose two usage-node endpoints are both visible.

Port usages are unaffected: a `port x : Iface` still contributes only a
typing edge (see above), no usage node.

#### Reference usages (`ref part`, `actor`, `subject`)

A composite `part x : Def` declares that the owner *has its own* `x`. When
several defs each need to name the **same** instance — the surgeon in the
operational context is the same person as the surgeon in the clinical
activity — only one of them should compose it; the rest declare a
reference:

```
part def Kontext          { part surgeon : Surgeon; }          // owns it
part def ClinicalCooling  { ref part surgeon : Surgeon { … } } // refers to it
```

A `ref part` (and likewise `actor` / `subject`) contributes **no usage
node, no composition edge, and no line in the owner's box** — only its
`perform Name.action;` swimlane assignments are read. Without this, each
context would add another `…::surgeon` node, the type would no longer be a
singleton, and the same person would appear several times in the tree and
on the canvas.

### Dialect notes — non-standard constructs

This tool's dialect is **not** fully standard SysML v2; the official
reference parser (see README, "Setting up the validation parsers")
rejects these constructs the explorer accepts:

- `use case useDiagram ... for ...` (an explorer-only diagram-definition
  block)
- `actor def` (in standard v2, actors are usages typed by part defs, not defs)
- unquoted hyphenated satisfy references (`satisfy REQ-201;` — the standard
  grammar requires `satisfy 'REQ-201';`)
- `perform action …` / `perform activity.action;` swimlane activity blocks
  (explorer-only; the spec has no first-class swimlane syntax)

When writing models meant to pass the official parser, use only standard
syntax; the explorer accepts both spellings of `satisfy`.

## Validation (`src/sysml_explorer/app.py`)

The parser double-checks what it read and reports problems as warnings —
so a diagram can't quietly look more complete or more correct than the
model is. Checked:

- **unbalanced braces** — an unexpected `}` (with its line number) or
  unclosed `{` at end of file
- **unrecognized statements** — a skipped statement whose first word is not
  a known SysML v2/KerML keyword is reported (catches keyword typos like
  `atribute`, and SysML v1 leftovers like `block`). Statements starting
  with a *known* keyword the tool doesn't render (`constraint`, `state`,
  `subject`, …) are legitimate model content and stay silent.
- **ambiguous names** — references are resolved by simple name (or
  requirement short name), so the same name defined in more than one
  package is flagged; resolution keeps the first definition. A fully
  qualified reference (`B::M`) always resolves exactly and is never
  ambiguous. Exact duplicates (same qualified name twice) are flagged too.
- **unresolved references** — a `satisfy`, specialization (`:>`), typing,
  or composition target that doesn't resolve to any element; a `useDiagram`
  `for` subject that doesn't resolve; a use case connection endpoint that
  doesn't resolve to an actor/use case def; a use case `connection` without
  the mandatory `from` clause. In every case the edge/diagram is still
  dropped, but now with a warning.

Warnings are surfaced in three places: the model JSON (`warnings` array in
`/api/model`, prefixed with the source file name where applicable), the
server console at startup, and the viewer — a **⚠ n** toolbar counter,
which expands into a banner listing every message (hidden entirely when
the model is clean). `sysml-explorer <folder> --check` runs only the
validation and exits nonzero on warnings, for use as a pre-commit/CI gate.
These checks are intentionally lightweight; for reference-grade
diagnostics see "Validating with the official SysML v2 parser" in the
README.

## Viewer (`viewer.html`)

- drag elements to arrange them; drag the background to pan; mouse wheel zooms
- **Click to highlight**: left-clicking an element outlines it (red) and
  outlines every connection touching it plus the elements on the other end
  (blue) — a quick way to trace what's wired to what. Left-clicking a
  connection instead outlines that connection and its two endpoint elements.
  Click the background, or press Esc, to clear the highlight. It's a
  transient view aid, not saved to the layout file.
- **Save** (or Ctrl+S) persists the active View (membership, positions,
  pan/zoom, display options) and the global state (docs, tree panel,
  drilldown) in one action; unsaved changes are flagged and warned on close
- auto-layout for elements without a saved position (layered: parents above
  children, wholes above parts); **Auto-layout** (under **More**) re-runs it
  for all
- **Fit** zooms to the whole diagram
- **Reload model** (under **More**) re-parses the folder's `.sysml` files
  without losing the arrangement (positions are keyed by qualified element
  name)
- **Display ▾** menu (per View, saved in the View's `options`):
  - **attributes** / **parts** — hide the respective compartments.
    Attribute redefinitions nested under a part (e.g. `.length = 120.0`)
    follow *attributes*, and are also hidden when *parts* is off.
  - **keywords** — show «part def» / «requirement» / … in node headers
    (off by default)
  - **edge labels** — show composition role names and «satisfy» text on
    lines (off by default; **connector** edges always keep their label)
  - **package paths** — show the package line under the name (off by default)
  - **docs on node** — show `doc` body text in a compartment (off by default;
    documentation *links* still use the 📄 marker / context menu)
- Toolbar is split into primary controls (Tree, view switcher, Save, Fit)
  and overflow (**Display ▾**, **More ▾**). The title shows the active View
  name only (or the drilldown diagram name) — not the source file list.
  A muted **v0.0.1**-style label next to the title shows the explorer
  package version.
- An empty View shows a centered hint: check elements in the tree to add them.
- parse errors are shown in a banner instead of a broken page
- A **legend** (bottom-left) explains the arrow styles for edge kinds
  currently visible. Human-friendly labels: specialization → **kind of**,
  typing → **is a** (model edge kinds unchanged; see README "What the
  viewer simplifies" to reverse). Satisfy edges are drawn dark yellow so
  they stay distinguishable from typing without labels.

(A reader-friendly summary of how these defaults deviate from standard
SysML notation is in the README, "What the viewer simplifies".)

## Views (`viewer.html`)

A **View** is a curated, named presentation of model content — SysML v2's
own term for this (`view def`/`viewpoint def`). Unlike the block definition
diagram's element list (which is just "everything the parser found"), a
View's membership is entirely up to you: nothing is in it until you add it,
typically from the element tree.

- The **view** dropdown switches between Views. Alongside it: **+**
  (prompts for a name, creates it empty, and switches to it). **Rename** /
  **Delete** live under **More ▾** (confirmation on delete; if it was the
  last View, a fresh empty one is created so there's always something to
  look at).
- A brand-new folder (no `views/` yet) gets one View auto-created on first
  launch, named "Default" and seeded with every def the parser found (not
  the usage nodes, which would put each part on the canvas twice) — so the
  first launch isn't a blank canvas. Every View you create by hand
  after that starts empty (and shows the empty-view hint until you add
  members).
- **Add elements** by checking them in the element tree (see below); an edge
  between two elements renders automatically once both are members.
  **Remove from view** (right-click an element) drops just that element —
  its saved position goes with it, so re-adding it later re-runs auto-layout
  for it rather than remembering the old spot.
- **Right-click context menu** (designed to grow — new entries are added in
  `nodeMenuItems()` in `viewer.html`):
  - on an *element*: **Open use case diagram** / **Open activity diagram**
    (only offered when the element has one — see below), the **Show …**
    related-element actions (see below), **Remove from view**.
  - on a *connection*: **Hide connection** (removes only the line, without
    removing either endpoint — for decluttering a busy View).
  - on the *background*: **Unhide connections (n)**, **Fit view**,
    **Auto-layout**.
  - close with Esc or by clicking elsewhere.
- **Show related elements**: right-click an element (in a View, not in a
  drilldown) to pull everything the model associates with it into the
  current View, without hunting for the names in the tree:
  - **Show decomposition (n)** — its composition children, all levels down
    (the internal blocks of the block, and their own parts). Def level
    only: the walk skips usage nodes, so one right-click can't drag both
    levels of the tree in at once.
  - **Show usages (n)** — the per-usage nodes this def declares
    (`inputTempSensor : Thermistor`, `outputTempSensor : Thermistor`), for
    when the roles matter more than the type they share. See Usage nodes.
  - **Show specializations (n)** — the elements that specialize it, all
    levels down (e.g. right-click `TemperatureSensor` to get `Thermistor`
    and `Thermocouple` — the possible realizations).
  - **Show satisfied requirements (n)** — the requirements it satisfies.
    On a requirement the same entry reads **Show satisfying elements**
    (what satisfies it), and **Show satisfy relations** when both
    directions exist.
  - **Show all related (n)** — the union of the four.
  Each count is what the View is still *missing*; an entry with nothing to
  add is greyed out. Added elements get auto-layout positions (nothing
  already in the View moves), so remember to **Save**. Implemented by
  `relatedIds()` / `relatedGroups()` / `relatedMenuItems()` in
  `viewer.html`, walking the parsed model's own edges.
- **Documentation links**: right-click an element → **Add documentation
  link…** opens a dialog to enter a file path (e.g. a PDF; relative paths
  resolve from the model folder) or an http(s) URL. **Browse folder…** in
  that dialog opens a folder-tree browser rooted at the model's working
  folder (served by `GET /api/browse?path=`, which refuses to list anything
  outside that folder); clicking through folders and then a file fills the
  path field with the picked file's path relative to the working folder.
  Linked elements show a 📄 marker, and the menu gains **Open documentation
  (file.pdf)**, which opens the file in a new browser tab (local files are
  served via `/api/doc`). Links are global (not per-View) and stored in the
  layout file (`docs`) — remember to **Save**. Enter an empty value in
  **Edit documentation link…** to remove a link.
- Each View's membership, positions, hidden connections, pan/zoom, and
  display options are saved in its own file (`<folder>/views/<id>.json`)
  with `"version": 1` — see Server below. The id is a filesystem-safe
  slug derived from the name when the View is created and never changes,
  even if you rename it afterwards.

## Default views (`src/sysml_explorer/app.py`)

Three Views every model is expected to have, so a folder doesn't start as
an unstructured pile of elements. They are declared in
`DEFAULT_VIEW_SPECS` (id, display name, and a `doc` describing exactly
what belongs in the View):

| id | name | shows |
| --- | --- | --- |
| `context` | **1 Context** | every member of the context block plus the connections between them; the context block itself on top, **unconnected** — its composition edges to the members are in `hiddenEdges`, since containment is what the diagram is about rather than information in it |
| `decomposition` | **2 Decomposition** | the system part def and up to three levels of composition below it, as a pyramid: level 1 centred on top, level 2 spread beneath, level 3 under its own parent. Realization specializations of a level-2 part (`Thermistor :> TemperatureSensor`) count as level 3. Attributes/parts compartments off, **docs on**; connector edges hidden so only the tree shows |
| `interconnections` | **3 Interconnections** | the connections declared in the system part def, between its **first-level parts only**. The system block itself is deliberately not a member, so no composition edge competes with the connectors. (The system's "internal block diagram", named for what it shows rather than for SysML v1.) |

Today these are **hand-authored JSON** — see
`examples/MedicalDevice/views/{context,decomposition,interconnections}.json`
for the reference set. Generating them from the parsed model is stubbed:

- `build_default_views(model, folder=None)` — **placeholder**. Will return
  one view dict per spec it can generate (the `views/<id>.json` format plus
  an `"id"` key naming the file); specs that don't apply to a model (no
  context block, no system part def) are simply omitted. Currently returns
  `[]`. Its docstring lists the model pieces an implementation needs.
- `sync_default_views(folder, model)` — writes whatever `build_default_views`
  produced into `<folder>/views/`, and is already called at server startup
  (printing `regenerated default view: <id>` per file). It refuses to write
  any id not in `DEFAULT_VIEW_SPECS`, so a generated View can replace its
  own stale file but can never clobber a View made by hand. A no-op while
  the builder is a placeholder.

## Element tree (`viewer.html`)

- A left-side panel lists every element in the *model* (not just the active
  View), grouped into a collapsible tree by `packagePath` (click a package
  header to expand/collapse its branch) — this is how you build up a View.
  Toggle the panel itself with the **Tree** toolbar button; its open/
  closed state is saved in the layout file (`treeOpen`, default open).
- **Search** box at the top of the panel filters by name, short name, or
  qualified id (case-insensitive). **Kind chips** (All / Req / Part / Actor /
  Use case) further narrow the list. While a filter is active, matching
  packages stay expanded.
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
  purple = actor, green = use case, blue = non-part usages; `part` /
  `part def` and other def-level elements are uncolored). Singleton part
  usages are omitted from the tree (their part def stands in for them).
- Disabled (greyed out, non-interactive) while in UCD or activity mode,
  since View membership only applies to the block definition diagram.

## Use case diagrams (`viewer.html`)

- Actors (`actor def`) and use cases (`use case def`) render as ordinary
  block-definition nodes too — actors tinted pale purple, use cases pale
  green — so they show up in the normal BDD view and can be added to any
  View like any other element, including `satisfy` edges from a use case to
  the requirements it addresses, and **association** edges to whichever
  actors/use cases they're linked to in a `useDiagram` (see the association
  bullet under Parsing above) — add both ends to a View to see it.
- A `use case useDiagram Name for Subject { ... }` block turns `Subject`
  into an entry point: it carries a 🎭 marker (next to any 📄 marker) and
  gains **Open use case diagram** in its right-click menu (only offered from
  the block definition diagram, not from inside a drilldown).
- Opening it switches the whole canvas to **UCD mode**: the actor/use-case
  roles declared in the `useDiagram` block become nodes (named after the
  role, e.g. `operator`), connected by plain purple **association** edges
  for each `connection n from a to b;` — the diagram's normal nodes/edges are
  replaced, not overlaid. A connection without the mandatory `from` clause
  (e.g. a bare system-level trigger with only a `to`) is ambiguous and is
  dropped at parse time rather than guessed.
- The drilldown chrome: the **◀ Back to BDD** toolbar button, **Close use
  case diagram** in the background menu, and the **view** controls/**Unhide**
  disabled while active.
- The legend gains an **association (actor ↔ use case)** row whenever
  association edges are visible — in UCD mode or in the block definition
  diagram, wherever they end up rendering.
- The current mode and owner are saved in the layout file (`mode`,
  `ucdOwner`); an owner that no longer resolves falls back to the block
  definition diagram.

## Activity diagrams (`viewer.html`)

- A `perform action Name { ... }` block nested in a `part def` or
  `use case def` turns that def into an entry point: it carries a 🎬 marker
  and gains **Open activity diagram** in its right-click menu (from the
  block definition diagram only).
- Opening it switches the canvas to **activity mode**: a swimlane layout of
  the nested `action` usages. Each `part` / `actor` / `subject` role is a
  **vertical column** (top → bottom); succession order advances **downward**.
  A `decide` node renders as a diamond; `if <guard> then` / `else` become
  outgoing edges labeled with the guard (and `no` for `else`). Control
  endpoints `start` / `done` render as rounded nodes centered across the
  lanes. Flow edge guards are always shown (not gated by the edge-labels
  Display toggle).
- Dragging an action only moves it vertically — its swimlane (x) is fixed
  from the `perform` assignment, so actions cannot be moved between lanes.
- Same drilldown chrome as UCD (**◀ Back to BDD**, background **Close
  activity diagram**); View membership controls are disabled while active.
- Mode and owner are saved in the layout file (`mode`, `activityOwner`).
- Explorer dialect (not standard SysML v2) — see Dialect notes above.
  Spec-level `activity def` as a first-class definition kind is still not
  parsed as its own diagram type.

## Version

Package version lives in `src/sysml_explorer/version.py` (`__version__`,
currently **0.0.1**) and must match `pyproject.toml`. The viewer toolbar
shows `v…` next to the title (injected when `GET /` serves `viewer.html`).
`GET /api/model` also includes `explorerVersion`.

## Server (`src/sysml_explorer/app.py`)

- `GET /` — the viewer page (version placeholder `{{EXPLORER_VERSION}}`
  substituted from `__version__`)
- `GET /api/model` — the folder is re-globbed for `.sysml` files and
  re-parsed on every request, so a file added, edited, or removed in the
  folder shows up on refresh/**Reload model** without restarting the server;
  the response includes the validation `warnings` array (see Validation)
  and `explorerVersion`
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
