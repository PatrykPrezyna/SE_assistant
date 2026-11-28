"""Write a use-case activity as standard SysML v2.

The diagram and the chat both call `apply_edit`. The text uses `perform`
inside the actor who does each step, `first`/`then` for order, `decide` /
`merge` / `fork` / `join` for the control nodes, and `flow` for an item
handed from one step to the next. See specs/0002-activity-diagram.md.
"""

import re
from pathlib import Path

from .app import parse_models


class ActivityEditError(Exception):
    """The edit cannot be applied. The message is safe to show to the user."""


_IDENT = re.compile(r"[A-Za-z_]\w*")
_BARE_OK = frozenset({"start", "done"})
_QUOTE_WORDS = frozenset("""
    action actor attribute decide else end first flow fork if import in item
    join merge out package part perform subject then use
""".split())


def apply_edit(folder, command):
    """Apply one activity command to the model folder. Returns a result dict."""
    folder = Path(folder)
    if not isinstance(command, dict):
        raise ActivityEditError("The edit was not understood.")
    op = (command.get("op") or "").strip()
    if op == "add-activity":
        return _add_activity(folder, command)
    owner = _resolve_owner(folder, command.get("owner"))
    text, path = _read_owner_file(folder, owner)
    behavior = _behavior_for(folder, owner)
    _mutate(behavior, command, op)
    if owner.get("nested"):
        text = _rewrite_nested(text, owner, behavior)
    else:
        text = _rewrite_definition(text, owner, behavior)
    text, extras = _ensure_part_defs(folder, path, text, behavior, command)
    path.write_text(text, encoding="utf-8", newline="\n")
    written = [path, *extras]
    return {
        "ok": True,
        "owner": owner["id"],
        "file": path.name,
        "files": [p.name for p in written],
        "message": _message(op, command, owner),
    }


def _mutate(behavior, command, op):
    if op == "add-lane":
        _add_lane(behavior, _need(command, "name", "Who is the new stakeholder?"))
    elif op == "add-action":
        _add_action(behavior, command)
    elif op == "connect":
        _connect(behavior, command)
    elif op == "add-decision":
        _add_decision(behavior, command)
    elif op == "add-fork":
        _add_fork(behavior, command)
    elif op == "add-merge":
        _add_merge(behavior, command)
    elif op == "add-join":
        _add_join(behavior, command)
    elif op == "add-flow":
        _add_flow(behavior, command)
    elif op == "rename":
        _rename(behavior, command)
    elif op == "delete":
        _delete(behavior, command)
    elif op == "add-subactivity":
        _add_subactivity(behavior, command)
    else:
        raise ActivityEditError(
            f"Unknown edit '{op}'. Ask what should change on the diagram."
        )


def _need(command, key, question):
    value = command.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ActivityEditError(question)
    return value.strip().strip("'")


def _message(op, command, owner):
    name = command.get("name") or command.get("yes") or ""
    if op == "add-action" and name:
        return f"Added '{name}' to the activity in the SysML model."
    if op == "add-decision":
        return "Added a decision to the activity in the SysML model."
    if op == "add-fork":
        return "Added a fork and a join to the activity in the SysML model."
    if op == "add-lane":
        return f"Added the {name} lane to the activity in the SysML model."
    if op == "add-subactivity":
        return f"Added sub-activity '{name}' to the SysML model."
    return f"Updated the activity in the SysML model ({owner['name']})."


# ---------------------------------------------------------------- resolve


def _load(folder):
    paths = sorted(Path(folder).glob("*.sysml"), key=lambda p: p.name)
    if not paths:
        return {"nodes": [], "edges": [], "activities": [], "warnings": []}, []
    texts = [p.read_text(encoding="utf-8") for p in paths]
    return parse_models(texts, [p.name for p in paths]), paths


