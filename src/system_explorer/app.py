"""System Explorer — interactive SysML v2 model viewer with manual placement.

Takes a folder as input: every .sysml file directly inside it (not
recursive) is parsed and merged into one model, so cross-file references
(e.g. satisfy) resolve. Serves the model in the browser as one or more
user-created Views (SysML v2's term for a curated presentation of model
content) — each View is its own file in <folder>/views/, holding the
element positions, pan/zoom, and filters for that View. Global state
(documentation links, the element tree panel, the active View) lives in
a single layout.json in that same folder.

Usage (after `pip install -e .` in this repo, or the git URL in README.md):
    system-explorer <folder> [--port 8199] [--no-open]
    system-explorer <folder> --check   # validate only, nonzero on warnings
    system-explorer <folder> --print   # dump parsed JSON
    system-explorer <folder> --publish <outdir>  # static view-only site

Without installing, from a checkout of this repo:
    python -m system_explorer <folder>   # run from src/
"""

import argparse
import json
import mimetypes
import os
import re
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .version import __version__

# Assistant imports are done on-demand to avoid circular dependencies

# ----------------------------------------------------------------------
# Parsing
# ----------------------------------------------------------------------


def _extract_docs(text, docs):
    """Replace `doc /* ... */` blocks with `doc §N§;` markers."""

    def repl(m):
        body = re.sub(r"\s+", " ", m.group(1)).strip()
        docs.append(body)
        # trailing newlines keep line numbers stable for brace warnings
        return f"doc §{len(docs) - 1}§;" + "\n" * m.group(1).count("\n")

    return re.sub(r"\bdoc\s*/\*(.*?)\*/", repl, text, flags=re.S)


def _strip_comments(text):
    # newlines inside block comments are kept so brace warnings report the
    # line numbers of the original source
    text = re.sub(
        r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S
    )
    return re.sub(r"//[^\n]*", "", text)


def _parse_blocks(text, warn=None):
    """Split source into a tree of {header, children} blocks."""
    root = []
    stack = [root]
    buf = []
    line = 1
    for ch in text:
        if ch == "\n":
            line += 1
        if ch == "{":
            node = {"header": "".join(buf).strip(), "children": []}
            stack[-1].append(node)
            stack.append(node["children"])
            buf = []
        elif ch == "}":
            header = "".join(buf).strip()
            if header:
                stack[-1].append({"header": header, "children": None})
            if len(stack) > 1:
                stack.pop()
            elif warn:
                warn(f"unbalanced braces: unexpected '}}' at line {line}")
            buf = []
        elif ch == ";":
            header = "".join(buf).strip()
            if header:
                stack[-1].append({"header": header, "children": None})
            buf = []
        else:
            buf.append(ch)
    if len(stack) > 1 and warn:
        warn(f"unbalanced braces: {len(stack) - 1} unclosed '{{' at end of file")
    return root


# Valid SysML v2 / KerML statement keywords, including ones the parser does
# not render (constraints, states, calcs, ...). A skipped statement starting
# with one of these is legitimate model content and stays silent; anything
# else is reported as an unrecognized statement — in a pragmatic regex
# parser that's the closest thing to a syntax check, and it catches keyword
# typos like `atribute`.
KNOWN_KEYWORDS = frozenset("""
    abstract about accept action actor after alias all allocate allocation
    analysis and as assert assign assume at attribute bind binding by calc
    comment concern connect connection constraint decide def default
    dependency derived do doc else end entry enum event exhibit exit expose
    filter first flow for fork frame from if implies import in include
    individual inout interface istype item join language locale loop merge
    message metadata nonunique not objective occurrence of or ordered out
    package parallel part perform port private protected public readonly
    redefines ref references render rendering rep require requirement return
    satisfy send snapshot specializes stakeholder standard state subject
    subsets succession terminate then timeslice to transition until use
    variant variation verification verify via view viewpoint when while xor
""".split())


def _snippet(header, n=60):
    header = re.sub(r"\s+", " ", header)
    return header if len(header) <= n else header[:n] + "…"


def _warn_if_unknown(header, warn):
    """Statements the parser skips are fine if they start with a known SysML
    keyword; anything else is likely a typo or malformed syntax."""
    token = header.split(None, 1)[0]
    if token.startswith(("@", "#")) or token.lower() in KNOWN_KEYWORDS:
        return
    warn(f"unrecognized statement skipped: '{_snippet(header)}'")


