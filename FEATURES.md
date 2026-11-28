# System Explorer — feature reference

Complete, always-up-to-date reference of what the explorer parses, renders,
validates, and serves. Written to be loaded as context by an LLM coding
agent working on this tool or on a model viewed with it (humans welcome
too). Setup, troubleshooting, and developer workflow live in
[README.md](README.md).

## CLI

```
system-explorer <folder> [--port 8199] [--no-open]
```

- `<folder>` — every `.sysml` file directly inside it (not recursive —
  subfolders are ignored) is merged into one model, so cross-file
  references (e.g. `satisfy`) resolve.
- `--port` — HTTP port, default 8199. `--no-open` — don't open the browser.
- `--print` — dump the parsed model as JSON and exit (debugging aid).
- `--check` — run only the validation: print every warning (see
  **Validation**) and exit nonzero if there are any, usable as a
  pre-commit/CI gate.
- `--publish <outdir>` — write a static view-only **Viewer** site into
  `<outdir>` and exit (see **Published Viewer**). Combined with `--check`,
  the site is written only when validation reports no warnings.

Each View is saved to `<folder>/views/<id>.json` (including activity
Views); everything else (documentation links, the element tree panel, the
active View, expert mode, whether the home page is open) is saved to
`<folder>/layout.json`. Both formats carry a `version` field (currently
`1`); older files without it are treated as version 1 on load. Keys older
versions wrote to `layout.json` (`ibdOwner`, `mode`, `ucdOwner`,
`activityOwner`, `drilldownNodes`, `drilldownHiddenEdges`, `drilldownView`)
are ignored on load and dropped on the next save (`STALE_LAYOUT_KEYS` in
`viewer.html`).

Validators that ship with the package (setup in README.md, *Setting up the
validation parsers*):

- `python -m system_explorer.official_check <folder>` — the OMG pilot
  implementation (reference parser) via its Jupyter kernel; must run under
  the python of the conda env that has the kernel.
- `python -m system_explorer.jamied_check <folder-or-file>` — the JamieD
  `sysml-v2-lsp` community parser; needs Node.js and the VS Code/Cursor
  extension.

## Parsing (`src/system_explorer/app.py`)

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
- `actor x : Def` / `subject x : Def` nested in a `use case def` — the
  use case's participants; each becomes an **association** edge (see
  below).
- `perform action Name { action a { doc /*…*/ } first start; then a; then done; }`
  nested inside a `part def` or `use case def` — declares an activity for that
  def (a swimlane activity View; see Activity diagrams). Role usages elsewhere in
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
- **verify** (`verify requirement 'REQ-123';` inside `objective { }` on a
  `verification def`, or as a direct statement) — dashed blue line, open
  arrow at the requirement, «verify» label. Same name resolution as satisfy.
  A verification case is a design-verification method, not a requirement.
- **association** (use case ↔ actor / subject) — plain purple line, no
  arrowhead, from an `actor x : ActorDef` / `subject x : SubjectDef` usage
  nested in a `use case def` (the SysML v2 spelling — e.g. CoolSpine's
  `DeliverTherapeuticCooling` body), labeled with the role name. Renders in
  the block definition diagram whenever both ends are View members. Two
  roles of the same type in one use case give one edge, not two.
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
  see [NOTATION.md](NOTATION.md) N3), carrying that usage's own
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

- Def level (the default) is unchanged — auto-seeded Views contain defs
  only, so existing Views keep working and nothing appears twice.
- Usage nodes are opt-in: check them in the element tree, or right-click a
  def and use **Show decomposition** / **Show usages**.
