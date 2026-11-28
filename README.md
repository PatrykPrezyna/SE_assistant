# System Explorer

A lightweight, text-first systems-engineering tool for SysML v2 models. It
reads a folder of `.sysml` files and serves an interactive diagram in the
browser. You arrange elements by hand and curate named **Views**, SysML v2's
term for a purpose-built presentation of model content. It also validates the
model. Each View is a plain JSON file next to the model, so the model and its
diagrams are versioned in git together.

Built as an alternative to auto-layout-only viewers (the SysML v2 pilot
Jupyter implementation, SysIDE) and heavyweight commercial modelers
(Cameo/MagicDraw). It is a pip-installable Python package with no
dependencies beyond the standard library.

This is the implementation repository for my research on how systems
engineering can be democratized: specifically, how MBSE can improve product
development for small and mid-size organizations and resource-constrained
teams. Master's thesis: https://www.overleaf.com/project/6920a69cf448138c4e3fd087.
The design direction is in [ARCHITECTURE.md](ARCHITECTURE.md), and everything
the tool parses, renders, validates and serves is in [FEATURES.md](FEATURES.md).

## Install

```
pip install "git+https://github.com/PatrykPrezyna/SE_assistant.git"
```

To upgrade later, rerun the command with `--upgrade`. To work on the tool
itself, use an editable install from a checkout: `pip install -e .`.

## Usage

```
system-explorer <folder> [--port 8199] [--no-open]
```

This opens the diagram in your browser at `http://127.0.0.1:<port>/`. Every
`.sysml` file directly inside `<folder>` is merged into one model; subfolders
are ignored. Each View is saved to `<folder>/views/<id>.json`, and global
state (documentation links, the element tree panel, the active View) goes
to `<folder>/layout.json`.

Validate without starting the server:

```
system-explorer <folder> --check
```

This prints every validation warning (see *Validation* in
[FEATURES.md](FEATURES.md)) and exits nonzero if there are any, so it works as
a pre-commit or CI gate. `--print` dumps the parsed model as JSON.

## Example model (for testing)

This repo ships the tool only — there is no sample model here. Use the
CoolSpine medical-device model to try System Explorer:

```
git clone https://github.com/PatrykPrezyna/cool-spine-model.git
cd cool-spine-model
system-explorer .
```

That checkout is the reference model for manual testing and for the hosted
demo (`GITHUB_REPO` in [`render.yaml`](render.yaml)).

## Published Viewer (phone)

The Explorer is where an engineer edits `.sysml` (by hand or with the AI
chat) and arranges prepared Views. The Viewer is a separate, view-only site
generated from that folder: elements stay where they were placed, a tap
shows the element's `doc` text, the requirements it `satisfy`s, and its
documentation link.

```
system-explorer <folder> --publish docs
```

`<outdir>` (here `docs/`) receives `index.html`, `model.json`, `views.json`,
`docs.json`, and copies of documentation files that live inside the model
folder. Open `index.html` through any static host. Activity Views are left
out; block Views are published.

On each push of the model repository, GitHub Actions can run that command
and deploy the folder to GitHub Pages. The workflow lives in the model
repo at `.github/workflows/viewer.yml` (added in `spine-cooling`). It
installs this package from a pinned ref, so a later Explorer change does
not rebuild the site until that ref moves. An `http(s)` documentation link
opens as-is. A path outside the model folder is listed in `docs.json`
under `omitted` and is not copied.

## Setting up the validation parsers

`system-explorer --check` is a fast, dependency-free sanity check built on this
tool's own pragmatic parser. It is good for CI gates, but it is **not** a
grammar. For real validation, use one (ideally both) of the two validators
that ship with the package.

### Official SysML v2 parser (preferred, spec-grade)

The OMG **pilot implementation** is the reference parser for the SysML v2
textual notation, with the full grammar, semantic checks, and standard-library
resolution. It is Java/Xtext-based and distributed as a Jupyter kernel
(`jupyter-sysml-kernel` on conda-forge). `system_explorer.official_check`
drives that kernel headlessly, so you get a one-command file check instead of
an interactive notebook.