def _resolve_owner(folder, owner):
    owner = (owner or "").strip()
    if not owner:
        raise ActivityEditError("Which use case should this change? Ask the user.")
    model, _paths = _load(folder)
    if "::sub::" in owner:
        parent_id, _, action = owner.partition("::sub::")
        parent = next((n for n in model["nodes"] if n["id"] == parent_id), None)
        if parent is None:
            raise ActivityEditError(
                "That sub-activity's use case is not in the model. Ask which one."
            )
        return {
            "id": owner, "name": action, "kind": "action",
            "nested": True, "parent": parent,
        }
    for node in model["nodes"]:
        if node["id"] == owner and node["kind"] in ("use case def", "action def"):
            return node
    matches = [
        n for n in model["nodes"]
        if n["name"] == owner and n["kind"] in ("use case def", "action def")
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ActivityEditError(
            f"More than one '{owner}'. Ask which use case."
        )
    raise ActivityEditError(
        f"There is no use case named '{owner}'. "
        "Ask which activity, or whether to create one."
    )


def _behavior_for(folder, owner):
    if owner.get("nested"):
        model, _paths = _load(folder)
        found = next(
            (a for a in model["activities"] if a["owner"] == owner["id"]), None
        )
        if found:
            return _copy_behavior(found)
        return _empty_behavior(owner["name"])
    model, _paths = _load(folder)
    acts = [a for a in model["activities"] if a["owner"] == owner["id"]]
    standard = [a for a in acts if a.get("name") == owner["name"]]
    chosen = (standard or acts or [None])[0]
    if chosen is None:
        behavior = _empty_behavior(owner["name"])
        for edge in model["edges"]:
            if edge["kind"] != "association" or edge["from"] != owner["id"]:
                continue
            type_name = edge["to"].split("::")[-1]
            behavior["lanes"].append({
                "role": edge.get("label") or _role_for(type_name, []),
                "type": type_name, "action": "",
            })
        return behavior
    return _copy_behavior(chosen)


def _copy_behavior(activity):
    return {
        "name": activity.get("name") or "",
        "actions": [
            {"name": a["name"], "doc": a.get("doc"), "sub": a.get("sub")}
            for a in activity.get("actions") or []
        ],
        "decisions": list(activity.get("decisions") or []),
        "forks": list(activity.get("forks") or []),
        "joins": list(activity.get("joins") or []),
        "merges": list(activity.get("merges") or []),
        "edges": [
            {"from": e["from"], "to": e["to"], "label": e.get("label") or ""}
            for e in activity.get("edges") or []
        ],
        "flows": [
            {"from": f["from"], "to": f["to"], "item": f.get("item") or "payload"}
            for f in activity.get("flows") or []
        ],
        "lanes": [
            {"role": l["role"], "type": l.get("type") or "", "action": l.get("action") or ""}
            for l in activity.get("lanes") or []
        ],
    }


def _empty_behavior(name):
    return {
        "name": name, "actions": [], "decisions": [], "forks": [],
        "joins": [], "merges": [],
        "edges": [{"from": "start", "to": "done", "label": ""}],
        "flows": [], "lanes": [],
    }


# ---------------------------------------------------------------- mutations


def _names(behavior):
    used = {a["name"] for a in behavior["actions"]}
    for key in ("decisions", "forks", "joins", "merges"):
        used.update(behavior[key])
    used.update(("start", "done"))
    return used


def _fresh(behavior, kind):
    used = _names(behavior)
    n = 1
    while f"{kind}{n}" in used:
        n += 1
    behavior[{"decide": "decisions", "merge": "merges",
              "fork": "forks", "join": "joins"}[kind]].append(f"{kind}{n}")
    return f"{kind}{n}"


def _role_for(type_name, lanes):
    base = re.sub(r"[^A-Za-z0-9_]", "", type_name)
    if not base:
        base = "actor"
    role = base[0].lower() + base[1:]
    taken = {lane["role"] for lane in lanes}
    if role not in taken:
        return role
    n = 2
    while f"{role}{n}" in taken:
        n += 1
    return f"{role}{n}"


def _find_lane(behavior, who):
    who_l = (who or "").strip().lower()
    if not who_l:
        return None
    for lane in behavior["lanes"]:
        if lane["role"].lower() == who_l or (lane.get("type") or "").lower() == who_l:
            return lane
    return None


def _add_lane(behavior, name):
    if _find_lane(behavior, name):
        return
    role = _role_for(name, behavior["lanes"])
    behavior["lanes"].append({"role": role, "type": name, "action": ""})
    behavior.setdefault("newTypes", []).append(name)


def _lane_of(behavior, action):
    for lane in behavior["lanes"]:
        if lane.get("action") == action and lane.get("type"):
            return lane["type"]
    return ""


def _ensure_action(behavior, name, lane_name):
    if not any(a["name"] == name for a in behavior["actions"]):
        behavior["actions"].append({"name": name, "doc": None, "sub": None})
    if not lane_name:
        return
    if not _find_lane(behavior, lane_name):
        _add_lane(behavior, lane_name)
    lane = _find_lane(behavior, lane_name)
    if not any(l["role"] == lane["role"] and l.get("action") == name
               for l in behavior["lanes"]):
        behavior["lanes"].append({
            "role": lane["role"], "type": lane.get("type") or "", "action": name,
        })


def _successors(behavior, source):
    return [
        e for e in behavior["edges"]
        if e["from"] == source and not e.get("label")
    ]


def _drop_edges_from(behavior, source, unguarded_only=True):
    behavior["edges"] = [
        e for e in behavior["edges"]
        if not (e["from"] == source and (not unguarded_only or not e.get("label")))
    ]


def _add_action(behavior, command):
    name = _need(command, "name", "What should the step be called?")
    lane = command.get("lane") or command.get("who") or ""
    if isinstance(lane, str):
        lane = lane.strip()
    if not lane:
        raise ActivityEditError(
            f"Who does '{name}'? Ask which stakeholder's lane it belongs in."
        )
    _ensure_action(behavior, name, lane)
    after = (command.get("after") or "").strip()
    if not after:
        return
    if not _known(behavior, after):
        raise ActivityEditError(
            f"There is no step '{after}' to place this after. Ask where it goes."
        )
    succs = _successors(behavior, after)
    splice = bool(command.get("splice"))
    if splice and len(succs) == 1 and succs[0]["to"] != name:
        nxt = succs[0]["to"]
        _drop_edges_from(behavior, after)
        behavior["edges"].append({"from": after, "to": name, "label": ""})
        behavior["edges"].append({"from": name, "to": nxt, "label": ""})
        return
    if (after == "start" and len(behavior["actions"]) == 1
            and any(e["from"] == "start" and e["to"] == "done"
                    for e in behavior["edges"])):
        behavior["edges"] = [
            e for e in behavior["edges"]
            if not (e["from"] == "start" and e["to"] == "done")
        ]
        behavior["edges"].append({"from": "start", "to": name, "label": ""})
        behavior["edges"].append({"from": name, "to": "done", "label": ""})
        return
    if not any(e["from"] == after and e["to"] == name for e in behavior["edges"]):
        behavior["edges"].append({"from": after, "to": name, "label": ""})


def _known(behavior, name):
    if name in ("start", "done"):
        return True
    if any(a["name"] == name for a in behavior["actions"]):
        return True
    for key in ("decisions", "forks", "joins", "merges"):
        if name in behavior[key]:
            return True
    return False


def _connect(behavior, command):
    source = _need(command, "source", "Which step does the arrow leave?")
    target = _need(command, "target", "Which step does the arrow go to?")
    if not _known(behavior, source) or not _known(behavior, target):
        raise ActivityEditError(
            "One of those steps is not on the diagram. Ask which steps to connect."
        )
    if not any(e["from"] == source and e["to"] == target and not e.get("label")
               for e in behavior["edges"]):
        behavior["edges"].append({"from": source, "to": target, "label": ""})


def _add_decision(behavior, command):
    after = _need(command, "after", "Which step does the decision follow?")
    guard = _need(command, "guard", "What is the condition on the yes path?")
    yes = _need(command, "yes", "What happens when the condition is true?")
    no = _need(command, "no", "What happens otherwise?")
    if not _known(behavior, after):
        raise ActivityEditError(
            f"There is no step '{after}'. Ask which step the decision follows."
        )
    yes_lane = command.get("yesLane") or command.get("lane") or _lane_of(behavior, after)
    no_lane = command.get("noLane") or command.get("lane") or _lane_of(behavior, after)
    if not yes_lane or not no_lane:
        raise ActivityEditError(
            "Who does each outcome? Ask which lane the two steps belong in."
        )
    _ensure_action(behavior, yes, yes_lane)
    _ensure_action(behavior, no, no_lane)
    decide = _fresh(behavior, "decide")
    merge = _fresh(behavior, "merge")
    # What used to follow `after` should follow the merge, so both outcomes
    # rejoin. If that next step is itself an outcome, follow whatever came
    # after the outcome instead.
    continuation = []
    for edge in _successors(behavior, after):
        if edge["to"] in (yes, no):
            continuation.extend(e["to"] for e in _successors(behavior, edge["to"]))
            _drop_edges_from(behavior, edge["to"])
        else:
            continuation.append(edge["to"])
    _drop_edges_from(behavior, after)
    behavior["edges"].append({"from": after, "to": decide, "label": ""})
    behavior["edges"].append({"from": decide, "to": yes, "label": guard})
    behavior["edges"].append({"from": decide, "to": no, "label": "no"})
    behavior["edges"].append({"from": yes, "to": merge, "label": ""})
    behavior["edges"].append({"from": no, "to": merge, "label": ""})
    for target in continuation:
        if target not in (yes, no, decide, merge):
            behavior["edges"].append({"from": merge, "to": target, "label": ""})


def _branch_list(command):
    raw = command.get("branches")
    if not isinstance(raw, list) or len(raw) < 2:
        raise ActivityEditError(
            "A fork needs at least two parallel steps, each with a name and a lane. "
            "Ask for the ones that are missing."
        )
    branches = []
    for item in raw:
        if isinstance(item, str):
            branches.append({"name": item.strip(), "lane": ""})
        elif isinstance(item, dict):
            branches.append({
                "name": (item.get("name") or "").strip(),
                "lane": (item.get("lane") or item.get("who") or "").strip(),
            })
        else:
            raise ActivityEditError("Each parallel step needs a name. Ask for it.")
    if any(not b["name"] for b in branches):
        raise ActivityEditError("Each parallel step needs a name. Ask for it.")
    if any(not b["lane"] for b in branches):
        raise ActivityEditError(
            "Who does each parallel step? Ask which lane each one is in."
        )
    return branches


def _add_fork(behavior, command):
    after = _need(command, "after", "Which step does the fork follow?")
    if not _known(behavior, after):
        raise ActivityEditError(
            f"There is no step '{after}'. Ask which step splits into parallel work."
        )
    branches = _branch_list(command)
    fork = _fresh(behavior, "fork")
    join = _fresh(behavior, "join")
    names = {b["name"] for b in branches}
    succs = _successors(behavior, after)
    _drop_edges_from(behavior, after)
    behavior["edges"].append({"from": after, "to": fork, "label": ""})
    for branch in branches:
        _ensure_action(behavior, branch["name"], branch["lane"])
        behavior["edges"].append({"from": fork, "to": branch["name"], "label": ""})
        if not _successors(behavior, branch["name"]):
            behavior["edges"].append(
                {"from": branch["name"], "to": join, "label": ""}
            )
    for edge in succs:
        if edge["to"] not in names:
            behavior["edges"].append({"from": join, "to": edge["to"], "label": ""})
    if not any(e["from"] == join for e in behavior["edges"]):
        behavior["edges"].append({"from": join, "to": "done", "label": ""})


def _add_merge(behavior, command):
    sources = command.get("sources") or command.get("after")
    if isinstance(sources, str):
        sources = [s.strip() for s in sources.split(",") if s.strip()]
    if not isinstance(sources, list) or len(sources) < 2:
        raise ActivityEditError(
            "A merge needs the steps that come back together. Ask which ones."
        )
    merge = _fresh(behavior, "merge")
    for source in sources:
        if not _known(behavior, source):
            raise ActivityEditError(f"There is no step '{source}'.")
        behavior["edges"].append({"from": source, "to": merge, "label": ""})
    then = (command.get("then") or "").strip()
    if then:
        behavior["edges"].append({"from": merge, "to": then, "label": ""})


def _add_join(behavior, command):
    command = dict(command)
    command["op"] = "add-fork"
    # A join on its own is the same bar as the end of a fork. Callers that
    # already have the parallel steps use add-fork. This op joins named sources.
    sources = command.get("sources") or []
    if isinstance(sources, str):
        sources = [s.strip() for s in sources.split(",") if s.strip()]
    if len(sources) < 2:
        raise ActivityEditError(
            "A join needs the parallel steps that must all finish. Ask which ones."
        )
    join = _fresh(behavior, "join")
    for source in sources:
        if not _known(behavior, source):
            raise ActivityEditError(f"There is no step '{source}'.")
        behavior["edges"] = [
            e for e in behavior["edges"]
            if not (e["from"] == source and not e.get("label"))
        ]
        behavior["edges"].append({"from": source, "to": join, "label": ""})
    then = (command.get("then") or "done").strip()
    behavior["edges"].append({"from": join, "to": then, "label": ""})


def _add_flow(behavior, command):
    source = _need(command, "source", "Which step hands something on?")
    target = _need(command, "target", "Which step receives it?")
    if not any(a["name"] == source for a in behavior["actions"]):
        raise ActivityEditError(f"There is no step '{source}'.")
    if not any(a["name"] == target for a in behavior["actions"]):
        raise ActivityEditError(f"There is no step '{target}'.")
    item = (command.get("item") or "payload").strip() or "payload"
    if not any(f["from"] == source and f["to"] == target for f in behavior["flows"]):
        behavior["flows"].append({"from": source, "to": target, "item": item})


def _rename(behavior, command):
    old = _need(command, "name", "Which step should be renamed?")
    new = _need(command, "newName", "What is the new name?")
    if not any(a["name"] == old for a in behavior["actions"]):
        raise ActivityEditError(f"There is no step '{old}' to rename.")
    for action in behavior["actions"]:
        if action["name"] == old:
            action["name"] = new
    for edge in behavior["edges"]:
        if edge["from"] == old:
            edge["from"] = new
        if edge["to"] == old:
            edge["to"] = new
    for flow in behavior["flows"]:
        if flow["from"] == old:
            flow["from"] = new
        if flow["to"] == old:
            flow["to"] = new
    for lane in behavior["lanes"]:
        if lane.get("action") == old:
            lane["action"] = new


def _delete(behavior, command):
    name = _need(command, "name", "Which step should be deleted?")
    incoming = [e for e in behavior["edges"] if e["to"] == name and not e.get("label")]
    outgoing = [e for e in behavior["edges"] if e["from"] == name and not e.get("label")]
    behavior["actions"] = [a for a in behavior["actions"] if a["name"] != name]
    behavior["lanes"] = [l for l in behavior["lanes"] if l.get("action") != name]
    for key in ("decisions", "forks", "joins", "merges"):
        behavior[key] = [n for n in behavior[key] if n != name]
    behavior["edges"] = [
        e for e in behavior["edges"] if e["from"] != name and e["to"] != name
    ]
    behavior["flows"] = [
        f for f in behavior["flows"] if f["from"] != name and f["to"] != name
    ]
    if len(incoming) == 1 and len(outgoing) == 1:
        src, dst = incoming[0]["from"], outgoing[0]["to"]
        if not any(e["from"] == src and e["to"] == dst for e in behavior["edges"]):
            behavior["edges"].append({"from": src, "to": dst, "label": ""})


def _add_subactivity(behavior, command):
    name = _need(command, "name", "What should the sub-activity be called?")
    lane = (command.get("lane") or command.get("who") or "").strip()
    if not lane:
        raise ActivityEditError(
            f"Who performs '{name}'? Ask which lane the sub-activity sits in."
        )
    _ensure_action(behavior, name, lane)
    for action in behavior["actions"]:
        if action["name"] == name:
            action["sub"] = name
    after = (command.get("after") or "").strip()
    if after and _known(behavior, after):
        command = {"name": name, "lane": lane, "after": after, "splice": True}
        # The action already exists; add_action will only connect.
        _add_action(behavior, command)


# ---------------------------------------------------------------- render


def q(name):
    """A SysML name, quoted when it has spaces or would be read as a keyword."""
    if name in _BARE_OK:
        return name
    if _IDENT.fullmatch(name or "") and name not in _QUOTE_WORDS:
        return name
    return "'" + (name or "").replace("'", "") + "'"


def _render_behavior(behavior, indent="    "):
    lines = []
    outgoing, incoming = {}, {}
    for flow in behavior["flows"]:
        item = flow.get("item") or "payload"
        outgoing[flow["from"]] = item
        incoming[flow["to"]] = item
    sub_actions = {a["name"] for a in behavior["actions"] if a.get("sub")}
    for action in behavior["actions"]:
        name = action["name"]
        pins = []
        if name in outgoing:
            pins.append(f"{indent}    out item {q(outgoing[name])};")
        if name in incoming:
            pins.append(f"{indent}    in item {q(incoming[name])};")
        if name in sub_actions:
            lines.append(f"{indent}action {q(name)} {{")
            lines.append(f"{indent}    first start then done;")
            lines.append(f"{indent}}}")
            continue
        if pins:
            lines.append(f"{indent}action {q(name)} {{")
            lines.extend(pins)
            lines.append(f"{indent}}}")
        else:
            lines.append(f"{indent}action {q(name)};")
    for kind, key in (("fork", "forks"), ("join", "joins"),
                      ("decide", "decisions"), ("merge", "merges")):
        for cname in behavior[key]:
            if cname == kind:
                lines.append(f"{indent}{kind};")
            else:
                lines.append(f"{indent}{kind} {q(cname)};")
    guards = []
    for edge in behavior["edges"]:
        label = edge.get("label") or ""
        if (_IDENT.fullmatch(label) and label not in ("no", "else")
                and label not in guards):
            guards.append(label)
    for guard in guards:
        lines.append(f"{indent}attribute {q(guard)} : Boolean;")
    lines.extend(_succession_lines(behavior, indent))
    for flow in behavior["flows"]:
        item = q(flow.get("item") or "payload")
        lines.append(
            f"{indent}flow {q(flow['from'])}.{item} to {q(flow['to'])}.{item};"
        )
    return lines


def _succession_lines(behavior, indent):
    guarded = {}
    for edge in behavior["edges"]:
        if edge.get("label"):
            guarded.setdefault(edge["from"], []).append(edge)
    lines = []
    emitted = set()
    for edge in behavior["edges"]:
        if edge.get("label"):
            continue
        lines.append(
            f"{indent}first {q(edge['from'])} then {q(edge['to'])};"
        )
        if edge["to"] in guarded and edge["to"] not in emitted:
            lines.extend(_guard_lines(guarded[edge["to"]], indent))
            emitted.add(edge["to"])
    for source, outs in guarded.items():
        if source not in emitted:
            lines.extend(_guard_lines(outs, indent))
    return lines


def _guard_lines(outs, indent):
    lines = []
    for index, edge in enumerate(outs):
        label = edge.get("label") or ""
        if label in ("no", "else") and index == len(outs) - 1:
            lines.append(f"{indent}else {q(edge['to'])};")
        else:
            lines.append(f"{indent}if {label} then {q(edge['to'])};")
    return lines


def _actor_blocks(behavior, indent="    "):
    order, actions, types = [], {}, {}
    for lane in behavior["lanes"]:
        role = lane["role"]
        if role not in actions:
            order.append(role)
            actions[role] = []
            types[role] = lane.get("type") or ""
        if lane.get("action") and lane["action"] not in actions[role]:
            actions[role].append(lane["action"])
    blocks = []
    for role in order:
        typed = f" : {q(types[role])}" if types[role] else ""
        performs = actions[role]
        if not performs:
            blocks.append(f"{indent}actor {q(role)}{typed};")
            continue
        lines = [f"{indent}actor {q(role)}{typed} {{"]
        for action in performs:
            lines.append(f"{indent}    perform {q(action)};")
        lines.append(f"{indent}}}")
        blocks.append("\n".join(lines))
    return blocks


# ---------------------------------------------------------------- splice


def _scan_statements(body):
    items = []
    i = 0
    start = 0
    depth = 0
    in_line = in_block = in_str = False
    while i < len(body):
        c = body[i]
        nxt = body[i + 1] if i + 1 < len(body) else ""
        if in_line:
            if c == "\n":
                in_line = False
            i += 1
            continue
        if in_block:
            if c == "*" and nxt == "/":
                in_block = False
                i += 2
                # `doc /* ... */` is a statement even without a semicolon.
                if depth == 0 and body[start:i].lstrip().startswith("doc"):
                    items.append(body[start:i])
                    start = i
            else:
                i += 1
            continue
        if in_str:
            if c == "\\" and i + 1 < len(body):
                i += 2
                continue
            if c == "'":
                in_str = False
            i += 1
            continue
        if c == "/" and nxt == "/":
            in_line = True
            i += 2
            continue
        if c == "/" and nxt == "*":
            in_block = True
            i += 2
            continue
        if c == "'":
            in_str = True
            i += 1
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth = max(0, depth - 1)
            if depth == 0:
                items.append(body[start:i + 1])
                i += 1
                start = i
                continue
        elif c == ";" and depth == 0:
            items.append(body[start:i + 1])
            i += 1
            start = i
            continue
        i += 1
    tail = body[start:]
    if tail.strip():
        items.append(tail)
    return items


def _header_of(statement):
    head = statement.split("{", 1)[0]
    head = re.sub(r"/\*.*?\*/", " ", head, flags=re.S)
    head = re.sub(r"//[^\n]*", " ", head)
    return re.sub(r"\s+", " ", head).strip().rstrip(";").strip()


def _is_dropped(header):
    from .app import _is_behavior_header
    if _is_behavior_header(header):
        return True
    if header.startswith("perform action "):
        return True
    return False


_ACTOR_HEAD = re.compile(
    r"^(actor|subject|part)\s+(?:'([^']*)'|([A-Za-z_]\w*))"
    r"(?:\s*:\s*(?:'([^']*)'|([A-Za-z_]\w*)))?"
)


def _rewrite_definition(text, owner, behavior):
    kind = "use case def" if owner["kind"] == "use case def" else "action def"
    span = _find_definition(text, kind, owner["name"])
    rendered = _render_behavior(behavior, "        ")
    actors = _actor_blocks(behavior, "        ")
    if span is None:
        block = _fresh_block(kind, owner["name"], actors, rendered)
        return _insert_in_package(text, block)
    start, open_brace, end = span
    if open_brace is None:
        block = _fresh_block(kind, owner["name"], actors, rendered)
        return text[:start] + block.rstrip() + text[end:]
    body = text[open_brace + 1:end - 1]
    kept = []
    seen_roles = set()
    for statement in _scan_statements(body):
        header = _header_of(statement)
        if not header or _is_dropped(header):
            continue
        if re.match(r"^attribute\s+\w+\s*:\s*Boolean$", header):
            continue
        actor = _ACTOR_HEAD.match(header)
        if actor and actor.group(1) in ("actor", "part"):
            role = actor.group(2) or actor.group(3)
            if any(lane["role"] == role for lane in behavior["lanes"]):
                seen_roles.add(role)
                continue
        kept.append(statement.strip())
    # Actors the behavior still wants are rendered fresh, so drop nothing
    # else. Subject lines and docs stay in `kept`.
    pieces = []
    if kept:
        pieces.append("\n    ".join(kept))
    pieces.extend(actors)
    pieces.extend(rendered)
    inner = "\n    ".join(p for p in pieces if p) 
    # `pieces` already carry their own indent when they are multi-line.
    body_text = "\n".join(p for p in pieces if p)
    if body_text and not body_text.endswith("\n"):
        body_text += "\n"
    return text[:open_brace + 1] + "\n" + body_text + "    " + text[end - 1:]


def _fresh_block(kind, name, actors, rendered):
    lines = [f"    {kind} {q(name)} {{"]
    lines.extend(actors)
    lines.extend(rendered)
    lines.append("    }")
    return "\n".join(lines) + "\n"


def _rewrite_nested(text, owner, behavior):
    parent = owner["parent"]
    kind = "use case def" if parent["kind"] == "use case def" else "action def"
    span = _find_definition(text, kind, parent["name"])
    if span is None or span[1] is None:
        raise ActivityEditError(
            "The sub-activity's parent is not in the file that was edited."
        )
    _start, open_brace, end = span
    body = text[open_brace + 1:end - 1]
    action_span = _find_definition(body, "action", owner["name"])
    rendered = _render_behavior(behavior, "        ")
    actors = _actor_blocks(behavior, "        ")
    inner_lines = actors + rendered
    block = "    action " + q(owner["name"]) + " {\n" + "\n".join(inner_lines)
    if inner_lines:
        block += "\n"
    block += "    }"
    if action_span is None:
        new_body = body.rstrip() + "\n" + block + "\n"
    else:
        a_start, _a_open, a_end = action_span
        new_body = body[:a_start] + block + body[a_end:]
    return text[:open_brace + 1] + new_body + text[end - 1:]


def _find_definition(text, kind, name):
    """(start, open_brace or None, end) of `kind name`, or None."""
    pattern = re.compile(
        rf"\b{kind}\s+(?:'{re.escape(name)}'|{re.escape(name)})\b"
    )
    match = pattern.search(text)
    if not match:
        return None
    i = match.end()
    while i < len(text) and text[i] in " \t\r\n":
        i += 1
    if i < len(text) and text[i] == ";":
        return match.start(), None, i + 1
    if i >= len(text) or text[i] != "{":
        return None
    depth = 0
    in_line = in_block = in_str = False
    j = i
    while j < len(text):
        c = text[j]
        nxt = text[j + 1] if j + 1 < len(text) else ""
        if in_line:
            if c == "\n":
                in_line = False
            j += 1
            continue
        if in_block:
            if c == "*" and nxt == "/":
                in_block = False
                j += 2
            else:
                j += 1
            continue
        if in_str:
            if c == "'":
                in_str = False
            j += 1
            continue
        if c == "/" and nxt == "/":
            in_line = True
            j += 2
            continue
        if c == "/" and nxt == "*":
            in_block = True
            j += 2
            continue
        if c == "'":
            in_str = True
            j += 1
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return match.start(), i, j + 1
        j += 1
    return None


def _insert_in_package(text, block):
    match = re.search(r"\bpackage\s+(?:'[^']+'|\w+)\s*\{", text)
    if not match:
        if text.strip():
            return text.rstrip() + "\n" + block
        return "package Model {\n" + block + "}\n"
    # Insert before the package's closing brace.
    span_end = _matching_brace(text, match.end() - 1)
    if span_end is None:
        return text.rstrip() + "\n" + block
    return text[:span_end] + "\n" + block + text[span_end:]


def _matching_brace(text, open_index):
    depth = 0
    in_line = in_block = in_str = False
    j = open_index
    while j < len(text):
        c = text[j]
        nxt = text[j + 1] if j + 1 < len(text) else ""
        if in_line:
            if c == "\n":
                in_line = False
            j += 1
            continue
        if in_block:
            if c == "*" and nxt == "/":
                in_block = False
                j += 2
            else:
                j += 1
            continue
        if in_str:
            if c == "'":
                in_str = False
            j += 1
            continue
        if c == "/" and nxt == "/":
            in_line = True
            j += 2
            continue
        if c == "/" and nxt == "*":
            in_block = True
            j += 2
            continue
        if c == "'":
            in_str = True
            j += 1
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return j
        j += 1
    return None


def _read_owner_file(folder, owner):
    target = owner["parent"]["name"] if owner.get("nested") else owner["name"]
    kind = "use case def"
    if owner.get("nested"):
        kind = "use case def" if owner["parent"]["kind"] == "use case def" else "action def"
    elif owner["kind"] == "action def":
        kind = "action def"
    paths = sorted(Path(folder).glob("*.sysml"), key=lambda p: p.name)
    for path in paths:
        text = path.read_text(encoding="utf-8")
        if _find_definition(text, kind, target):
            return text, path
    if not paths:
        path = Path(folder) / "UseCases.sysml"
        return "package UseCases {\n}\n", path
    return paths[0].read_text(encoding="utf-8"), paths[0]


def _ensure_part_defs(folder, edited_path, edited_text, behavior, command):
    """Make sure each lane's stakeholder exists as a part def."""
    types = []
    for lane in behavior["lanes"]:
        if lane.get("type"):
            types.append(lane["type"])
    for extra in behavior.get("newTypes") or []:
        if extra not in types:
            types.append(extra)
    # description only when the caller passed one for a lane just added
    description = (command.get("description") or "").strip()
    added_name = (command.get("name") or "").strip() if command.get("op") == "add-lane" else ""
    model, paths = _load(folder)
    existing = {
        n["name"] for n in model["nodes"]
        if n["kind"] in ("part def", "actor def", "item def")
    }
    # The file we are about to write is not on disk yet. Scan its text too.
    for match in re.finditer(
        r"\b(?:part|actor|item)\s+def\s+(?:'([^']+)'|([A-Za-z_]\w*))", edited_text
    ):
        existing.add(match.group(1) or match.group(2))
    missing = [name for name in types if name not in existing]
    if not missing:
        return edited_text, []
    context = next((p for p in paths if p.name.endswith("Context.sysml")
                    and p.resolve() != edited_path.resolve()), None)
    chunks = []
    for name in missing:
        doc = description if name == added_name and description else ""
        if doc:
            chunks.append(
                f"    part def {q(name)} {{\n        doc /* {doc} */\n    }}\n"
            )
        else:
            chunks.append(f"    part def {q(name)};\n")
    block = "".join(chunks)
    if context is not None:
        current = context.read_text(encoding="utf-8")
        context.write_text(
            _insert_after_package_open(current, block), encoding="utf-8", newline="\n"
        )
        return edited_text, [context]
    return _insert_after_package_open(edited_text, block), []


def _insert_after_package_open(text, block):
    """Put new definitions just inside the package, ahead of the use cases."""
    match = re.search(r"\bpackage\s+(?:'[^']+'|\w+)\s*\{", text)
    if not match:
        return _insert_in_package(text, block)
    return text[:match.end()] + "\n" + block + text[match.end():]


def _add_activity(folder, command):
    name = _need(command, "name", "What should the new activity be called?")
    actors = command.get("actors") or command.get("lanes") or []
    if isinstance(actors, str):
        actors = [a.strip() for a in actors.split(",") if a.strip()]
    if not isinstance(actors, list):
        actors = []
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    paths = sorted(folder.glob("*.sysml"), key=lambda p: p.name)
    path = paths[0] if paths else folder / "UseCases.sysml"
    text = path.read_text(encoding="utf-8") if path.exists() else "package UseCases {\n}\n"
    if _find_definition(text, "use case def", name):
        raise ActivityEditError(
            f"'{name}' already exists. Open that activity instead of creating it."
        )
    behavior = _empty_behavior(name)
    for actor in actors:
        if isinstance(actor, str) and actor.strip():
            _add_lane(behavior, actor.strip())
    block_lines = [f"    use case def {q(name)} {{"]
    block_lines.extend(_actor_blocks(behavior, "        "))
    block_lines.append("        first start then done;")
    block_lines.append("    }")
    block = "\n".join(block_lines) + "\n"
    text = _insert_in_package(text, block)
    text, extras = _ensure_part_defs(folder, path, text, behavior, command)
    path.write_text(text, encoding="utf-8", newline="\n")
    written = [path, *extras]
    model, _paths = _load(folder)
    owner = next(
        (n["id"] for n in model["nodes"]
         if n["name"] == name and n["kind"] == "use case def"),
        name,
    )
    return {
        "ok": True,
        "owner": owner,
        "file": path.name,
        "files": [p.name for p in written],
        "message": f"Added activity '{name}' to the SysML model.",
    }
