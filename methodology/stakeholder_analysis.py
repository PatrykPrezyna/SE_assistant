"""Stakeholder analysis: check a register and write the SysML it implies.

The activity is defined in product-development.yaml (steps, categories,
exit rules, output paths). The team fills in process/stakeholders.yaml in
a model folder. This script does not invent stakeholders. It checks the
register against the exit rules and, on `apply`, writes a standard SysML v2
model plus process/state.yaml.

    python methodology/stakeholder_analysis.py check <model-folder>
    python methodology/stakeholder_analysis.py apply <model-folder>

Exit codes: 0 when every exit rule is met, 2 when the activity is still
open, 1 when the register or the methodology file is malformed.
"""

import argparse
import re
import sys
from pathlib import Path

ACTIVITY_ID = "stakeholder-analysis"
DEFAULT_METHODOLOGY = Path(__file__).resolve().parent / "product-development.yaml"
SYSTEM_DEFAULT = "SystemOfInterest"

BASE_DEF = "Stakeholder"
CONTEXT_DEF = "OperationalContext"
NEED_DEF = "UserNeed"

IDENT = re.compile(r"^[A-Z][A-Za-z0-9]*$")
NEED_ID = re.compile(r"^[A-Za-z][A-Za-z0-9-]*$")
KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
EXIT_IDS = ("has-stakeholder", "each-has-need", "each-categorized")

GENERATED_NOTE = (
    "Generated from process/stakeholders.yaml by stakeholder_analysis.py. "
    "Edit the register and run the tool again. Hand edits are overwritten."
)


class YamlError(Exception):
    def __init__(self, message, line=None):
        self.line = line
        prefix = f"line {line}: " if line else ""
        super().__init__(prefix + message)


class MethodologyError(Exception):
    pass


class Result:
    def __init__(self, code, report, files):
        self.code = code
        self.report = report
        self.files = files  # list of (relative Path, text) to write on apply


def load_yaml(text):
    """Load the small YAML subset these methodology files use.

    Block mappings and lists, comments, plain scalars, single- and
    double-quoted strings, `[]`, `{}`, booleans, and integers. No anchors,
    no multiline `|` / `>` blocks, and no non-empty flow collections.
    """
    lines = _tokenize(text)
    if not lines:
        return None
    value, index = _parse_block(lines, 0)
    if index != len(lines):
        raise YamlError("unexpected content", lines[index][0])
    return value


def load_yaml_file(path):
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise YamlError(f"cannot read {path}: {exc}") from exc
    try:
        return load_yaml(text)
    except YamlError as exc:
        raise YamlError(f"{path}: {exc}", exc.line) from exc


def dump_yaml(value):
    """Serialize the structures this tool writes (state files)."""
    return "\n".join(_dump_lines(value, 0)) + "\n"


def _tokenize(text):
    lines = []
    for number, raw in enumerate(text.splitlines(), 1):
        if "\t" in raw:
            raise YamlError("tabs are not allowed; indent with spaces", number)
        stripped = _strip_comment(raw).rstrip()
        if not stripped.strip():
            continue
        indent = len(stripped) - len(stripped.lstrip(" "))
        lines.append((number, indent, stripped.strip()))
    return lines


def _strip_comment(line):
    out = []
    quote = None
    i = 0
    while i < len(line):
        char = line[i]
        if quote:
            out.append(char)
            if quote == "'" and char == "'" and i + 1 < len(line) and line[i + 1] == "'":
                out.append(line[i + 1])
                i += 2
                continue
            if char == quote:
                quote = None
            i += 1
            continue
        if char in ("'", '"'):
            quote = char
            out.append(char)
            i += 1
            continue
        if char == "#":
            break
        out.append(char)
        i += 1
    return "".join(out)


def _parse_block(lines, index):
    text = lines[index][2]
    indent = lines[index][1]
    if text.startswith("- ") or text == "-":
        return _parse_list(lines, index, indent)
    return _parse_map(lines, index, indent)


