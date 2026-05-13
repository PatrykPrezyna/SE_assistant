"""Interactive SysML v2 model explorer with manual element placement.

Takes a folder as input: every .sysml file directly inside it (not
recursive) is parsed and merged into one model, so cross-file references
(e.g. satisfy) resolve. Serves the model in the browser as one or more
user-created Views (SysML v2's term for a curated presentation of model
content) — each View is its own file in <folder>/views/, holding the
element positions, pan/zoom, and filters for that View. Global state
(documentation links, the element tree panel, IBD/UCD drilldown) lives in
a single layout.json in that same folder.

Usage (after `pip install -e tools/sysml_explorer`, from any repo):
    sysml-explorer <folder> [--port 8199] [--no-open]
    sysml-explorer <folder> --print   # dump parsed JSON

Without installing, from a checkout of this tool:
    python -m sysml_explorer <folder>   # run from tools/sysml_explorer/src
"""

import argparse
import json
import mimetypes
import re
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

# ----------------------------------------------------------------------
# Parsing
# ----------------------------------------------------------------------


def _extract_docs(text, docs):
    """Replace `doc /* ... */` blocks with `doc §N§;` markers."""

    def repl(m):
        body = re.sub(r"\s+", " ", m.group(1)).strip()
        docs.append(body)
        return f"doc §{len(docs) - 1}§;"

    return re.sub(r"\bdoc\s*/\*(.*?)\*/", repl, text, flags=re.S)


def _strip_comments(text):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def _parse_blocks(text):
    """Split source into a tree of {header, children} blocks."""
    root = []
    stack = [root]
    buf = []
    for ch in text:
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
            buf = []
        elif ch == ";":
            header = "".join(buf).strip()
            if header:
                stack[-1].append({"header": header, "children": None})
            buf = []
        else:
            buf.append(ch)
    return root


RE_PACKAGE = re.compile(r"^package\s+(?:<'([^']*)'>\s*)?(\w+)$")
RE_PART_DEF = re.compile(
    r"^(abstract\s+)?(part|requirement|item|action|port|actor|use\s+case)\s+def\s+(\w+)"
    r"(?:\s*:>\s*(.+))?$"
)
RE_USAGE = re.compile(
    r"^(part|requirement|item|action|port)\s+(:>>\s*)?(?:<'([^']*)'>\s*)?(\w+)"
    r"(?:\s*:\s*([\w][\w:]*))?$"
)
RE_ATTR = re.compile(
    r"^attribute\s+(:>>\s*)?(\w+)"
    r"(?:\s*:\s*([\w][\w:]*))?"
    r"(?:\s+default\s+(.+?)|\s*=\s*(.+?))?$"
)
RE_DOC = re.compile(r"^doc\s+§(\d+)§$")
RE_SATISFY = re.compile(
    r"^satisfy\s+(?:requirement\s+)?([\w:.\-]+)(?:\s+by\s+.+)?$"
)
RE_IBD = re.compile(r"^ibd\s+def\s+(\w+)\s+of\s+([\w:]+)$")
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

# use case diagram: `use case useDiagram Name for Subject { ... }` contributes
# no node of its own (like ibd def); its body declares actor/use-case role
# usages and named associations between them, resolved after all files parse
RE_UC_DIAGRAM = re.compile(r"^use\s+case\s+useDiagram\s+(\w+)\s+for\s+([\w:]+)$")
RE_UC_ROLE = re.compile(r"^(actor|use\s+case)\s+(\w+)(?:\s*:\s*([\w][\w:]*))?$")
RE_UC_CONNECTION = re.compile(
    r"^connection\s+(\w+)\s+from\s+([\w.]+)\s+to\s+([\w.]+)$"
)


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
        self.connections = []  # {owner_id|owner_name, name, from, to}
        self.ucds = []  # {owner_name, roles: [{name,type,kind}], connections: [{name,from,to}]}
        self.docs = []
        self._by_name = {}
        self._by_short = {}

    def add_node(self, node):
        self.nodes.append(node)
        self._by_name.setdefault(node["name"], node["id"])
        if node.get("shortName"):
            self._by_short.setdefault(node["shortName"], node["id"])

    def resolve(self, name):
        """Map a (possibly qualified) type or short name to a node id."""
        simple = name.split("::")[-1]
        return self._by_name.get(simple) or self._by_short.get(simple)


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