RE_PACKAGE = re.compile(r"^package\s+(?:<'([^']*)'>\s*)?(\w+)$")
RE_PART_DEF = re.compile(
    r"^(abstract\s+)?(part|requirement|verification|item|action|port|actor|use\s+case)\s+def\s+"
    r"(?:<'([^']*)'>\s*)?(\w+)"
    r"(?:\s*:>\s*(.+))?$"
)
RE_USAGE = re.compile(
    r"^(part|requirement|item|action|port)\s+(:>>\s*)?(?:<'([^']*)'>\s*)?(\w+)"
    r"(?:\s*:\s*([\w][\w:]*))?"
    r"(?:\s*(\[[^\]]+\]))?$"
)
RE_ATTR = re.compile(
    r"^attribute\s+(:>>\s*)?(\w+)"
    r"(?:\s*:\s*([\w][\w:]*))?"
    r"(?:\s+default\s+(.+?)|\s*=\s*(.+?))?$"
)
RE_DOC = re.compile(r"^doc\s+§(\d+)§$")
# the reference may be plain (REQ-123) or quoted ('REQ-123') — the quoted
# form is the spec-compliant spelling for names with hyphens, and the only
# one the official SysML v2 parser accepts
RE_SATISFY = re.compile(
    r"^satisfy\s+(?:requirement\s+)?(?:'([^']+)'|([\w:.\-]+))(?:\s+by\s+.+)?$"
)
# same reference spelling as satisfy; lives in an `objective { }` on a
# verification def (SysML v2), and is also accepted as a direct statement
RE_VERIFY = re.compile(
    r"^verify\s+(?:requirement\s+)?(?:'([^']+)'|([\w:.\-]+))(?:\s+by\s+.+)?$"
)
# connection statement forms (endpoints may be dotted part paths):
#   connect a.b to c.d                              (standard SysML v2)
#   connection name : a.b to c.d                    (shorthand, see examples)
#   connection name [: Type] connect a.b to c.d     (standard SysML v2)
RE_CONNECT = re.compile(r"^connect\s+([\w.]+)\s+to\s+([\w.]+)$")
RE_CONNECTION = re.compile(
    r"^connection\s+(\w+)"
    r"(?:\s*:\s*([\w.]+)\s+to\s+([\w.]+)"
    r"|(?:\s*:\s*[\w:]+)?\s+connect\s+([\w.]+)\s+to\s+([\w.]+))$"
)

# activity diagram (swimlane style): `perform action <name> { ... }` nested
# inside a `part def` / `use case def` declares an activity — its body holds
# nested `action` usages and a `first .. then .. then done;` succession chain.
# Elsewhere in the same def, swimlane roles are assigned with
# `perform <activity>.<action>;` on `part`, `actor`, or `subject` usages.
# Not standard SysML v2 syntax (the spec has no first-class "swimlane");
# see FEATURES.md dialect notes.
RE_PERFORM_ACTION = re.compile(r"^perform\s+action\s+(\w+)$")
RE_PERFORM_LANE = re.compile(r"^perform\s+(\w+)\.(\w+)$")
# actor / subject / `ref part` usages — swimlane roles only; not treated as
# nested parts / composition. `ref part` (SysML v2 reference usage) names an
# instance that some other element composes, so it must not add a second node
# for the same thing.
RE_REFERENCE_USAGE = re.compile(
    r"^(actor|subject|ref\s+part)\s+(?:<'([^']*)'>\s*)?(\w+)"
    r"(?:\s*:\s*([\w][\w:]*))?"
    r"(?:\s*(\[[^\]]+\]))?$"
)
RE_FIRST = re.compile(r"^first\s+(\w+)$")
RE_THEN = re.compile(r"^then\s+(\w+)$")
# conditional successions after a decide node (SysML v2):
#   if <guard> then <target>;
#   else <target>;
RE_IF_THEN = re.compile(r"^if\s+(.+?)\s+then\s+(\w+)$")
RE_ELSE = re.compile(r"^else\s+(\w+)$")


def _match_connection(header):
    """Return (name, from, to) for any supported connection syntax, or None."""
    m = RE_CONNECT.match(header)
    if m:
        return "", m.group(1), m.group(2)
    m = RE_CONNECTION.match(header)
    if m:
        name, a1, b1, a2, b2 = m.groups()
        return name, a1 or a2, b1 or b2
    return None


class Model:
    def __init__(self):
        self.packages = []  # top-level package names, in file order
        self.nodes = []  # {id, name, kind, ...}
        self.edges = []  # {kind, from, to, label}
        self.connections = []  # {owner_id, name, from, to}
        self.activities = []  # {owner, name, actions, decisions, flow, edges, lanes}
        self.docs = []
        self.warnings = []  # human-readable validation messages
        self._by_name = {}  # simple name -> [ids], in parse order
        self._by_short = {}  # short name -> [ids], in parse order
        self._ids = set()

    def add_node(self, node, warn=None, index=True):
        """`index=False` registers the node (so its full id resolves and it
        renders) without putting its simple name in the lookup registries —
        used for usage nodes, whose role names are local to their owner and
        would otherwise collide across defs (`controller`, `pump`, …)."""
        if node["id"] in self._ids and warn:
            warn(f"duplicate element '{node['id']}'")
        self._ids.add(node["id"])
        self.nodes.append(node)
        if not index:
            return
        ids = self._by_name.setdefault(node["name"], [])
        if node["id"] not in ids:
            ids.append(node["id"])
        if node.get("shortName"):
            ids = self._by_short.setdefault(node["shortName"], [])
            if node["id"] not in ids:
                ids.append(node["id"])

    def resolve(self, name):
        """Map a (possibly qualified) type or short name to a node id. A
        fully qualified name must match an id exactly; otherwise the last
        segment is looked up and the first definition wins (ambiguous names
        get a model-level warning, see parse_models)."""
        if name in self._ids:
            return name
        simple = name.split("::")[-1]
        ids = self._by_name.get(simple) or self._by_short.get(simple)
        return ids[0] if ids else None


def _attr_line(m):
    redef, name, typ, default, value = m.groups()
    line = name
    if typ:
        line += f" : {typ}"
    if default:
        line += f" = {default.strip()}"
    if value:
        line += f" = {value.strip()}"
    return line


def _collect_doc(children, model):
    for child in children or []:
        m = RE_DOC.match(child["header"])
        if m:
            return model.docs[int(m.group(1))]
    return None


