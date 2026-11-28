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
    if name == "edit_activity":
        return _edit_activity(arguments, settings)
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


def activity_brief(folder):
    """A short list of activities, so the chat can name the use case it edits."""
    folder = Path(folder)
    paths = sorted(folder.glob("*.sysml"), key=lambda p: p.name)
    if not paths:
        return "(none yet)"
    try:
        from system_explorer.app import parse_models
        model = parse_models(
            [p.read_text(encoding="utf-8") for p in paths],
            [p.name for p in paths],
        )
    except (OSError, ValueError):
        return "(the model could not be read)"
    lines = []
    for act in model.get("activities") or []:
        owner = act.get("owner") or ""
        label = owner.split("::")[-1]
        lanes = []
        for lane in act.get("lanes") or []:
            who = lane.get("type") or lane.get("role")
            if who and who not in lanes:
                lanes.append(who)
        steps = [a.get("name") for a in act.get("actions") or [] if a.get("name")]
        lines.append(
            f"- {label} (owner {owner}); "
            f"lanes: {', '.join(lanes) or 'none'}; "
            f"steps: {', '.join(steps) or 'none'}"
        )
    return "\n".join(lines[:12]) if lines else "(none yet)"


def _edit_activity(arguments, settings):
    from system_explorer.activity_edit import ActivityEditError, apply_edit
    try:
        result = apply_edit(settings.model_folder, arguments)
    except ActivityEditError as exc:
        return "Not written. Ask the user this before trying again: " + str(exc)
    return result.get("message") or "Updated the activity in the SysML model."


def _report(result):
    text = result.report or ""
    if len(text) > MAX_OUTPUT:
        text = text[:MAX_OUTPUT] + "\n…(truncated)"
    return text


def _doc_body(description):
    """A SysML doc comment, or ` {}` when there is nothing to say.

    Sentences keep a single trailing period. Splitting on '. ' and then
    appending another period used to write 'anesthesiologist..'.
    """
    text = (description or "").strip()
    if not text:
        return " {}"
    sentences = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        for piece in raw.split(". "):
            piece = piece.strip().strip(".").strip()
            if piece:
                sentences.append(piece)
    if not sentences:
        return " {}"
    lines = "\n".join(f"        {sentence}." for sentence in sentences)
    return " {\n        doc /*\n" + lines + "\n        */\n    }"


def _add_model_element(arguments, settings):
    """Add a model element following existing model conventions.
    
    Stakeholders (people) should be part def in Context, not actor def.
    Use cases can reference them as actor/subject roles.
    """
    element_type = arguments.get("element_type", "").strip().lower()
    name = arguments.get("name", "").strip()
    description = arguments.get("description", "").strip()
    
    if not element_type or not name:
        return "Error: Both element_type and name are required."
    
    # Validate element type - note: "stakeholder" creates a part def for a person
    valid_types = {
        "stakeholder": "part def",  # People: Nurse, Patient, Surgeon, etc.
        "part": "part def",         # Equipment/components
        "requirement": "requirement def",
        "use_case": "use case def",
    }
    
    if element_type not in valid_types:
        return f"Error: Invalid element_type. Must be one of: {', '.join(valid_types.keys())}"
    
    # Sanitize name (must be valid SysML identifier)
    if not re.match(r'^[A-Z][A-Za-z0-9]*$', name):
        return f"Error: Name '{name}' must be UpperCamelCase (start with capital letter, no spaces or special chars)"
    
    sysml_keyword = valid_types[element_type]
    
    # Find appropriate file based on conventions
    folder = Path(settings.model_folder)
    
    # For stakeholders, use or create a Context file
    if element_type == "stakeholder":
        # Look for existing Context file
        context_files = [f for f in folder.glob("*Context.sysml")]
        if context_files:
            target_file = context_files[0]
        else:
            target_file = folder / "SystemContext.sysml"
    else:
        # For other elements, use a general file
        target_file = folder / "ModelElements.sysml"
    
    # Check if element already exists in any file
    for file in folder.glob("*.sysml"):
        try:
            content = file.read_text(encoding="utf-8")
            # Look for the definition
            if re.search(rf'\b{sysml_keyword}\s+{name}\s*[{{;]', content):
                return f"Element '{name}' already exists in {file.name}. Use a different name or modify the existing element manually."
        except (OSError, UnicodeError):
            continue
    
    # Build the SysML element with proper doc comment formatting
    doc_text = _doc_body(description)
    
    sysml_text = f"\n    {sysml_keyword} {name}{doc_text}\n"
    
    # Insert into file following conventions
    if target_file.exists():
        content = target_file.read_text(encoding="utf-8")
        # Find the package and insert before closing brace
        # Simple: insert before last } of the file
        lines = content.split("\n")
        insert_pos = len(lines) - 1
        while insert_pos > 0 and not lines[insert_pos].strip():
            insert_pos -= 1
        if lines[insert_pos].strip() == "}":
            lines.insert(insert_pos, sysml_text)
            content = "\n".join(lines)
        else:
            # Just append
            if not content.endswith("\n"):
                content += "\n"
            content += sysml_text
    else:
        # Create new file with proper package
        package_name = target_file.stem
        content = f"package {package_name} {{\n{sysml_text}}}\n"
    
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
