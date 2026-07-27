#!/usr/bin/env python3
"""Enforce SE methodology conventions on a directory of SysML sources.

Project-agnostic: pass any model folder. The script scans the top-level
*.sysml files and reports violations of the modeling rules below. The rules
are fully described here (this file is the single source of truth for the
methodology — there is no separate rules document).

RULE 1 — file name matches package name
    Each top-level *.sysml file declares exactly one root package whose name
    equals the file stem (PackageName.sysml -> `package PackageName`).

RULE 2 — singleton part usages are named after their definition
    If a `part def` is used exactly once in the whole model, the usage name
    must be the same as (or clearly similar to) the definition name, so
    readers immediately see they are the same thing:
        good: part ups : UPS;              (identical, just lowercase)
        good: part reservoir : FluidReservoir;   (shares the word "reservoir")
        bad:  part box : UPS;              (nothing in common)

RULE 3 — multiple part usages of one type are named by role
    If several usages share one `part def`, each usage must be named by its
    role / intention, not by numbering the type name:
        good: part inputTempSensor : Thermistor;
              part outputTempSensor : Thermistor;
        bad:  part thermistor1 : Thermistor;
              part thermistor2 : Thermistor;

Exit codes:
  0 — all checks passed
  1 — one or more violations
  2 — usage / IO error
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# ======================================================================
# SECTION 1 — Parsing helpers
#
# The model files are plain text. We do not need a full SysML parser for
# these checks: comment-stripping plus a few line-based regexes is enough.
# ======================================================================

# Strip // line comments and /* */ block comments (incl. doc bodies)
# before matching, so commented-out model text is never checked.
_LINE_COMMENT_RE = re.compile(r"//.*?$", re.MULTILINE)
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)

# Root package declaration: `package Name {` / `package Name;` / `package 'Name'`
_PACKAGE_RE = re.compile(
    r"(?m)^\s*package\s+(?:'([^']+)'|([A-Za-z_][\w]*))\s*[{;]"
)

# Part definition: `part def Name` (optionally `abstract`), e.g.
#   part def UPS {            abstract part def TemperatureSensor {
_PART_DEF_RE = re.compile(
    r"^\s*(?:abstract\s+)?part\s+def\s+(?:'([^']+)'|(\w+))"
)

# Typed part usage: `part name : Type` (optionally `ref part`), e.g.
#   part ups : UPS;           ref part coolSpine : CoolSpineDevice {
# `(?!>)` avoids matching specialization arrows (`:>`), which belong to
# definitions, not usages.
_PART_USAGE_RE = re.compile(
    r"^\s*(?:ref\s+)?part\s+(?:'([^']+)'|(\w+))\s*:\s*(?!>)"
    r"(?:'([^']+)'|([\w.:]+))"
)

# Splits an identifier into lowercase words, e.g.
#   "inputTempSensor" -> ["input", "temp", "sensor"]
#   "UPS"             -> ["ups"]
_WORD_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+")


@dataclass
class PartUsage:
    """One `part name : Type` occurrence found in a model file."""

    name: str        # usage name, e.g. "inputTempSensor"
    type_name: str   # type it is declared with, e.g. "Thermistor"
    file: Path       # file it appears in
    line: int        # 1-based line number


@dataclass
class ModelFile:
    """Everything the checks need to know about one *.sysml file."""

    path: Path
    root_package: str | None   # first root package name, None if missing
    part_defs: list[str]       # names of `part def`s declared in this file
    part_usages: list[PartUsage]


def _strip_comments(text: str) -> str:
    text = _BLOCK_COMMENT_RE.sub("", text)
    return _LINE_COMMENT_RE.sub("", text)


def name_words(identifier: str) -> list[str]:
    """Lowercase word list of a camelCase / PascalCase identifier."""
    return [w.lower() for w in _WORD_RE.findall(identifier)]


def names_similar(usage_name: str, def_name: str) -> bool:
    """Heuristic for RULE 2: is the usage name "clearly similar" to the def?

    True when the names are equal ignoring case, or when they share a word,
    or when a word of one is a >=3-letter prefix of a word of the other
    (so "microRef" counts as similar to "CustomMicroRefrigerationUnit").
    """
    if usage_name.lower() == def_name.lower():
        return True
    usage_words = name_words(usage_name)
    def_words = name_words(def_name)
    for uw in usage_words:
        for dw in def_words:
            if uw == dw:
                return True
            if len(uw) >= 3 and dw.startswith(uw):
                return True
            if len(dw) >= 3 and uw.startswith(dw):
                return True
    return False


def parse_model_file(path: Path) -> ModelFile:
    """Extract the root package, part defs, and part usages from one file.

    Works line by line on the comment-stripped text so every usage can be
    reported with its line number.
    """
    text = _strip_comments(path.read_text(encoding="utf-8"))

    m = _PACKAGE_RE.search(text)
    root_package = (m.group(1) or m.group(2)) if m else None

    part_defs: list[str] = []
    part_usages: list[PartUsage] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        def_match = _PART_DEF_RE.match(line)
        if def_match:
            part_defs.append(def_match.group(1) or def_match.group(2))
        else:
            usage_match = _PART_USAGE_RE.match(line)
            if usage_match:
                type_name = usage_match.group(3) or usage_match.group(4)
                # Qualified types like Pkg::Type — compare by last segment.
                type_name = type_name.replace("::", ".").split(".")[-1]
                part_usages.append(PartUsage(
                    name=usage_match.group(1) or usage_match.group(2),
                    type_name=type_name,
                    file=path,
                    line=lineno,
                ))

    return ModelFile(path, root_package, part_defs, part_usages)


def iter_model_files(model_dir: Path) -> list[Path]:
    """Top-level *.sysml only (not under Spec/ or subfolders)."""
    return sorted(p for p in model_dir.glob("*.sysml") if p.is_file())


# ======================================================================
# SECTION 2 — The checks (one function per rule)
#
# Each check takes the parsed model files and returns a list of
# human-readable violation messages (empty list = rule satisfied).
# ======================================================================


def check_rule1_package_matches_filename(files: list[ModelFile]) -> list[str]:
    """RULE 1: root package name must equal the file stem.

    Tested per file: PackageName.sysml must contain `package PackageName`.
    """
    errors: list[str] = []
    for mf in files:
        stem = mf.path.stem
        if mf.root_package is None:
            errors.append(
                f"{mf.path.name}: no root `package` declaration found "
                f"(expected `package {stem}`)"
            )
        elif mf.root_package != stem:
            errors.append(
                f"{mf.path.name}: root package `{mf.root_package}` does not "
                f"match file stem `{stem}` (rename the file or the package "
                f"so they are identical)"
            )
    return errors


def check_rule2_singleton_usage_named_like_def(
    files: list[ModelFile],
) -> list[str]:
    """RULE 2: a type used exactly once must have a usage name similar to it.

    Tested model-wide: count usages per `part def`; when a def has a single
    usage, its name must pass the `names_similar` heuristic
    (e.g. `part ups : UPS` — good; `part box : UPS` — flagged).
    Very short usage names (3 characters or fewer, e.g. `adc`) are treated
    as abbreviations and skipped — too short to compare meaningfully.
    """
    defined = {name for mf in files for name in mf.part_defs}
    usages_by_type: dict[str, list[PartUsage]] = {}
    for mf in files:
        for usage in mf.part_usages:
            if usage.type_name in defined:
                usages_by_type.setdefault(usage.type_name, []).append(usage)

    errors: list[str] = []
    for type_name, usages in sorted(usages_by_type.items()):
        if len(usages) != 1:
            continue  # multiple usages -> RULE 3 territory
        usage = usages[0]
        if len(usage.name) <= 3:
            continue  # abbreviation such as `adc` — accepted as-is
        if not names_similar(usage.name, type_name):
            # Suggested fix: "UPS" -> "ups", "FluidReservoir" -> "fluidReservoir"
            suggestion = (
                type_name.lower() if type_name.isupper()
                else type_name[0].lower() + type_name[1:]
            )
            errors.append(
                f"{usage.file.name}:{usage.line}: `part {usage.name} : "
                f"{type_name}` is the only usage of `{type_name}` but its "
                f"name does not resemble the definition (rename it to match, "
                f"e.g. `{suggestion}`)"
            )
    return errors


def check_rule3_multiple_usages_named_by_role(
    files: list[ModelFile],
) -> list[str]:
    """RULE 3: usages sharing one type must not be `typeName1`, `typeName2`.

    Tested model-wide: for every `part def` with two or more usages, flag any
    usage whose name is just the type name plus an optional number
    (`thermistor1` for `Thermistor` — flagged; role names such as
    `inputTempSensor` / `csfTempSensor` — good).
    """
    defined = {name for mf in files for name in mf.part_defs}
    usages_by_type: dict[str, list[PartUsage]] = {}
    for mf in files:
        for usage in mf.part_usages:
            if usage.type_name in defined:
                usages_by_type.setdefault(usage.type_name, []).append(usage)

    errors: list[str] = []
    for type_name, usages in sorted(usages_by_type.items()):
        if len(usages) < 2:
            continue  # single usage -> RULE 2 territory
        for usage in usages:
            # "thermistor1" -> base "thermistor", suffix "1"
            base = usage.name.rstrip("0123456789")
            has_number = base != usage.name
            if has_number and base.lower() == type_name.lower():
                errors.append(
                    f"{usage.file.name}:{usage.line}: `part {usage.name} : "
                    f"{type_name}` is one of {len(usages)} usages of "
                    f"`{type_name}` — name it by its role / intention "
                    f"(like `inputTempSensor`), not by numbering the type"
                )
    return errors


# ======================================================================
# SECTION 3 — Runner and command-line interface
# ======================================================================

_ALL_CHECKS = [
    check_rule1_package_matches_filename,
    check_rule2_singleton_usage_named_like_def,
    check_rule3_multiple_usages_named_by_role,
]


def run_checks(model_dir: Path) -> list[str]:
    """Parse every model file once, then run all rule checks on the result."""
    paths = iter_model_files(model_dir)
    if not paths:
        return [f"no *.sysml files found in {model_dir}"]

    files: list[ModelFile] = []
    errors: list[str] = []
    for path in paths:
        try:
            files.append(parse_model_file(path))
        except OSError as exc:
            errors.append(f"{path.name}: cannot read file ({exc})")

    for check in _ALL_CHECKS:
        errors.extend(check(files))
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check SE methodology conventions for SysML model directories."
    )
    parser.add_argument(
        "model_dir",
        nargs="?",
        default=".",
        type=Path,
        help="Directory containing top-level *.sysml files (default: .)",
    )
    args = parser.parse_args(argv)
    model_dir = args.model_dir.resolve()
    if not model_dir.is_dir():
        print(f"ERROR: not a directory: {model_dir}", file=sys.stderr)
        return 2

    errors = run_checks(model_dir)
    if errors:
        print(f"Methodology check FAILED ({len(errors)} issue(s)) in {model_dir}:")
        for err in errors:
            print(f"  - {err}")
        return 1

    n = len(iter_model_files(model_dir))
    print(f"Methodology check OK ({n} file(s)) in {model_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