def _interpret_activity(name, children, model, warn):
    """Parse a `perform action <name> { ... }` body: nested `action` usages
    and succession control (`first` / `then` / `decide` / `if … then` /
    `else`). Returns
    `{"name", "actions", "decisions", "flow", "edges"}` where:
      - `flow` is every node name in encounter order (for layout / compat)
      - `edges` is `[{"from","to","label"}]` (label empty, or a guard like
        "yes" / "no")
      - `decisions` lists decide-node names (rendered as diamonds)
    `then` immediately after an `action` declaration is a succession *from
    that action* (SysML v2); other `then`s continue the `first`/`then`
    chain. `if`/`else` branch from the most recent `decide`."""
    actions = []
    decisions = []
    flow = []
    edges = []
    seen = set()

    def add_node(n):
        if n not in seen:
            seen.add(n)
            flow.append(n)

    def add_edge(frm, to, label=""):
        add_node(frm)
        add_node(to)
        edges.append({"from": frm, "to": to, "label": label})

    last_chain = None       # current end of first/then chain
    last_action = None      # most recently declared action (for its `then`)
    current_decide = None
    prev_kind = None        # "action" | "chain" | "branch" | None

    for child in children:
        header = child["header"]
        fm = RE_FIRST.match(header)
        if fm:
            last_chain = fm.group(1)
            add_node(last_chain)
            last_action = None
            prev_kind = "chain"
            continue
        im = RE_IF_THEN.match(header)
        if im:
            guard, target = im.groups()
            guard = guard.strip()
            if not current_decide:
                warn(f"activity '{name}': 'if … then' without a preceding decide")
            else:
                add_edge(current_decide, target, guard)
            last_chain = target
            last_action = None
            prev_kind = "branch"
            continue
        em = RE_ELSE.match(header)
        if em:
            target = em.group(1)
            if not current_decide:
                warn(f"activity '{name}': 'else' without a preceding decide")
            else:
                add_edge(current_decide, target, "no")
            last_chain = target
            last_action = None
            prev_kind = "branch"
            continue
        tm = RE_THEN.match(header)
        if tm:
            target = tm.group(1)
            if prev_kind == "action" and last_action:
                add_edge(last_action, target)
            elif last_chain is not None:
                add_edge(last_chain, target)
            else:
                add_node(target)
            last_chain = target
            if target == "decide":
                current_decide = target
                if target not in decisions:
                    decisions.append(target)
            last_action = None
            prev_kind = "chain"
            continue
        am = RE_USAGE.match(header)
        if am and am.group(1) == "action":
            _, _, _short, aname, _typ, _mult = am.groups()
            actions.append(
                {"name": aname, "doc": _collect_doc(child["children"], model)}
            )
            last_action = aname
            prev_kind = "action"
            continue
        _warn_if_unknown(header, warn)

    # linear first/then with no explicit edges yet (shouldn't happen if
    # first+then were seen, but keep a fallback from consecutive flow)
    if not edges and len(flow) >= 2:
        for a, b in zip(flow, flow[1:]):
            edges.append({"from": a, "to": b, "label": ""})

    return {
        "name": name,
        "actions": actions,
        "decisions": decisions,
        "flow": flow,
        "edges": edges,
    }


