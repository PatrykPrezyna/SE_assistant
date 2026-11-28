# Notation profile

This file is the graphical notation of the Explorer
([`viewer.html`](src/system_explorer/viewer.html)). The textual model stays
standard SysML v2: none of these rules change `.sysml`. The published Viewer
([`publish_viewer.html`](src/system_explorer/publish_viewer.html)) follows a
rule only where that rule says so.

Each rule has a stable id. **Standard** is the textbook drawing. **Explorer**
and **Published Viewer** are what the two pages draw. **Model** is always
unchanged. **Override** is a Display option saved on the View, or **fixed**
(the page always draws it this way).

A change to one of these drawings updates this file and
`NotationProfileTests` in the same change.

Naming style (UpperCamelCase definitions, lowerCamelCase usages, a single
usage named after its definition) is a model-text rule. It belongs to the
convention linter in [ARCHITECTURE.md](ARCHITECTURE.md), not to this profile.

## N1 — Kind keywords

**Standard.** A node header carries a kind keyword, such as «part def» or
«requirement».

**Explorer.** The header shows the name. The keyword line appears only when
the View turns it on.

**Published Viewer.** The header shows the name. The detail sheet still
shows «kind», as it does in the Explorer.

**Model.** Unchanged.

**Override.** Display option `keywords` (default off). The published Viewer
has no Display menu, so the keyword stays off.

## N2 — Part usages match part definitions

**Standard.** A usage box is distinguished from its definition box.

**Explorer.** A `part` usage uses the same white fill and the same uncolored
tree dot as a `part def`. Other non-def kinds can still take a tint.

**Published Viewer.** Same white fill for a part usage and a part def. The
page has no separate usage tint. Requirements, actors, and use cases keep
their own fills (N8).

**Model.** Unchanged. The element is still a usage.

**Override.** Fixed.

## N3 — Usage headers show the role name

**Standard.** A usage is labeled `role : Type`, for example
`inputTempSensor : Thermistor`.

**Explorer.** The header shows the role name (`inputTempSensor`). The type
stays in the model as `usageType` and on the typing edge (N6, **is a**).
A parts-compartment line inside a definition still shows `role : Type`.

**Published Viewer.** Same header: the role name, with a short name in
front of it when the element has one, and no `: Type`. Compartment lines
still show `role : Type`.

**Model.** Unchanged.

**Override.** Fixed.

## N4 — Singleton part usages collapse onto their definition

**Standard.** `part battery : Battery` and `part def Battery` are two
elements, and both can appear.

**Explorer.** When a part def has exactly one part usage in the whole model,
that usage is omitted from the element tree and from **Show usages**. When
both are members of the View, only the definition is drawn. A type with
several usages (two Thermistors) keeps every usage.

**Published Viewer.** When both the definition and its single usage are in
the published View, only the definition is drawn. The page has no element
tree.

**Model.** Unchanged. Both elements remain in the model.

**Override.** Fixed.

## N5 — Edge labels

**Standard.** Composition edges carry a role name, and satisfy edges carry
a «satisfy» label.

**Explorer.** Those labels are hidden. A legend (N6) explains the arrow
styles. Connector labels (which connection, which ports) and flow guards
(yes/no after a decide) stay on the line.

**Published Viewer.** Same. Connector labels and flow guards stay; other
edge labels are hidden.

**Model.** Unchanged. Edge kinds in the model JSON stay
`specialization`, `typing`, `satisfy`, and the rest.

**Override.** Display option `edgeLabels` (default off). Connector and flow
labels are fixed on. The published Viewer has no Display menu, so other
labels stay off.

## N6 — Legend wording and satisfy color

**Standard.** The legend names the relationship: specialization (`A :> B`),
typed by (`part x : Def`).

**Explorer.** The legend uses plain wording for the two relationships a
non-modeler meets first. The model edge kind is unchanged.

| Model edge kind | Textbook relationship | Legend text |
|-----------------|----------------------|-------------|
| `specialization` | specialization (`A :> B`) | kind of |
| `typing` | typed by (`part x : Def`) | is a |

Satisfy edges are dark yellow, so they stay distinct from typing edges
(both dashed, open arrow) while labels are off (N5).