One-time setup (needs conda; Java is bundled by the package):

```
conda create -n sysml -c conda-forge jupyter-sysml-kernel jupyter_client
%USERPROFILE%\miniconda3\envs\sysml\python.exe -m pip install "git+https://github.com/PatrykPrezyna/SE_assistant.git"
```

If conda fails with `CERTIFICATE_VERIFY_FAILED` (typical behind antivirus
HTTPS inspection, the same AVG family as the loopback issue under
Troubleshooting), tell conda to trust the Windows certificate store instead
of its bundled CA file: prefix the command with `CONDA_SSL_VERIFY=truststore`.

Then check a model folder. The folder semantics match `system-explorer`: every
`.sysml` file directly inside it, name-sorted, in one kernel session so
cross-file references resolve. **Invoke the env's python directly**:

```
%USERPROFILE%\miniconda3\envs\sysml\python.exe -u -m system_explorer.official_check <folder>
```

The module imports nothing else from the package, so it also runs by file
path (`src/system_explorer/official_check.py`) without installing the package
into the env. To find the env's python on any machine, a *short-lived* probe
is fine: `conda run -n sysml python -c "import sys; print(sys.executable)"`.

**Do not run the check itself through `conda run`.** `conda run` never drains
the kernel JVM's console output, so the pipe fills and the whole run
deadlocks (observed as repeated 30-minute hangs). It also buffers all output
until the end even when it does work.

Every `ERROR:`/`WARNING:` line the reference parser reports is printed with
its file name (and line/column), and the check exits nonzero if there were
any. Notes:

- **The first run is slow.** Kernel startup loads the ~200-file standard
  library, which can take 10+ minutes cold (antivirus scanning each file).
  Once the OS and antivirus caches are warm it drops to seconds. `--timeout`
  (default 900 s) covers both startup and each file's evaluation.
- Files are fed to the kernel in name-sorted order. An `import` of a package
  defined in a file that sorts *later* produces resolution errors that the
  explorer (which merges everything before resolving) doesn't have.
- The explorer accepts a few non-standard constructs that the official parser
  rejects. See "Dialect notes" in [FEATURES.md](FEATURES.md).

### Fallback: JamieD sysml-v2-support parser (fast, community grammar)

When the conda env isn't available, or for a quick check after every edit
(this one is fast), use the parser bundled with the free VS Code / Cursor
extension **JamieD.sysml-v2-support** (`sysml-v2-lsp`, ANTLR-based: a
community grammar, not the reference one). It needs the extension installed
(VS Code or Cursor) and Node.js on PATH.

```
python -m system_explorer.jamied_check <folder-or-file>
```

Exit code 0 means clean; diagnostics are printed with file and line. The
module locates the extension's bundled MCP server automatically; override
that with the `SYSML_V2_LSP_MCP` environment variable. To give an AI agent the
same parser as an MCP tool, point its MCP config at
`node <extension>/node_modules/sysml-v2-lsp/dist/server/mcpServer.js` and
call the `validate` tool with `{ "code": "<file contents>" }`.

## Hosting for a team