def _interpret_def(block, model, pkg_path, warn):
    m = RE_PART_DEF.match(block["header"])
    abstract, keyword, short, name, supers = m.groups()
    keyword = re.sub(r"\s+", " ", keyword)
    node = {
        "id": "::".join(pkg_path + [name]),
        "name": name,
        "kind": f"{keyword} def",
        "shortName": short,
        "abstract": bool(abstract),
        "package": "::".join(pkg_path[1:]),
        "packagePath": "::".join(pkg_path),
        "attributes": [],
        "parts": [],
        "doc": _collect_doc(block["children"], model),
    }
    super_names = [s.strip() for s in (supers or "").split(",") if s.strip()]
    model.add_node(node, warn)

    # swimlane assignments (`perform <activity>.<action>;`) collected from
    # part / actor / subject usage bodies as they're seen, keyed by activity
    # name — attached to the activity once its `perform action <name> { ... }`
    # block is reached. Assumes the role usages appear before the activity
    # block in source order, as in the ClinicalCoolingInteraction pattern.
    lanes_by_activity = {}

    def _collect_lane_performs(uname, utype, children):
        for sub in children or []:
            lm = RE_PERFORM_LANE.match(sub["header"])
            if lm:
                act_name, action_name = lm.groups()
                lanes_by_activity.setdefault(act_name, []).append(
                    {"role": uname, "type": utype or "", "action": action_name}
                )

    for child in block["children"] or []:
        header = child["header"]
        am = RE_ATTR.match(header)
        if am:
            node["attributes"].append(_attr_line(am))
            continue
        pa = RE_PERFORM_ACTION.match(header)
        if pa:
            activity = _interpret_activity(
                pa.group(1), child["children"] or [], model, warn
            )
            activity["lanes"] = lanes_by_activity.get(activity["name"], [])
            model.activities.append({"owner": node["id"], **activity})
            continue
        sf = RE_SATISFY.match(header)
        if sf:
            model.edges.append(
                {
                    "kind": "satisfy",
                    "from": node["id"],
                    "to_name": sf.group(1) or sf.group(2),
                    "label": "«satisfy»",
                }
            )
            continue
        vf = RE_VERIFY.match(header)
        if vf:
            model.edges.append(
                {
                    "kind": "verify",
                    "from": node["id"],
                    "to_name": vf.group(1) or vf.group(2),
                    "label": "«verify»",
                }
            )
            continue
        if header == "objective" or header.startswith("objective "):
            for sub in child["children"] or []:
                nested = RE_VERIFY.match(sub["header"])
                if nested:
                    model.edges.append(
                        {
                            "kind": "verify",
                            "from": node["id"],
                            "to_name": nested.group(1) or nested.group(2),
                            "label": "«verify»",
                        }
                    )
                    continue
                if sub["header"].startswith("doc"):
                    continue
                _warn_if_unknown(sub["header"], warn)
            continue
        conn = _match_connection(header)
        if conn:
            cname, cfrom, cto = conn
            model.connections.append(
                {"owner_id": node["id"], "name": cname, "from": cfrom, "to": cto}
            )
            continue
        asu = RE_REFERENCE_USAGE.match(header)
        if asu:
            role_kw, _short, uname, utype, _mult = asu.groups()
            _collect_lane_performs(uname, utype, child["children"])
            # actor/subject nested in a use case def is the SysML v2 way of
            # saying who participates — surface that as an association to
            # the role's type so the BDD can show use case ↔ actor/subject.
            # `ref part` stays a swimlane-only reference (owned elsewhere).
            if (utype and node["kind"] == "use case def"
                    and role_kw in ("actor", "subject")):
                model.edges.append(
                    {"kind": "association", "from": node["id"],
                     "to_name": utype, "label": uname}
                )
            continue
        um = RE_USAGE.match(header)
        if um:
            keyword, redef, _short, uname, utype, mult = um.groups()
            text = uname + (f" : {utype}" if utype else "") + (f" {mult}" if mult else "")
            entry = {"text": text, "attrs": [],
                     "isPort": keyword == "port"}
            node["parts"].append(entry)
            # attribute redefinitions inside the nested usage, e.g.
            # part :>> mechanics : MechanicalAssembly { attribute :>> length = 120; }
            for sub in child["children"] or []:
                sm = RE_ATTR.match(sub["header"])
                if sm:
                    entry["attrs"].append(_attr_line(sm))
            _collect_lane_performs(uname, utype, child["children"])
            if utype and keyword == "port":
                # a nested `port x : Iface` is interface typing, not part
                # containment — giving it a composition (has-part) diamond
                # made port-typed elements like a fluid/electrical interface
                # def read as a *part* of everything that has one of its
                # ports, rather than as a type those ports are typed by.
                model.edges.append(
                    {"kind": "typing", "from": node["id"],
                     "to_name": utype, "label": ""}
                )
            elif utype:
                # the usage itself is an element: two usages of the same type
                # (inputTempSensor / outputTempSensor : Thermistor) are two
                # distinct parts of the owner, so give each its own node in
                # addition to the owner→type composition edge. Views pick
                # whichever level they want; the viewer drops the type-level
                # edge when its usage node is on the diagram.
                usage_id = f"{node['id']}::{uname}"
                model.add_node(
                    {
                        "id": usage_id,
                        "name": uname,
                        "kind": keyword,
                        "shortName": None,
                        "abstract": False,
                        "package": node["package"],
                        "packagePath": node["packagePath"],
                        "attributes": list(entry["attrs"]),
                        "parts": [],
                        "doc": _collect_doc(child["children"], model),
                        "usageOwner": node["id"],
                        "usageType": utype,
                    },
                    warn,
                    index=False,
                )
                model.edges.append(
                    {"kind": "composition", "from": node["id"],
                     "to_name": utype, "label": uname, "usageId": usage_id}
                )
                model.edges.append(
                    {"kind": "composition", "from": node["id"],
                     "to_name": usage_id, "label": ""}
                )
                model.edges.append(
                    {"kind": "typing", "from": usage_id,
                     "to_name": utype, "label": ""}
                )
            continue
        _warn_if_unknown(header, warn)
    return node, super_names


def _interpret_usage(header, children, model, pkg_path, warn):
    m = RE_USAGE.match(header)
    _, _, short, name, typ, _mult = m.groups()
    node = {
        "id": "::".join(pkg_path + [name]),
        "name": name,
        "kind": m.group(1),
        "shortName": short,
        "abstract": False,
        "package": "::".join(pkg_path[1:]),
        "packagePath": "::".join(pkg_path),
        "attributes": [],
        "parts": [],
        "doc": _collect_doc(children, model),
    }
    model.add_node(node, warn)
    if typ:
        model.edges.append(
            {"kind": "typing", "from": node["id"], "to_name": typ, "label": ""}
        )
    return node


def _walk(children, model, pkg_path, deferred_supers, warn):
    for block in children:
        header = block["header"]
        if header.startswith(("import", "private import", "public import")):
            continue
        pm = RE_PACKAGE.match(header)
        if pm:
            name = pm.group(2)
            if not pkg_path:
                model.packages.append(name)
            _walk(block["children"] or [], model, pkg_path + [name],
                  deferred_supers, warn)
            continue
        if RE_PART_DEF.match(header):
            node, supers = _interpret_def(block, model, pkg_path, warn)
            for s in supers:
                deferred_supers.append((node["id"], s))
            continue
        if RE_USAGE.match(header):
            _interpret_usage(header, block["children"], model, pkg_path, warn)
            continue
        _warn_if_unknown(header, warn)


