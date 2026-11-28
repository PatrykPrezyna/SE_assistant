"""The only commands the model may run: stakeholder check and apply, plus model element creation."""

import importlib.util
from pathlib import Path
import re

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
    if name == "add_model_element":
        return _add_model_element(arguments, settings)
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


def _add_model_element(arguments, settings):
    """Add a model element (actor, part def, requirement, etc.) to the appropriate SysML file."""
    element_type = arguments.get("element_type", "").strip().lower()
    name = arguments.get("name", "").strip()
    description = arguments.get("description", "").strip()
    package = arguments.get("package", "Context").strip()
    
    if not element_type or not name:
        return "Error: Both element_type and name are required."
    
    # Validate element type
    valid_types = {
        "actor": "actor def",
        "part": "part def",
        "requirement": "requirement def",
        "use_case": "use case def",
        "action": "action def",
    }
    
    if element_type not in valid_types:
        return f"Error: Invalid element_type. Must be one of: {', '.join(valid_types.keys())}"
    
    # Sanitize name (must be valid SysML identifier)
    if not re.match(r'^[A-Z][A-Za-z0-9]*$', name):
        return f"Error: Name '{name}' must be UpperCamelCase (start with capital letter, no spaces or special chars)"
    
    sysml_keyword = valid_types[element_type]
    
    # Find or create the appropriate .sysml file
    folder = Path(settings.model_folder)
    target_file = folder / "model_elements.sysml"
    
    # Check if element already exists
    existing_files = list(folder.glob("*.sysml"))
    for file in existing_files:
        content = file.read_text(encoding="utf-8")
        if f"{sysml_keyword} {name}" in content:
            return f"Element '{name}' already exists in {file.name}. Use a different name or modify the existing element manually."
    
    # Build the SysML element
    doc_text = f" {{\n  doc /* {description} */\n}}" if description else " {}"
    sysml_text = f"\n{sysml_keyword} {name}{doc_text}\n"
    
    # Append to file (or create if it doesn't exist)
    if target_file.exists():
        content = target_file.read_text(encoding="utf-8")
        # Try to add within existing package or at the end
        if f"package {package}" in content:
            # Insert before closing brace of package
            # Simple approach: append at end of file
            if not content.endswith("\n"):
                content += "\n"
            content += sysml_text
        else:
            # Wrap in package
            if not content.strip():
                content = f"package {package} {{\n{sysml_text}}}\n"
            else:
                if not content.endswith("\n"):
                    content += "\n"
                content += sysml_text
    else:
        content = f"package {package} {{\n{sysml_text}}}\n"
    
    target_file.write_text(content, encoding="utf-8")
    
    return f"Added {sysml_keyword} '{name}' to {target_file.name}. The model will refresh automatically."


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
