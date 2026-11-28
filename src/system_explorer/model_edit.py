"""Small structured edits that write standard SysML v2 text.

Stakeholders are `part def` elements in the context file. Use cases are
`use case def` elements with `actor` usages. See specs/0003.
"""

import re
from pathlib import Path

_UPPER = re.compile(r"^[A-Z][A-Za-z0-9]*$")
_FILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.sysml$")
_MAX_TEXT = 1_000_000


def apply_edit(folder, body):
    """Run one edit. `body` is the JSON object from the client.

    Returns a dict with `ok`. On success, `changed` lists file names,
    `files` lists `{name, before, after}` for undo, and `addedIds` /
    `showIds` are element ids the view should reveal.
    """
    if not isinstance(body, dict):
        return _err("Request body must be a JSON object.")
    action = (body.get("action") or "").strip()
    folder = Path(folder)
    if action == "add_stakeholder":
        return add_stakeholder(folder, body.get("name"), body.get("description"))
    if action == "add_use_case":
        return add_use_case(folder, body.get("name"), body.get("description"))
    if action == "link_actor":
        return link_actor(folder, body.get("stakeholder"), body.get("useCase"))
    if action == "restore_files":
        return restore_files(folder, body.get("files"))
    return _err("Unknown edit.")


def add_stakeholder(folder, name, description=""):
    folder = Path(folder)
    name = upper_camel(name)
    if not name:
        return _err("Use a name like Nurse or Notified body.")
    taken = _name_taken(folder, name)
    if taken:
        return _err(f"{name} is already in {taken.name}.")
    path = _context_path(folder)
    before = _read(path)
    package = _package_name(before, _package_ident(path.stem, "SystemContext"))
    block = _def_block("part def", name, description)
    after = _insert_member(before, package, block)
    return _commit(folder, path, before, after, f"Add stakeholder {name}",
                   [f"{package}::{name}"], [f"{package}::{name}"])


def add_use_case(folder, name, description=""):
    folder = Path(folder)
    name = upper_camel(name)
    if not name:
        return _err("Use a name like Deliver cooling.")
    taken = _name_taken(folder, name)
    if taken:
        return _err(f"{name} is already in {taken.name}.")
    path = _usecase_path(folder)
    before = _read(path)
    package = _package_name(before, _package_ident(path.stem, "UseCases"))
    block = _def_block("use case def", name, description)
    after = _insert_member(before, package, block)
    return _commit(folder, path, before, after, f"Add use case {name}",
                   [f"{package}::{name}"], [f"{package}::{name}"])


def link_actor(folder, stakeholder, use_case):
    folder = Path(folder)
    who = upper_camel(stakeholder)
    case = upper_camel(use_case)
    if not who or not case:
        return _err("Pick a stakeholder and a use case.")
    who_file = _defining_file(folder, "part def", who)
    case_file = _defining_file(folder, "use case def", case)
    if who_file is None:
        return _err(f"No stakeholder {who} yet. Add the person first.")
    if case_file is None:
        return _err(f"No use case {case} yet.")
    before = _read(case_file)
    body_span = _def_body_span(before, "use case def", case)
    if body_span is None:
        return _err(f"Could not find use case {case}.")
    body = before[body_span[0]:body_span[1]] if body_span[0] is not None else ""
    if body_span[0] is not None and re.search(
            rf"\bactor\s+\w+\s*:\s*{re.escape(who)}\b", body):
        return _err(f"{who} is already an actor of {case}.")
    role = _fresh_role(body, lower_camel(who))
    after = _insert_actor(before, case, role, who)
    who_pkg = _package_containing(who_file.read_text(encoding="utf-8"), who)
    case_pkg = _package_name(before, "")
    if who_pkg and who_pkg != case_pkg:
        after = _ensure_import(after, who_pkg)
    if after == before:
        return _err(f"Could not update use case {case}.")
    who_id = _element_id(who_file, who)
    case_id = _element_id(case_file, case)
    show = [i for i in (who_id, case_id) if i]
    return _commit(folder, case_file, before, after,
                   f"Link {who} as actor of {case}", [], show)