**Published Viewer.** The same legend and the same dark-yellow satisfy
edges.

**Model.** Unchanged.

**Override.** Fixed.

## N7 — Package paths and documentation on the node

**Standard.** A node may show its package and its documentation body.

**Explorer.** Both are off. A documentation *link* still uses the marker
and the context menu. The detail sheet still shows the `doc` body.

**Published Viewer.** Same: no package line and no doc body on the node.
A documentation link still uses the marker, and opens from the detail
sheet.

**Model.** Unchanged. `doc` bodies are kept (N12).

**Override.** Display options `packages` and `docsOnNode` (both default
off). The published Viewer has no Display menu, so both stay off.

## N8 — Actors and use cases

**Standard.** Actors are stick figures and use cases are ellipses.

**Explorer.** Both are boxes: actors pale purple, use cases pale green.
They join any View, like any other node.

**Published Viewer.** Same boxes and the same tints.

**Model.** Unchanged.

**Override.** Fixed.

## N9 — Attribute and parts compartments

**Standard.** Compartments are part of the node.

**Explorer.** Attribute and parts compartments are shown, and each View can
hide them. Attribute redefinitions nested under a part follow
*attributes*, and hide when *parts* is off.

**Published Viewer.** Attribute and parts compartments are shown, including
attribute redefinitions nested under a part.

**Model.** Unchanged.

**Override.** Display options `attrs` and `parts` (both default on). The
published Viewer has no Display menu, so both stay on.

## N10 — Activity Views

**Standard.** SysML v2 has no `activity` keyword. A process is an action
usage owned by a use case (or by another action). Who does a step is
`perform` inside that person's part. Order is `first`/`then`. `fork`,
`join`, `decide`, and `merge` are control nodes. An item handed on is
`flow`.

**Explorer.** Opening a use case draws that process as swimlanes, one
column per actor. The older `perform action` block is still drawn the
same way. The diagram is an Explorer View; see [FEATURES.md](FEATURES.md).

**Published Viewer.** Activity Views are left out of the published site.
Block Views are published.

**Model.** Edits from the activity bar and from the chat write the
standard forms into the `.sysml` files. The older `perform action` blocks
are left as they are until someone edits that activity.

**Override.** Fixed.

## N11 — Rendered subset

**Standard.** A conforming tool draws every construct in the model.

**Explorer.** The page draws the subset this tool parses. A statement whose
first word is a known keyword the tool does not draw (`constraint`,
`state`, `view`, and the others listed with them in the parser) is skipped
with no warning. An unknown first word produces a validation warning
(`unrecognized statement`).

**Published Viewer.** Same model JSON, so the same subset.

**Model.** Unchanged. Skipped statements remain in the `.sysml` files.

**Override.** Fixed.

## N12 — Comments and doc bodies

**Standard.** Comments and documentation are both part of the text.

**Explorer.** `//` and `/* */` comments are stripped before parsing. A
`doc /* ... */` body is kept and can be shown on the node (N7).

**Published Viewer.** Same parsed model, so the same bodies, shown on the
detail sheet.

**Model.** The files on disk keep their comments. Stripping happens in the
parser.

**Override.** Fixed. Showing a kept `doc` body on an Explorer node is N7.

## Implementation notes

These are the code sites behind the fixed rules. The rules above stay
normative; this appendix is only where to edit them.

- **N2.** In [`viewer.html`](src/system_explorer/viewer.html), drop the
  `&& d.kind !== "part"` / `&& kind !== "part"` guards in `createNodeEl`
  and `treeDotClass` so parts get `.usage` / `k-usage` again.
- **N3.** In `buildNodeContent`, append
  `+ (d.usageType ? " : " + d.usageType : "")` to the name line again.
- **N4.** Remove `singletonPartUsageIds` filtering in `filterTreeNodes` and
  `relatedGroups`, and `suppressedSingletonUsages` in `buildBddNodesEdges`.
  The published page has its own `suppressedSingletonUsages`.
- **N6.** Labels live in `LEGEND_LABELS`. Textbook wording is
  `specialization: "specialization (is a)"` and `typing: "typed by"`.
  Update `test_legend_lists_only_visible_edge_kinds`, which checks the
  typing row text, and `NotationProfileTests`.
