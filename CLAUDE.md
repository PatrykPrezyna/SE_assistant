# SE_assistant

The **System Explorer** (`system-explorer`) Python package: an interactive
SysML v2 model explorer (manual element placement, curated Views) plus
model validation. This repo contains only the tool. Models live in their own repos and use it after
`pip install`; the reference example is the CoolSpine model,
https://github.com/PatrykPrezyna/cool-spine-model.

Layout: `pyproject.toml` at the root; the package is in
`src/system_explorer/` (`app.py` = parser + local server + CLI, `cloud.py` =
hosted mode, `viewer.html` = the whole UI, `official_check.py` /
`jamied_check.py` = external-parser validators run with `python -m`); tests
are in `tests/test_system_explorer.py`. Dev install: `pip install -e .`, then
`system-explorer <folder>`. Without installing: `python -m system_explorer
<folder>` from `src/`.

**Rule: every new feature added to this tool must, in the same change:**
1. be documented in `FEATURES.md` (the feature reference; `README.md`
   covers setup, hosting and developer workflow), and
2. get a test in `tests/test_system_explorer.py`
   (plain unittest; parser tests, HTTP tests via `ServerFixture`,
   headless-Edge DOM tests for viewer behavior — these auto-skip without Edge).

Run the suite before reporting a feature done:

```
python tests/test_system_explorer.py -v
```

Gotchas:

- When testing the server via a background task, stopping the task can
  orphan the python child still holding the port — kill python processes
  whose command line matches `system_explorer` (module invocation or the
  installed `system-explorer` entry point) explicitly.
- The user often runs an explorer from an editable install of this
  checkout. While it runs, renaming directories under `src/` can fail with
  "Permission denied" (move files individually), and moving package files
  breaks that server's page reload until it is restarted.
- If *every* DOM test fails with an empty page, headless Edge cannot run in
  the current environment (e.g. a sandboxed agent shell). That is not a
  viewer bug; run the suite in a normal terminal.
