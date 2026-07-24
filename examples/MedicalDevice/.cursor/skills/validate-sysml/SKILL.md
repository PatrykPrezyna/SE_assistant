---
name: validate-sysml
description: >-
  Validates SysML v2 model files: project-agnostic SE methodology check
  (scripts/check_methodology.py) plus the OMG pilot parser (preferred) or
  JamieD sysml-v2-support MCP/CLI fallback. Use after SysML edits, before
  finishing modeling work, or when the user invokes /validate-sysml.
---

# Validate SysML

Run **both** layers. Do not skip methodology because the grammar parser passed.

## 1. Methodology (always, first)

`scripts/check_methodology.py` is model-agnostic. Point it at the directory that
holds the top-level `*.sysml` files (this example folder when working here):

```bash
python scripts/check_methodology.py .
```

- Exit code must be 0.
- On failure: list every violation to the user, then fix (rename package/file)
  or ask how they want to resolve it. Do not finish with open methodology failures.

Current rules in the script include: root package name equals file stem.

## 2. Syntax — preferred: OMG pilot (conda env `sysml`)

```bash
conda run -n sysml python -c "import jupyter_client, sys; print(sys.executable)"
```

If that succeeds, run the printed python **directly** on `official_check.py` for this folder (path depends on whether this example still lives under SE_assistant). Do not kill long startups.

## 3. Syntax — fallback: JamieD

1. If MCP server `sysml-v2-jamied` is available, call `validate` with each file's contents.
2. Else, from SE_assistant root: `python tools/validate_sysml_jamied.py examples/MedicalDevice`

## Report

- Methodology: pass/fail + each violation
- Grammar: exit/tool status + each `ERROR:` / `WARNING:`
- Fix issues before declaring the task done
