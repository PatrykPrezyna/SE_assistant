"""The only commands the model may run: stakeholder check and apply."""

import importlib.util
from pathlib import Path

from .config import repo_root

_STAKEHOLDER = None
MAX_OUTPUT = 8000


def stakeholder_module():
    global _STAKEHOLDER
    if _STAKEHOLDER is None:
        path = repo_root() / "methodology" / "stakeholder_analysis.py"
        spec = importlib.util.spec_from_file_location("stakeholder_analysis", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _STAKEHOLDER = module
    return _STAKEHOLDER


def run_tool(name, arguments, settings):
    """Run one allowed tool. Any other name is rejected and nothing is written."""
    arguments = arguments or {}
    if not isinstance(arguments, dict):
        return "Rejected: tool arguments must be an object."
    if name == "stakeholder_check":
        return _report(stakeholder_module().execute(
            "check", settings.model_folder, settings.methodology
        ))
    if name == "stakeholder_apply":
        if arguments:
            refusal = _write_register(arguments, settings)
            if refusal:
                return refusal
        return _report(stakeholder_module().execute(
            "apply", settings.model_folder, settings.methodology
        ))
    return f"Rejected unknown tool '{name}'."


def _write_register(arguments, settings):
    """Validate and write process/stakeholders.yaml. Return an error string, or ''."""
    module = stakeholder_module()
    register = {
        "system": arguments.get("system") or "SystemOfInterest",
        "stakeholders": _clean_stakeholders(arguments.get("stakeholders")),
    }
    try:
        errors = module.validate_register(register, settings.methodology)
    except module.MethodologyError as exc:
        return f"Register was not written.\n{exc}"
    if errors:
        return "Register was not written.\n" + "\n".join(f"- {error}" for error in errors)
    text = (
        "# Written by the SE assistant after the team confirmed the list.\n"
        + module.dump_yaml(register)
    )
    path = Path(settings.model_folder) / "process" / "stakeholders.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return ""


def _clean_stakeholders(raw):
    if not isinstance(raw, list):
        return raw
    people = []
    for item in raw:
        if not isinstance(item, dict):
            people.append(item)
            continue
        category = item.get("category")
        if isinstance(category, str):
            category = (
                category.strip().lower()
                .replace(" ", "").replace("-", "").replace("_", "")
            )
            if category in ("internalstakeholder", "internal"):
                category = "internal"
            elif category == "regulatory":
                category = "regulatory"
            elif category == "customer":
                category = "customer"
        person = {
            "name": item.get("name"),
            "category": category,
            "needs": item.get("needs") or [],
        }
        description = item.get("description")
        if isinstance(description, str) and description.strip():
            person["description"] = description.strip()
        people.append(person)
    return people


def _report(result):
    text = result.report or ""
    if len(text) > MAX_OUTPUT:
        text = text[:MAX_OUTPUT] + "\n…(truncated)"
    return text


def folder_context(folder, limit=12000):
    """Names of files the team may have shared, plus the text of small text files.

    PDFs are listed and not parsed. Nothing outside `folder` is read.
    """
    folder = folder.resolve()
    lines = []
    used = 0
    text_suffixes = {".md", ".txt", ".csv"}
    skip_names = {".env", ".git"}
    for path in sorted(folder.rglob("*")):
        if not path.is_file():
            continue
        try:
            relative = path.resolve().relative_to(folder)
        except ValueError:
            continue
        if any(part in skip_names or part == "__pycache__" for part in relative.parts):
            continue
        if path.suffix.lower() == ".pdf":
            lines.append(f"{relative.as_posix()} (PDF, not read)")
            continue
        if path.suffix.lower() not in text_suffixes:
            lines.append(relative.as_posix())
            continue
        if used >= limit:
            lines.append(f"{relative.as_posix()} (not included; context is full)")
            continue
        try:
            body = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            lines.append(f"{relative.as_posix()} (not read)")
            continue
        chunk = body[: min(4000, limit - used)]
        used += len(chunk)
        lines.append(f"{relative.as_posix()}:\n{chunk}")
    return "\n".join(lines) if lines else "(no extra files)"