def _interpret_def(block, model, pkg_path):
    m = RE_PART_DEF.match(block["header"])
    abstract, keyword, name, supers = m.groups()
    keyword = re.sub(r"\s+", " ", keyword)
    node = {
        "id": "::".join(pkg_path + [name]),
        "name": name,
        "kind": f"{keyword} def",
        "abstract": bool(abstract),
        "package": "::".join(pkg_path[1:]),
        "packagePath": "::".join(pkg_path),
        "attributes": [],
        "parts": [],
        "doc": _collect_doc(block["children"], model),
    }
    super_names = [s.strip() for s in (supers or "").split(",") if s.strip()]
    model.add_node(node)

    for child in block["children"] or []:
        header = child["header"]
        am = RE_ATTR.match(header)
        if am:
            node["attributes"].append(_attr_line(am))
            continue
        sf = RE_SATISFY.match(header)
        if sf:
            model.edges.append(
                {
                    "kind": "satisfy",
                    "from": node["id"],
                    "to_name": sf.group(1),
                    "label": "«satisfy»",
                }
            )
            continue
        conn = _match_connection(header)
        if conn:
            cname, cfrom, cto = conn
            model.connections.append(
                {"owner_id": node["id"], "name": cname, "from": cfrom, "to": cto}
            )
            continue
        um = RE_USAGE.match(header)
        if um:
            _, redef, _short, uname, utype = um.groups()
            entry = {"text": uname + (f" : {utype}" if utype else ""), "attrs": []}
            node["parts"].append(entry)
            # attribute redefinitions inside the nested usage, e.g.
            # part :>> mechanics : MechanicalAssembly { attribute :>> length = 120; }
            for sub in child["children"] or []:
                sm = RE_ATTR.match(sub["header"])
                if sm:
                    entry["attrs"].append(_attr_line(sm))
            if utype:
                model.edges.append(
                    {
                        "kind": "composition",
                        "from": node["id"],
                        "to_name": utype,
                        "label": uname,
                    }
                )
    return node, super_names


def _interpret_usage(header, children, model, pkg_path):
    m = RE_USAGE.match(header)
    _, _, short, name, typ = m.groups()
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
    model.add_node(node)
    if typ:
        model.edges.append(
            {"kind": "typing", "from": node["id"], "to_name": typ, "label": ""}
        )
    return node


def _walk(children, model, pkg_path, deferred_supers):
    for block in children:
        header = block["header"]
        if header.startswith(("import", "private import", "public import")):
            continue
        pm = RE_PACKAGE.match(header)
        if pm:
            name = pm.group(2)
            if not pkg_path:
                model.packages.append(name)
            _walk(block["children"] or [], model, pkg_path + [name], deferred_supers)
            continue
        im = RE_IBD.match(header)
        if im:
            # an ibd def contributes no node; its connections attach to the
            # target part def (resolved after all files are parsed).
            # `ref`/`part` re-declarations inside it are ignored — the target
            # def's own part list is authoritative.
            target = im.group(2)
            for child in block["children"] or []:
                conn = _match_connection(child["header"])
                if conn:
                    cname, cfrom, cto = conn
                    model.connections.append(
                        {"owner_name": target, "name": cname,
                         "from": cfrom, "to": cto}
                    )
            continue
        um = RE_UC_DIAGRAM.match(header)
        if um:
            # a use case diagram contributes no node; its body declares
            # actor/use-case role usages and named associations between
            # them, attached to the subject (resolved after all files
            # parse, same as ibd def)
            subject = um.group(2)
            roles, conns = [], []
            for child in block["children"] or []:
                rm = RE_UC_ROLE.match(child["header"])
                if rm:
                    kind, rname, rtype = rm.groups()
                    roles.append({"name": rname, "type": rtype or "",
                                  "kind": re.sub(r"\s+", " ", kind)})
                    continue
                cm = RE_UC_CONNECTION.match(child["header"])
                if cm:
                    cname, cfrom, cto = cm.groups()
                    conns.append({"name": cname, "from": cfrom, "to": cto})
            model.ucds.append(
                {"owner_name": subject, "roles": roles, "connections": conns}
            )
            continue
        if RE_PART_DEF.match(header):
            node, supers = _interpret_def(block, model, pkg_path)
            for s in supers:
                deferred_supers.append((node["id"], s))
            continue
        if RE_USAGE.match(header):
            _interpret_usage(header, block["children"], model, pkg_path)
            continue


def parse_models(texts):
    """Parse and merge several .sysml sources into one model, so that
    cross-file references (e.g. satisfy of an imported requirement) resolve."""
    model = Model()
    deferred = []
    for text in texts:
        text = _extract_docs(text, model.docs)
        text = _strip_comments(text)
        _walk(_parse_blocks(text), model, [], deferred)

    edges = []
    for child_id, super_name in deferred:
        to_id = model.resolve(super_name)
        if to_id:
            edges.append(
                {"kind": "specialization", "from": child_id, "to": to_id, "label": ""}
            )
    for e in model.edges:
        to_id = model.resolve(e.pop("to_name", "") or "")
        if to_id:
            e["to"] = to_id
            edges.append(e)

    connections = []
    for c in model.connections:
        owner = c.get("owner_id") or model.resolve(c.get("owner_name", ""))
        if owner:  # unresolved ibd targets are dropped silently
            connections.append(
                {"owner": owner, "name": c["name"],
                 "from": c["from"], "to": c["to"]}
            )

    ucds = []
    for u in model.ucds:
        owner = model.resolve(u["owner_name"])
        if owner:  # unresolved use case diagram subjects are dropped silently
            ucds.append(
                {"owner": owner, "roles": u["roles"], "connections": u["connections"]}
            )

    # a use case diagram's associations are between role usages (e.g.
    # `operator : Operator`), local to that diagram — but they're really
    # relationships between the actor/use-case defs themselves, so surface
    # them as ordinary edges too, resolving each role to its type. That way
    # they render in the block definition diagram whenever both the actor
    # and use case happen to be in the same View, not just inside the UCD.
    # A def can appear in several roles/diagrams; keep one edge per pair.
    seen_association_pairs = set()
    for u in ucds:
        role_types = {r["name"]: r["type"] for r in u["roles"]}
        for c in u["connections"]:
            from_id = model.resolve(role_types.get(c["from"], ""))
            to_id = model.resolve(role_types.get(c["to"], ""))
            if not from_id or not to_id or from_id == to_id:
                continue
            pair = tuple(sorted((from_id, to_id)))
            if pair in seen_association_pairs:
                continue
            seen_association_pairs.add(pair)
            edges.append(
                {"kind": "association", "from": from_id, "to": to_id,
                 "label": c["name"]}
            )

    package = " + ".join(model.packages) if model.packages else None
    return {"package": package, "nodes": model.nodes, "edges": edges,
            "connections": connections, "ucds": ucds}