def parse_models(texts, names=None):
    """Parse and merge several .sysml sources into one model, so that
    cross-file references (e.g. satisfy of an imported requirement) resolve.

    Validation warnings (unbalanced braces, unrecognized statements,
    ambiguous names, unresolved references) are collected under "warnings"
    in the result; pass `names` (one per text) to prefix each parse-time
    warning with its source file."""
    model = Model()
    deferred = []
    for i, text in enumerate(texts):
        label = names[i] if names else None
        def warn(msg, _label=label):
            model.warnings.append(f"{_label}: {msg}" if _label else msg)
        text = _extract_docs(text, model.docs)
        text = _strip_comments(text)
        _walk(_parse_blocks(text, warn), model, [], deferred, warn)

    # references are resolved by simple/short name, so a name defined in
    # more than one place is ambiguous — resolution keeps the first
    for registry, what in ((model._by_name, "name"),
                           (model._by_short, "short name")):
        for name, ids in registry.items():
            if len(ids) > 1:
                model.warnings.append(
                    f"ambiguous {what} '{name}' defined in {len(ids)} places "
                    f"({', '.join(ids)}) — references resolve to the first"
                )

    edges = []
    for child_id, super_name in deferred:
        to_id = model.resolve(super_name)
        if to_id:
            edges.append(
                {"kind": "specialization", "from": child_id, "to": to_id, "label": ""}
            )
        else:
            model.warnings.append(
                f"unresolved specialization target '{super_name}' "
                f"(from {child_id})"
            )
    for e in model.edges:
        to_name = e.pop("to_name", "") or ""
        to_id = model.resolve(to_name)
        if to_id:
            e["to"] = to_id
            edges.append(e)
        else:
            model.warnings.append(
                f"unresolved {e['kind']} target '{to_name}' (from {e['from']})"
            )

    connections = [
        {"owner": c["owner_id"], "name": c["name"], "from": c["from"], "to": c["to"]}
        for c in model.connections
    ]

    # a `connect`/`connection` statement wires two *usages* together, but
    # that's really a relationship between the part defs those usages are
    # typed by (through a specific pair of ports) — surface it as an
    # ordinary edge too, resolving each role to its type via the owner's
    # own composition edges, so it renders in the block definition diagram
    # whenever both defs happen to be members of the active View.
    role_types_by_owner = {}
    role_usages_by_owner = {}
    for e in edges:
        if e["kind"] == "composition" and e["label"]:
            role_types_by_owner.setdefault(e["from"], {})[e["label"]] = e["to"]
            if e.get("usageId"):
                role_usages_by_owner.setdefault(e["from"], {})[e["label"]] = (
                    e["usageId"]
                )
    for c in connections:
        role_types = role_types_by_owner.get(c["owner"], {})
        role_usages = role_usages_by_owner.get(c["owner"], {})
        from_role, _, from_rest = c["from"].partition(".")
        to_role, _, to_rest = c["to"].partition(".")
        from_id = role_types.get(from_role)
        to_id = role_types.get(to_role)
        if not (from_id and to_id):
            continue
        label = " · ".join(filter(None, [c["name"], from_rest, to_rest]))
        # the same wire, once between the types and once between the two
        # usage nodes — each only renders when both of its endpoints are in
        # the View, and the viewer drops the type-level one when the
        # usage-level one is also on the diagram
        from_usage = role_usages.get(from_role)
        to_usage = role_usages.get(to_role)
        edge = {"kind": "connector", "from": from_id, "to": to_id, "label": label}
        if from_usage and to_usage:
            edge["fromUsage"] = from_usage
            edge["toUsage"] = to_usage
            edges.append(
                {"kind": "connector", "from": from_usage, "to": to_usage,
                 "label": label}
            )
        edges.append(edge)

    # associations come from actor/subject usages nested in a use case def;
    # two roles of the same type in one use case still mean one
    # relationship, so keep one edge per unordered pair
    seen_association_pairs = set()
    collapsed = []
    for e in edges:
        if e["kind"] == "association":
            pair = tuple(sorted((e["from"], e["to"])))
            if pair in seen_association_pairs:
                continue
            seen_association_pairs.add(pair)
        collapsed.append(e)

    package = " + ".join(model.packages) if model.packages else None
    return {"package": package, "nodes": model.nodes, "edges": collapsed,
            "connections": connections, "activities": model.activities,
            "warnings": model.warnings}


def parse_sysml(text):
    return parse_models([text])


# ----------------------------------------------------------------------
# Server
# ----------------------------------------------------------------------

VIEWER = Path(__file__).with_name("viewer.html")


def _sysml_files(folder: Path):
    """.sysml files directly inside folder (not recursive), name-sorted."""
    return sorted(folder.glob("*.sysml"), key=lambda p: p.name)


def load_folder(folder: Path):
    """Parse every .sysml file directly in `folder` into one model.

    Returns (model, paths); the model is None when there are no files.
    """
    paths = _sysml_files(folder)
    if not paths:
        return None, paths
    model = parse_models([p.read_text(encoding="utf-8") for p in paths],
                         [p.name for p in paths])
    return model, paths


RE_VIEW_ID = re.compile(r"^[a-z0-9-]+$")


def _slugify(name, existing):
    """Filesystem-safe, stable view id derived from its display name. The
    id is fixed at creation time; renaming only changes the `name` field
    inside the file, never the id/filename."""
    base = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-") or "view"
    slug = base
    n = 2
    while slug in existing:
        slug = f"{base}-{n}"
        n += 1
    return slug