def _parse_list(lines, index, dash_indent):
    items = []
    total = len(lines)
    while (
        index < total
        and lines[index][1] == dash_indent
        and (lines[index][2].startswith("- ") or lines[index][2] == "-")
    ):
        line_no, _, text = lines[index]
        rest = text[2:].strip() if text.startswith("- ") else ""
        index += 1
        key_indent = dash_indent + 2
        if rest == "":
            if index >= total or lines[index][1] <= dash_indent:
                items.append(None)
            else:
                item, index = _parse_block(lines, index)
                items.append(item)
            continue
        if _is_key_line(rest):
            mapping = {}
            index = _fill_map(
                lines, index, key_indent, mapping, pending=(line_no, rest)
            )
            items.append(mapping)
        else:
            items.append(_parse_scalar(rest, line_no))
    return items, index


def _parse_map(lines, index, key_indent):
    if lines[index][1] != key_indent:
        raise YamlError(
            f"expected indent {key_indent} and found {lines[index][1]}",
            lines[index][0],
        )
    mapping = {}
    index = _fill_map(lines, index, key_indent, mapping, pending=None)
    return mapping, index


def _fill_map(lines, index, key_indent, mapping, pending):
    total = len(lines)
    while True:
        if pending is not None:
            line_no, text = pending
            pending = None
        else:
            if index >= total or lines[index][1] != key_indent:
                break
            if lines[index][2].startswith("- ") or lines[index][2] == "-":
                break
            line_no, _, text = lines[index]
            index += 1
        key, raw_value, has_value = _split_key(text, line_no)
        if key in mapping:
            raise YamlError(f"duplicate key '{key}'", line_no)
        if not has_value:
            if index < total and lines[index][1] > key_indent:
                child, index = _parse_block(lines, index)
                mapping[key] = child
            else:
                mapping[key] = None
        else:
            mapping[key] = _parse_scalar(raw_value, line_no)
    return index


def _is_key_line(text):
    try:
        _split_key(text, 0)
    except YamlError:
        return False
    return True


def _split_key(text, line_no):
    quote = None
    for i, char in enumerate(text):
        if quote:
            if char == quote:
                quote = None
            continue
        if char in ("'", '"'):
            quote = char
            continue
        if char == ":":
            key = text[:i].strip()
            rest = text[i + 1 :]
            if not KEY.fullmatch(key):
                raise YamlError(f"invalid key '{key}'", line_no)
            if rest.strip() == "":
                return key, "", False
            return key, rest.strip(), True
    raise YamlError(f"expected 'key:' and found '{text}'", line_no)


def _parse_scalar(text, line_no):
    if text == "[]":
        return []
    if text == "{}":
        return {}
    if text == "true":
        return True
    if text == "false":
        return False
    if text in ("null", "~"):
        return None
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if len(text) >= 2 and text[0] == text[-1] == '"':
        return _unescape(text[1:-1], line_no)
    if len(text) >= 2 and text[0] == text[-1] == "'":
        return text[1:-1].replace("''", "'")
    if text[:1] in ("'", '"', "[", "{", ">", "|", "&", "*", "!", "%", "@"):
        raise YamlError(f"unsupported scalar '{text}'", line_no)
    return text


def _unescape(text, line_no):
    out = []
    i = 0
    while i < len(text):
        char = text[i]
        if char != "\\":
            out.append(char)
            i += 1
            continue
        if i + 1 >= len(text):
            raise YamlError("dangling escape in a double-quoted string", line_no)
        nxt = text[i + 1]
        if nxt == "n":
            out.append("\n")
        elif nxt == "t":
            out.append("\t")
        elif nxt in ('\\', '"'):
            out.append(nxt)
        else:
            raise YamlError(f"unknown escape '\\{nxt}'", line_no)
        i += 2
    return "".join(out)


