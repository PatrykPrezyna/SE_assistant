# SysML v2 Explorer

A lightweight local tool that renders an interactive diagram from a folder of
SysML v2 text files (`.sysml`) and lets you arrange the elements manually by
dragging. You curate as many named **Views** as you like — SysML v2's term
for a purpose-built presentation of model content — each holding its own
elements, positions, and pan/zoom. Every View is its own plain
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
To use it without a local checkout of this repo:

```
pip install "git+https://github.com/PatrykPrezyna/SE_assistant.git#subdirectory=tools/sysml_explorer"
```

## Usage

```
sysml-explorer <folder> [--port 8199] [--no-open]
```

Opens the diagram in your browser at `http://127.0.0.1:<port>/`. Each View is
saved to `<folder>/views/<id>.json`; everything else (documentation links,
the element tree panel, UCD drilldown state) is saved to
`<folder>/layout.json`.

Every `.sysml` file directly inside `<folder>` (subfolders are
ignored) is merged into one model

```
sysml-explorer examples/MedicalDevice
```

Validate without starting the server — prints every validation warning (see
Validation in [FEATURES.md](FEATURES.md)) and exits nonzero if there are
any, so it can be used as a pre-commit or CI gate:

```
sysml-explorer <folder> --check
```

When developing this tool, always start the version from the current checkout

```
cd tools/sysml_explorer/src
python -m sysml_explorer C:\sources\SE_assistant\examples\MedicalDevice
```

## What the viewer simplifies vs. standard SysML notation

To keep diagrams readable, the viewer deliberately deviates from textbook
SysML rendering. At a glance (all of these are **Display** toggles you can
turn back on per View, except where noted):

- **Element kind keywords are hidden** — node headers show just the name,
  not «part def» / «requirement» / etc.
- **Parts and part definitions look the same** — standard BDD often
  distinguishes usage vs definition boxes; here a `part` usage node uses
  the same white fill (and uncolored tree dot) as a `part def`. Other
  non-def kinds can still get a tint. Reverse: in
  [`viewer.html`](src/sysml_explorer/viewer.html), drop the
  `&& d.kind !== "part"` / `&& kind !== "part"` guards in `createNodeEl`
  and `treeDotClass` so parts get `.usage` / `k-usage` again.
- **Usage node headers omit `: Type`** — SysML often labels a usage
  `inputTempSensor : Thermistor`; the viewer shows only the role name
  (`inputTempSensor`). The type remains in the model (`usageType`) and on
  the typing edge (legend: **is a**). Parts-compartment lines inside a
  def still show `role : Type`. Reverse: in `buildNodeContent`, append
  `+ (d.usageType ? " : " + d.usageType : "")` to the name line again.
- **Singleton part usages collapse onto their part def** — in SysML a
  usage (`part battery : Battery`) and its definition (`part def Battery`)
  are two elements. Here, if a part def has **exactly one** usage in the
  whole model, that usage is hidden from the **element tree** and from
  **Show usages**, and if both are somehow View members only the **def**
  is drawn on the canvas. If the type has **several** usages (e.g. two
  Thermistors), every usage stays visible as today. Reverse: remove
  `singletonPartUsageIds` filtering in `filterTreeNodes` /
  `relatedGroups`, and `suppressedSingletonUsages` in `buildBddNodesEdges`
  (`viewer.html`).
- **Edge labels are hidden** — no composition role names or «satisfy»
  labels on the lines. A **legend** explains the arrow styles instead.
  Connector edges always keep their label (which connection / ports).
- **Legend wording is human-friendly, not SysML-textbook** — the edge
  kinds are still specialization (`:>`) and typing (`: Def`) in the model;
  the legend just says **kind of** and **is a** so non-engineers can read
  the diagram. Mapping (and how to reverse it):

  | Model / edge kind | SysML idea | Legend text today |
  |-------------------|------------|-------------------|
  | `specialization` | specialization (`A :> B`) | `kind of` |
  | `typing` | typed by (`part x : Def`) | `is a` |

  Labels live in `LEGEND_LABELS` in
  [`src/sysml_explorer/viewer.html`](src/sysml_explorer/viewer.html).
  To restore textbook wording, set
  `specialization: "specialization (is a)"` and `typing: "typed by"`
  (and update the assertion in `test_legend_lists_only_visible_edge_kinds`
  that checks the typing row text).