def restore_files(folder, files):
    """Put listed files back. An empty text deletes the file.

    Used by undo/redo. Names must be bare `*.sysml` files in the folder.
    """
    folder = Path(folder).resolve()
    if not isinstance(files, list) or not files or len(files) > 20:
        return _err("Nothing to restore.")
    planned = []
    for item in files:
        if not isinstance(item, dict):
            return _err("Invalid file.")
        name = item.get("name") or ""
        if not isinstance(name, str) or not _FILE.match(name):
            return _err("Invalid file name.")
        text = item.get("text")
        if not isinstance(text, str) or len(text) > _MAX_TEXT:
            return _err("Invalid file text.")
        path = (folder / name).resolve()
        if path.parent != folder:
            return _err("Invalid file name.")
        planned.append((path, text))
    changed = []
    written = []
    for path, text in planned:
        before = _read(path)
        if text == before:
            continue
        if text == "":
            if path.exists():
                path.unlink()
        else:
            path.write_text(text if text.endswith("\n") else text + "\n",
                            encoding="utf-8")
        changed.append(path.name)
        written.append({"name": path.name, "before": before, "after": text})
    if not changed:
        return {"ok": True, "message": "No change.", "changed": [],
                "files": [], "addedIds": [], "showIds": []}
    return {"ok": True, "message": "Restore model text", "changed": changed,
            "files": written, "addedIds": [], "showIds": []}


def upper_camel(raw):
    """'the nurse' and 'Nurse' both become a SysML definition name."""
    raw = (raw or "").strip()
    if not raw or len(raw) > 80:
        return None
    if _UPPER.match(raw) and not raw.isupper():
        return raw
    parts = re.findall(r"[A-Za-z][A-Za-z0-9]*", raw)
    if not parts:
        return None
    bits = []
    for part in parts:
        if part.isupper():
            part = part.lower()
        bits.append(part[:1].upper() + part[1:])
    name = "".join(bits)
    if not _UPPER.match(name) or len(name) > 80:
        return None
    return name


def lower_camel(name):
    if name.isupper():
        return name.lower()
    return name[:1].lower() + name[1:]


def _err(message):
    return {"ok": False, "error": message}


def _sysml_files(folder):
    return sorted((p for p in Path(folder).glob("*.sysml") if p.is_file()),
                  key=lambda p: p.name.lower())


def _read(path):
    path = Path(path)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _context_path(folder):
    hits = [p for p in _sysml_files(folder) if "context" in p.name.lower()]
    return hits[0] if hits else Path(folder) / "SystemContext.sysml"


def _usecase_path(folder):
    def match(name):
        folded = name.lower()
        return ("usecase" in folded or "use_case" in folded
                or "use-case" in folded)
    hits = [p for p in _sysml_files(folder) if match(p.name)]
    return hits[0] if hits else Path(folder) / "UseCases.sysml"


def _package_ident(stem, fallback):
    ident = re.sub(r"[^A-Za-z0-9]", "", stem or "")
    if not ident or ident[0].isdigit() or not ident[0].isalpha():
        return fallback
    return ident


def _package_name(text, fallback):
    match = re.search(r"(?m)^[ \t]*package\s+(\w+)", text or "")
    return match.group(1) if match else fallback


def _package_containing(text, name):
    """Package declaration nearest above `part def <name>`."""
    match = re.search(rf"\bpart\s+def\s+{re.escape(name)}\b", text)
    if not match:
        return _package_name(text, "")
    packages = re.findall(r"\bpackage\s+(\w+)", text[:match.start()])
    return packages[-1] if packages else ""


def _name_taken(folder, name):
    pattern = re.compile(
        rf"\b(?:part|requirement|item|action|port|actor|use\s+case|"
        rf"verification)\s+def\s+(?:<'[^']*'>\s*)?{re.escape(name)}\b")
    for path in _sysml_files(folder):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        if pattern.search(text):
            return path
    return None


def _defining_file(folder, keyword, name):
    pattern = re.compile(
        rf"\b{keyword}\s+(?:<'[^']*'>\s*)?{re.escape(name)}\b")
    for path in _sysml_files(folder):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        if pattern.search(text):
            return path
    return None


def _element_id(path, name):
    """Qualified id the explorer will assign: Package::Name for one package."""
    text = _read(path)
    package = _package_containing(text, name) or _package_name(text, "")
    if not package:
        return name
    return f"{package}::{name}"


def _clean_description(description):
    text = " ".join((description or "").split())
    text = text.replace("*/", "* /").replace("{", "(").replace("}", ")")
    return text[:500]