def _dump_lines(value, indent):
    pad = " " * indent
    if isinstance(value, dict):
        lines = []
        for key, item in value.items():
            if not KEY.fullmatch(str(key)):
                raise YamlError(f"cannot write key '{key}'")
            if isinstance(item, (dict, list)) and item:
                lines.append(f"{pad}{key}:")
                lines.extend(_dump_lines(item, indent + 2))
            elif item == []:
                lines.append(f"{pad}{key}: []")
            elif item == {}:
                lines.append(f"{pad}{key}: {{}}")
            else:
                lines.append(f"{pad}{key}: {_dump_scalar(item)}")
        return lines
    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, dict) and item:
                pairs = list(item.items())
                first_key, first_value = pairs[0]
                rest = pairs[1:]
                if isinstance(first_value, (dict, list)) and first_value:
                    lines.append(f"{pad}- {first_key}:")
                    lines.extend(_dump_lines(first_value, indent + 4))
                elif first_value == []:
                    lines.append(f"{pad}- {first_key}: []")
                else:
                    lines.append(f"{pad}- {first_key}: {_dump_scalar(first_value)}")
                for key, child in rest:
                    child_pad = " " * (indent + 2)
                    if isinstance(child, (dict, list)) and child:
                        lines.append(f"{child_pad}{key}:")
                        lines.extend(_dump_lines(child, indent + 4))
                    elif child == []:
                        lines.append(f"{child_pad}{key}: []")
                    else:
                        lines.append(f"{child_pad}{key}: {_dump_scalar(child)}")
            elif isinstance(item, list):
                raise YamlError("cannot write a list nested directly in a list")
            else:
                lines.append(f"{pad}- {_dump_scalar(item)}")
        return lines
    raise YamlError(f"cannot write a {type(value).__name__} at the root")


def _dump_scalar(value):
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if not isinstance(value, str):
        raise YamlError(f"cannot write a {type(value).__name__}")
    if value == "" or _needs_quotes(value):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _needs_quotes(value):
    if value in ("true", "false", "null", "~") or re.fullmatch(r"-?\d+", value):
        return True
    if value[:1] in ("'", '"', "[", "{", ">", "|", "&", "*", "!", "%", "@", "-", "?"):
        return True
    if value != value.strip() or "\n" in value or "#" in value or ":" in value:
        return True
    return False


def load_methodology(path):
    data = load_yaml_file(path)
    if not isinstance(data, dict):
        raise MethodologyError(f"{path}: the methodology file must be a mapping")
    methodology_id = data.get("id")
    if not isinstance(methodology_id, str) or not methodology_id:
        raise MethodologyError(f"{path}: missing methodology id")
    activities = data.get("activities")
    if not isinstance(activities, list):
        raise MethodologyError(f"{path}: activities must be a list")
    matches = [item for item in activities if isinstance(item, dict) and item.get("id") == ACTIVITY_ID]
    if len(matches) != 1:
        raise MethodologyError(
            f"{path}: expected exactly one activity '{ACTIVITY_ID}'"
        )
    activity = matches[0]
    _require_activity(activity, path)
    return methodology_id, activity