- **Package paths and doc text are hidden** on nodes by default — open
  **Display** to show them; documentation *links* still use the marker /
  context menu.
- **Satisfy edges are drawn dark yellow**, so they stay distinguishable
  from typing edges (both dashed, open arrow) without labels.
- **Actors are plain boxes** (tinted pale purple), not stick figures;
  **use cases are plain boxes** (pale green), not ellipses — both behave
  like any other node and can join any View.
- **Attributes / parts compartments** can be hidden from **Display**.
- **`useDiagram` blocks contribute no node of their own** — their content
  attaches to the subject element, which gets a marker and a right-click
  drilldown instead.
- **`perform action` swimlanes** are an explorer-only activity drilldown
  (see FEATURES.md), not standard `activity def` diagrams.
- **Actor ↔ use case associations are lifted to the defs**: a `useDiagram`
  connection is declared between local role usages, but the block
  definition diagram renders it between the defs they're typed by.
- **Only the supported subset is rendered** — statements with known
  keywords the tool doesn't draw (`constraint`, `state`, `subject`, …) are
  silently skipped; unknown first words trigger a validation warning.
- **Comments (`//`, `/* */`) are stripped; `doc` bodies are kept** and can
  be shown on the node via **Display → docs on node**.

## Setting up the validation parsers

`sysml-explorer --check` is a fast, dependency-free sanity check built on
this tool's own pragmatic parser — good for CI gates, **not** a grammar.
For real validation install one (ideally both) of the following.

### Official SysML v2 parser (preferred, spec-grade)

The OMG **pilot implementation** is the reference parser for the SysML v2
textual notation — full grammar, semantic checks, and standard-library
resolution. It is Java/Xtext-based and distributed as a Jupyter kernel
(`jupyter-sysml-kernel` on conda-forge);
`tools/sysml_explorer/official_check.py` drives that kernel headlessly so
you get a one-command file check instead of an interactive notebook.

One-time setup (needs conda; Java is bundled by the package):

```
conda create -n sysml -c conda-forge jupyter-sysml-kernel jupyter_client
```

If conda fails with `CERTIFICATE_VERIFY_FAILED` (typical behind antivirus
HTTPS inspection — same AVG family as the loopback issue under
Troubleshooting), tell conda to trust the Windows certificate store instead
of its bundled CA file:

```
CONDA_SSL_VERIFY=truststore conda create -n sysml -c conda-forge jupyter-sysml-kernel jupyter_client
```

Then check a model folder (same folder semantics as `sysml-explorer`:
every `.sysml` directly inside it, name-sorted, one kernel session so
cross-file references resolve) — **invoke the env's python directly**:

```
%USERPROFILE%\miniconda3\envs\sysml\python.exe -u tools/sysml_explorer/official_check.py <folder>
```

(To find the env's python on any machine, a *short-lived* probe is fine:
`conda run -n sysml python -c "import sys; print(sys.executable)"`.)

**Do not run the check itself through `conda run`** — it never drains the
kernel JVM's console output, so the pipe fills and the whole run deadlocks
(observed as repeated 30-minute hangs); it also buffers all output until
the end even when it does work.

Every `ERROR:`/`WARNING:` line the reference parser reports is printed
prefixed with its file name (with line/column), and the script exits
nonzero if there were any. Notes:

- **the first run is slow**: kernel startup loads the ~200-file standard
  library, which can take 10+ minutes cold (antivirus scanning each file);
  once the OS/antivirus caches are warm it drops to seconds. `--timeout`
  (default 900 s) covers both startup and each file's evaluation.
- files are fed to the kernel in name-sorted order; an `import` of a
  package defined in a file that sorts *later* will produce resolution
  errors the explorer (which merges everything before resolving) doesn't
  have.