The same explorer can run in the cloud, so teammates just open a URL and
sign in with GitHub, with nothing to install. The container clones the
*model* repo, pulls teammates' pushes about every 30 s, and turns every View
save into a commit on `main` authored by whoever saved it. *Hosted mode* in
[FEATURES.md](FEATURES.md) describes how it behaves. The setup below uses
[Render](https://render.com) via the blueprint in `render.yaml`. Any platform
that runs a Dockerfile works the same way (Fly.io, Azure Container Apps,
Cloud Run) with the same environment variables.

1. **Push the code.** Render builds the image from this repo, so
   `Dockerfile`, `render.yaml`, and `src/` must be on `main`.
2. **Create a token the server uses to pull and push the model repo.**
   GitHub → Settings → Developer settings → Personal access tokens →
   *Fine-grained tokens* → Generate. Repository access: *Only select
   repositories* → the **model** repo (e.g. `cool-spine-model`).
   Permissions → Repository → **Contents: Read and write** (Metadata: read
   is added automatically). Copy the token and note its expiry date, because
   the server stops syncing when it expires.
3. **Create the sign-in app.** GitHub → Settings → Developer settings →
   *OAuth Apps* → New OAuth App:
   - Homepage URL: `https://system-explorer.onrender.com`
   - Authorization callback URL: `https://system-explorer.onrender.com/auth/callback`

   Register it, then *Generate a new client secret*. Copy the Client ID and
   the secret. If Render gives the service a different URL in step 4, come
   back and change both URLs.
4. **Create the service.** Sign in to Render with GitHub → **New →
   Blueprint** → pick this repo. Render reads `render.yaml` and asks for the
   secret values:
   - `PUBLIC_URL`: `https://system-explorer.onrender.com`, the same URL as in
     step 3, with no trailing slash
   - `GITHUB_TOKEN`: the token from step 2
   - `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET`: from step 3
   - `ALLOWED_USERS`: leave empty to let in every collaborator on the model
     repo, or list GitHub logins (`alice,bob`)

   `SESSION_SECRET` is generated for you. `GITHUB_REPO` (default
   `PatrykPrezyna/cool-spine-model`), `MODEL_PATH` (default `.`, the repo
   root) and `GITHUB_BRANCH` are set in `render.yaml`. Click **Apply**.
5. **Check it.** The deploy log ends with `Serving
   PatrykPrezyna/cool-spine-model:. on port 8080`. Open the URL: you are
   sent to GitHub to sign in and land on the explorer's home page.
6. **Invite teammates.** Model repo → Settings → Collaborators → *Add
   people*. Once they accept, they can sign in. If you set `ALLOWED_USERS`,
   add their logins there instead.

Living with it:

- **Pull before editing Views locally.** Saves in the hosted explorer are
  pushed to `main`, so run `git pull` before you edit Views on your own
  machine.
- **Changing the model needs no redeploy.** Push `.sysml` edits as usual; the
  hosted explorer picks them up on the next refresh. Only changes to the
  explorer itself (`src/`, `Dockerfile`, `pyproject.toml`) trigger a rebuild.
- **Concurrent edits.** If two people edit the same View at the same time,
  the last save wins.
- **Free plan.** The service sleeps after 15 min idle, and the next visitor
  waits about a minute for it to wake. Render's *Starter* plan keeps it
  awake. Nothing is lost while it sleeps, because every save is already in
  git.
- **Several models.** Create one service per model, each with its own
  `GITHUB_REPO`/`MODEL_PATH`, URL, and OAuth app.

Try the container locally before deploying:

```
docker build -t system-explorer .
docker run --rm -p 8080:8080 -e GITHUB_REPO=PatrykPrezyna/cool-spine-model \
  -e MODEL_PATH=. -e GITHUB_TOKEN=<token> -e ALLOW_ANONYMOUS=1 system-explorer
```

`ALLOW_ANONYMOUS=1` turns sign-in off for this local test. Saves still go to
the real `main` branch, so set `GITHUB_BRANCH` to a scratch branch if you
want to experiment.

## What the viewer simplifies vs. standard SysML notation

Diagrams in this tool follow the notation profile in
[NOTATION.md](NOTATION.md). That file is the normative list: each rule
states the textbook drawing, what the Explorer draws, what the published
Viewer draws, and whether a Display option can turn it back. The `.sysml`
files stay standard SysML v2.

## Using an LLM coding agent as a modeling assistant

To make an agent (Cursor, Claude Code, …) a reliable SysML modeling
assistant, put a scoped rules or instructions file (`AGENTS.md`, a Cursor
rule, `CLAUDE.md`) in the **model** repo. A good one states:

1. **One model, many files.** Every `*.sysml` file directly in the folder is
   one combined model; cross-file `import`, `satisfy`, typing, and
   specialization must resolve across packages.
2. **Dialect.** Spec-compliant SysML v2 textual notation, with the official
   parser as the arbiter. In particular: requirement short names
   (`requirement <'REQ-123'> Name : Base`), and **quoted** satisfy
   references (`satisfy 'REQ-123';`). The explorer accepts unquoted
   references; the official grammar does not.
3. **How to validate, in order of preference.** First the official parser
   (`python -m system_explorer.official_check`, run once after a batch of
   edits; tell the agent it is slow by design and must not be killed or
   given a short timeout). Then the JamieD parser
   (`python -m system_explorer.jamied_check`) as a fast check after every
   edit. Never substitute `system-explorer --check` for either: it's a sanity
   check, not a grammar. The exit code must be 0 before finishing.
4. **Rules of thumb.** Prefer additive edits, update all cross-references
   when renaming, and summarize files touched and remaining diagnostics.

Also point the agent at [FEATURES.md](FEATURES.md), so it knows exactly which
constructs the explorer parses and renders (and which warnings it emits)
when it edits models meant to be viewed here.

## Guided activity: stakeholder analysis

The first process step lives outside the viewer. The activity is declared in
[`methodology/product-development.yaml`](methodology/product-development.yaml):
write a list of stakeholders, write at least one user need for each, and
categorize each stakeholder as customer, internal, or regulatory. A model
folder holds the register at `process/stakeholders.yaml`. The script checks
that register and writes standard SysML v2.

```
python methodology/stakeholder_analysis.py check methodology/example
python methodology/stakeholder_analysis.py apply methodology/example
```

`check` prints the method and which exit rules are still open, and does not
write files. `apply` writes `stakeholders.sysml`, `user_needs.sysml`, and
`process/state.yaml` when the register is well formed. Exit code 0 means the
activity is done, 2 means it is still open, and 1 means the register is
malformed. `methodology/example` is a finished register for a small infusion
pump. Open that folder with `system-explorer` to see the stakeholders, the
three categories, and the needs. Details are in
[FEATURES.md](FEATURES.md) under *Stakeholder analysis*.

## SE assistant (local chat)

The chat is a separate program from the explorer. It asks the team what
they are building, calls the stakeholder tool, and links to the diagram.
The model provider is an OpenAI-compatible chat endpoint, so a cloud
subscription and a later local model are the same client with different
settings.

Copy [`.env.example`](.env.example) to `.env` (gitignored) and set
`ASSISTANT_BASE_URL`, `ASSISTANT_API_KEY`, `ASSISTANT_MODEL`, and
`MODEL_FOLDER`. Then, from this repo:

```
python -m assistant
```

Open http://127.0.0.1:8201/ and keep System Explorer open on the same
`MODEL_FOLDER`. `EXPLORER_URL` is the "Open the diagram" link. Put the
API key only in `.env` or the environment, never in the model files.
How to run it, and a picture of the repository, are in
[src/assistant/README.md](src/assistant/README.md). Behavior details are in
[FEATURES.md](FEATURES.md) under *SE assistant*.

## Deploy on Render

The SE assistant can be deployed as a web service on [Render](https://render.com)
so the chat interface is accessible from any browser.

**Quick deploy:**

1. Push this repo to GitHub (or fork it).
2. Sign in to Render → **New → Web Service** → connect your GitHub account
   and select this repository.
3. Configure the service:
   - **Build Command:** `pip install .`
   - **Start Command:** `python -m assistant`
   - Set environment variables (see below).
4. Deploy. The service will be available at `https://<your-service>.onrender.com`.

**Environment variables** (set in the Render dashboard):

Required:
- `ASSISTANT_HOST=0.0.0.0` (must bind to 0.0.0.0 for Render)
- `SE_DATA_DIR=/var/data/se-models` (where model files are stored)

Optional AI features (leave empty to run without AI):
- `ASSISTANT_BASE_URL` (e.g., `https://api.openai.com/v1`)
- `ASSISTANT_API_KEY` (your API key)
- `ASSISTANT_MODEL` (e.g., `gpt-4`)

Optional security (HTTP Basic Auth):
- `SE_AUTH_USER` (username for Basic Auth)
- `SE_AUTH_PASSWORD` (password for Basic Auth)

**Using the Blueprint:**

Alternatively, use `render-assistant.yaml`:

```bash
# In Render dashboard: New → Blueprint
# Select this repository
# Render reads render-assistant.yaml and prompts for secret values
```

**Health check:** `/healthz` returns `{"status": "ok"}`

**Important notes:**

- **Free plan:** The filesystem is ephemeral. Model edits are lost on restart
  or redeploy. The service seeds the example model on first start.
- **Persistent storage:** Attach a persistent disk (requires a paid plan) to
  keep edits across restarts. Uncomment the `disks` section in
  `render-assistant.yaml` or add a disk in the Render dashboard at
  `/var/data/se-models`.
- **Security:** Enable HTTP Basic Auth (`SE_AUTH_USER` / `SE_AUTH_PASSWORD`)
  to protect the public endpoint. Without it, anyone with the URL can access
  the assistant.
- **Service sleep:** Free services sleep after 15 minutes of inactivity. The
  next visitor waits ~50 seconds for wake-up. Paid plans keep services awake.

## Troubleshooting

**PDFs download instead of opening in the tab.** The server serves
documentation with `Content-Type: application/pdf` and
`Content-Disposition: inline` (and answers HEAD probes), which is everything
a browser needs to render the PDF in the tab. If your browser downloads a
copy instead, it is a browser setting. In Edge, open
`edge://settings/content/pdfDocuments` and switch **off** "Always download
PDF files"; in Chrome, open `chrome://settings/content/pdf` and choose "Open
PDFs in Chrome". A PDF-reader browser extension (e.g. Adobe Acrobat) taking
over PDF handling can cause the same behavior.

**Large responses hang or arrive truncated.** Antivirus loopback filters
(observed with AVG Web Shield) can intercept `127.0.0.1` HTTP traffic and
nondeterministically swallow the tail of large, fast responses, even from
Python's stock `http.server`. The server therefore sends payloads in paced
~32 KB chunks (`_write_all`), which delivers reliably. If large documentation
files ever hang again, add an antivirus exception for local Python web
servers before debugging the tool.

## Development

```
src/system_explorer/
  app.py             parser, local HTTP server, and the system-explorer CLI
  publish.py         --publish: static view-only Viewer site
  cloud.py           hosted mode (system-explorer-cloud)
  viewer.html        the Explorer UI
  publish_viewer.html  the view-only Viewer page (--publish fills it in)
  official_check.py  OMG pilot-parser validator (python -m system_explorer.official_check)
  jamied_check.py    JamieD parser validator (python -m system_explorer.jamied_check)
tests/test_system_explorer.py
FEATURES.md          feature reference
NOTATION.md          graphical notation profile
```

Set up with `pip install -e .`. To run the current checkout without
installing, run `python -m system_explorer <folder>` from `src/`. Run the
tests with:

```
python tests/test_system_explorer.py -v
```

The tests are plain `unittest` with no dependencies. They cover the parser
(nodes, attributes, parts structure, edges, requirements/docs, validation
warnings), the HTTP API (model serving, layout and View round-trips), the
validator modules, and, when Microsoft Edge is available, end-to-end
rendering: the page is loaded headless and the DOM is checked. Hosted mode is
covered with a local bare git repo standing in for GitHub and stubbed OAuth
calls (skipped when `git` isn't on PATH). The official parser has an
end-to-end test too, but it's **opt-in** (`SYSML_OFFICIAL_CHECK_TEST=1` plus
the `sysml` conda env) because kernel startup can take 10+ minutes.

Every new feature gets, in the same change:

1. a bullet (or section) in **[FEATURES.md](FEATURES.md)**, and
2. a test in `tests/test_system_explorer.py` proving it works.

## Related tools

Other SysML v2 tools I found useful, and projects close to this one:

- JupyterLab with the OMG SysML v2 kernel (the same conda env as the
  official parser above)
- SysIDE (Sensmetry) VS Code extension
- [spec42](https://github.com/elan8/spec42)
- [PySysML2](https://github.com/DAF-Digital-Transformation-Office/PySysML2)
- [sysmod-sysmlv2-api](https://github.com/Open-MBEE/sysmod-sysmlv2-api), a
  methodology-aware (SYSMOD) API
- [sysmodeler.ai](https://sysmodeler.ai)