def _require_activity(activity, path):
    method = activity.get("method")
    if not isinstance(method, dict):
        raise MethodologyError(f"{path}: {ACTIVITY_ID} is missing method")
    steps = method.get("steps")
    if not isinstance(steps, list) or not steps:
        raise MethodologyError(f"{path}: {ACTIVITY_ID} needs at least one method step")
    for step in steps:
        if not isinstance(step, dict) or not isinstance(step.get("text"), str):
            raise MethodologyError(f"{path}: each method step needs a text")
    categories = method.get("categories")
    if not isinstance(categories, list) or not categories:
        raise MethodologyError(f"{path}: {ACTIVITY_ID} needs categories")
    seen = set()
    for category in categories:
        if not isinstance(category, dict):
            raise MethodologyError(f"{path}: a category must be a mapping")
        cid = category.get("id")
        sysml = category.get("sysml")
        label = category.get("label")
        if not isinstance(cid, str) or not cid:
            raise MethodologyError(f"{path}: a category is missing id")
        if cid in seen:
            raise MethodologyError(f"{path}: duplicate category '{cid}'")
        seen.add(cid)
        if not isinstance(label, str) or not label:
            raise MethodologyError(f"{path}: category '{cid}' is missing label")
        if not isinstance(sysml, str) or not IDENT.fullmatch(sysml):
            raise MethodologyError(
                f"{path}: category '{cid}' sysml name must be UpperCamelCase"
            )
        doc = category.get("doc", "")
        if not isinstance(doc, str):
            raise MethodologyError(f"{path}: category '{cid}' doc must be a string")
        _reject_doc(doc, f"category '{cid}' doc")
    exit_rules = method.get("exit")
    if not isinstance(exit_rules, list):
        raise MethodologyError(f"{path}: {ACTIVITY_ID} method.exit must be a list")
    found = []
    for rule in exit_rules:
        if not isinstance(rule, dict) or not isinstance(rule.get("id"), str):
            raise MethodologyError(f"{path}: each exit rule needs an id")
        if not isinstance(rule.get("text"), str):
            raise MethodologyError(f"{path}: exit rule '{rule.get('id')}' needs text")
        if rule["id"] not in EXIT_IDS:
            raise MethodologyError(
                f"{path}: this tool does not check exit rule '{rule['id']}'"
            )
        found.append(rule["id"])
    missing = [rule_id for rule_id in EXIT_IDS if rule_id not in found]
    if missing:
        raise MethodologyError(
            f"{path}: {ACTIVITY_ID} is missing exit rules: {', '.join(missing)}"
        )
    register = activity.get("register")
    outputs = activity.get("outputs")
    if not isinstance(register, str) or not register:
        raise MethodologyError(f"{path}: {ACTIVITY_ID} is missing register")
    if not isinstance(outputs, dict):
        raise MethodologyError(f"{path}: {ACTIVITY_ID} outputs must be a mapping")
    for key in ("stakeholders", "needs", "state"):
        if not isinstance(outputs.get(key), str) or not outputs[key]:
            raise MethodologyError(f"{path}: outputs.{key} must be a relative path")
    for label, relative in (("register", register), *outputs.items()):
        _relative_path(relative, label)


def _relative_path(relative, label):
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or path.parts == ():
        raise MethodologyError(f"{label} must stay inside the model folder: {relative}")
    return path


def _reject_doc(text, where):
    if "/*" in text or "*/" in text:
        raise MethodologyError(f"{where} cannot contain a comment delimiter")


def validate_register(register, methodology_path=None):
    """Return error strings for a register mapping. Empty means it can be applied."""
    if not isinstance(register, dict):
        return ["the register must be a mapping"]
    _methodology_id, activity = load_methodology(
        methodology_path or DEFAULT_METHODOLOGY
    )
    errors, _people, _system = _read_register(activity, register)
    return errors


def execute(command, model_folder, methodology_path=None):
    """Run `check` or `apply`. `apply` writes Result.files; `check` does not."""
    if command not in ("check", "apply"):
        raise MethodologyError(f"unknown command '{command}'")
    methodology_path = Path(methodology_path or DEFAULT_METHODOLOGY)
    model_folder = Path(model_folder)
    try:
        if not model_folder.is_dir():
            return Result(1, f"model folder does not exist: {model_folder}\n", [])
        methodology_id, activity = load_methodology(methodology_path)
        result = _analyse(model_folder, methodology_id, activity, command)
    except (YamlError, MethodologyError) as exc:
        return Result(1, f"{exc}\n", [])
    if command == "apply":
        for relative, text in result.files:
            _write(model_folder / relative, text)
    return result


def _analyse(model_folder, methodology_id, activity, command):
    register_rel = _relative_path(activity["register"], "register")
    register_path = model_folder / register_rel
    if not register_path.is_file():
        return _missing_register(methodology_id, activity, register_rel, command)
    try:
        register = load_yaml_file(register_path)
    except YamlError as exc:
        return Result(1, f"{exc}\nModel files were not changed.\n", [])
    errors, people, system = _read_register(activity, register)
    if errors:
        lines = [f"{activity['name']} was not applied.", "", "The register has errors:"]
        lines.extend(f"  - {error}" for error in errors)
        lines.append("")
        lines.append("Model files were not changed.")
        return Result(1, "\n".join(lines) + "\n", [])
    rules = _exit_rules(activity, people)
    status = "done" if all(rule["met"] for rule in rules) else "open"
    files = []
    wrote_model = False
    if people:
        outputs = activity["outputs"]
        files.append(
            (_relative_path(outputs["stakeholders"], "outputs.stakeholders"),
             _stakeholders_sysml(activity, people, system))
        )
        files.append(
            (_relative_path(outputs["needs"], "outputs.needs"),
             _needs_sysml(people))
        )
        wrote_model = True
    state = _state(methodology_id, activity, status, system, people, rules, wrote_model)
    files.append((_relative_path(activity["outputs"]["state"], "outputs.state"), _state_text(state)))
    report = _report(activity, status, people, rules, files, command)
    code = 0 if status == "done" else 2
    return Result(code, report, files)


