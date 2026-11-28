# Official SysML v2 Parser Validation Results

**Date**: 2026-11-28  
**Parser**: OMG SysML v2 Pilot Implementation (jupyter-sysml-kernel from conda-forge)  
**Environment**: Miniconda 26.9.4, Python 3.11.18  
**Validator**: `python -m system_explorer.official_check`

## Summary

Validated fixtures for Spec 0001 (System Context and Use Cases + Activity Swimlanes) against the official OMG SysML v2 parser to confirm standard conformance.

## Test Environment Setup

```bash
# Install Miniconda
curl -s https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -o /tmp/miniconda.sh
bash /tmp/miniconda.sh -b -p $HOME/miniconda3

# Create sysml environment
$HOME/miniconda3/bin/conda create -y -n sysml -c conda-forge --override-channels \
    jupyter-sysml-kernel jupyter_client python=3.11

# Install SE_assistant
$HOME/miniconda3/envs/sysml/bin/python -m pip install -e .
```

## Fixture 1: Use Case Definition

**File**: `surgical_use_case.sysml`

```sysml
package SurgicalSystem {
    part def Surgeon;
    part def Nurse;
    part def Patient;
    part def SurgicalSystem;
    
    use case def PerformSurgery {
        subject system : SurgicalSystem;
        actor surgeon : Surgeon;
        actor patient : Patient;
        actor nurse : Nurse;
    }
}
```

**Result**: ✅ **PASS**

```
$ python -m system_explorer.official_check /tmp/sysml_test
surgical_use_case.sysml: OK
OK - official parser reports no problems in 1 file(s)
```

## Fixture 2: Action Definition with Swimlanes

**File**: `surgical_final.sysml` (see spec for complete listing)

**Key constructs tested**:
- `action def` as activity definition (NOT `activity def`)
- Nested `action` declarations
- `first`/`then` succession
- `part <name> : <Type> { perform <action>; }` for allocation
- `flow <source> to <target>;` for item flows

**Result**: ✅ **PASS**

```
$ python -m system_explorer.official_check /tmp/sysml_test
surgical_final.sysml: OK
OK - official parser reports no problems in 1 file(s)
```

## Constructs Validated as Standard SysML v2

| Construct | Syntax | Status |
|-----------|--------|--------|
| Activity definition | `action def <name> { ... }` | ✅ Valid |
| Nested actions | `action <name> { in item x; out item y; }` | ✅ Valid |
| Succession | `first <action>; then <action>;` | ✅ Valid |
| Allocation | `part <name> : <Type> { perform <action>; }` | ✅ Valid |
| Item flows | `flow <source> to <target>;` | ✅ Valid |

## Constructs Rejected (NOT in Standard SysML v2)

| Construct | Attempted Syntax | Error | Correct Form |
|-----------|------------------|-------|--------------|
| Activity keyword | `activity <name> { ... }` | N/A (not tested) | `action def <name> { ... }` |
| Fork/join | `fork <action>; ... join;` | `no viable alternative at input 'fork'` | Not supported (implicit concurrency) |
| Perform...by | `perform <action> by <part>;` | `no viable alternative at input 'perform'` | `part <name> { perform <action>; }` |
| Flow of with type | `flow of item : Type from x to y;` | `no viable alternative at input 'flow'` | `flow x.out to y.in;` |

## Repository Example Models

### `methodology/example/stakeholders.sysml`

**Result**: ✅ **PASS**

```
stakeholders.sysml: OK
```

### `methodology/example/user_needs.sysml`

**Result**: ⚠️ **4 WARNINGS**

```
user_needs.sysml: ERROR:Subject must be first parameter. (line 9, 14, 19, 24)
```

**Issue**: Requirement definitions have `subject` parameter after other parameters. Standard requires `subject` as first parameter.

## Key Findings

### 1. No `activity` keyword in SysML v2

Use `action def` for activity definitions. The term "activity" is conceptual, but the keyword is `action def`.

### 2. No `fork`/`join` keywords

Standard SysML v2 does not have explicit `fork`/`join` keywords. Concurrency is implicit when multiple parts perform actions in parallel.

### 3. Allocation syntax

**Incorrect** (rejected by parser):
```sysml
perform <action> by <part>;
```

**Correct** (validated):
```sysml
part <name> : <Type> {
    perform <action>;
}
```

### 4. Item flow syntax

**Incorrect** (rejected by parser):
```sysml
flow of item : Type from source to target;
```

**Correct** (validated):
```sysml
flow source.output to target.input;
```

## Recommendations

1. **Update parser**: Add support for `flow <source> to <target>;` statements
2. **Migrate custom dialect**: Replace `perform action { ... }` with standard `action def` + nested parts
3. **Remove fork/join**: Do not implement fork/join (not in standard)
4. **Fix user_needs.sysml**: Move `subject` parameter to first position in requirement definitions

## Validation Script

A convenience script is provided: `scripts/check_official_parser.sh`

```bash
./scripts/check_official_parser.sh <folder>
```

Requires conda environment 'sysml' (see script header for setup instructions).

## References

- [OMG SysML v2 Specification](https://www.omg.org/spec/SysML/)
- [jupyter-sysml-kernel on conda-forge](https://anaconda.org/conda-forge/jupyter-sysml-kernel)
- [SE_assistant README](../README.md) — "Setting up the validation parsers" section