def parse_sysml(text):
    return parse_models([text])


# ----------------------------------------------------------------------
# Server
# ----------------------------------------------------------------------

VIEWER = Path(__file__).with_name("viewer.html")


def _sysml_files(folder: Path):
    """.sysml files directly inside folder (not recursive), name-sorted."""
    return sorted(folder.glob("*.sysml"), key=lambda p: p.name)


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


def make_handler(folder: Path, layout_path: Path):
    views_dir = folder / "views"

    def view_path(view_id):
        # reject anything that isn't a plain slug, e.g. path traversal via id
        if not view_id or not RE_VIEW_ID.match(view_id):
            return None
        return views_dir / f"{view_id}.json"


    class Handler(BaseHTTPRequestHandler):
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
            return p if p.is_file() else None

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/":
                self._send(VIEWER.read_text(encoding="utf-8"), "text/html")
            elif path == "/api/model":
                try:
                    model_paths = _sysml_files(folder)
                    if not model_paths:
                        self._send(json.dumps(
                            {"error": f"no .sysml files found in {folder}"}))
                        return
                    model = parse_models(
                        [p.read_text(encoding="utf-8") for p in model_paths]
                    )
                    model["file"] = ", ".join(p.name for p in model_paths)
                    self._send(json.dumps(model))
                except Exception as exc:  # surface parse errors in the UI
                    self._send(json.dumps({"error": str(exc)}))
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
                        views.append({"id": p.stem, "name": data.get("name", p.stem)})
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
            else:
                self.send_error(404)

        def do_HEAD(self):
            # PDF viewer extensions and download managers probe with HEAD;
            # answering 501 can make them fall back to downloading
            if self.path.split("?")[0] == "/api/doc":
                p = self._doc_path()
                if p:
                    self._send_file(p, head=True)
                    return
            self.send_error(404)

        def _read_json_body(self):
            length = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(length).decode("utf-8"))

        def do_POST(self):
            path = self.path.split("?")[0]
            if path == "/api/layout":
                data = self._read_json_body()  # validate before writing
                layout_path.write_text(
                    json.dumps(data, indent=2) + "\n", encoding="utf-8"
                )
                self._send('{"ok": true}')
            elif path == "/api/views":
                body = self._read_json_body()
                name = (body.get("name") or "").strip() or "Untitled"
                views_dir.mkdir(parents=True, exist_ok=True)
                existing = {p.stem for p in views_dir.glob("*.json")}
                view_id = _slugify(name, existing)
                data = {"name": name, "elements": [], "nodes": {},
                        "hiddenEdges": [], "view": None, "options": {}}
                (views_dir / f"{view_id}.json").write_text(
                    json.dumps(data, indent=2) + "\n", encoding="utf-8"
                )
                self._send(json.dumps({"id": view_id, "name": name}))
            else:
                self.send_error(404)

        def do_PUT(self):
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
            self._send('{"ok": true}')

        def do_DELETE(self):
            path = self.path.split("?")[0]
            if not path.startswith("/api/views/"):
                self.send_error(404)
                return
            p = view_path(path[len("/api/views/"):])
            if p and p.is_file():
                p.unlink()
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
    args = ap.parse_args()

    folder = Path(args.folder).resolve()
    if not folder.is_dir():
        sys.exit(f"not a folder: {folder}")
    model_paths = _sysml_files(folder)
    if not model_paths:
        sys.exit(f"no .sysml files found directly in {folder}")

    if args.print:
        model = parse_models([p.read_text(encoding="utf-8") for p in model_paths])
        print(json.dumps(model, indent=2))
        return

    # the layout file lives in the folder, independent of which .sysml
    # files happen to be in it
    layout_path = folder / "layout.json"
    server = ThreadingHTTPServer(
        ("127.0.0.1", args.port), make_handler(folder, layout_path)
    )
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Serving {len(model_paths)} .sysml file(s) from {folder} at {url}")
    print(f"  ({', '.join(p.name for p in model_paths)})")
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