def make_handler(folder: Path, layout_path: Path, cloud=None, assistant_settings=None):
    """Build the request handler class for `folder`.

    `cloud` is None for the local tool. When the server is hosted (see
    cloud.py) it is a CloudContext: requests must carry a signed-in session
    (`cloud.auth`, None = anonymous access), reads first pull the git
    checkout the folder lives in and every write is committed and pushed
    (`cloud.sync`), and linked documentation may not leave the checkout
    (`cloud.repo_root`).
    
    `assistant_settings` enables the SE assistant chat routes when set.
    """
    views_dir = folder / "views"

    def view_path(view_id):
        # reject anything that isn't a plain slug, e.g. path traversal via id
        if not view_id or not RE_VIEW_ID.match(view_id):
            return None
        return views_dir / f"{view_id}.json"


    class Handler(BaseHTTPRequestHandler):
        user = None  # signed-in user dict in cloud mode (see _gate)

        def _gate(self):
            """Cloud mode front door; True when the request was answered here.

            /healthz is public (hosting platforms probe it), /auth/* is the
            sign-in flow, everything else needs a session — the page gets
            redirected to sign-in, the API gets a 401.
            """
            if cloud is None:
                return False
            path = self.path.split("?")[0]
            if path == "/healthz":
                self._send('{"ok": true}')
                return True
            if cloud.auth is not None:
                if path.startswith("/auth/"):
                    cloud.auth.handle(self, path)
                    return True
                self.user = cloud.auth.session_user(self.headers.get("Cookie"))
                if self.user is None:
                    if self.command == "GET" and path == "/":
                        self.send_response(302)
                        self.send_header("Location", "/auth/login")
                        self.end_headers()
                    else:
                        self.send_error(401, "sign in required")
                    return True
            if self.command in ("GET", "HEAD"):
                cloud.sync.pull()  # throttled: picks up teammates' pushes
            return False

        def _saved(self, paths, message):
            # cloud mode: every change to views/layout becomes a git commit
            if cloud is not None:
                cloud.sync.commit_and_push(paths, message, self.user)

        def _write_all(self, data):
            # Paced chunked writes: antivirus loopback filters (verified with
            # AVG Web Shield on this machine — even stock http.server is hit)
            # nondeterministically swallow the tail of large fast responses.
            # ~32KB chunks with a short pause deliver reliably (6/6 vs 1/6).
            chunk = 32 * 1024
            view = memoryview(data)
            for i in range(0, len(view), chunk):
                self.wfile.write(view[i:i + chunk])
                self.wfile.flush()
                if i + chunk < len(view):
                    time.sleep(0.01)

        def _send(self, body, ctype="application/json"):
            data = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", f"{ctype}; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self._write_all(data)

        def _send_file(self, p: Path, head=False):
            ctype = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
            data = p.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            # inline = render in the tab (browser permitting), never download
            self.send_header(
                "Content-Disposition", f'inline; filename="{p.name}"'
            )
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if not head:
                self._write_all(data)

        def _doc_path(self):
            qs = parse_qs(urlsplit(self.path).query)
            target = qs.get("path", [""])[0]
            if not target:
                return None
            p = Path(target)
            if not p.is_absolute():
                p = folder / target
            if cloud is not None:
                # hosted: only files inside the git checkout, never the
                # server's own filesystem
                try:
                    p.resolve().relative_to(cloud.repo_root.resolve())
                except ValueError:
                    return None
            return p if p.is_file() else None

        def _browse_dir(self):
            # folder-tree browser for the "Add documentation link" dialog:
            # path is relative to the model folder and may not escape it
            qs = parse_qs(urlsplit(self.path).query)
            rel = qs.get("path", [""])[0]
            base = folder.resolve()
            target = (base / rel).resolve() if rel else base
            try:
                target.relative_to(base)
            except ValueError:
                return None  # path traversal outside the model folder
            return target if target.is_dir() else None

        def _check_assistant_auth(self):
            """Check Basic Auth for assistant in local mode. Returns True if authorized."""
            # Cloud mode: use GitHub session
            if cloud is not None:
                return self.user is not None
            # Local mode: check Basic Auth if configured
            if not assistant_settings:
                return True  # No settings = no auth required
            if not assistant_settings.auth_user or not assistant_settings.auth_password:
                return True  # Auth not configured
            try:
                from assistant.server import check_basic_auth
                auth_header = self.headers.get("Authorization", "")
                return check_basic_auth(auth_header, assistant_settings.auth_user, assistant_settings.auth_password)
            except (ImportError, ModuleNotFoundError):
                return False
        
        def do_GET(self):
            if self._gate():
                return
            path = self.path.split("?")[0]
            if path == "/":
                self._send(VIEWER.read_text(encoding="utf-8"), "text/html")
            elif path == "/assistant_panel.css":
                css_path = Path(__file__).parent / "assistant_panel.css"
                if css_path.is_file():
                    self._send(css_path.read_text(encoding="utf-8"), "text/css")
                else:
                    self.send_error(404)
            elif path == "/assistant_panel.js":
                js_path = Path(__file__).parent / "assistant_panel.js"
                if js_path.is_file():
                    self._send(js_path.read_text(encoding="utf-8"), "application/javascript")
                else:
                    self.send_error(404)
            elif path == "/api/session" and assistant_settings:
                if not self._check_assistant_auth():
                    self.send_error(401, "Authentication required")
                    return
                try:
                    from assistant.server import session_payload
                    payload = session_payload(assistant_settings)
                    self._send(json.dumps(payload))
                except (ImportError, ModuleNotFoundError):
                    self.send_error(503, "Assistant not available")
            elif path == "/api/model":
                try:
                    model, model_paths = load_folder(folder)
                    if model is None:
                        self._send(json.dumps(
                            {"error": f"no .sysml files found in {folder}",
                             "explorerVersion": __version__}))
                        return
                    model["file"] = ", ".join(p.name for p in model_paths)
                    model["explorerVersion"] = __version__
                    self._send(json.dumps(model))
                except Exception as exc:  # surface parse errors in the UI
                    self._send(json.dumps(
                        {"error": str(exc), "explorerVersion": __version__}))
            elif path == "/api/layout":
                if layout_path.exists():
                    self._send(layout_path.read_text(encoding="utf-8"))
                else:
                    self._send("{}")
            elif path == "/api/views":
                views = []
                if views_dir.is_dir():
                    for p in sorted(views_dir.glob("*.json")):
                        try:
                            data = json.loads(p.read_text(encoding="utf-8"))
                        except (OSError, ValueError):
                            continue
                        # the home page shows a card per view, so the
                        # listing carries what a card needs (blurb + size)
                        # and callers stay at one request
                        elements = data.get("elements")
                        views.append({
                            "id": p.stem,
                            "name": data.get("name", p.stem),
                            "description": data.get("description", ""),
                            "elementCount":
                                len(elements) if isinstance(elements, list) else 0,
                            "kind": data.get("kind") or "bdd",
                            "activityOwner": data.get("activityOwner"),
                        })
                self._send(json.dumps(views))
            elif path.startswith("/api/views/"):
                p = view_path(path[len("/api/views/"):])
                if p and p.is_file():
                    self._send(p.read_text(encoding="utf-8"))
                else:
                    self.send_error(404, "view not found")
            elif path == "/api/doc":
                # serve a linked documentation file (e.g. a PDF) so the
                # browser can open it; relative paths resolve against the
                # first model file's directory
                p = self._doc_path()
                if p:
                    self._send_file(p)
                else:
                    self.send_error(404, "documentation file not found")
            elif path == "/api/browse":
                # folder-tree listing for the documentation-link file picker
                d = self._browse_dir()
                if d is None:
                    self.send_error(404, "folder not found")
                else:
                    rel = d.relative_to(folder.resolve()).as_posix()
                    entries = [
                        {"name": p.name, "isDir": p.is_dir()}
                        for p in sorted(
                            d.iterdir(),
                            key=lambda p: (not p.is_dir(), p.name.lower()),
                        )
                    ]
                    self._send(json.dumps(
                        {"path": "" if rel == "." else rel, "entries": entries}
                    ))
            else:
                self.send_error(404)

        def do_HEAD(self):
            # PDF viewer extensions and download managers probe with HEAD;
            # answering 501 can make them fall back to downloading
            if self._gate():
                return
            if self.path.split("?")[0] == "/api/doc":
                p = self._doc_path()
                if p:
                    self._send_file(p, head=True)
                    return
            self.send_error(404)

        def _read_json_body(self):
            length = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(length).decode("utf-8"))
        
        def _assistant_complete(self, messages, tools):
            """Wrapper for assistant complete that handles model writes in hosted mode."""
            from assistant.provider import complete
            result = complete(messages, assistant_settings, tools)
            return result

        def do_POST(self):
            if self._gate():
                return
            path = self.path.split("?")[0]
            if path == "/api/chat" and assistant_settings:
                if not self._check_assistant_auth():
                    self.send_error(401, "Authentication required")
                    return
                try:
                    body = self._read_json_body()
                except (ValueError, json.JSONDecodeError):
                    self._send(json.dumps({"error": "request body must be JSON"}))
                    return
                try:
                    from assistant.server import chat_payload
                except (ImportError, ModuleNotFoundError):
                    self.send_error(503, "Assistant not available")
                    return
                payload = chat_payload(body, assistant_settings, self._assistant_complete)
                # If assistant wrote model files, commit them in hosted mode
                if cloud is not None and payload.get("notes"):
                    sysml_files = list(folder.glob("*.sysml"))
                    if sysml_files:
                        cloud.sync.commit_and_push(sysml_files, "Assistant: update model", self.user)
                status = 200 if not payload.get("error") else 400
                if payload.get("error") and assistant_settings.configuration_error():
                    status = 503
                data = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if path == "/api/layout":
                data = self._read_json_body()  # validate before writing
                layout_path.write_text(
                    json.dumps(data, indent=2) + "\n", encoding="utf-8"
                )
                self._saved([layout_path], "Update explorer layout")
                self._send('{"ok": true}')
            elif path == "/api/views":
                body = self._read_json_body()
                name = (body.get("name") or "").strip() or "Untitled"
                kind = body.get("kind") or "bdd"
                activity_owner = body.get("activityOwner")
                description = body.get("description") or ""
                views_dir.mkdir(parents=True, exist_ok=True)
                existing = {p.stem for p in views_dir.glob("*.json")}
                view_id = _slugify(name, existing)
                data = {"version": 1, "name": name, "elements": [], "nodes": {},
                        "hiddenEdges": [], "view": None, "options": {}}
                if kind != "bdd":
                    data["kind"] = kind
                if activity_owner:
                    data["activityOwner"] = activity_owner
                if description:
                    data["description"] = description
                (views_dir / f"{view_id}.json").write_text(
                    json.dumps(data, indent=2) + "\n", encoding="utf-8"
                )
                self._saved([views_dir / f"{view_id}.json"],
                            f"Create view '{name}'")
                self._send(json.dumps({"id": view_id, "name": name,
                                       "description": description,
                                       "elementCount": 0,
                                       "kind": kind,
                                       "activityOwner": activity_owner}))
            else:
                self.send_error(404)

        def do_PUT(self):
            if self._gate():
                return
            path = self.path.split("?")[0]
            if not path.startswith("/api/views/"):
                self.send_error(404)
                return
            p = view_path(path[len("/api/views/"):])
            if not p:
                self.send_error(400, "invalid view id")
                return
            data = self._read_json_body()  # validate before writing
            views_dir.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            name = data.get("name", p.stem) if isinstance(data, dict) else p.stem
            self._saved([p], f"Update view '{name}'")
            self._send('{"ok": true}')

        def do_DELETE(self):
            if self._gate():
                return
            path = self.path.split("?")[0]
            if not path.startswith("/api/views/"):
                self.send_error(404)
                return
            p = view_path(path[len("/api/views/"):])
            if p and p.is_file():
                p.unlink()
                self._saved([p], f"Delete view '{p.stem}'")
                self._send('{"ok": true}')
            else:
                self.send_error(404, "view not found")

        def log_message(self, fmt, *args):
            pass  # keep the console quiet

    return Handler


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "folder",
        help="path to a folder containing .sysml files; every .sysml file "
             "directly inside it (not recursive) is merged into one model "
             "so cross-file references (e.g. satisfy) resolve",
    )
    ap.add_argument("--port", type=int, default=8199)
    ap.add_argument("--no-open", action="store_true", help="don't open the browser")
    ap.add_argument(
        "--print", action="store_true", help="print parsed model JSON and exit"
    )
    ap.add_argument(
        "--check", action="store_true",
        help="validate the model: print every warning and exit nonzero "
             "if there are any (usable as a pre-commit/CI gate)",
    )
    ap.add_argument(
        "--publish", metavar="OUTDIR",
        help="write a static view-only Viewer site (for GitHub Pages) "
             "and exit. With --check, the site is written only when the "
             "model has no warnings",
    )
    args = ap.parse_args()

    folder = Path(args.folder).resolve()
    if not folder.is_dir():
        sys.exit(f"not a folder: {folder}")
    model, model_paths = load_folder(folder)
    if model is None:
        sys.exit(f"no .sysml files found directly in {folder}")

    if args.publish and args.print:
        sys.exit("use either --print or --publish")

    if args.check or args.publish:
        for w in model["warnings"]:
            print(f"warning: {w}")
    if args.check and model["warnings"]:
        n = len(model["warnings"])
        sys.exit(f"{n} warning(s) in {len(model_paths)} file(s)")
    if args.publish:
        from .publish import publish_site
        outdir = Path(args.publish)
        info = publish_site(folder, outdir)
        print(f"Published {info['views']} view(s) to {outdir.resolve()}")
        if info["skippedActivity"]:
            print(f"skipped {info['skippedActivity']} activity view(s)")
        if info["omitted"]:
            print("omitted documentation links outside the model folder:")
            for raw in info["omitted"]:
                print(f"  {raw}")
        return
    if args.check:
        print(f"OK — {len(model['nodes'])} elements, no warnings")
        return

    if args.print:
        print(json.dumps(model, indent=2))
        return

    # the layout file lives in the folder, independent of which .sysml
    # files happen to be in it
    layout_path = folder / "layout.json"
    url = f"http://127.0.0.1:{args.port}/"

    # Assistant configuration (optional, same as cloud.py)
    assistant_settings = None
    base_url = os.environ.get("ASSISTANT_BASE_URL", "")
    api_key = os.environ.get("ASSISTANT_API_KEY", "")
    model_name = os.environ.get("ASSISTANT_MODEL", "")
    if base_url and model_name:
        try:
            from assistant.config import Settings as AssistantSettings
            assistant_settings = AssistantSettings(
                base_url=base_url,
                api_key=api_key,
                model=model_name,
                model_folder=str(folder),
                explorer_url=url,
                methodology=os.environ.get("ASSISTANT_METHODOLOGY",
                                          str(folder / "methodology" / "product-development.yaml")),
                host="127.0.0.1",
                port=os.environ.get("ASSISTANT_PORT", 8201),
                chat_path=os.environ.get("ASSISTANT_CHAT_PATH", "/chat/completions"),
                auth=os.environ.get("ASSISTANT_AUTH", "bearer"),
                auth_user=os.environ.get("ASSISTANT_AUTH_USER", ""),
                auth_password=os.environ.get("ASSISTANT_AUTH_PASSWORD", ""),
            )
            print(f"SE assistant enabled: {base_url} model {model_name}")
        except (ImportError, ModuleNotFoundError):
            print("SE assistant module not available; chat panel will be disabled")
    elif base_url or model_name:
        print("SE assistant partially configured (need both ASSISTANT_BASE_URL and ASSISTANT_MODEL)")

    class _ExplorerServer(ThreadingHTTPServer):
        # HTTPServer defaults this True so a restart can bind during
        # TIME_WAIT. On Windows that also lets a *second* explorer bind
        # the same port; the browser then gets a reset connection and
        # looks like the viewer "isn't running".
        allow_reuse_address = False

    try:
        server = _ExplorerServer(
            ("127.0.0.1", args.port), make_handler(folder, layout_path, assistant_settings=assistant_settings)
        )
    except OSError as exc:
        print(f"Port {args.port} is already in use — another explorer is "
              f"likely already serving {url}", file=sys.stderr)
        print(f"({exc})", file=sys.stderr)
        if not args.no_open:
            webbrowser.open(url)
        sys.exit(1)

    print(f"Serving {len(model_paths)} .sysml file(s) from {folder} at {url}")
    print(f"  ({', '.join(p.name for p in model_paths)})")
    for w in model["warnings"]:
        print(f"warning: {w}")
    print(f"Views will be saved to {folder / 'views'}")
    print(f"Global state will be saved to {layout_path}")
    print("Press Ctrl+C to stop.")
    if not args.no_open:
        threading.Timer(0.3, webbrowser.open, [url]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