- **Singleton collapse (viewer only):** if a part def has exactly one
  usage in the model, that usage is omitted from the element tree and
  **Show usages**; if both are View members, only the def box is drawn
  (see [NOTATION.md](NOTATION.md) N4). Multi-usage types still
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
part def Context          { part surgeon : Surgeon; }          // owns it
part def ClinicalCooling  { ref part surgeon : Surgeon { … } } // refers to it
```

A `ref part` (and likewise `actor` / `subject`) contributes **no usage
node, no composition edge, and no line in the owner's box** — only its
`perform Name.action;` swimlane assignments are read. Without this, each
context would add another `…::surgeon` node, the type would no longer be a
singleton, and the same person would appear several times in the tree and
on the canvas.

Exception: an `actor` / `subject` usage nested in a **`use case def`**
also emits an **association** edge from the use case to that role's type
(see association under Relationships above). `ref part` never does —
it remains a pure reference.

### Dialect notes — non-standard constructs

This tool's dialect is **not** fully standard SysML v2; the official
reference parser (see README, "Setting up the validation parsers")
rejects these constructs the explorer accepts:

- `actor def` (in standard v2, actors are usages typed by part defs, not defs)
- unquoted hyphenated satisfy references (`satisfy REQ-201;` — the standard
  grammar requires `satisfy 'REQ-201';`)
- `perform action …` / `perform activity.action;` swimlane activity blocks
  (explorer-only; the spec has no first-class swimlane syntax)

When writing models meant to pass the official parser, use only standard
syntax; the explorer accepts both spellings of `satisfy`.

No longer supported (removed in 0.1.0, as part of moving the dialect to
standard SysML v2): `use case useDiagram Name for Subject { ... }` blocks
and their use case diagram drilldown, and earlier `ibd def X of Owner`.
Such a block now starts with a known keyword, so it is skipped silently like
any other unrendered construct. Model use cases as a `use case def` with
nested `actor` / `subject` usages instead; they render as association edges
in any View.

## Validation (`src/system_explorer/app.py`)

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
  composition, or association target that doesn't resolve to any element.
  The edge is still dropped, but with a warning.

Warnings are surfaced in three places: the model JSON (`warnings` array in
`/api/model`, prefixed with the source file name where applicable), the
server console at startup, and the viewer — a **⚠ n** toolbar counter,
which expands into a banner listing every message (hidden entirely when
the model is clean). `system-explorer <folder> --check` runs only the
validation and exits nonzero on warnings, for use as a pre-commit/CI gate.
These checks are intentionally lightweight; for reference-grade
diagnostics use the validators listed under CLI above.

## Viewer (`viewer.html`)

- drag elements to arrange them; drag to pan; mouse wheel zooms. On a
  touch screen a one-finger drag pans and a two-finger pinch zooms, including
  when the drag starts on an element and when the detail sheet is open
- **Click to highlight**: left-clicking an element outlines it (red) and
  outlines every connection touching it plus the elements on the other end
  (blue) — a quick way to trace what's wired to what. Left-clicking a
  connection instead outlines that connection and its two endpoint elements.
  Click the background, or press Esc, to clear the highlight. It's a
  transient view aid, not saved to the layout file.
- **Save** (or Ctrl+S) persists the active View (membership, positions,
  pan/zoom, display options) and the global state (docs, tree panel, active
  View) in one action; unsaved changes are flagged and warned on close
- **Revert** goes back to the last saved version: it discards every unsaved
  edit and re-reads `layout.json` and `views/*.json` from disk (by re-running
  the viewer's normal boot path), so the canvas, the active View and the
  display options all return to what **Save** last wrote. The button is **disabled while there is nothing to go back to**
  (`setDirty` drives it), and asks for confirmation before throwing work
  away. Deliberately not an undo stack — Save is the single commit point,
  so one step back to it covers the "I made a mess, start over" case.
- auto-layout for elements without a saved position (layered: parents above
  children, wholes above parts). There is no manual "re-layout everything"
  command: once a View is arranged by hand, the saved positions are the
  authored content, and a single click that throws them all away is a
  bigger foot-gun than it is a convenience
- **+**, **−**, and **Fit** sit on the diagram, as on the published Viewer.
  **+** and **−** zoom around the center of the diagram that is still
  visible; **Fit** zooms to the whole diagram. The wheel still zooms toward
  the pointer, and a drag pans. The buttons stay above the detail sheet, and
  below the header when the header wraps onto a second line (a phone)
- **Reload model** (under **More**) re-parses the folder's `.sysml` files
  without losing the arrangement (positions are keyed by qualified element
  name)
- **Display ▾** and **More ▾** stay on the header while reading. **Edit**
  does not hide them. The menus open below the header.
- **Display ▾** menu (per View, saved in the View's `options`):
  - **attributes** / **parts** — hide the respective compartments.
    Attribute redefinitions nested under a part (e.g. `.length = 120.0`)
    follow *attributes*, and are also hidden when *parts* is off.
  - **«part def» keywords** — show «part def» / «requirement» / … in node
    headers (off by default)
  - **edge labels** — show composition role names and «satisfy» text on
    lines (off by default; **connector** edges always keep their label)
  - **package paths** — show the package line under the name (off by default)
  - **docs on node** — show `doc` body text in a compartment (off by default;
    documentation *links* still use the 📄 marker / context menu)
- The page chrome matches the published Viewer: a white header, the view
  name, a **Views** button back to the card list, a light grid on the
  canvas, and the same zoom buttons. It carries no app title and no
  version label. The *browser tab* title still tracks the active View.
- **Edit** (the header button, `expertMode` in `layout.json`) is the extra
  option. Off, the page is for reading. On, it reveals Tree, the view
  switcher, **+**, **Save**, and **Revert**, and elements can be dragged.
  **Display ▾** and **More ▾** stay available either way. A tap while
  reading opens the detail
  sheet (the element's `doc`, its documentation link, **Requirements**,
  **Satisfied by**, and **Verified by**) instead of starting a drag. The
  sheet covers at most the bottom half of the screen and scrolls inside
  that half. Dragging the diagram does not close it, so the diagram can
  still be panned and pinched while the sheet is open. A tap on empty
  canvas, or **×**, closes it.
- An empty View shows a centered hint: check elements in the tree to add them.
- parse errors are shown in a banner instead of a broken page
- A **legend** (bottom-left) explains the arrow styles for edge kinds
  currently visible. Human-friendly labels: specialization → **kind of**,
  typing → **is a** (model edge kinds unchanged; [NOTATION.md](NOTATION.md)
  N6). Satisfy edges are drawn dark yellow so they stay distinguishable
  from typing without labels.
- The graphical deviations from textbook SysML are the notation profile in
  [NOTATION.md](NOTATION.md). That file is normative for how the Explorer
  and the published Viewer draw; this page describes behavior and points
  at the rule ids.

## Expert mode (`viewer.html`)

Building a diagram by hand — picking elements out of the tree, creating
Views, hiding connections, changing what nodes show, saving — is the
editing option. It lives behind the **Edit** button in the header so the
page otherwise matches the published Viewer.

- **Off by default.** A folder with no `layout.json`, or one saved before
  this existed, opens with Edit off.
- **What Edit gates.** Custom-diagram controls are marked `expert-only`
  and hidden by `body:not(.expert) .expert-only`: **Tree**, the **+**
  new-View button, and **Rename view** / **Delete view** /
  **Unhide connections** under **More ▾**. The rest of the authoring
  chrome is marked `edit-only` and hidden by the same rule: the view
  switcher, **Save**, and **Revert**. Dragging an element and the
  right-click menu also wait for Edit. **Display ▾** (including
  **«part def» keywords** and **docs on node**) and **More ▾** stay
  on the header while reading.
- **What stays available while reading**: the home page and its **Views**
  button, **Display ▾**, **More ▾**, **+** / **−** / **Fit**, pan, the
  detail sheet, click-to-highlight, and activity Views.
- The element tree is on screen only when Edit is on *and* the tree is
  open. `treeOpen` stays the user's own preference while Edit is off, so
  turning Edit on restores the panel as it was (`treeVisible()` in
  `viewer.html`).
- The empty-View hint adapts: it says to check elements in the tree while
  Edit is on, and to turn Edit on otherwise.
- The state is saved in the layout file as `expertMode` (toggling it
  marks the layout dirty, like the Tree button does).

## Home page (`viewer.html`)

The landing screen: a short introduction to what the assistant is for, and a
card per View to start from. Someone who opens the model for the first time
gets an orientation instead of a diagram with no context, and someone who
comes back gets a table of contents.

- **What's on it**: the heading **Systems Engineering Assistant**, a
  one-line subtitle (model package · elements · relationships · views), the
  welcome copy — what Systems Engineering is for, that the assistant offers
  a set of artifacts to tailor to an organization's needs and maturity, that
  artifacts are revisited throughout the lifecycle, and that the point is to
  involve the whole development team — then the **Views** grid.
- **View cards** show the View's name, its `description` (see below) and its
  element count (or **Activity diagram** for an activity View). Clicking
  one switches to that View and leaves the home page. With no Views at
  all the grid says so and points at Edit.
- **Views** (first button in the header, always available — not
  hidden with Edit) brings the page back. It is hidden on the home page
  itself, matching the published Viewer. The page is an *overlay* over the
  canvas, not a separate screen: leaving and coming back never disturbs
  the diagram underneath or its pan/zoom.
- **Optional `description`** in a View file (`views/<id>.json`) is the card's
  blurb — one sentence on what the View is for. There is no UI to edit it
  (it is authored content, like the element arrangement); a View without one
  shows a muted *No description.* The field round-trips through **Save**
  untouched.
- **When it shows**: on first launch, and afterwards whenever the last
  **Save** happened with the home page open (`home` in `layout.json`). So a
  fresh folder opens on the introduction, while someone working inside a
  View goes straight back to that View.

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
  - on an *element*: the **Show …** related-element actions (see below),
    the documentation link entries, **Remove from view**. Activity diagrams
    are Views (see below), not a submenu.
  - on a *connection*: **Hide connection** (removes only the line, without
    removing either endpoint — for decluttering a busy View).
  - on the *background*: **Unhide connections (n)**, **Fit view**.
  - close with Esc or by clicking elsewhere.
- **Show related elements**: right-click an element (in a View, not in an
  activity View) to pull everything the model associates with it into the
  current View, without hunting for the names in the tree:
  - **Show decomposition (n)** — its direct composition children as
    **usage nodes** (roles), one hop only — e.g. `FluidReservoir` →
    `inputTempSensor` and `outputTempSensor`, not the shared
    `Thermistor` type and not grandchildren. See Usage nodes.
  - **Show usages (n)** — the same role nodes, but only for types that
    have more than one usage in the model (singleton usages stay
    collapsed onto their part def). Prefer **Show decomposition** when
    you want every part of the block.
  - **Show type (n)** — the definition this usage is typed by (the
    typing / "is a" edge) — e.g. right-click `outputTempSensor` to get
    `Thermistor`. Empty on a part def that isn't itself a typed usage.
  - **Show specializations (n)** — the elements that specialize it, all
    levels down (e.g. right-click `TemperatureSensor` to get `Thermistor`
    and `Thermocouple` — the possible realizations).
  - **Show satisfied requirements (n)** — the requirements it satisfies.
    On a requirement the same entry reads **Show satisfying elements**
    (what satisfies it), and **Show satisfy relations** when both
    directions exist.
  - **Show all related (n)** — the union of the five.
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
- Each View's membership, positions, hidden connections, pan/zoom,
  display options, and optional `description` (the home page blurb) are
  saved in its own file (`<folder>/views/<id>.json`) with `"version": 1`
  — see Server below. The id is a filesystem-safe
  slug derived from the name when the View is created and never changes,
  even if you rename it afterwards.

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
- Disabled (greyed out, non-interactive) while an activity View is
  active, since View membership only applies to the block definition
  diagram.

## Use cases and actors (`viewer.html`)

- Actors (`actor def`) and use cases (`use case def`) render as ordinary
  block-definition nodes — actors tinted pale purple, use cases pale green
  — and can be added to any View like any other element, including
  `satisfy` edges from a use case to the requirements it addresses, and
  **association** edges to whichever actors/subjects are nested in the use
  case (see association under Parsing above) — add both ends to a View to
  see it.
- The legend gains an **association (actor/subject ↔ use case)** row
  whenever association edges are visible.
- There is no separate use case diagram mode: a View containing the use
  cases and their participants *is* the use case diagram.

## Activity diagrams (`viewer.html`)

- A `perform action Name { ... }` block nested in a `part def` or
  `use case def` is a first-class **View**, listed next to Context /
  Decomposition in the view dropdown and on the home-page cards — not a
  submenu on the use case. The owner def still carries a 🎬 marker on the
  block definition diagram.
- Each activity View file has `"kind": "activity"` and `"activityOwner"`
  (the owning def's id). Positions and pan/zoom are stored on that View
  like any other. If none exists yet, the explorer creates one named
  **Activity — &lt;owner&gt;** on startup.
- Selecting the View switches the canvas to **activity mode**: a swimlane
  layout of the nested `action` usages. Each `part` / `actor` / `subject`
  role is a **vertical column** (top → bottom); succession order advances
  **downward**. A `decide` node renders as a diamond; `if <guard> then` /
  `else` become outgoing edges labeled with the guard (and `no` for
  `else`). Control endpoints `start` / `done` render as rounded nodes
  centered across the lanes. Flow edge guards are always shown (not gated
  by the edge-labels Display toggle).
- Dragging an action only moves it vertically — its swimlane (x) is fixed
  from the `perform` assignment, so actions cannot be moved between lanes.
- Switch away with the view dropdown or Home, same as any other View; a
  saved session reopens it through `activeView` in `layout.json`.
- Explorer dialect (not standard SysML v2) — see Dialect notes above.
  Spec-level `activity def` as a first-class definition kind is still not
  parsed as its own diagram type.

## Version

The package version lives only in `src/system_explorer/version.py`
(`__version__`, currently **0.1.0**); `pyproject.toml` reads it from there
(`dynamic = ["version"]`), so there is no second copy to keep in sync. It is
not shown in the viewer UI; `GET /api/model` reports it as
`explorerVersion`.

## Server (`src/system_explorer/app.py`)

- `GET /` — the viewer page, served verbatim
- `GET /api/model` — the folder is re-globbed for `.sysml` files and
  re-parsed on every request, so a file added, edited, or removed in the
  folder shows up on refresh/**Reload model** without restarting the server;
  the response includes the validation `warnings` array (see Validation)
  and `explorerVersion`
- `GET /api/layout` / `POST /api/layout` — global state persistence, always
  at `<folder>/layout.json`
- `GET /api/views` — list of `{id, name, description, elementCount, kind,
  activityOwner}` for every View (`<folder>/views/*.json`); the extra
  fields are what the home page's cards need, so it renders from this one
  request. `kind` is `"bdd"` unless the file says `"activity"`.
- `GET /api/views/<id>` — one View's full content
- `POST /api/views` — create a View; body `{"name": "..."}` (optional
  `kind`, `activityOwner`, `description`), response the same shape as a
  listing entry. The id is a slug derived from the name (lowercased,
  non-alphanumerics collapsed to `-`; a colliding slug gets a `-2`,
  `-3`, … suffix) and is fixed for the View's lifetime
- `PUT /api/views/<id>` — replace a View's content (also used for renames —
  the id/filename never changes, only the `name` field inside); an
  idempotent create-or-replace, not update-only
- `DELETE /api/views/<id>` — remove a View

## Published Viewer (`publish.py`, `publish_viewer.html`)

`system-explorer <folder> --publish <outdir>` writes a static site that
shows the prepared block Views and nothing else. It is the phone page: view
only, no dragging, no saving, no element tree. Activity Views (`kind:
"activity"`) are skipped and counted on stdout. The Explorer remains the
tool that creates Views and positions.

`<outdir>` contents:

- `index.html` — `publish_viewer.html` with the model, Views, and
  documentation links embedded so the page renders without a server
- `model.json` — the same parsed model the Explorer serves, plus
  `explorerVersion` and `file`
- `views.json` — `{views: [{id, name, description, elements, nodes,
  hiddenEdges}]}` for every block View, in filename order. Invalid JSON
  and ids that are not slugs are skipped
- `docs.json` — `{links, omitted}`. `links` maps an element id to an
  `http(s)` URL or to `files/<path>` inside the site. `omitted` lists
  documentation links that were not published
- `files/` — copies of linked files that resolve inside the model folder.
  A path that escapes the folder, or that is not a file, is omitted. The
  `files/` directory is replaced on every publish

On the page, the home screen lists those Views. Opening one draws its
members at the saved positions (elements with no saved position stack in a
column underneath). The whole View is then shifted so its top-left
sits on the page; relative placement is unchanged. A single usage of a part def is hidden when that def is
also on the View, matching the Explorer. Nodes follow the Explorer's
default notation ([NOTATION.md](NOTATION.md)): the name only, attribute and
parts compartments on, no package line and no doc body, edge labels off
except connector labels and flow guards. A legend names the visible edge
kinds (**kind of**, **is a**, and the rest). Satisfy edges are dark yellow.
A documentation link shows the marker on the node. Edges between visible members are
drawn, except hidden edges and the type-level edges the Explorer already
suppresses when the usage nodes are on the diagram. A tap opens a panel
with the element's `doc` text, an **Open documentation** link when one was
published, **Requirements** (every element it `satisfy`s, with that
requirement's `doc`), and **Satisfied by** when the element is itself a
requirement. The panel covers at most the bottom half of the screen and
scrolls inside that half, so the rest of the diagram stays visible. A drag
on the diagram pans it while the panel stays open; a pinch zooms even when
the fingers start on the panel. **+** and **−** stay above the panel and
zoom the visible part of the diagram. Positions cannot be changed.
`?v=<view id>&e=<element id>` opens that View and panel directly.

The diagram opens fitted to the screen, including a phone, so the whole View
is visible without scrolling the page. **+**, **−**, and **Fit** zoom around
the center of the diagram that is still visible; **Fit** returns to the
whole View. A pinch does the same, the mouse wheel zooms toward the pointer,
and a drag pans once the View is zoomed in. The page itself does not scroll
or browser-zoom.

With `--check`, warnings are printed and the site is not written when there
are any.

## Hosted mode (`src/system_explorer/cloud.py`)

`system-explorer-cloud` serves one model folder of a GitHub repo to a whole
team from a container (`Dockerfile` and `render.yaml`, a ready-made Render
blueprint, are at the root of this repo; the model lives in its own repo). Step-by-step setup is in
README.md → *Hosting for a team*. The git repo stays the single source of
truth — the container holds only a disposable clone:

- **Startup** — clones `GITHUB_BRANCH` of `GITHUB_REPO` into `WORK_DIR` and
  serves `MODEL_PATH` (a folder inside the repo; it may not escape it, and
  it must contain `.sysml` files, or the server refuses to start).
- **Reads pull** — every signed-in GET first runs `git pull --rebase`, at
  most once per `PULL_INTERVAL` seconds (default 30), so `.sysml` edits and
  Views pushed from teammates' IDEs show up on refresh. A failed pull is
  aborted and logged, and the server keeps serving what it has.
- **Writes commit and push** — creating, saving, renaming, or deleting a
  View and saving `layout.json` each make one commit, authored as the
  signed-in GitHub user (via their `<id>+<login>@users.noreply.github.com`
  address, so GitHub links it to their account), with messages like
  `Update view 'Context'`. A save that changes nothing makes no commit.
  Pushes run in the background, so a burst of saves goes out as one push about
  1 s later. A push rejected because someone else pushed first is retried
  once after a rebase. Concurrent edits to the *same* View are not merged:
  the last save wins.
- **Sign-in** — every page and API request needs a session; signed out, `/`
  redirects to `/auth/login` (GitHub OAuth) and the API returns 401. Only
  collaborators on `GITHUB_REPO` get in, unless `ALLOWED_USERS` (a comma-separated
  list of GitHub logins, case-insensitive) is set, in which case only those
  users can sign in. The session is a stateless HMAC-signed cookie (`HttpOnly`,
  `SameSite=Lax`, `Secure` when `PUBLIC_URL` is https) that lasts 7 days;
  rotating `SESSION_SECRET` signs everyone out. `/auth/logout` signs out,
  and `/auth/me` returns `{login, name}`.
- **`/healthz`** — public, `{"ok": true}`, for the platform's health check.
- **Documentation links** — `/api/doc` serves only files inside the clone,
  never absolute paths or `../` escapes onto the server's filesystem.
- **Token hygiene** — `GITHUB_TOKEN` goes into each git command as an HTTP
  header, so it never ends up in `.git/config`, the remote URL, or error output.

Environment variables:

| Variable | Required | Meaning |
|---|---|---|
| `GITHUB_REPO` | yes | `owner/name` of the repo holding the model |
| `MODEL_PATH` | yes | model folder inside the repo; `.` when the model is at the repo root |
| `GITHUB_TOKEN` | yes | fine-grained PAT for that repo: *Contents* read/write (+ *Metadata* read, granted by default) |
| `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` | yes* | the GitHub OAuth app used for sign-in |
| `SESSION_SECRET` | yes* | long random string that signs session cookies |
| `PUBLIC_URL` | yes* | the URL people open, e.g. `https://system-explorer.onrender.com` |
| `ALLOWED_USERS` | no | comma-separated logins; replaces the collaborator check |
| `GITHUB_BRANCH` | no | default `main` |
| `PULL_INTERVAL` | no | seconds between pulls, default `30` |
| `PORT` | no | default `8080` (most platforms set it) |
| `WORK_DIR` | no | where the clone lives, default `/tmp/system-explorer/repo` |
| `GIT_REMOTE` | no | clone URL override (non-GitHub host, or a local path for testing) |
| `ALLOW_ANONYMOUS` | no | `1` turns sign-in off (*not needed then). Local testing only |

## Stakeholder analysis (`methodology/stakeholder_analysis.py`)

The first guided activity. It is a repository script, not part of the
installed viewer: the viewer only reads the SysML it writes. The activity
declaration is [`methodology/product-development.yaml`](methodology/product-development.yaml).
The worked model is [`methodology/example`](methodology/example).

```
python methodology/stakeholder_analysis.py check <model-folder>
python methodology/stakeholder_analysis.py apply <model-folder>
```

`--methodology` overrides the activities file. The default is
`product-development.yaml` beside the script.

**Method.** Three steps, printed by both commands:

1. Write a list of stakeholders.
2. Write at least one user need for each stakeholder.
3. Categorize each stakeholder as customer, internal, or regulatory.

**Register.** `<model-folder>/process/stakeholders.yaml`. `system` is an
UpperCamelCase name (default `SystemOfInterest` when the key is omitted).
Each stakeholder has an UpperCamelCase `name`, an optional `description`,
a `category` of `customer`, `internal`, or `regulatory`, and a `needs`
list. Each need has an `id` such as `NEED-1`, an UpperCamelCase `name`,
and a `text`. Names must not collide with each other or with the generated
definitions `Stakeholder`, `Customer`, `InternalStakeholder`,
`RegulatoryStakeholder`, `OperationalContext`, and `UserNeed`.

**Exit rules.** `has-stakeholder` (at least one stakeholder),
`each-has-need` (every stakeholder has at least one need),
`each-categorized` (every stakeholder has one of the three categories).
A missing category or a missing need leaves the activity open and still
writes the model. An unknown category, a duplicate id or name, a bad
identifier, or a YAML syntax error is a malformed register: nothing is
written.

**Exit codes.** 0 when every exit rule is met, 2 when the activity is
open, 1 when the folder, the methodology file, or the register is
malformed.

**check** prints the method, the roster, and the exit rules. It does not
create or modify files. **apply** writes:

- `stakeholders.sysml` — abstract category definitions, one `part def` per
  stakeholder specializing its category (or `Stakeholder` when the
  category is still unset), the system of interest, and an
  `OperationalContext` that composes them. Written only when the register
  lists at least one stakeholder.
- `user_needs.sysml` — a `UserNeed` requirement definition and one
  requirement usage per need, with the need text and stakeholder in
  `doc` and a `stakeholder` feature typed by that stakeholder's part def.
  The explorer draws the requirements and their docs; it does not draw a
  separate edge for the `stakeholder` feature.
- `process/state.yaml` — methodology id, activity id, `open` or `done`,
  and the exit-rule results.

When the register file is missing, `apply` creates a commented template
at `process/stakeholders.yaml` and an open `process/state.yaml`, and does
not write SysML. `check` only reports that the register is missing.

Both commands read the category ids, labels, docs, step text, and output
paths from the activity declaration, so a later activities file can rename
those without changing the script. Adding an exit rule the script does
not know is an error, rather than a rule that looks enforced and is not.

`validate_register(register)` returns the same structural errors `apply`
would refuse, without writing a file. The assistant uses it before it
saves a register the team has confirmed.

## SE assistant (`src/assistant/`)

An AI-powered modeling assistant integrated into the System Explorer viewer
as a collapsible chat panel. The assistant guides teams through the
product-development methodology, helps capture stakeholder needs, and
generates SysML models.

**UI.** A "Chat" button in the toolbar opens a side panel with the
assistant conversation. The panel slides in from the right and can be
toggled or closed. When the assistant is not configured (missing
`ASSISTANT_BASE_URL` or `ASSISTANT_MODEL`), the panel displays a clear
message and the explorer continues to work normally.

**Routes.** `GET /api/session` returns the opening message, configuration
status, and model folder. `POST /api/chat` takes `{"messages": [{"role",
"content"}]}` of user and assistant turns and returns the updated
transcript plus short notes for tools that ran. The transcript is kept in
the browser. Both routes require authentication: GitHub session in hosted
mode, HTTP Basic Auth in local mode (when `SE_AUTH_USER` and
`SE_AUTH_PASSWORD` are set).

**Provider.** `POST {ASSISTANT_BASE_URL}{ASSISTANT_CHAT_PATH}` with an
OpenAI-compatible `/chat/completions` JSON body. `ASSISTANT_AUTH=bearer`
(default) sends `Authorization: Bearer {ASSISTANT_API_KEY}`.
`ASSISTANT_AUTH=api-key` sends the key in the `api-key` header instead.
The key is never written to the page, transcript, or model files. Set
`ASSISTANT_BASE_URL`, `ASSISTANT_API_KEY`, and `ASSISTANT_MODEL` to enable
the assistant; leave them unset to run the explorer without AI features.

**First message.** A model folder with no `process/state.yaml` starts with
the fixed greeting (what the project is, and whether documents already
exist). An open activity continues that activity and names the unmet exit
rules. A finished activity says so and waits for a review or a change.

**Tools.** The assistant may call `stakeholder_check`, `stakeholder_apply`,
and `add_model_element`. `check` does not write. `apply` with a register
argument validates it, writes `process/stakeholders.yaml`, then generates
the SysML files. A register that fails validation is not written. `apply`
without arguments regenerates from the register already in the folder. The
prompt tells the model to call `apply` only after the team confirms the
list, and not when the folder already has a SysML model to edit.
`add_model_element` with `element_type: stakeholder` writes a `part def`
into the existing `*Context.sysml` file (the same shape as Patient and
Surgeon), after the assistant has asked what the person does. After four
tool rounds without a final answer, the turn stops.

**Methodology file.** The prompt reads `methodology/product-development.yaml`
from this tool, not from the model folder. Hosted mode clones only the
model repo, which does not contain that file. The Docker image copies
`methodology/` to `/app/methodology`, and both local and hosted mode
resolve the file from the tool. A missing file is reported in the chat
instead of dropping the HTTP connection.

**Model writes.** When the assistant generates or updates `.sysml` files,
they go into the explorer's model folder. In hosted mode, these files are
automatically committed and pushed to the git repo (authored as the
signed-in GitHub user), just like manual View saves. The viewer reloads
the model and adds the new definitions to the diagram (a new context
element is shown on the context view) without a page reload.

**Panel assets.** `assistant_panel.js` and `assistant_panel.css` are
package data. A `pip install` of this tool (including the hosted image)
serves them at `/assistant_panel.js` and `/assistant_panel.css`. Same-origin
`fetch` sends the GitHub session cookie on its own.

**Documents.** Text files (`.txt`, `.md`, `.csv`) in the model folder are
included in the prompt, up to a size cap. PDFs are named and not parsed.
`.env` is never read into the prompt.

**Hosted mode environment variables** (add these to `render.yaml` for the
`system-explorer` service):

- `ASSISTANT_BASE_URL` — provider endpoint (e.g. `https://api.openai.com/v1`), sync: false
- `ASSISTANT_API_KEY` — provider API key, sync: false
- `ASSISTANT_MODEL` — model name (e.g. `gpt-4`), sync: false

When these are unset, the explorer runs normally and the chat panel shows
"Assistant not configured."

**Standalone mode.** The standalone `python -m assistant` server is still
available for local testing but is not needed for normal use:

```
python -m assistant
python -m assistant say "We are starting a portable infusion pump."
```

It binds to `127.0.0.1:8201` unless `ASSISTANT_HOST` / `ASSISTANT_PORT`
say otherwise. Settings are read from the environment first, then from a
`.env` file in the current directory or the repo root (`.env.example`
lists all names). Use `SE_AUTH_USER` / `SE_AUTH_PASSWORD` for HTTP Basic
Auth on the standalone server.