def _missing_register(methodology_id, activity, register_rel, command):
    rules = []
    for rule in activity["method"]["exit"]:
        if rule["id"] == "has-stakeholder":
            detail = ["The register file is missing."]
        else:
            detail = ["Waiting for a stakeholder list."]
        rules.append({
            "id": rule["id"],
            "met": False,
            "text": rule["text"],
            "detail": detail,
        })
    state = _state(methodology_id, activity, "open", None, [], rules, False)
    files = [
        (register_rel, _register_template(activity)),
        (_relative_path(activity["outputs"]["state"], "outputs.state"), _state_text(state)),
    ]
    report = _report(activity, "open", [], rules, files, command, missing=True)
    return Result(2, report, files)


def _register_template(activity):
    categories = ", ".join(item["id"] for item in activity["method"]["categories"])
    return (
        f"# Stakeholder register for {activity['name']}.\n"
        "# Edit this file, then run:\n"
        "#   python methodology/stakeholder_analysis.py apply <model-folder>\n"
        "#\n"
        f"# category is one of: {categories}\n"
        "# name, and each need's name, are UpperCamelCase (Surgeon, SetTargetTemperature).\n"
        "# Each stakeholder needs at least one user need before this activity is done.\n"
        "\n"
        f"system: {SYSTEM_DEFAULT}\n"
        "stakeholders: []\n"
    )


def _read_register(activity, register):
    errors = []
    if not isinstance(register, dict):
        return ["the register must be a mapping"], [], None
    categories = {item["id"]: item for item in activity["method"]["categories"]}
    reserved = {BASE_DEF, CONTEXT_DEF, NEED_DEF}
    reserved.update(item["sysml"] for item in categories.values())
    system = register.get("system", SYSTEM_DEFAULT)
    if not isinstance(system, str) or not IDENT.fullmatch(system):
        errors.append(
            f"system must be an UpperCamelCase name, got {system!r}"
        )
        system = None
    elif system in reserved:
        errors.append(f"system name '{system}' is used by the generated model")
        system = None
    raw_people = register.get("stakeholders", [])
    if raw_people is None:
        raw_people = []
    if not isinstance(raw_people, list):
        errors.append("stakeholders must be a list")
        return errors, [], system
    people = []
    seen_names = set()
    seen_need_ids = set()
    seen_need_names = set()
    listed = ", ".join(categories)
    for index, raw in enumerate(raw_people):
        where = f"stakeholders[{index}]"
        if not isinstance(raw, dict):
            errors.append(f"{where} must be a mapping")
            continue
        name = raw.get("name")
        if not isinstance(name, str) or not IDENT.fullmatch(name):
            errors.append(
                f"{where}.name must be UpperCamelCase, got {name!r}"
            )
            continue
        where = name
        if name in seen_names:
            errors.append(f"duplicate stakeholder '{name}'")
            continue
        if name in reserved or name == system:
            errors.append(f"stakeholder name '{name}' is used by the generated model")
            continue
        seen_names.add(name)
        description = raw.get("description", "")
        if description is None:
            description = ""
        if not isinstance(description, str):
            errors.append(f"{name}.description must be a string")
            description = ""
        else:
            try:
                _reject_doc(description, f"{name}.description")
            except MethodologyError as exc:
                errors.append(str(exc))
        category_id = raw.get("category")
        category = None
        if category_id in (None, ""):
            category_id = None
        elif not isinstance(category_id, str) or category_id not in categories:
            errors.append(
                f"{name}.category {category_id!r} is not one of {listed}"
            )
            category_id = None
        else:
            category = categories[category_id]
        needs, need_errors = _read_needs(
            name, raw.get("needs", []), seen_need_ids, seen_need_names
        )
        errors.extend(need_errors)
        people.append({
            "name": name,
            "description": description.strip(),
            "category_id": category_id,
            "category": category,
            "needs": needs,
        })
    for person in people:
        for need in person["needs"]:
            if need["name"] in seen_names or need["name"] == system or need["name"] in reserved:
                errors.append(
                    f"{person['name']} need '{need['name']}' collides with another element name"
                )
    if errors:
        return errors, [], system
    return [], people, system