- this tool's dialect is **not** fully standard SysML v2 and the official
  parser will reject the non-standard parts: `use case useDiagram ... for
  ...`, `actor def` (v2 actors are usages typed by part defs, not defs), and
  unquoted hyphenated references like `satisfy REQ-201` (write
  `satisfy 'REQ-201';`). See "Dialect notes" in [FEATURES.md](FEATURES.md).
  Expect errors on those until the models are migrated to standard syntax.
- `official_check.py` deliberately lives *outside* the `sysml_explorer`
  package: it must run under a python that has `jupyter_client` (the conda
  env above), while the explorer itself stays stdlib-only.

### Fallback: JamieD sysml-v2-support parser (fast, community grammar)

When the conda env isn't available (or for a quick check after every edit —
this one is fast), use the parser bundled with the free VS Code / Cursor
extension **JamieD.sysml-v2-support** (`sysml-v2-lsp`, ANTLR-based — a
community grammar, not the reference one). Requirements: the extension
installed (VS Code or Cursor) and Node.js on PATH.

```
python tools/validate_sysml_jamied.py <folder-or-file>
```

Exit code 0 means clean; diagnostics are printed with file/line. The script
auto-locates the extension's bundled MCP server (override with the
`SYSML_V2_LSP_MCP` env var). The same parser is also exposed as a Cursor
MCP server named `sysml-v2-jamied` (see `.cursor/mcp.json`, which launches
it via `tools/sysml_jamied_mcp.cmd`) — call its `validate` tool with
`{ "code": "<file contents>" }`.

## Using an LLM coding agent as a modeling assistant

To make an agent (Cursor, Claude Code, …) a reliable SysML modeling
assistant for a model folder, give it a **scoped rule/instructions file**.
The working example in this repo is
[.cursor/rules/medicaldevice-sysml.mdc](../../.cursor/rules/medicaldevice-sysml.mdc),
scoped to `examples/MedicalDevice/**`. A good rule file states:

1. **One model, many files** — every `*.sysml` directly in the folder is one
   combined model; cross-file `import`, `satisfy`, typing, and
   specialization must resolve across packages. Prefer sibling packages in
   the folder root (`*_req.sysml`, `*_bdd.sysml`, …).
2. **Dialect** — spec-compliant SysML v2 textual notation, with the
   official parser as the arbiter. In particular: requirement short names
   `requirement def <'REQ-123'> Name`, and **quoted** satisfy references
   (`satisfy 'REQ-123';` — the explorer accepts unquoted, the official
   grammar does not).
3. **How to validate, in order of preference** — official parser via
   `official_check.py` (run once after a batch of edits; warn the agent it
   is slow by design and must not be killed or given a short timeout), the
   JamieD parser via `validate_sysml_jamied.py` as a fast fallback after
   every edit, and *never* substituting `sysml-explorer --check` for
   either — it's a sanity check, not a grammar. Exit code must be 0 before
   finishing.
4. **Rules of thumb** — prefer additive edits, update all cross-references
   when renaming, summarize files touched and remaining diagnostics.

Additionally, point the agent at [FEATURES.md](FEATURES.md) so it knows
exactly which constructs the explorer parses and renders (and which
warnings it emits) when it edits models meant to be viewed here.

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
parts structure, edges, requirements/docs, validation warnings), the HTTP
API (model serving, layout round-trip), and — when Microsoft Edge is
available — end-to-end rendering: the page is loaded headless and the DOM
is checked for each attribute/parts filter combination.
`official_check.py` has an end-to-end test too, but it's **opt-in** —
`SYSML_OFFICIAL_CHECK_TEST=1` plus the `sysml` conda env (see "Setting up
the validation parsers") — because official-kernel startup can take 10+
minutes, too slow for the default suite.

## Development conventions

Every new feature gets:
1. a bullet (or section) in **[FEATURES.md](FEATURES.md)**, and
2. a test in `test_sysml_explorer.py` proving it works.
