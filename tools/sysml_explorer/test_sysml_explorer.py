"""Tests for the SysML explorer tool.

Run:  python tools/sysml_explorer/test_sysml_explorer.py -v

Covers the parser, the HTTP API, and (when Microsoft Edge is available)
end-to-end rendering of the viewer with the compartment filters.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
from sysml_explorer import make_handler, parse_models, parse_sysml  # noqa: E402

SAMPLE = """
package TestPkg {
    private import ScalarValues::*;

    abstract part def Motor {
        attribute torque : Real;             // stall torque
        attribute cost : Real default 10.0;
        satisfy R-1;
    }

    part def BigMotor :> Motor {
        attribute :>> torque = 42.0;
    }

    part def Wheel;

    part def Chassis {
        attribute length : Real default 100.0;
        part w : Wheel;
    }

    part def Robot {
        part drive : BigMotor;
        part frame : Chassis {
            attribute :>> length = 55.0;
        }
    }

    ibd def RobotIBD of Robot {
        ref drive : BigMotor;
        ref frame : Chassis;
        connection driveLink : drive.shaft to frame.mount;
    }

    part robot1 : Robot;

    package Reqs {
        requirement def Req;
        requirement <'R-1'> Fast : Req {
            doc /* Robot shall be fast. */
        }
    }
}
"""


def node(model, name):
    return next(n for n in model["nodes"] if n["name"] == name)


def edges_of(model, kind):
    return [e for e in model["edges"] if e["kind"] == kind]


class ParserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = parse_sysml(SAMPLE)

    def test_package_name(self):
        self.assertEqual(self.model["package"], "TestPkg")

    def test_part_def_nodes(self):
        motor = node(self.model, "Motor")
        self.assertEqual(motor["kind"], "part def")
        self.assertTrue(motor["abstract"])
        self.assertFalse(node(self.model, "BigMotor")["abstract"])

    def test_attributes_with_type_default_and_redefinition(self):
        self.assertEqual(
            node(self.model, "Motor")["attributes"],
            ["torque : Real", "cost : Real = 10.0"],
        )
        self.assertEqual(node(self.model, "BigMotor")["attributes"], ["torque = 42.0"])

    def test_parts_structure_separates_nested_attribute_redefs(self):
        # regression test: nested redefs must NOT be plain part lines,
        # so the viewer can hide them with the attributes filter
        self.assertEqual(
            node(self.model, "Robot")["parts"],
            [
                {"text": "drive : BigMotor", "attrs": []},
                {"text": "frame : Chassis", "attrs": ["length = 55.0"]},
            ],
        )

    def test_specialization_edges(self):
        specs = edges_of(self.model, "specialization")
        self.assertEqual(
            [(e["from"], e["to"]) for e in specs],
            [("TestPkg::BigMotor", "TestPkg::Motor")],
        )

    def test_composition_edges_with_role_labels(self):
        comps = edges_of(self.model, "composition")
        self.assertEqual(
            {(e["from"], e["to"], e["label"]) for e in comps},
            {
                ("TestPkg::Robot", "TestPkg::BigMotor", "drive"),
                ("TestPkg::Robot", "TestPkg::Chassis", "frame"),
                ("TestPkg::Chassis", "TestPkg::Wheel", "w"),
            },
        )

    def test_typing_edges(self):
        typings = edges_of(self.model, "typing")
        self.assertEqual(
            {(e["from"], e["to"]) for e in typings},
            {
                ("TestPkg::robot1", "TestPkg::Robot"),
                ("TestPkg::Reqs::Fast", "TestPkg::Reqs::Req"),
            },
        )

    def test_requirement_short_name_doc_and_package(self):
        fast = node(self.model, "Fast")
        self.assertEqual(fast["kind"], "requirement")
        self.assertEqual(fast["shortName"], "R-1")
        self.assertEqual(fast["doc"], "Robot shall be fast.")
        self.assertEqual(fast["package"], "Reqs")

    def test_comments_are_stripped(self):
        text = json.dumps(self.model)
        self.assertNotIn("stall torque", text)

    def test_satisfy_edge_resolves_requirement_short_name(self):
        sats = edges_of(self.model, "satisfy")
        self.assertEqual(
            [(e["from"], e["to"]) for e in sats],
            [("TestPkg::Motor", "TestPkg::Reqs::Fast")],
        )

    def test_package_path_includes_top_level_package(self):
        self.assertEqual(node(self.model, "Motor")["packagePath"], "TestPkg")
        self.assertEqual(node(self.model, "Fast")["packagePath"], "TestPkg::Reqs")


class IbdParserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = parse_sysml(SAMPLE)

    def test_ibd_connection_resolves_to_owner_def(self):
        conns = self.model["connections"]
        self.assertEqual(len(conns), 1)
        c = conns[0]
        self.assertEqual(c["owner"], "TestPkg::Robot")
        self.assertEqual(c["name"], "driveLink")
        self.assertEqual(c["from"], "drive.shaft")
        self.assertEqual(c["to"], "frame.mount")

    def test_ibd_def_contributes_no_node(self):
        self.assertNotIn("RobotIBD", [n["name"] for n in self.model["nodes"]])

    def test_unresolved_ibd_owner_dropped_not_fatal(self):
        text = "package P { ibd def X of NoSuchDef { connection c : a.b to c.d; } }"
        self.assertEqual(parse_sysml(text)["connections"], [])

    def test_plain_connect_statement_inside_part_def(self):
        text = """
        package P {
            part def Thing;
            part def Box {
                part a : Thing;
                part b : Thing;
                connect a.x to b.y;
            }
        }
        """
        conns = parse_sysml(text)["connections"]
        self.assertEqual(len(conns), 1)
        self.assertEqual(
            (conns[0]["owner"], conns[0]["from"], conns[0]["to"]),
            ("P::Box", "a.x", "b.y"),
        )


UCD_SAMPLE = """
package UcdPkg {
    part def System;

    actor def Operator {
        doc /* The human operator. */
    }

    actor def Helper;

    use case def Start {
        doc /* Starts the system. */
        satisfy R-1;
    }

    use case def Stop;

    package Reqs {
        requirement def Req;
        requirement <'R-1'> Fast : Req { doc /* Shall start fast. */ }
    }

    use case useDiagram SystemUseCases for System {
        actor operator : Operator;
        use case start : Start;
        use case stop : Stop;

        connection opStart from operator to start;
        connection opStop from operator to stop;
        connection noFrom to stop;
    }
}
"""


class UcdParserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = parse_sysml(UCD_SAMPLE)

    def test_actor_and_use_case_defs_are_nodes(self):
        self.assertEqual(node(self.model, "Operator")["kind"], "actor def")
        self.assertEqual(node(self.model, "Start")["kind"], "use case def")

    def test_use_case_satisfy_edge_resolves(self):
        sats = edges_of(self.model, "satisfy")
        self.assertEqual(
            [(e["from"], e["to"]) for e in sats],
            [("UcdPkg::Start", "UcdPkg::Reqs::Fast")],
        )

    def test_use_case_diagram_resolves_subject_and_roles(self):
        ucds = self.model["ucds"]
        self.assertEqual(len(ucds), 1)
        u = ucds[0]
        self.assertEqual(u["owner"], "UcdPkg::System")
        self.assertEqual(
            {(r["name"], r["kind"], r["type"]) for r in u["roles"]},
            {("operator", "actor", "Operator"), ("start", "use case", "Start"),
             ("stop", "use case", "Stop")},
        )

    def test_connection_without_from_is_dropped(self):
        # "connection noFrom to stop;" has no "from" clause and is ambiguous
        # (system-level trigger?), so it's dropped silently rather than guessed
        u = self.model["ucds"][0]
        names = {c["name"] for c in u["connections"]}
        self.assertEqual(names, {"opStart", "opStop"})

    def test_unresolved_use_case_diagram_subject_dropped_not_fatal(self):
        text = "package P { use case useDiagram X for NoSuchSystem { actor a : A; } }"
        self.assertEqual(parse_sysml(text)["ucds"], [])

    def test_use_case_diagram_associations_become_edges_between_defs(self):
        # a useDiagram's connections are between role usages; they also
        # surface as ordinary "association" edges between the underlying
        # actor/use-case defs so they render outside UCD mode too (noFrom's
        # connection was already dropped at parse time, see above)
        assocs = edges_of(self.model, "association")
        self.assertEqual(
            {(e["from"], e["to"]) for e in assocs},
            {("UcdPkg::Operator", "UcdPkg::Start"),
             ("UcdPkg::Operator", "UcdPkg::Stop")},
        )

    def test_duplicate_association_pairs_across_diagrams_are_deduped(self):
        text = """
        package P {
            actor def A;
            use case def U;
            part def Sys;
            use case useDiagram D1 for Sys {
                actor a : A;
                use case u : U;
                connection c1 from a to u;
            }
            use case useDiagram D2 for Sys {
                actor a : A;
                use case u : U;
                connection c2 from a to u;
            }
        }
        """
        assocs = edges_of(parse_sysml(text), "association")
        self.assertEqual(len(assocs), 1)


class MultiFileTests(unittest.TestCase):
    ARCH = "package Arch { part def Frame { satisfy O-1; } }"
    REQS = """
    package OtherReqs {
        requirement def OReq;
        requirement <'O-1'> Light : OReq { doc /* Shall be light. */ }
    }
    """

    def test_cross_file_satisfy_resolves_after_merge(self):
        model = parse_models([self.ARCH, self.REQS])
        self.assertEqual(model["package"], "Arch + OtherReqs")
        sats = edges_of(model, "satisfy")
        self.assertEqual(
            [(e["from"], e["to"]) for e in sats],
            [("Arch::Frame", "OtherReqs::Light")],
        )

    def test_unresolved_satisfy_is_dropped_not_fatal(self):
        model = parse_models([self.ARCH])  # requirements file not loaded
        self.assertEqual(edges_of(model, "satisfy"), [])


class CliFolderTests(unittest.TestCase):
    """The CLI takes a folder, not explicit file paths: every .sysml file
    directly inside it (not recursive) is merged into one model."""

    SRC = str(Path(__file__).parent / "src")

    def run_print(self, folder):
        env = dict(os.environ, PYTHONPATH=self.SRC)
        return subprocess.run(
            [sys.executable, "-m", "sysml_explorer", str(folder), "--print"],
            capture_output=True, text=True, timeout=30, env=env,
        )

    def test_print_merges_all_sysml_files_in_folder(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "a.sysml").write_text(MultiFileTests.ARCH, encoding="utf-8")
            (Path(d) / "b.sysml").write_text(MultiFileTests.REQS, encoding="utf-8")
            out = self.run_print(d)
            self.assertEqual(out.returncode, 0, out.stderr)
            model = json.loads(out.stdout)
            names = {n["name"] for n in model["nodes"]}
            self.assertEqual(names, {"Frame", "OReq", "Light"})

    def test_subfolder_sysml_files_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "top.sysml").write_text(MultiFileTests.ARCH, encoding="utf-8")
            nested = Path(d) / "nested"
            nested.mkdir()
            (nested / "deep.sysml").write_text(MultiFileTests.REQS, encoding="utf-8")
            out = self.run_print(d)
            model = json.loads(out.stdout)
            names = {n["name"] for n in model["nodes"]}
            self.assertEqual(names, {"Frame"})

    def test_empty_folder_errors_out(self):
        with tempfile.TemporaryDirectory() as d:
            out = self.run_print(d)
            self.assertNotEqual(out.returncode, 0)

    def test_missing_folder_errors_out(self):
        out = self.run_print("no_such_folder_xyz")
        self.assertNotEqual(out.returncode, 0)


_AUTO_VIEWS = object()  # sentinel: auto-seed one "Default" view with every element


class ServerFixture:
    """Serves a model from every .sysml file in a temp folder, on an
    ephemeral port.

    By default seeds a single View (id "default") containing every element
    parsed from `text`/`extra`, mirroring what the real server bootstraps on
    first launch — most tests just want *something* on the canvas. Pass
    `views={}` for an empty <folder>/views/ (e.g. to test the bootstrap
    itself), or `views={id: content, ...}` for specific View content.
    """

    def __init__(self, text=SAMPLE, extra=None, views=_AUTO_VIEWS):
        self.dir = tempfile.TemporaryDirectory()
        self.folder = Path(self.dir.name)
        self.model_path = self.folder / "model.sysml"
        self.model_path.write_text(text, encoding="utf-8")
        if extra is not None:
            (self.folder / "extra.sysml").write_text(extra, encoding="utf-8")
        self.layout_path = self.folder / "layout.json"
        self.views_dir = self.folder / "views"

        if views is _AUTO_VIEWS:
            texts = [text] + ([extra] if extra is not None else [])
            elements = [n["id"] for n in parse_models(texts)["nodes"]]
            views = {"default": {"name": "Default", "elements": elements,
                                  "nodes": {}, "hiddenEdges": [], "view": None,
                                  "options": {}}}
        if views:
            self.views_dir.mkdir(parents=True, exist_ok=True)
            for view_id, content in views.items():
                (self.views_dir / f"{view_id}.json").write_text(
                    json.dumps(content), encoding="utf-8"
                )

        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0), make_handler(self.folder, self.layout_path)
        )
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()

    def get(self, path):
        with urllib.request.urlopen(self.url + path, timeout=10) as r:
            return r.read().decode("utf-8")

    def get_raw(self, path):
        with urllib.request.urlopen(self.url + path, timeout=10) as r:
            return r.status, r.headers, r.read()

    def post(self, path, data):
        req = urllib.request.Request(
            self.url + path,
            data=json.dumps(data).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.read().decode("utf-8")

    def put(self, path, data):
        req = urllib.request.Request(
            self.url + path,
            data=json.dumps(data).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="PUT",
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.read().decode("utf-8")

    def delete(self, path):
        req = urllib.request.Request(self.url + path, method="DELETE")
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.read().decode("utf-8")

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.dir.cleanup()


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ServerFixture()

    @classmethod
    def tearDownClass(cls):
        cls.srv.close()

    def test_root_serves_viewer(self):
        self.assertIn("<svg", self.srv.get("/"))

    def test_root_serves_click_to_highlight_feature(self):
        # click-to-highlight can't be exercised via a real mouse event in
        # these tests (see ViewerRenderingTests docstring for why), so check
        # that the highlighting machinery is shipped in the page: the
        # selection functions and the .sel/.hl CSS rules they toggle.
        page = self.srv.get("/")
        self.assertIn("function selectNode(id)", page)
        self.assertIn("function selectEdge(key)", page)
        self.assertIn("function clearSelection()", page)
        self.assertIn(".node.sel rect.body", page)
        self.assertIn(".node.hl rect.body", page)
        self.assertIn(".edge.sel line.wire", page)
        self.assertIn(".edge.hl line.wire", page)

    def test_model_endpoint_parses_file(self):
        model = json.loads(self.srv.get("/api/model"))
        self.assertEqual(model["package"], "TestPkg")
        self.assertEqual(model["file"], "model.sysml")

    def test_layout_roundtrip(self):
        # /api/layout holds only the global state now (Views are separate
        # files); the server round-trips whatever blob it's given
        self.assertEqual(json.loads(self.srv.get("/api/layout")), {})
        layout = {"docs": {}, "treeOpen": True, "activeView": "default"}
        self.assertEqual(json.loads(self.srv.post("/api/layout", layout)), {"ok": True})
        self.assertEqual(json.loads(self.srv.get("/api/layout")), layout)
        self.assertTrue(self.srv.layout_path.exists())

    def test_multiple_files_served_as_one_model(self):
        # files directly in the folder are merged, name-sorted
        # ("extra.sysml" < "model.sysml")
        srv = ServerFixture(text=MultiFileTests.ARCH, extra=MultiFileTests.REQS)
        try:
            model = json.loads(srv.get("/api/model"))
            self.assertEqual(model["package"], "OtherReqs + Arch")
            self.assertEqual(model["file"], "extra.sysml, model.sysml")
            names = {n["name"] for n in model["nodes"]}
            self.assertEqual(names, {"Frame", "OReq", "Light"})
        finally:
            srv.close()

    def test_new_file_in_folder_picked_up_without_restart(self):
        # /api/model re-globs the folder on every request, so a file added
        # after the server started shows up on the next fetch
        srv = ServerFixture()
        try:
            before = json.loads(srv.get("/api/model"))
            self.assertEqual(before["file"], "model.sysml")
            (srv.folder / "extra.sysml").write_text(
                MultiFileTests.REQS, encoding="utf-8"
            )
            after = json.loads(srv.get("/api/model"))
            self.assertEqual(after["file"], "extra.sysml, model.sysml")
        finally:
            srv.close()

    def test_subfolder_sysml_files_not_loaded(self):
        # only .sysml files directly in the folder count; nested ones don't
        srv = ServerFixture()
        try:
            nested = srv.folder / "nested"
            nested.mkdir()
            (nested / "deep.sysml").write_text(MultiFileTests.REQS, encoding="utf-8")
            model = json.loads(srv.get("/api/model"))
            self.assertEqual(model["file"], "model.sysml")
        finally:
            srv.close()

    def test_doc_endpoint_serves_relative_pdf(self):
        pdf = b"%PDF-1.4 dummy content"
        (Path(self.srv.dir.name) / "spec.pdf").write_bytes(pdf)
        status, headers, body = self.srv.get_raw("/api/doc?path=spec.pdf")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/pdf")
        # inline + filename: render in the browser tab, name it if saved
        self.assertEqual(headers["Content-Disposition"],
                         'inline; filename="spec.pdf"')
        self.assertEqual(body, pdf)

    def test_doc_endpoint_answers_head_requests(self):
        pdf = b"%PDF-1.4 head test"
        (Path(self.srv.dir.name) / "head.pdf").write_bytes(pdf)
        req = urllib.request.Request(
            self.srv.url + "/api/doc?path=head.pdf", method="HEAD")
        with urllib.request.urlopen(req, timeout=10) as r:
            self.assertEqual(r.status, 200)
            self.assertEqual(r.headers["Content-Type"], "application/pdf")
            self.assertEqual(r.headers["Content-Length"], str(len(pdf)))
            self.assertEqual(r.read(), b"")

    def test_doc_endpoint_serves_large_file_completely(self):
        # regression: unbuffered wfile.write() truncated payloads beyond one
        # socket send(), so real-world PDFs arrived incomplete and hung
        pdf = b"%PDF-1.4 " + os.urandom(1_500_000)
        (Path(self.srv.dir.name) / "big.pdf").write_bytes(pdf)
        status, _, body = self.srv.get_raw("/api/doc?path=big.pdf")
        self.assertEqual(status, 200)
        self.assertEqual(len(body), len(pdf))
        self.assertEqual(body, pdf)

    def test_doc_endpoint_missing_file_is_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.srv.get_raw("/api/doc?path=nope.pdf")
        self.assertEqual(ctx.exception.code, 404)

    def test_model_endpoint_reports_parse_trouble_as_json(self):
        # endpoint must always answer JSON, never a 500 page
        self.srv.model_path.write_text("part def {{{", encoding="utf-8")
        try:
            json.loads(self.srv.get("/api/model"))  # no exception raised
        finally:
            self.srv.model_path.write_text(SAMPLE, encoding="utf-8")


class ViewApiTests(unittest.TestCase):
    """CRUD for /api/views: each View is its own JSON file in
    <folder>/views/<id>.json, where the id is a stable slug derived from
    the name at creation time (renaming only changes the `name` field)."""

    def setUp(self):
        self.srv = ServerFixture(views={})  # start with no views at all

    def tearDown(self):
        self.srv.close()

    def test_no_views_initially(self):
        self.assertEqual(json.loads(self.srv.get("/api/views")), [])

    def test_create_view_returns_slug_id(self):
        created = json.loads(self.srv.post("/api/views", {"name": "Logical Architecture"}))
        self.assertEqual(created, {"id": "logical-architecture", "name": "Logical Architecture"})
        self.assertTrue((self.srv.views_dir / "logical-architecture.json").exists())

    def test_created_view_is_seeded_empty(self):
        created = json.loads(self.srv.post("/api/views", {"name": "Empty"}))
        view = json.loads(self.srv.get(f"/api/views/{created['id']}"))
        self.assertEqual(view, {"name": "Empty", "elements": [], "nodes": {},
                                 "hiddenEdges": [], "view": None, "options": {}})

    def test_duplicate_name_gets_a_distinct_slug(self):
        first = json.loads(self.srv.post("/api/views", {"name": "My View"}))
        second = json.loads(self.srv.post("/api/views", {"name": "My View"}))
        self.assertEqual(first["id"], "my-view")
        self.assertEqual(second["id"], "my-view-2")

    def test_get_missing_view_is_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.srv.get_raw("/api/views/no-such-view")
        self.assertEqual(ctx.exception.code, 404)

    def test_get_rejects_invalid_id_as_not_found(self):
        # ids are slugs (lowercase/digits/hyphen only); anything else can
        # never resolve to a real file, regardless of what's on disk
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.srv.get_raw("/api/views/UPPERCASE")
        self.assertEqual(ctx.exception.code, 404)

    def test_put_updates_existing_view(self):
        created = json.loads(self.srv.post("/api/views", {"name": "V"}))
        updated = {"name": "V", "elements": ["TestPkg::Motor"],
                   "nodes": {"TestPkg::Motor": {"x": 5, "y": 6}},
                   "hiddenEdges": [], "view": {"tx": 1, "ty": 2, "s": 1},
                   "options": {"attrs": False}}
        self.srv.put(f"/api/views/{created['id']}", updated)
        self.assertEqual(json.loads(self.srv.get(f"/api/views/{created['id']}")), updated)

    def test_put_to_new_id_creates_it(self):
        # PUT is an idempotent create-or-replace, not update-only — the
        # client relies on this for the auto-seeded bootstrap View
        content = {"name": "Fresh", "elements": [], "nodes": {},
                   "hiddenEdges": [], "view": None, "options": {}}
        self.srv.put("/api/views/fresh", content)
        self.assertEqual(json.loads(self.srv.get("/api/views/fresh")), content)

    def test_put_rejects_invalid_id(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.srv.put("/api/views/UPPERCASE", {"name": "x"})
        self.assertEqual(ctx.exception.code, 400)

    def test_delete_removes_view(self):
        created = json.loads(self.srv.post("/api/views", {"name": "Gone"}))
        self.srv.delete(f"/api/views/{created['id']}")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.srv.get_raw(f"/api/views/{created['id']}")
        self.assertEqual(ctx.exception.code, 404)

    def test_delete_missing_view_is_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.srv.delete("/api/views/no-such-view")
        self.assertEqual(ctx.exception.code, 404)

    def test_list_reflects_created_and_deleted_views(self):
        a = json.loads(self.srv.post("/api/views", {"name": "A"}))
        b = json.loads(self.srv.post("/api/views", {"name": "B"}))
        listed = {v["id"] for v in json.loads(self.srv.get("/api/views"))}
        self.assertEqual(listed, {a["id"], b["id"]})
        self.srv.delete(f"/api/views/{a['id']}")
        listed = {v["id"] for v in json.loads(self.srv.get("/api/views"))}
        self.assertEqual(listed, {b["id"]})


def find_edge():
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        if base:
            p = Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            if p.exists():
                return str(p)
    return None


EDGE = find_edge()


def dump_dom(url):
    out = subprocess.run(
        [EDGE, "--headless", "--disable-gpu", "--virtual-time-budget=3000",
         "--dump-dom", url + "/"],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    return out.stdout


@unittest.skipUnless(EDGE, "Microsoft Edge not found; skipping rendering tests")
class ViewerRenderingTests(unittest.TestCase):
    """Load the page headless and check what the filters leave in the DOM."""

    ATTR_LINE = "torque = 42.0"   # top-level attribute (BigMotor)
    PART_LINE = "drive : BigMotor"  # part line (Robot)
    REDEF_LINE = "length = 55.0"  # attribute redef nested under a part (Robot)

    @classmethod
    def setUpClass(cls):
        cls.srv = ServerFixture()

    @classmethod
    def tearDownClass(cls):
        cls.srv.close()

    def render(self, attrs, parts):
        # overwrite the auto-seeded "default" View's options; its membership
        # (every element) stays the same — filters are what's under test
        all_elements = [n["id"] for n in parse_sysml(SAMPLE)["nodes"]]
        view = {"name": "Default", "elements": all_elements, "nodes": {},
                "hiddenEdges": [], "view": None,
                "options": {"attrs": attrs, "parts": parts}}
        (self.srv.views_dir / "default.json").write_text(
            json.dumps(view), encoding="utf-8")
        return dump_dom(self.srv.url)

    def check(self, dom, attr_shown, part_shown, redef_shown):
        self.assertGreater(dom.count('class="node'), 5, "nodes did not render")
        self.assertEqual(self.ATTR_LINE in dom, attr_shown, "top-level attribute")
        self.assertEqual(self.PART_LINE in dom, part_shown, "part line")
        self.assertEqual(self.REDEF_LINE in dom, redef_shown, "nested attr redef")

    def test_all_shown(self):
        self.check(self.render(True, True), True, True, True)

    def test_kind_keywords_hidden_by_default(self):
        # SHOW_KEYWORDS in viewer.html defaults to false: no keyword header
        # lines (the only class="stereo" texts) while node titles still render.
        # Don't grep for «part def» itself — the JS source in the dump
        # legitimately mentions it in a comment.
        dom = self.render(True, True)
        self.assertNotIn('class="stereo"', dom)
        self.assertIn(">Robot</text>", dom)

    def test_attrs_off_hides_nested_redefs_too(self):
        # regression: nested redefs used to survive the attributes filter
        self.check(self.render(False, True), False, True, False)

    def test_parts_off_hides_parts_and_their_redefs(self):
        self.check(self.render(True, False), True, False, False)

    def test_both_off_leaves_names_only(self):
        dom = self.render(False, False)
        self.check(dom, False, False, False)
        self.assertIn(">Robot<", dom)


@unittest.skipUnless(EDGE, "Microsoft Edge not found; skipping rendering tests")
class ViewRenderingTests(unittest.TestCase):
    """Views: an element is on the canvas iff it's a member of the active
    View; an edge only renders when both endpoints are members; hiddenEdges/
    docs/title reflect the active View/model."""

    def names(self, dom):
        # node titles are the class="name" text elements. Requirement
        # titles carry a short-name prefix ("R-1 Fast"), so keep the last
        # token only.
        found = re.findall(r'"name"[^>]*>([^<]+)</text>', dom)
        return {t.split()[-1] for t in found}

    def make_view(self, name, elements, **overrides):
        v = {"name": name, "elements": elements, "nodes": {}, "hiddenEdges": [],
             "view": None, "options": {}}
        v.update(overrides)
        return v

    def serve(self, views, active, extra_layout=None):
        srv = ServerFixture(views=views)
        layout = {"activeView": active}
        if extra_layout:
            layout.update(extra_layout)
        srv.layout_path.write_text(json.dumps(layout), encoding="utf-8")
        return srv

    def test_view_shows_only_its_member_elements(self):
        views = {"v": self.make_view(
            "V", ["TestPkg::Reqs::Req", "TestPkg::Reqs::Fast"])}
        with self.serve(views, "v") as srv:
            self.assertEqual(self.names(dump_dom(srv.url)), {"Req", "Fast"})

    def test_empty_view_shows_nothing(self):
        views = {"v": self.make_view("V", [])}
        with self.serve(views, "v") as srv:
            self.assertEqual(dump_dom(srv.url).count('class="node'), 0)

    def test_satisfy_edge_rendered_when_both_endpoints_are_members(self):
        views = {"v": self.make_view("V", ["TestPkg::Motor", "TestPkg::Reqs::Fast"])}
        with self.serve(views, "v") as srv:
            self.assertIn('class="edge satisfy"', dump_dom(srv.url))

    def test_edge_not_rendered_when_one_endpoint_missing(self):
        views = {"v": self.make_view("V", ["TestPkg::Reqs::Fast"])}
        with self.serve(views, "v") as srv:
            self.assertNotIn('class="edge satisfy"', dump_dom(srv.url))

    def test_hidden_edge_in_view_is_not_rendered(self):
        elements = ["TestPkg::Robot", "TestPkg::BigMotor", "TestPkg::Chassis"]
        with self.serve({"v": self.make_view("V", elements)}, "v") as srv:
            all_edges = dump_edge_count(dump_dom(srv.url))
        views2 = {"v": self.make_view(
            "V", elements,
            hiddenEdges=["composition|TestPkg::Robot|TestPkg::BigMotor|drive"])}
        with self.serve(views2, "v") as srv2:
            self.assertEqual(dump_edge_count(dump_dom(srv2.url)), all_edges - 1)

    def test_title_shows_active_view_name(self):
        views = {"v": self.make_view("Logical Architecture", ["TestPkg::Motor"])}
        with self.serve(views, "v") as srv:
            self.assertIn("Logical Architecture", dump_dom(srv.url))

    def test_doc_link_marker_rendered(self):
        views = {"v": self.make_view("V", ["TestPkg::Robot"])}
        with self.serve(views, "v", {"docs": {"TestPkg::Robot": "specs/robot.pdf"}}) as srv:
            self.assertEqual(dump_dom(srv.url).count('<text class="docicon"'), 1)

    def test_page_ships_remove_from_view_menu_action(self):
        # right-click can't be simulated headless; check the menu-building
        # logic that would produce the item is shipped
        views = {"v": self.make_view("V", ["TestPkg::Motor"])}
        with self.serve(views, "v") as srv:
            self.assertIn("Remove from view", dump_dom(srv.url))

    def test_context_menu_container_present_and_empty(self):
        views = {"v": self.make_view("V", ["TestPkg::Motor"])}
        with self.serve(views, "v") as srv:
            self.assertIn('<div id="ctxmenu"></div>', dump_dom(srv.url))

    def test_edges_expose_data_key_for_click_selection(self):
        elements = ["TestPkg::Robot", "TestPkg::BigMotor"]
        with self.serve({"v": self.make_view("V", elements)}, "v") as srv:
            self.assertIn(
                'data-key="composition|TestPkg::Robot|TestPkg::BigMotor|drive"',
                dump_dom(srv.url))

    def test_edge_labels_hidden_by_default(self):
        # SHOW_EDGE_LABELS defaults to false: no role-name text on the
        # composition edges (the part compartment line "drive : BigMotor"
        # is a different string and must survive)
        elements = ["TestPkg::Robot", "TestPkg::BigMotor"]
        with self.serve({"v": self.make_view("V", elements)}, "v") as srv:
            dom = dump_dom(srv.url)
            self.assertNotIn(">drive</text>", dom)
            self.assertIn(">drive : BigMotor</text>", dom)

    @staticmethod
    def legend_rows(dom):
        # count only inside the legend div (it precedes the canvas svg);
        # the raw JS source later in the dump also contains the row markup
        segment = dom.split('id="legend"')[1].split('<svg id="canvas"')[0]
        return segment.count('<div class="lrow">')

    def test_legend_lists_only_visible_edge_kinds(self):
        all_elements = [n["id"] for n in parse_sysml(SAMPLE)["nodes"]]
        with self.serve({"v": self.make_view("All", all_elements)}, "v") as srv:
            self.assertEqual(self.legend_rows(dump_dom(srv.url)), 4)
        # Reqs subpackage only: Req/Fast, connected by a single typing edge
        reqs = {"v": self.make_view(
            "Reqs", ["TestPkg::Reqs::Req", "TestPkg::Reqs::Fast"])}
        with self.serve(reqs, "v") as srv2:
            dom = dump_dom(srv2.url)
            self.assertEqual(self.legend_rows(dom), 1)
            self.assertIn("typed by", dom.split('id="legend"')[1][:400])

    def test_bootstrap_creates_default_view_seeded_with_all_elements(self):
        # a folder with no views/ at all gets one auto-created on first
        # launch, pre-populated so the canvas isn't blank
        with ServerFixture(views={}) as srv:
            self.assertEqual(dump_dom(srv.url).count('class="node'), 8)
            self.assertEqual(json.loads(srv.get("/api/views")),
                              [{"id": "default", "name": "Default"}])


def dump_edge_count(dom):
    return dom.count('class="edge')


def node_segment(dom, node_id):
    """Slice of the DOM covering one node's <g class="node...">, from its
    own opening tag up to the next node's opening tag (or the layer's end).
    Good enough for a containment check (e.g. "does this node have the IBD
    icon") without a full HTML parser."""
    starts = [m.start() for m in re.finditer(r'<g class="node[^"]*" data-id="', dom)]
    idx = dom.index(f'data-id="{node_id}"')
    start = max(s for s in starts if s <= idx)
    later = [s for s in starts if s > start]
    end = min(later) if later else len(dom)
    return dom[start:end]


def tree_classes(dom):
    m = re.search(r'<div id="tree"(?: class="([^"]*)")?', dom)
    assert m, "tree div not found"
    return (m.group(1) or "").split()


def elem_row(dom, name):
    """The tree row <div class="elem ..."> for the element labeled `name`
    (rows have no nested <div>, so the first </div> closes the row)."""
    for row in re.findall(r'<div class="elem[^"]*"[^>]*>.*?</div>', dom, re.S):
        if f">{name}</span>" in row:
            return row
    raise AssertionError(f"tree row for {name!r} not found")


def pkg_row(dom, name):
    """The tree package header <div class="pkg">...</div> for package
    `name` (its own </div> closes it — the sibling .pkg-body is appended
    after, not nested inside, so this can't overrun into the body)."""
    for row in re.findall(r'<div class="pkg"[^>]*>.*?</div>', dom, re.S):
        if row.endswith(f"{name}</div>"):
            return row
    raise AssertionError(f"tree package header for {name!r} not found")


@unittest.skipUnless(EDGE, "Microsoft Edge not found; skipping rendering tests")
class ElementTreeRenderingTests(unittest.TestCase):
    """Left-side element tree: lists every model element grouped by
    package, shows whether each is a member of the active View (and thus
    on the canvas), and lets each be added/removed via its checkbox."""

    @classmethod
    def setUpClass(cls):
        cls.srv = ServerFixture()  # auto-seeded "Default" view with all 8 elements

    @classmethod
    def tearDownClass(cls):
        cls.srv.close()

    def render(self, layout=None):
        if layout is None:
            self.srv.layout_path.unlink(missing_ok=True)
        else:
            self.srv.layout_path.write_text(json.dumps(layout), encoding="utf-8")
        return dump_dom(self.srv.url)

    def test_tree_open_and_enabled_by_default(self):
        classes = tree_classes(self.render())
        self.assertNotIn("hidden", classes)
        self.assertNotIn("disabled", classes)

    def test_tree_panel_hidden_via_saved_option(self):
        classes = tree_classes(self.render({"treeOpen": False}))
        self.assertIn("hidden", classes)

    def test_tree_disabled_while_in_ibd_mode(self):
        classes = tree_classes(self.render(
            {"mode": "ibd", "ibdOwner": "TestPkg::Robot"}))
        self.assertIn("disabled", classes)

    def test_tree_lists_every_element_and_package_header(self):
        dom = self.render()
        for name in ["Motor", "BigMotor", "Wheel", "Chassis", "Robot",
                     "robot1", "Req", "Fast"]:
            elem_row(dom, name)  # raises if the row is missing
        self.assertIn(">Reqs<", dom.split('id="tree"')[1].split('<svg id="canvas"')[0])

    def test_checkbox_checked_for_view_member(self):
        dom = self.render()  # default view = every element
        row = elem_row(dom, "Motor")
        self.assertIn("checked", row)
        self.assertNotIn("dimmed", row)

    def test_checkbox_unchecked_and_dimmed_for_non_member(self):
        views = {"v": {"name": "V", "elements": ["TestPkg::Motor"], "nodes": {},
                        "hiddenEdges": [], "view": None, "options": {}}}
        with ServerFixture(views=views) as srv:
            srv.layout_path.write_text(json.dumps({"activeView": "v"}), encoding="utf-8")
            dom = dump_dom(srv.url)
            motor_row = elem_row(dom, "Motor")
            self.assertIn("checked", motor_row)
            self.assertNotIn("dimmed", motor_row)
            wheel_row = elem_row(dom, "Wheel")
            self.assertNotIn("checked", wheel_row)
            self.assertIn("dimmed", wheel_row)

    def test_dot_classes_reflect_element_kind(self):
        dom = self.render()
        self.assertIn("k-req", elem_row(dom, "Fast"))
        self.assertIn("k-usage", elem_row(dom, "robot1"))
        self.assertNotIn("k-req", elem_row(dom, "Motor"))
        self.assertNotIn("k-usage", elem_row(dom, "Motor"))

    def test_package_checkbox_checked_when_all_descendants_are_members(self):
        dom = self.render()  # default view = every element
        self.assertIn("checked", pkg_row(dom, "Reqs"))
        # TestPkg is the top-level package covering all 8 elements incl. Reqs
        self.assertIn("checked", pkg_row(dom, "TestPkg"))

    def test_package_checkbox_unchecked_when_no_descendants_are_members(self):
        views = {"v": {"name": "V", "elements": ["TestPkg::Motor"], "nodes": {},
                        "hiddenEdges": [], "view": None, "options": {}}}
        with ServerFixture(views=views) as srv:
            srv.layout_path.write_text(json.dumps({"activeView": "v"}), encoding="utf-8")
            dom = dump_dom(srv.url)
            self.assertNotIn("checked", pkg_row(dom, "Reqs"))

    def test_package_checkbox_reflects_nested_subpackage_membership(self):
        # a view containing only the Reqs subpackage's elements: Reqs itself
        # is fully covered, but the outer TestPkg (which also has Motor,
        # Robot, ...) is only partially covered, so it must NOT read checked
        views = {"v": {"name": "V",
                        "elements": ["TestPkg::Reqs::Req", "TestPkg::Reqs::Fast"],
                        "nodes": {}, "hiddenEdges": [], "view": None, "options": {}}}
        with ServerFixture(views=views) as srv:
            srv.layout_path.write_text(json.dumps({"activeView": "v"}), encoding="utf-8")
            dom = dump_dom(srv.url)
            self.assertIn("checked", pkg_row(dom, "Reqs"))
            self.assertNotIn("checked", pkg_row(dom, "TestPkg"))


@unittest.skipUnless(EDGE, "Microsoft Edge not found; skipping rendering tests")
class IbdRenderingTests(unittest.TestCase):
    """Internal block diagram mode, entered via the persisted layout
    (mode/ibdOwner). The stray "nodes"/"selectedPackage" keys in these
    layout dicts are inert leftovers from the pre-Views layout shape —
    harmless, the server/client just ignore unknown keys."""

    @classmethod
    def setUpClass(cls):
        cls.srv = ServerFixture()

    @classmethod
    def tearDownClass(cls):
        cls.srv.close()

    def render(self, layout):
        self.srv.layout_path.write_text(json.dumps(layout), encoding="utf-8")
        return dump_dom(self.srv.url)

    def button_tag(self, dom, id_):
        m = re.search(r'<button id="%s"[^>]*>' % id_, dom)
        self.assertIsNotNone(m, f"{id_} button not found")
        return m.group(0)

    def test_ibd_shows_role_boxes_not_the_owner_def(self):
        dom = self.render({"nodes": {}, "selectedPackage": None,
                           "mode": "ibd", "ibdOwner": "TestPkg::Robot"})
        # role boxes are named after the part roles (drive, frame), typed by
        # BigMotor/Chassis -- not the owner def "Robot" itself
        self.assertIn(">drive</text>", dom)
        self.assertIn(">frame</text>", dom)
        self.assertNotIn(">Robot</text>", dom)

    def test_ibd_connection_renders_as_connector_edge(self):
        dom = self.render({"nodes": {}, "selectedPackage": None,
                           "mode": "ibd", "ibdOwner": "TestPkg::Robot"})
        self.assertIn('class="edge connector"', dom)

    def test_bdd_mode_has_no_connector_edges(self):
        dom = self.render({"nodes": {}, "selectedPackage": None})
        self.assertNotIn('class="edge connector"', dom)

    def test_back_button_shown_only_in_ibd_mode(self):
        bdd_dom = self.render({"nodes": {}, "selectedPackage": None})
        ibd_dom = self.render({"nodes": {}, "selectedPackage": None,
                               "mode": "ibd", "ibdOwner": "TestPkg::Robot"})
        self.assertIn("none", self.button_tag(bdd_dom, "ibdBackBtn"))
        self.assertNotIn("none", self.button_tag(ibd_dom, "ibdBackBtn"))

    def test_unknown_ibd_owner_falls_back_to_bdd(self):
        dom = self.render({"nodes": {}, "selectedPackage": None,
                           "mode": "ibd", "ibdOwner": "TestPkg::NoSuchDef"})
        self.assertGreater(dom.count('class="node'), 5)
        self.assertIn("none", self.button_tag(dom, "ibdBackBtn"))

    @staticmethod
    def legend_segment(dom):
        # scope to the legend div only: the JS source later in the dump
        # also contains the "connector (IBD)" string literal
        return dom.split('id="legend"')[1].split('<svg id="canvas"')[0]

    def test_ibd_legend_row_shown_only_in_ibd_mode(self):
        bdd_dom = self.render({"nodes": {}, "selectedPackage": None})
        ibd_dom = self.render({"nodes": {}, "selectedPackage": None,
                               "mode": "ibd", "ibdOwner": "TestPkg::Robot"})
        self.assertNotIn("connector (IBD)", self.legend_segment(bdd_dom))
        self.assertIn("connector (IBD)", self.legend_segment(ibd_dom))

    def test_ibd_icon_shown_on_element_owning_connections(self):
        # Robot owns "ibd def RobotIBD of Robot { connection ... }"
        dom = self.render({"nodes": {}, "selectedPackage": None})
        self.assertIn('class="ibdicon"', node_segment(dom, "TestPkg::Robot"))

    def test_ibd_icon_shown_on_usage_typed_by_ibd_owner(self):
        # robot1 : Robot -- the icon follows through the typing edge too
        dom = self.render({"nodes": {}, "selectedPackage": None})
        self.assertIn('class="ibdicon"', node_segment(dom, "TestPkg::robot1"))

    def test_ibd_icon_not_shown_on_element_without_ibd(self):
        dom = self.render({"nodes": {}, "selectedPackage": None})
        self.assertNotIn('class="ibdicon"', node_segment(dom, "TestPkg::BigMotor"))


NESTED_IBD_SAMPLE = """
package NestPkg {
    part def Sensor {
        connection c : x.a to y.b;
    }
    part def Vehicle {
        part sensor : Sensor;
        connection d : sensor.a to sensor.b;
    }
}
"""


@unittest.skipUnless(EDGE, "Microsoft Edge not found; skipping rendering tests")
class NestedIbdRenderingTests(unittest.TestCase):
    """Regression: detecting a role box's own IBD (to offer "Open internal
    block diagram" one level down) used to resolve the role's type via a
    client-side model.resolve() that doesn't exist -- /api/model returns
    plain JSON, not the Python Model instance -- crashing IBD-mode rendering
    entirely. Covered here because the icon (added alongside the fix) is
    computed the same way and would have failed loudly if the crash were
    still there."""

    @classmethod
    def setUpClass(cls):
        cls.srv = ServerFixture(NESTED_IBD_SAMPLE)

    @classmethod
    def tearDownClass(cls):
        cls.srv.close()

    def render(self, layout):
        self.srv.layout_path.write_text(json.dumps(layout), encoding="utf-8")
        return dump_dom(self.srv.url)

    def test_role_box_with_own_ibd_renders_and_gets_icon(self):
        dom = self.render({"nodes": {}, "selectedPackage": None,
                           "mode": "ibd", "ibdOwner": "NestPkg::Vehicle"})
        self.assertIn(">sensor</text>", dom)
        self.assertIn('class="ibdicon"',
                       node_segment(dom, "NestPkg::Vehicle::ibd::sensor"))


@unittest.skipUnless(EDGE, "Microsoft Edge not found; skipping rendering tests")
class UcdRenderingTests(unittest.TestCase):
    """Use case diagram mode, entered via the persisted layout
    (mode/ucdOwner) the same way IbdRenderingTests drives ibdOwner."""

    @classmethod
    def setUpClass(cls):
        cls.srv = ServerFixture(UCD_SAMPLE)

    @classmethod
    def tearDownClass(cls):
        cls.srv.close()

    def render(self, layout):
        self.srv.layout_path.write_text(json.dumps(layout), encoding="utf-8")
        return dump_dom(self.srv.url)

    def button_tag(self, dom, id_):
        m = re.search(r'<button id="%s"[^>]*>' % id_, dom)
        self.assertIsNotNone(m, f"{id_} button not found")
        return m.group(0)

    UCD_LAYOUT = {"nodes": {}, "selectedPackage": None,
                  "mode": "ucd", "ucdOwner": "UcdPkg::System"}
    BDD_LAYOUT = {"nodes": {}, "selectedPackage": None}

    def test_ucd_shows_role_boxes_not_the_subject(self):
        dom = self.render(self.UCD_LAYOUT)
        self.assertIn(">operator</text>", dom)
        self.assertIn(">start</text>", dom)
        self.assertIn(">stop</text>", dom)
        self.assertNotIn(">System</text>", dom)

    def test_ucd_connection_renders_as_association_edge(self):
        # only opStart/opStop resolve; noFrom was dropped at parse time
        dom = self.render(self.UCD_LAYOUT)
        self.assertEqual(dom.count('class="edge association"'), 2)

    def test_bdd_mode_shows_actor_usecase_association_too(self):
        # a use case diagram's associations are really relationships between
        # the actor/use-case defs, so they surface as ordinary edges in the
        # block definition diagram too, whenever both ends are in the View
        # (here: Operator+Start, Operator+Stop -- Helper has no connection)
        dom = self.render(self.BDD_LAYOUT)
        self.assertEqual(dom.count('class="edge association"'), 2)

    def test_back_button_shown_only_in_ucd_mode(self):
        bdd_dom = self.render(self.BDD_LAYOUT)
        ucd_dom = self.render(self.UCD_LAYOUT)
        self.assertIn("none", self.button_tag(bdd_dom, "ibdBackBtn"))
        self.assertNotIn("none", self.button_tag(ucd_dom, "ibdBackBtn"))

    def test_unknown_ucd_owner_falls_back_to_bdd(self):
        dom = self.render({"nodes": {}, "selectedPackage": None,
                           "mode": "ucd", "ucdOwner": "UcdPkg::NoSuchSubject"})
        self.assertIn("none", self.button_tag(dom, "ibdBackBtn"))

    def test_association_legend_row_shown_in_both_bdd_and_ucd_mode(self):
        def legend_segment(dom):
            return dom.split('id="legend"')[1].split('<svg id="canvas"')[0]
        label = "association (actor ↔ use case)"
        self.assertIn(label, legend_segment(self.render(self.BDD_LAYOUT)))
        self.assertIn(label, legend_segment(self.render(self.UCD_LAYOUT)))

    def test_ucd_icon_shown_on_subject_element(self):
        dom = self.render(self.BDD_LAYOUT)
        self.assertIn('class="ucdicon"', node_segment(dom, "UcdPkg::System"))

    def test_ucd_icon_not_shown_on_element_without_use_case_diagram(self):
        dom = self.render(self.BDD_LAYOUT)
        self.assertNotIn('class="ucdicon"', node_segment(dom, "UcdPkg::Start"))

    def test_actor_and_usecase_defs_get_distinct_css_classes(self):
        dom = self.render(self.BDD_LAYOUT)
        self.assertIn('class="node actor"', dom)
        self.assertIn('class="node usecase"', dom)


if __name__ == "__main__":
    unittest.main()
