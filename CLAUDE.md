# SE_assistant

Systems-engineering playground: SysML v2 models, CAD generation, and
simulations (see `examples/RoboticArm/` — 1_SystemModel, 2_CAD, Simulation).

## tools/sysml_explorer — SysML explorer

Interactive SysML v2 model explorer with manual element placement. Packaged
as a standalone pip package (`tools/sysml_explorer/pyproject.toml`, src at
`tools/sysml_explorer/src/sysml_explorer/`) so it can be installed and run
against a model in any repo, not just this one:
`pip install -e tools/sysml_explorer` then `sysml-explorer <folder>`.
Without installing: `python -m sysml_explorer <folder>` from
`tools/sysml_explorer/src`. Active development area.

**Rule: every new feature added to this tool must, in the same change:**
1. be documented in `tools/sysml_explorer/FEATURES.md` (the feature
   reference; `README.md` covers only setup/developer workflow), and
2. get a test in `tools/sysml_explorer/test_sysml_explorer.py`
   (plain unittest; parser tests, HTTP tests via `ServerFixture`,
   headless-Edge DOM tests for viewer behavior — these auto-skip without Edge).

Run the suite before reporting a feature done:

```
python tools/sysml_explorer/test_sysml_explorer.py -v
```

Gotcha: when testing the server via a background task, stopping the task can
orphan the python child still holding the port — kill python processes whose
command line matches `sysml_explorer` (module invocation or the installed
`sysml-explorer` entry point) explicitly.
