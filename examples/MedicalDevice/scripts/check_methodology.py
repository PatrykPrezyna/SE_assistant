#!/usr/bin/env python3
"""Enforce SE methodology conventions on a directory of SysML sources.

Project-agnostic: pass any model folder. Rules (extend as the methodology grows):
  1. Each top-level *.sysml file declares exactly one root package whose
     name equals the file stem (PackageName.sysml -> package PackageName).

Exit codes:
  0 — all checks passed
  1 — one or more violations
  2 — usage / IO error
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# First top-level package declaration: package Name { / ; or package 'Name'
_PACKAGE_RE = re.compile(
    r"(?m)^\s*package\s+(?:'([^']+)'|([A-Za-z_][\w]*))\s*[{;]"
)

# Strip // line comments and /* */ block comments before matching.
_LINE_COMMENT_RE = re.compile(r"//.*?$", re.MULTILINE)
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


def _strip_comments(text: str) -> str:
    text = _BLOCK_COMMENT_RE.sub("", text)
    return _LINE_COMMENT_RE.sub("", text)


def root_package_name(text: str) -> str | None:
    """Return the first root package name in *text*, or None if missing."""
    m = _PACKAGE_RE.search(_strip_comments(text))
    if not m:
        return None
    return m.group(1) or m.group(2)


def iter_model_files(model_dir: Path) -> list[Path]:
    """Top-level *.sysml only (not under Spec/ or subfolders)."""
    return sorted(p for p in model_dir.glob("*.sysml") if p.is_file())


def check_package_matches_filename(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"{path.name}: cannot read file ({exc})"]

    pkg = root_package_name(text)
    stem = path.stem
    if pkg is None:
        errors.append(
            f"{path.name}: no root `package` declaration found "
            f"(expected `package {stem}`)"
        )
    elif pkg != stem:
        errors.append(
            f"{path.name}: root package `{pkg}` does not match file stem "
            f"`{stem}` (rename the file or the package so they are identical)"
        )
    return errors


def run_checks(model_dir: Path) -> list[str]:
    files = iter_model_files(model_dir)
    if not files:
        return [f"no *.sysml files found in {model_dir}"]

    errors: list[str] = []
    for path in files:
        errors.extend(check_package_matches_filename(path))
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