def _read_needs(owner, raw_needs, seen_ids, seen_names):
    if raw_needs is None:
        raw_needs = []
    if not isinstance(raw_needs, list):
        return [], [f"{owner}.needs must be a list"]
    needs = []
    errors = []
    for index, raw in enumerate(raw_needs):
        where = f"{owner}.needs[{index}]"
        if not isinstance(raw, dict):
            errors.append(f"{where} must be a mapping")
            continue
        need_id = raw.get("id")
        name = raw.get("name")
        text = raw.get("text")
        if not isinstance(need_id, str) or not NEED_ID.fullmatch(need_id):
            errors.append(f"{where}.id must be a short name such as NEED-1, got {need_id!r}")
            continue
        if not isinstance(name, str) or not IDENT.fullmatch(name):
            errors.append(f"{where}.name must be UpperCamelCase, got {name!r}")
            continue
        if not isinstance(text, str) or not text.strip():
            errors.append(f"{where}.text must be a non-empty string")
            continue
        try:
            _reject_doc(text, f"{where}.text")
        except MethodologyError as exc:
            errors.append(str(exc))
            continue
        if need_id in seen_ids:
            errors.append(f"duplicate need id '{need_id}'")
            continue
        if name in seen_names:
            errors.append(f"duplicate need name '{name}'")
            continue
        seen_ids.add(need_id)
        seen_names.add(name)
        needs.append({"id": need_id, "name": name, "text": " ".join(text.split())})
    return needs, errors


def _exit_rules(activity, people):
    by_id = {rule["id"]: rule["text"] for rule in activity["method"]["exit"]}
    uncategorized = [person["name"] for person in people if person["category_id"] is None]
    without_needs = [person["name"] for person in people if not person["needs"]]
    checks = {
        "has-stakeholder": (
            bool(people),
            [] if people else ["The register has no stakeholders."],
        ),
        "each-has-need": (
            bool(people) and not without_needs,
            [f"{name} has no user need." for name in without_needs]
            or ([] if people else ["There are no stakeholders to check."]),
        ),
        "each-categorized": (
            bool(people) and not uncategorized,
            [f"{name} has no category." for name in uncategorized]
            or ([] if people else ["There are no stakeholders to check."]),
        ),
    }
    rules = []
    for rule in activity["method"]["exit"]:
        met, detail = checks[rule["id"]]
        item = {"id": rule["id"], "met": met, "text": by_id[rule["id"]]}
        if not met:
            item["detail"] = detail
        rules.append(item)
    return rules


def _role(name):
    return name[0].lower() + name[1:]


