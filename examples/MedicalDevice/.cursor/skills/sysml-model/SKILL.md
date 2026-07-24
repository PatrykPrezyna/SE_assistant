---
name: sysml-model
description: >-
  Extends or edits the CoolSpine SysML v2 model (requirements, system parts,
  context, satisfy links) while keeping packages consistent. Use when modeling
  CoolSpine, adding parts/ports/requirements, importing from datasheets, or
  when the user invokes /sysml-model.
---

# SysML model workflow

## Before editing

1. Read the relevant `*.sysml` files in this folder (req / system / context).
2. Identify which package owns the change; avoid duplicating defs across files.
3. If the user cites a datasheet, look under `Spec/` first.

## Edit rules

- Spec-compliant SysML v2 textual notation only.
- **Package name = file stem** (`PackageName.sysml` ↔ `package PackageName`). See `.cursor/rules/methodology.mdc`.
- Requirements: `requirement <'REQ-…'> Name : BaseReq { doc /* … */; … }`
  (usage with short name — `satisfy` targets usages, not `requirement def`s).
- Implementations: `satisfy 'REQ-…';` (quoted short name).
- Cross-package: `private import OtherPackage::*;`
- Device-only structure stays in `CoolSpineSystem`; clinical actors stay in `CoolSpineSystemContext`.

## After editing

1. Update all cross-references affected by renames.
2. Run `/validate-sysml` (methodology script + grammar parser). Report any methodology violations to the user.
3. If structure changed, ask whether `views/` / `layout.json` (sysml-explorer) should be updated — those files are outside the SysML source of truth.
4. Summarize: files touched, elements added/changed, open questions.