def _def_block(keyword, name, description):
    text = _clean_description(description)
    if not text:
        return f"    {keyword} {name};"
    return (f"    {keyword} {name} {{\n"
            f"        doc /* {text} */\n"
            f"    }}")


def _insert_member(before, package, block):
    if not before.strip():
        return f"package {package} {{\n{block}\n}}\n"
    text = before if before.endswith("\n") else before + "\n"
    lines = text.splitlines()
    index = None
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip() == "}":
            index = i
            break
    piece = "\n" + block
    if index is None:
        return text + piece + "\n"
    lines.insert(index, piece)
    return "\n".join(lines) + "\n"


def _match_brace(text, open_at):
    depth = 0
    for i in range(open_at, len(text)):
        char = text[i]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return i
    return None


def _def_body_span(text, keyword, name):
    """Return (body_start, body_end) inside the braces, or (None, None)
    when the definition is a single semicolon statement. None if missing."""
    match = re.search(rf"\b{keyword}\s+{re.escape(name)}\b", text)
    if not match:
        return None
    rest = text[match.end():]
    brace = rest.find("{")
    semi = rest.find(";")
    if semi != -1 and (brace == -1 or semi < brace):
        return (None, None)
    if brace == -1:
        return None
    open_at = match.end() + brace
    close_at = _match_brace(text, open_at)
    if close_at is None:
        return None
    return (open_at + 1, close_at)


def _fresh_role(body, base):
    used = set(re.findall(r"\b(?:actor|subject|part)\s+(\w+)", body or ""))
    if base not in used:
        return base
    n = 2
    while f"{base}{n}" in used:
        n += 1
    return f"{base}{n}"


def _insert_actor(text, use_case, role, type_name):
    match = re.search(rf"\buse\s+case\s+def\s+{re.escape(use_case)}\b", text)
    if not match:
        return text
    rest = text[match.end():]
    brace = rest.find("{")
    semi = rest.find(";")
    line = f"        actor {role} : {type_name};"
    if semi != -1 and (brace == -1 or semi < brace):
        at = match.end() + semi
        block = " {\n" + line + "\n    }"
        return text[:at] + block + text[at + 1:]
    if brace == -1:
        return text
    open_at = match.end() + brace
    close_at = _match_brace(text, open_at)
    if close_at is None:
        return text
    # Drop the indent that sat in front of the closing brace, so the new
    # actor line does not leave a blank line of spaces behind it.
    head = text[:close_at].rstrip()
    return head + "\n" + line + "\n    " + text[close_at:]


def _ensure_import(text, package):
    stmt = f"private import {package}::*;"
    if stmt in text or f"import {package}::*" in text:
        return text
    match = re.search(r"(?m)^[ \t]*package\s+\w+\s*\{", text)
    if not match:
        return stmt + "\n" + text
    return text[:match.end()] + "\n    " + stmt + text[match.end():]


def _warnings(folder):
    from .app import load_folder
    model, _paths = load_folder(Path(folder))
    if not model:
        return []
    return list(model.get("warnings") or [])


def _commit(folder, path, before, after, message, added_ids, show_ids):
    if after == before:
        return _err("No change.")
    existed = path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    before_warnings = _warnings(folder)
    path.write_text(after, encoding="utf-8")
    extra = [w for w in _warnings(folder) if w not in before_warnings]
    if extra:
        if existed:
            path.write_text(before, encoding="utf-8")
        elif path.exists():
            path.unlink()
        return _err(extra[0])
    # Re-read ids from the parser so a nested package is qualified correctly.
    added = _ids_for(folder, added_ids)
    show = _ids_for(folder, show_ids)
    return {
        "ok": True,
        "message": message,
        "changed": [path.name],
        "files": [{"name": path.name, "before": before, "after": _read(path)}],
        "addedIds": added,
        "showIds": show or added,
    }


def _ids_for(folder, guessed):
    """Swap Package::Name guesses for the ids the parser actually assigned."""
    if not guessed:
        return []
    from .app import load_folder
    model, _paths = load_folder(Path(folder))
    if not model:
        return guessed
    by_name = {}
    for node in model["nodes"]:
        by_name.setdefault(node["name"], []).append(node["id"])
    out = []
    for guess in guessed:
        name = guess.split("::")[-1]
        ids = by_name.get(name) or []
        if guess in ids:
            out.append(guess)
        elif len(ids) == 1:
            out.append(ids[0])
        elif ids:
            out.append(ids[-1])
        else:
            out.append(guess)
    return out