def _stakeholders_sysml(activity, people, system):
    lines = [
        f"// {GENERATED_NOTE}",
        "package Stakeholders {",
        f"    abstract part def {BASE_DEF} {{",
        "        doc /* A role with a stake in the system of interest. */",
        "    }",
        "",
    ]
    for category in activity["method"]["categories"]:
        doc = category.get("doc") or category["label"]
        lines.append(f"    abstract part def {category['sysml']} :> {BASE_DEF} {{")
        lines.append(f"        doc /* {doc} */")
        lines.append("    }")
        lines.append("")
    for person in people:
        if person["category"] is None:
            super_name = BASE_DEF
            category_label = "not set"
        else:
            super_name = person["category"]["sysml"]
            category_label = person["category"]["label"]
        doc = person["description"]
        category_sentence = f"Category: {category_label}."
        body = f"{doc} {category_sentence}".strip() if doc else category_sentence
        lines.append(f"    part def {person['name']} :> {super_name} {{")
        lines.append(f"        doc /* {body} */")
        lines.append("    }")
        lines.append("")
    lines.append(f"    part def {system} {{")
    lines.append("        doc /* System of interest named in the stakeholder register. Later activities add its structure. */")
    lines.append("    }")
    lines.append("")
    lines.append(f"    part def {CONTEXT_DEF} {{")
    lines.append("        doc /* The system of interest and the stakeholders around it. */")
    lines.append(f"        part {_role(system)} : {system};")
    for person in people:
        lines.append(f"        part {_role(person['name'])} : {person['name']};")
    lines.append("    }")
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def _needs_sysml(people):
    lines = [
        f"// {GENERATED_NOTE}",
        "package UserNeeds {",
        "    private import Stakeholders::*;",
        "",
        f"    requirement def {NEED_DEF} {{",
        "        doc /* A need stated by one stakeholder, before it is turned into a system requirement. */",
        "    }",
        "",
    ]
    for person in people:
        if person["category"] is None:
            label = "not set"
        else:
            label = person["category"]["label"]
        role = _role(person["name"])
        for need in person["needs"]:
            body = f"{need['text']} Stakeholder: {person['name']} ({label})."
            lines.append(
                f"    requirement <'{need['id']}'> {need['name']} : {NEED_DEF} {{"
            )
            lines.append(f"        doc /* {body} */")
            lines.append(f"        stakeholder {role} : {person['name']};")
            lines.append("    }")
            lines.append("")
    if lines[-1] == "":
        lines.pop()
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def _state(methodology_id, activity, status, system, people, rules, wrote_model):
    state = {
        "methodology": methodology_id,
        "activity": activity["id"],
        "status": status,
        "register": activity["register"],
    }
    if system:
        state["system"] = system
    if wrote_model:
        state["outputs"] = [
            activity["outputs"]["stakeholders"],
            activity["outputs"]["needs"],
        ]
    if people:
        state["stakeholders"] = [
            {
                "name": person["name"],
                "category": person["category_id"] if person["category_id"] else "unset",
                "needs": [need["id"] for need in person["needs"]],
            }
            for person in people
        ]
    state["exit"] = rules
    return state


def _state_text(state):
    return (
        "# Written by stakeholder_analysis.py. "
        "Re-run the tool after editing the register.\n"
        + dump_yaml(state)
    )


def _report(activity, status, people, rules, files, command, missing=False):
    lines = [f"{activity['name']} is {status}.", ""]
    summary = activity.get("summary")
    if isinstance(summary, str) and summary:
        lines.append(summary)
        lines.append("")
    lines.append("Method:")
    for number, step in enumerate(activity["method"]["steps"], 1):
        lines.append(f"  {number}. {step['text']}")
    lines.append("")
    if people:
        lines.append(f"Stakeholders: {len(people)}")
        for person in people:
            category = person["category_id"] or "unset"
            count = len(person["needs"])
            noun = "need" if count == 1 else "needs"
            lines.append(f"  {person['name']} — {category} — {count} {noun}")
        lines.append("")
    elif missing:
        lines.append("Register: missing.")
        lines.append("")
    lines.append("Exit:")
    for rule in rules:
        mark = "met" if rule["met"] else "open"
        lines.append(f"  [{mark}] {rule['text']}")
        for detail in rule.get("detail", []):
            lines.append(f"         {detail}")
    lines.append("")
    if files:
        written = ", ".join(relative.as_posix() for relative, _text in files)
        if command == "apply":
            lines.append(f"Wrote {written}.")
        else:
            lines.append(f"apply would write {written}.")
    lines.append(f"Status: {status}")
    return "\n".join(lines) + "\n"


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        if not text.endswith("\n"):
            handle.write("\n")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Check or apply the stakeholder-analysis activity."
    )
    parser.add_argument("command", choices=("check", "apply"))
    parser.add_argument("model_folder", type=Path)
    parser.add_argument(
        "--methodology",
        type=Path,
        default=None,
        help="activities file (default: product-development.yaml beside this script)",
    )
    args = parser.parse_args(argv)
    result = execute(args.command, args.model_folder, args.methodology)
    sys.stdout.write(result.report)
    return result.code


if __name__ == "__main__":
    sys.exit(main())
