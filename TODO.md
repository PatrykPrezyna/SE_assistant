## next steps
0. explain to me wht the lauout is doing - dowe realy need it
1. add legend
0.sysml v2 and consise list what we do differently
2. make the activity diagram useull
- how to document decision racionale 
- 


In tis tool: the system model should be 100% compatible tiwh sysmv2 model, any additioanl infromation like the link to a documentation or a picture should be saved outside the model, every simplification (like not showing the <part def>), the views with its meta data are saved independently of the model but should be validated and the ai agent in my coding ide should be instucted to validate all the viesw and ask if thait should be updated too, 

z. test the pasrser on a diferent laptop (is the oficial parser fast enough or should we use the one from the extension as a backup)
x. define a methodology 
y. 

## digital thread
1. connect to a CAD model or Simulation 
2. 

## Deployment
1. make people use it and comment
2. try differnt models, open source, hosted locally
3. make it easier to install maybe VS extension or clound hosted


Software craftsmanship — weaknesses
Name resolution is by simple name only. Model.resolve strips qualification and looks up the last segment (app.py:150-153), and setdefault keeps the first registration — two elements named Controller in different packages silently collide, and edges attach to whichever parsed first. Fine today; it will bite as models grow.
Everything unresolved is dropped silently — satisfy targets, IBD owners, UCD subjects. That's documented and deliberate, but for a tool whose pitch is "trust this diagram," silence is the wrong failure mode: a typo'd satisfy reference makes the requirement look unaddressed with no hint anything is wrong. A small "3 unresolved references" indicator in the toolbar would fit the mission much better than silence.
viewer.html is 1,515 lines of global-state JS (mode, hiddenEdges swapped by reference between BDD/drilldown). It's still readable and the size is defensible, but the "designed to grow" context menu comment suggests more features are coming, and this file is near the point where splitting it (or at least isolating the state machine) pays for itself. The 65-second Edge tests are also the suite's only coverage of that logic.
Minor: _parse_blocks scans char-by-char with no string-literal awareness, so a {/; inside a quoted attribute default would corrupt block structure; malformed JSON in a POST body produces an unhandled exception rather than a 400; no CI runs the suite automatically (it's manual by convention).


The custom dialect. ibd def X of Owner and use case useDiagram Name for Subject are not SysML v2 — a conforming parser (the pilot implementation, or any future commercial tool) will reject those files. That means your .sysml files can only ever be validated and consumed by this tool, which is the opposite of a single source of truth. The standard way to express both is connect inside part usages (which you already support) and view def/view for diagram membership. I'd treat migrating the dialect toward standard syntax as the highest-leverage improvement — more valuable than any new feature — because it's cheap now and expensive later, once views and models accumulate.
Coverage gaps mislead the very audience it targets. Non-engineers can't tell "not in the model" from "not parsed" (constraints, states, activities, interfaces are all unparsed). Combined with silent reference-dropping, the diagram can look more complete and more correct than the model is. Honest-uncertainty affordances — the unresolved-reference counter, maybe a per-file "N constructs skipped" note — matter more here than for a tool aimed at modelers.

## Generated default views (not implemented)

Moved here from the code (`DEFAULT_VIEW_SPECS` / `build_default_views()` /
`sync_default_views()`, a no-op placeholder, removed in 0.1.0). The idea:
every model gets three standard Views generated from the parsed model
instead of hand-authored JSON. The CoolSpine example's hand-made
`views/{context,decomposition,interconnections}.json` are the reference set.
A generator should only ever overwrite these three ids, never a View made
by hand.

| id | name | shows |
| --- | --- | --- |
| `context` | **1 Context** | every member of the context block plus the connections between them; the context block itself on top, with composition edges shown to its members (system, actors, external systems) |
| `decomposition` | **2 Decomposition** | the system part def and up to three levels of composition below it, as a pyramid: level 1 centred on top, level 2 spread beneath, level 3 under its own parent. Realization specializations of a level-2 part (`Thermistor :> TemperatureSensor`) count as level 3. Attributes/parts compartments off, **docs on**; connector edges hidden so only the tree shows |
| `interconnections` | **3 Interconnections** | the connections declared in the system part def, between its **first-level parts only**. The system block itself is deliberately not a member, so no composition edge competes with the connectors. (The system's "internal block diagram", named for what it shows rather than for SysML v1.) |

## Unfinished notes from the old README

Moved here when README.md became the tool's front page:

- SE task map link: TBD
- useful SysML tutorials: advent
- MAS4SysML citation: [@liuMAS4SysMLMultiAgentFramework2026]
- "System modeling:" (unfinished list entry)
- similar work: "Johnsep"
