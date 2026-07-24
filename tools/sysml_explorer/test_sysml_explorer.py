"""Tests for the SysML explorer tool.

Run:  python tools/sysml_explorer/test_sysml_explorer.py -v

Covers the parser, the HTTP API, and (when Microsoft Edge is available)
end-to-end rendering of the viewer with the compartment filters.
"""

import json
import os
import re
import shutil
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
from sysml_explorer import (  # noqa: E402
    DEFAULT_VIEW_SPECS,
    __version__,
    build_default_views,
    make_handler,
    parse_models,
    parse_sysml,
    sync_default_views,
)
from sysml_explorer import app as app_mod  # noqa: E402

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
                {"text": "drive : BigMotor", "attrs": [], "isPort": False},
                {"text": "frame : Chassis", "attrs": ["length = 55.0"], "isPort": False},
            ],
        )

    def test_port_usage_flagged_isport_part_usage_is_not(self):
        model = parse_sysml("""
        package P {
            port def Iface;
            part def Widget;
            part def Box {
                port face : Iface;
                part core : Widget;
            }
        }
        """)
        self.assertEqual(
            node(model, "Box")["parts"],
            [
                {"text": "face : Iface", "attrs": [], "isPort": True},
                {"text": "core : Widget", "attrs": [], "isPort": False},
            ],
        )
        # regression test: a port is typed by its interface def, not
        # "composed of" it — a composition diamond there made the interface
        # def read as a part of everything that has one of its ports.
        self.assertEqual(
            [(e["from"], e["to"]) for e in edges_of(model, "typing")],
            # the port's interface, then the `core` usage node's own type
            [("P::Box", "P::Iface"), ("P::Box::core", "P::Widget")],
        )
        self.assertEqual(
            [(e["from"], e["to"], e["label"]) for e in edges_of(model, "composition")],
            [("P::Box", "P::Widget", "core"), ("P::Box", "P::Box::core", "")],
        )

    def test_part_usage_with_multiplicity(self):
        # optional / bounded parts must still show as nested parts and
        # composition edges (CoolSpine Kontext.csfDrain : CsfDrain [0..1])
        model = parse_sysml("""
        package P {
            part def Drain;
            part def Display;
            part def Kontext {
                part csfDrain : Drain [0..1];
                part display : Display [0..1];
                part required : Drain [1];
            }
        }
        """)
        self.assertEqual(
            node(model, "Kontext")["parts"],
            [
                {"text": "csfDrain : Drain [0..1]", "attrs": [], "isPort": False},
                {"text": "display : Display [0..1]", "attrs": [], "isPort": False},
                {"text": "required : Drain [1]", "attrs": [], "isPort": False},
            ],
        )
        comps = [(e["from"], e["to"], e["label"]) for e in edges_of(model, "composition")]
        self.assertIn(("P::Kontext", "P::Drain", "csfDrain"), comps)
        self.assertIn(("P::Kontext", "P::Display", "display"), comps)
        self.assertIn(("P::Kontext", "P::Drain", "required"), comps)

    def test_specialization_edges(self):
        specs = edges_of(self.model, "specialization")
        self.assertEqual(
            [(e["from"], e["to"]) for e in specs],
            [("TestPkg::BigMotor", "TestPkg::Motor")],
        )

    def test_composition_edges_with_role_labels(self):
        # the role-labelled edges are the ones to the part *defs*; the
        # unlabelled ones point at the per-usage nodes (see UsageNodeTests)
        comps = [e for e in edges_of(self.model, "composition") if e["label"]]
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
                # every part usage node is typed by its def
                ("TestPkg::Robot::drive", "TestPkg::BigMotor"),
                ("TestPkg::Robot::frame", "TestPkg::Chassis"),
                ("TestPkg::Chassis::w", "TestPkg::Wheel"),
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

    def test_def_with_short_name_alias_is_parsed(self):
        # regression test: `requirement def <'ID'> Name { ... }` (short name
        # on the *def*, not a usage) must be recognized like any other def —
        # it was previously silently dropped because RE_PART_DEF had no
        # allowance for the <'...'> alias, and "requirement" being a known
        # keyword meant it failed silently, with no warning
        model = parse_sysml("""
        package P {
            requirement def <'SYS-1'> TopReq {
                doc /* Top-level requirement. */
            }
            part def A { satisfy 'SYS-1'; }
        }
        """)
        req = node(model, "TopReq")
        self.assertEqual(req["kind"], "requirement def")
        self.assertEqual(req["shortName"], "SYS-1")
        self.assertEqual(req["doc"], "Top-level requirement.")
        sats = edges_of(model, "satisfy")
        self.assertEqual([(e["from"], e["to"]) for e in sats],
                         [("P::A", "P::TopReq")])
        self.assertEqual(model["warnings"], [])

    def test_satisfy_accepts_quoted_short_name(self):
        # `satisfy 'REQ-1';` is the spec-compliant spelling for hyphenated
        # short names (the only form the official parser accepts); it must
        # resolve exactly like the unquoted explorer-dialect form
        model = parse_sysml("""
        package P {
            part def A { satisfy 'R-9'; }
            requirement def Req;
            requirement <'R-9'> Nine : Req;
        }
        """)
        sats = edges_of(model, "satisfy")
        self.assertEqual([(e["from"], e["to"]) for e in sats],
                         [("P::A", "P::Nine")])
        self.assertEqual(model["warnings"], [])


class ConnectionParserTests(unittest.TestCase):
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

    def test_connection_surfaces_as_connector_edge_between_defs(self):
        # a usage-level connect/connection is really a relationship between
        # the part defs it wires together — it should show up as an
        # ordinary edge too (kind "connector"), so a block definition
        # diagram can render it whenever both defs are in the active View.
        model = parse_sysml("""
        package P {
            part def Pump;
            part def Valve;
            part def Box {
                part pump : Pump;
                part valve : Valve;
                connection flowRate : pump.out to valve.in;
            }
        }
        """)
        conns = edges_of(model, "connector")
        # once between the defs, once between the two usage nodes
        self.assertEqual(
            {(c["from"], c["to"], c["label"]) for c in conns},
            {
                ("P::Pump", "P::Valve", "flowRate · out · in"),
                ("P::Box::pump", "P::Box::valve", "flowRate · out · in"),
            },
        )
        def_edge = [c for c in conns if c["from"] == "P::Pump"][0]
        self.assertEqual(def_edge["fromUsage"], "P::Box::pump")
        self.assertEqual(def_edge["toUsage"], "P::Box::valve")


class UsageNodeTests(unittest.TestCase):
    """Every part usage is an element of its own (`Owner::role`), so two
    usages of the same type are two parts of the owner rather than one
    shared type node."""

    MODEL = """
    package P {
        part def Thermistor;
        part def Controller;
        part def Reservoir {
            part inputTempSensor : Thermistor;
            part outputTempSensor : Thermistor {
                attribute :>> offset = 0.5;
            }
            connection senseBoth
                connect inputTempSensor to outputTempSensor;
        }
    }
    """

    def setUp(self):
        self.model = parse_sysml(self.MODEL)
        self.by_id = {n["id"]: n for n in self.model["nodes"]}

    def test_each_usage_gets_its_own_node(self):
        for role in ("inputTempSensor", "outputTempSensor"):
            n = self.by_id[f"P::Reservoir::{role}"]
            self.assertEqual(n["name"], role)
            self.assertEqual(n["kind"], "part")
            self.assertEqual(n["usageOwner"], "P::Reservoir")
            self.assertEqual(n["usageType"], "Thermistor")

    def test_usage_node_is_composed_by_its_owner_and_typed_by_its_def(self):
        comps = {(e["from"], e["to"], e["label"])
                 for e in edges_of(self.model, "composition")}
        typings = {(e["from"], e["to"])
                   for e in edges_of(self.model, "typing")}
        for role in ("inputTempSensor", "outputTempSensor"):
            usage = f"P::Reservoir::{role}"
            self.assertIn(("P::Reservoir", usage, ""), comps)
            self.assertIn((usage, "P::Thermistor"), typings)
            # the type-level edge stays, tagged with the usage it stands for
            self.assertIn(("P::Reservoir", "P::Thermistor", role), comps)
        tagged = {e["label"]: e.get("usageId")
                  for e in edges_of(self.model, "composition") if e["label"]}
        self.assertEqual(tagged["inputTempSensor"],
                         "P::Reservoir::inputTempSensor")

    def test_attribute_redefinitions_land_on_the_usage_node(self):
        self.assertEqual(
            self.by_id["P::Reservoir::outputTempSensor"]["attributes"],
            ["offset = 0.5"])

    def test_connection_between_two_usages_of_one_type_separates_them(self):
        # both roles are Thermistors, so the def-level edge is a self-loop;
        # the usage-level one actually says which end is which
        conns = {(c["from"], c["to"]) for c in edges_of(self.model, "connector")}
        self.assertIn(("P::Reservoir::inputTempSensor",
                       "P::Reservoir::outputTempSensor"), conns)

    def test_role_names_do_not_pollute_type_resolution(self):
        # two defs may each have a `sensor` role; that must not make the
        # name ambiguous or shadow a def of the same name
        model = parse_sysml("""
        package P {
            part def Thermistor;
            part def A { part sensor : Thermistor; }
            part def B { part sensor : Thermistor; }
        }
        """)
        self.assertEqual(model["warnings"], [])


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

ACTIVITY_SAMPLE = """
package ActPkg {
    part def Alice;
    part def Bob;

    part def Interaction {
        part alice : Alice {
            perform run.stepOne;
        }
        part bob : Bob {
            perform run.stepTwo;
        }

        perform action run {
            action stepOne {
                doc /* Alice does the first thing. */
            }
            action stepTwo {
                doc /* Bob does the second thing. */
            }

            first start;
            then stepOne;
            then stepTwo;
            then done;
        }
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


class ActivityParserTests(unittest.TestCase):
    """`perform action <name> { ... }` swimlane activity blocks (see
    app.py's dialect notes) — the pattern used in
    examples/MedicalDevice/CoolSpineSystemContext.sysml."""

    @classmethod
    def setUpClass(cls):
        cls.model = parse_sysml(ACTIVITY_SAMPLE)

    def test_activity_resolved_under_owning_def(self):
        acts = self.model["activities"]
        self.assertEqual(len(acts), 1)
        a = acts[0]
        self.assertEqual(a["owner"], "ActPkg::Interaction")
        self.assertEqual(a["name"], "run")

    def test_nested_actions_and_their_docs(self):
        a = self.model["activities"][0]
        self.assertEqual(
            {(x["name"], x["doc"]) for x in a["actions"]},
            {("stepOne", "Alice does the first thing."),
             ("stepTwo", "Bob does the second thing.")},
        )

    def test_succession_chain_kept_in_order_including_start_done(self):
        a = self.model["activities"][0]
        self.assertEqual(a["flow"], ["start", "stepOne", "stepTwo", "done"])

    def test_swimlane_assignment_from_perform_statements(self):
        a = self.model["activities"][0]
        self.assertEqual(
            {(l["role"], l["type"], l["action"]) for l in a["lanes"]},
            {("alice", "Alice", "stepOne"), ("bob", "Bob", "stepTwo")},
        )

    def test_no_activity_when_no_perform_action_block(self):
        self.assertEqual(parse_sysml(SAMPLE)["activities"], [])

    def test_linear_flow_emits_succession_edges(self):
        a = self.model["activities"][0]
        self.assertEqual(
            [(e["from"], e["to"], e["label"]) for e in a["edges"]],
            [("start", "stepOne", ""), ("stepOne", "stepTwo", ""),
             ("stepTwo", "done", "")],
        )

    def test_decide_if_else_branches(self):
        model = parse_sysml("""
        package P {
            part def Interaction {
                perform action go {
                    action yesPath { doc /* Take it. */ }
                    then done;

                    first start;
                    then decide;
                      if yes then yesPath;
                      else done;
                }
            }
        }
        """)
        a = model["activities"][0]
        self.assertEqual(a["decisions"], ["decide"])
        self.assertEqual(
            {(e["from"], e["to"], e["label"]) for e in a["edges"]},
            {
                ("yesPath", "done", ""),
                ("start", "decide", ""),
                ("decide", "yesPath", "yes"),
                ("decide", "done", "no"),
            },
        )
        self.assertIn("decide", a["flow"])
        self.assertIn("yesPath", a["flow"])

    def test_use_case_activity_with_actor_and_subject_lanes(self):
        model = parse_sysml("""
        package P {
            part def Surgeon;
            part def Anesthesiologist;
            part def Device;

            use case def Deliver {
                subject device : Device {
                    perform go.selfCheck;
                    perform go.cool;
                }
                actor surgeon : Surgeon {
                    perform go.decide;
                }
                actor anesthesiologist : Anesthesiologist {
                    perform go.switchOn;
                    perform go.setPoint;
                }

                perform action go {
                    action decide { doc /* Decide. */ }
                    action switchOn { doc /* On. */ }
                    action selfCheck { doc /* Check. */ }
                    action setPoint { doc /* Set. */ }
                    action cool { doc /* Cool. */ }

                    first start;
                    then decide;
                    then switchOn;
                    then selfCheck;
                    then setPoint;
                    then cool;
                    then done;
                }
            }
        }
        """)
        self.assertEqual(len(model["activities"]), 1)
        a = model["activities"][0]
        self.assertEqual(a["owner"], "P::Deliver")
        self.assertEqual(a["name"], "go")
        self.assertEqual(
            a["flow"],
            ["start", "decide", "switchOn", "selfCheck", "setPoint", "cool", "done"],
        )
        self.assertEqual(
            {(l["role"], l["type"], l["action"]) for l in a["lanes"]},
            {
                ("device", "Device", "selfCheck"),
                ("device", "Device", "cool"),
                ("surgeon", "Surgeon", "decide"),
                ("anesthesiologist", "Anesthesiologist", "switchOn"),
                ("anesthesiologist", "Anesthesiologist", "setPoint"),
            },
        )
        # actor/subject swimlanes must not invent composition edges
        self.assertEqual(edges_of(model, "composition"), [])

    def test_ref_part_refers_to_an_instance_owned_elsewhere(self):
        model = parse_sysml("""
        package P {
            part def Surgeon;

            part def Kontext {
                part surgeon : Surgeon;
            }

            part def Interaction {
                ref part surgeon : Surgeon {
                    perform go.request;
                }

                perform action go {
                    action request { doc /* Request. */ }
                    first start;
                    then request;
                    then done;
                }
            }
        }
        """)
        # only the composing def contributes a usage node, so the surgeon
        # stays a singleton and is not shown twice
        self.assertEqual(
            [n["id"] for n in model["nodes"] if n.get("usageOwner")],
            ["P::Kontext::surgeon"],
        )
        self.assertNotIn(
            "P::Interaction",
            [e["from"] for e in edges_of(model, "composition")],
        )
        # the reference still carries its swimlane assignment
        act = next(a for a in model["activities"] if a["owner"] == "P::Interaction")
        self.assertEqual(
            [(l["role"], l["type"], l["action"]) for l in act["lanes"]],
            [("surgeon", "Surgeon", "request")],
        )
        self.assertEqual(model["warnings"], [])


class ValidationTests(unittest.TestCase):
    """Parser validation warnings: syntax trouble, name collisions, and
    unresolved references are reported under model["warnings"] instead of
    being dropped silently."""

    def warnings_of(self, text):
        return parse_sysml(text)["warnings"]

    def test_clean_model_has_no_warnings(self):
        self.assertEqual(parse_sysml(SAMPLE)["warnings"], [])

    def test_cross_package_name_collision_warns(self):
        w = self.warnings_of(
            "package A { part def M; } package B { part def M; }")
        self.assertEqual(len(w), 1)
        self.assertIn("ambiguous name 'M'", w[0])
        self.assertIn("A::M", w[0])
        self.assertIn("B::M", w[0])

    def test_short_name_collision_warns(self):
        w = self.warnings_of("""
        package P {
            requirement def Req;
            requirement <'R-1'> A : Req;
            requirement <'R-1'> B : Req;
        }
        """)
        self.assertTrue(any("ambiguous short name 'R-1'" in x for x in w), w)

    def test_duplicate_element_warns(self):
        w = self.warnings_of("package A { part def M; part def M; }")
        self.assertEqual(len(w), 1)
        self.assertIn("duplicate element 'A::M'", w[0])

    def test_qualified_reference_resolves_exactly_despite_collision(self):
        model = parse_sysml("""
        package A { part def M; }
        package B { part def M; part def K :> B::M; }
        """)
        specs = edges_of(model, "specialization")
        self.assertEqual([(e["from"], e["to"]) for e in specs],
                         [("B::K", "B::M")])

    def test_unresolved_satisfy_warns_and_drops_edge(self):
        model = parse_sysml("package P { part def A { satisfy NOPE; } }")
        self.assertEqual(edges_of(model, "satisfy"), [])
        self.assertEqual(len(model["warnings"]), 1)
        self.assertIn("unresolved satisfy target 'NOPE' (from P::A)",
                      model["warnings"][0])

    def test_unresolved_specialization_warns(self):
        w = self.warnings_of("package P { part def A :> Ghost; }")
        self.assertTrue(
            any("unresolved specialization target 'Ghost'" in x for x in w), w)

    def test_use_case_connection_without_from_warns(self):
        w = parse_sysml(UCD_SAMPLE)["warnings"]
        self.assertEqual(len(w), 1)
        self.assertIn("use case connection dropped", w[0])
        self.assertIn("noFrom", w[0])

    def test_typo_keyword_warns_as_unrecognized(self):
        w = self.warnings_of("package P { part def A { atribute x : Real; } }")
        self.assertEqual(len(w), 1)
        self.assertIn("unrecognized statement", w[0])
        self.assertIn("atribute x : Real", w[0])

    def test_known_but_unrendered_constructs_stay_silent(self):
        # constraints, states, subjects, ... are valid SysML the tool
        # doesn't render — skipping them is not a validation problem
        w = self.warnings_of("""
        package P {
            part def A {
                subject : A;
                constraint c { x > 1 }
                state def Off;
                perform action go;
            }
        }
        """)
        self.assertEqual(w, [])

    def test_unclosed_brace_warns(self):
        w = self.warnings_of("package P { part def A {")
        self.assertTrue(any("unclosed '{'" in x for x in w), w)

    def test_unexpected_closing_brace_warns_with_line(self):
        w = self.warnings_of("package P { }\n}")
        self.assertEqual(len(w), 1)
        self.assertIn("unexpected '}' at line 2", w[0])

    def test_warnings_prefixed_with_file_name(self):
        w = parse_models(
            ["package P { part def A { satisfy NOPE; } }",
             "package Q { blob X; }"],
            names=["arch.sysml", "reqs.sysml"],
        )["warnings"]
        self.assertTrue(any(x.startswith("reqs.sysml: unrecognized") for x in w), w)
        # resolution happens after the merge, so unresolved-reference
        # warnings are model-level (no file prefix) but name the source id
        self.assertTrue(
            any("unresolved satisfy target 'NOPE' (from P::A)" in x for x in w), w)


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

    def run_check(self, folder):
        env = dict(os.environ, PYTHONPATH=self.SRC)
        return subprocess.run(
            [sys.executable, "-m", "sysml_explorer", str(folder), "--check"],
            capture_output=True, text=True, timeout=30, env=env,
        )

    def test_check_passes_clean_model(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "m.sysml").write_text(SAMPLE, encoding="utf-8")
            out = self.run_check(d)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertIn("no warnings", out.stdout)

    def test_check_reports_warnings_and_fails(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "m.sysml").write_text(
                "package P { part def A { satisfy NOPE; } }", encoding="utf-8")
            out = self.run_check(d)
            self.assertEqual(out.returncode, 1)
            self.assertIn("unresolved satisfy target 'NOPE'", out.stdout)
            self.assertIn("1 warning(s)", out.stderr)

    def test_missing_folder_errors_out(self):
        out = self.run_print("no_such_folder_xyz")
        self.assertNotEqual(out.returncode, 0)


@unittest.skipUnless(
    os.environ.get("SYSML_OFFICIAL_CHECK_TEST"),
    "set SYSML_OFFICIAL_CHECK_TEST=1 to run the official-parser test "
    "(kernel startup can take many minutes)")
@unittest.skipUnless(shutil.which("conda"), "conda not found; skipping official-parser test")
class OfficialParserCheckTests(unittest.TestCase):
    """official_check.py drives the OMG pilot implementation (the reference
    SysML v2 parser) through its Jupyter kernel, expected in a conda env
    named "sysml" (see README, "Setting up the validation parsers").
    Opt-in via SYSML_OFFICIAL_CHECK_TEST=1 because kernel startup
    (standard-library loading, antivirus scanning) can take 10+ minutes —
    too slow for the default suite; skips anyway when conda or the env is
    missing."""

    SCRIPT = str(Path(__file__).parent / "official_check.py")

    @classmethod
    def setUpClass(cls):
        # resolve the env's python via a short-lived `conda run` probe, then
        # invoke it DIRECTLY for the real check: a long-running `conda run`
        # never drains the kernel JVM's console output, the pipe fills, and
        # the whole run deadlocks (observed twice, 30-minute hangs)
        conda = shutil.which("conda")
        probe = subprocess.run(
            [conda, "run", "-n", "sysml", "python", "-c",
             "import jupyter_client, sys; print(sys.executable)"],
            capture_output=True, text=True, timeout=120,
        )
        if probe.returncode != 0 or not probe.stdout.strip():
            raise unittest.SkipTest(
                "conda env 'sysml' with the official kernel not found")
        cls.python = probe.stdout.strip().splitlines()[-1]

    def test_reference_diagnostics_per_file_and_exit_code(self):
        with tempfile.TemporaryDirectory() as d:
            # "block" is SysML v1 — the official grammar must reject it
            (Path(d) / "bad.sysml").write_text(
                "package Q { block B; }", encoding="utf-8")
            (Path(d) / "good.sysml").write_text(
                "package P { part def A; }", encoding="utf-8")
            out = subprocess.run(
                [self.python, self.SCRIPT, d],
                capture_output=True, text=True, timeout=1800,
            )
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("good.sysml: OK", out.stdout)
        self.assertIn("bad.sysml", out.stdout)
        self.assertIn("ERROR", out.stdout + out.stderr)


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

    def test_package_version_is_0_0_1(self):
        self.assertEqual(__version__, "0.0.1")
        self.assertEqual(app_mod.__version__, "0.0.1")

    def test_root_injects_explorer_version_into_toolbar(self):
        page = self.srv.get("/")
        self.assertIn('id="appVersion"', page)
        self.assertIn(f"v{__version__}", page)
        self.assertNotIn("{{EXPLORER_VERSION}}", page)

    def test_model_endpoint_includes_explorer_version(self):
        model = json.loads(self.srv.get("/api/model"))
        self.assertEqual(model["explorerVersion"], __version__)

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

    def test_root_serves_doc_link_file_browser(self):
        # "Add documentation link" opens a modal with a folder browser
        # (see openDocDialog/openFileBrowser in viewer.html) instead of a
        # plain prompt(); check the machinery shipped in the page.
        page = self.srv.get("/")
        self.assertIn("function openDocDialog(id, initial)", page)
        self.assertIn("function openFileBrowser(onPick, onCancel)", page)
        self.assertIn("/api/browse?path=", page)
        self.assertIn('id="modalOverlay"', page)

    def test_root_serves_clarity_sprint_chrome(self):
        # Phase-1 explorer chrome: Display/More menus, tree search + kind
        # chips, empty-view hint, and per-View display option helpers.
        page = self.srv.get("/")
        self.assertIn('id="displayMenu"', page)
        self.assertIn('id="moreMenu"', page)
        self.assertIn('id="treeSearch"', page)
        self.assertIn('id="treeKinds"', page)
        self.assertIn('id="emptyHint"', page)
        self.assertIn("function displayOpts()", page)
        self.assertIn("function applyDisplayOpts(opts)", page)
        self.assertIn("function updateEmptyHint()", page)
        self.assertIn("const VIEW_VERSION = 1", page)
        self.assertIn("const LAYOUT_VERSION = 1", page)
        self.assertIn('id="keywordsCb"', page)
        self.assertIn('id="packagesCb"', page)
        self.assertIn('id="docsOnNodeCb"', page)

    def test_model_endpoint_parses_file(self):
        model = json.loads(self.srv.get("/api/model"))
        self.assertEqual(model["package"], "TestPkg")
        self.assertEqual(model["file"], "model.sysml")

    def test_model_endpoint_includes_warnings(self):
        # SAMPLE is a clean model: the warnings key is present and empty
        model = json.loads(self.srv.get("/api/model"))
        self.assertEqual(model["warnings"], [])

    def test_model_endpoint_warnings_carry_file_name(self):
        with ServerFixture(text="package P { part def A { blob x; } }") as srv:
            model = json.loads(srv.get("/api/model"))
            self.assertEqual(len(model["warnings"]), 1)
            self.assertIn("model.sysml: unrecognized statement",
                          model["warnings"][0])

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

    def test_browse_endpoint_lists_root_folder(self):
        # the model folder always has model.sysml (from ServerFixture) plus
        # a views/ subfolder (auto-seeded); dirs sort before files
        data = json.loads(self.srv.get("/api/browse?path="))
        self.assertEqual(data["path"], "")
        names = {e["name"]: e["isDir"] for e in data["entries"]}
        self.assertTrue(names.get("views"))
        self.assertIn("model.sysml", names)
        self.assertFalse(names["model.sysml"])

    def test_browse_endpoint_lists_subfolder(self):
        srv = ServerFixture()
        try:
            sub = Path(srv.dir.name) / "docs"
            sub.mkdir()
            (sub / "spec.pdf").write_bytes(b"%PDF-1.4")
            data = json.loads(srv.get("/api/browse?path=docs"))
            self.assertEqual(data["path"], "docs")
            self.assertEqual(
                [e["name"] for e in data["entries"]], ["spec.pdf"])
        finally:
            srv.close()

    def test_browse_endpoint_rejects_path_traversal(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.srv.get_raw("/api/browse?path=..")
        self.assertEqual(ctx.exception.code, 404)

    def test_browse_endpoint_missing_folder_is_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.srv.get_raw("/api/browse?path=nope")
        self.assertEqual(ctx.exception.code, 404)

    def test_browse_endpoint_rejects_file_path(self):
        # path must resolve to a directory, not a file
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.srv.get_raw("/api/browse?path=model.sysml")
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
        self.assertEqual(view, {"version": 1, "name": "Empty", "elements": [],
                                 "nodes": {}, "hiddenEdges": [], "view": None,
                                 "options": {}})

    def test_create_view_includes_schema_version(self):
        created = json.loads(self.srv.post("/api/views", {"name": "V"}))
        view = json.loads(self.srv.get(f"/api/views/{created['id']}"))
        self.assertEqual(view["version"], 1)

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
    # server URLs are bare origins and need the trailing slash; a file:// URL
    # of a harness page (see run_js) is already complete
    if not url.endswith(("/", ".html")):
        url += "/"
    out = subprocess.run(
        [EDGE, "--headless", "--disable-gpu", "--virtual-time-budget=3000",
         "--dump-dom", url],
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
        all_elements = [n["id"] for n in parse_sysml(SAMPLE)["nodes"]
                        if not n.get("usageOwner")]
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
        # Display → keywords defaults to false: no keyword header lines
        # (the only class="stereo" texts) while node titles still render.
        # Don't grep for «part def» itself — the JS source in the dump
        # legitimately mentions it in a comment / checkbox label.
        dom = self.render(True, True)
        self.assertNotIn('class="stereo"', dom)
        self.assertIn(">Robot</text>", dom)

    def test_package_paths_hidden_by_default(self):
        # Display → package paths off by default (DISPLAY_DEFAULTS.packages).
        # Match SVG node package lines only — the element tree also uses
        # class="pkg" for package *headers*, which must still render.
        dom = self.render(True, True)
        self.assertNotIn('<text class="pkg"', dom)

    def test_keywords_option_shows_stereo(self):
        all_elements = [n["id"] for n in parse_sysml(SAMPLE)["nodes"]
                        if not n.get("usageOwner")]
        view = {"name": "Default", "elements": all_elements, "nodes": {},
                "hiddenEdges": [], "view": None,
                "options": {"attrs": True, "parts": True, "keywords": True}}
        (self.srv.views_dir / "default.json").write_text(
            json.dumps(view), encoding="utf-8")
        dom = dump_dom(self.srv.url)
        self.assertIn('class="stereo"', dom)

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

    def serve(self, views, active, extra_layout=None, text=SAMPLE):
        srv = ServerFixture(text=text, views=views)
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

    def test_connector_edge_rendered_when_both_connected_defs_are_members(self):
        views = {"v": self.make_view("V", ["TestPkg::BigMotor", "TestPkg::Chassis"])}
        with self.serve(views, "v") as srv:
            self.assertIn('class="edge connector"', dump_dom(srv.url))

    def test_connector_edge_label_shown_even_though_other_labels_are_not(self):
        # unlike composition/typing/satisfy, a connector's label is its only
        # informational content, so it's exempt from the edge-labels Display
        # toggle that hides other edge kinds' labels by default (see
        # test_edge_labels_hidden_by_default above)
        views = {"v": self.make_view("V", ["TestPkg::BigMotor", "TestPkg::Chassis"])}
        with self.serve(views, "v") as srv:
            self.assertIn(">driveLink · shaft · mount</text>", dump_dom(srv.url))

    def test_connector_edge_not_rendered_when_one_connected_def_missing(self):
        views = {"v": self.make_view("V", ["TestPkg::BigMotor"])}
        with self.serve(views, "v") as srv:
            self.assertNotIn('class="edge connector"', dump_dom(srv.url))

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

    def test_empty_view_shows_hint(self):
        views = {"v": self.make_view("Blank", [])}
        with self.serve(views, "v") as srv:
            dom = dump_dom(srv.url)
            # hint element is present and not hidden when the View has no members
            self.assertRegex(dom, r'<div id="emptyHint"(?! class="hidden")[^>]*>')
            self.assertIn("Check elements in the tree", dom)

    def test_nonempty_view_hides_empty_hint(self):
        views = {"v": self.make_view("V", ["TestPkg::Motor"])}
        with self.serve(views, "v") as srv:
            self.assertIn('id="emptyHint" class="hidden"', dump_dom(srv.url))

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

    def test_singleton_usage_collapsed_when_def_also_a_member(self):
        # BigMotor has one usage (drive). Both members → only the def box.
        elements = ["TestPkg::Robot", "TestPkg::Robot::drive", "TestPkg::BigMotor"]
        with self.serve({"v": self.make_view("V", elements)}, "v") as srv:
            dom = dump_dom(srv.url)
            self.assertNotIn('data-id="TestPkg::Robot::drive"', dom)
            self.assertIn('data-id="TestPkg::BigMotor"', dom)
            # type-level composition kept (usage not drawn)
            self.assertIn(
                'data-key="composition|TestPkg::Robot|TestPkg::BigMotor|drive"',
                dom)
            self.assertNotIn('data-key="typing|TestPkg::Robot::drive'
                             '|TestPkg::BigMotor|"', dom)

    def test_singleton_usage_shown_when_def_not_a_member(self):
        elements = ["TestPkg::Robot", "TestPkg::Robot::drive"]
        with self.serve({"v": self.make_view("V", elements)}, "v") as srv:
            dom = dump_dom(srv.url)
            self.assertIn('data-id="TestPkg::Robot::drive"', dom)
            self.assertIn('data-key="composition|TestPkg::Robot'
                          '|TestPkg::Robot::drive|"', dom)

    def test_multi_usage_type_still_draws_each_usage_with_def(self):
        # Thermistor has two usages — both stay visible next to the def.
        elements = [
            "P::Reservoir",
            "P::Reservoir::inputTempSensor",
            "P::Reservoir::outputTempSensor",
            "P::Thermistor",
        ]
        with self.serve(
                {"v": self.make_view("V", elements)}, "v",
                text=UsageNodeTests.MODEL) as srv:
            dom = dump_dom(srv.url)
            self.assertIn('data-id="P::Reservoir::inputTempSensor"', dom)
            self.assertIn('data-id="P::Reservoir::outputTempSensor"', dom)
            self.assertIn('data-id="P::Thermistor"', dom)
            self.assertIn(
                'data-key="typing|P::Reservoir::inputTempSensor|P::Thermistor|"',
                dom)

    def test_usage_node_looks_like_part_def_and_hides_type_in_header(self):
        # part usages share part-def styling; header is role only. Omit the
        # type def so singleton collapse does not hide the usage node.
        elements = ["TestPkg::Robot::drive"]
        with self.serve({"v": self.make_view("V", elements)}, "v") as srv:
            dom = dump_dom(srv.url)
            self.assertRegex(
                dom,
                r'<g class="node"[^>]*data-id="TestPkg::Robot::drive"')
            self.assertNotRegex(
                dom,
                r'<g class="node usage"[^>]*data-id="TestPkg::Robot::drive"')
            self.assertIn(">drive</text>", dom)
            self.assertNotIn("drive : BigMotor", dom)

    def test_type_level_edge_dropped_once_multi_usage_node_is_shown(self):
        # singleton collapse would keep the type-level edge; use a type with
        # two usages so drawing one usage actually drops its type-level edge.
        type_key = (
            'data-key="composition|P::Reservoir|P::Thermistor|inputTempSensor"')
        elements = ["P::Reservoir", "P::Thermistor"]
        with self.serve(
                {"v": self.make_view("V", elements)}, "v",
                text=UsageNodeTests.MODEL) as srv:
            self.assertIn(type_key, dump_dom(srv.url))
        with self.serve(
                {"v": self.make_view(
                    "V", elements + ["P::Reservoir::inputTempSensor"])}, "v",
                text=UsageNodeTests.MODEL) as srv:
            self.assertNotIn(type_key, dump_dom(srv.url))

    def test_edge_labels_hidden_by_default(self):
        # Display → edge labels defaults to false: no role-name text on the
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
        all_elements = [n["id"] for n in parse_sysml(SAMPLE)["nodes"]
                        if not n.get("usageOwner")]
        with self.serve({"v": self.make_view("All", all_elements)}, "v") as srv:
            # specialization, composition, typing, satisfy, and now connector
            # (BigMotor/Chassis's derived connector edge — see ConnectionParserTests)
            self.assertEqual(self.legend_rows(dump_dom(srv.url)), 5)
        # Reqs subpackage only: Req/Fast, connected by a single typing edge
        reqs = {"v": self.make_view(
            "Reqs", ["TestPkg::Reqs::Req", "TestPkg::Reqs::Fast"])}
        with self.serve(reqs, "v") as srv2:
            dom = dump_dom(srv2.url)
            self.assertEqual(self.legend_rows(dom), 1)
            self.assertIn("is a", dom.split('id="legend"')[1][:400])

    def test_bootstrap_creates_default_view_seeded_with_all_elements(self):
        # a folder with no views/ at all gets one auto-created on first
        # launch, pre-populated so the canvas isn't blank
        with ServerFixture(views={}) as srv:
            self.assertEqual(dump_dom(srv.url).count('class="node'), 8)
            self.assertEqual(json.loads(srv.get("/api/views")),
                              [{"id": "default", "name": "Default"}])


@unittest.skipUnless(EDGE, "Microsoft Edge not found; skipping rendering tests")
class WarningBannerRenderingTests(unittest.TestCase):
    """Validation warnings surface in the viewer: a ⚠ counter in the
    toolbar and the messages in the (initially hidden) warnings banner."""

    def test_warning_counter_and_banner_content(self):
        bad = "package P { part def A { satisfy MISSING; } }"
        with ServerFixture(text=bad) as srv:
            dom = dump_dom(srv.url)
        self.assertIn("⚠ 1", dom)
        self.assertIn("unresolved satisfy target 'MISSING'", dom)

    def test_clean_model_hides_warning_button(self):
        with ServerFixture() as srv:  # SAMPLE is warning-free
            dom = dump_dom(srv.url)
        # button stays hidden and empty: no "⚠ <count>" text anywhere
        self.assertNotRegex(dom, r"⚠ \d")


def dump_edge_count(dom):
    return dom.count('class="edge')


def node_segment(dom, node_id):
    """Slice of the DOM covering one node's <g class="node...">, from its
    own opening tag up to the next node's opening tag (or the layer's end).
    Good enough for a containment check (e.g. "does this node have the UCD
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

    def test_tree_lists_every_element_and_package_header(self):
        dom = self.render()
        # singleton part usages (robot1, drive, …) are hidden — defs only
        for name in ["Motor", "BigMotor", "Wheel", "Chassis", "Robot",
                     "Req", "Fast"]:
            elem_row(dom, name)  # raises if the row is missing
        with self.assertRaises(AssertionError):
            elem_row(dom, "robot1")
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
        # parts match part defs (uncolored); no k-usage tint
        self.assertNotIn("k-req", elem_row(dom, "Motor"))
        self.assertNotIn("k-usage", elem_row(dom, "Motor"))

    def test_tree_hides_singleton_part_usages_keeps_multi_usages(self):
        with ServerFixture(text=UsageNodeTests.MODEL, views={
            "v": {"name": "V", "elements": ["P::Thermistor"], "nodes": {},
                  "hiddenEdges": [], "view": None, "options": {}},
        }) as srv:
            srv.layout_path.write_text(
                json.dumps({"activeView": "v"}), encoding="utf-8")
            dom = dump_dom(srv.url)
            # two Thermistor roles stay listed; a one-off Controller role
            # would be hidden — Controller has no usage in this fixture
            elem_row(dom, "inputTempSensor")
            elem_row(dom, "outputTempSensor")
            elem_row(dom, "Thermistor")

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
class TreeCheckboxPositionPersistenceTests(unittest.TestCase):
    """Unchecking an element's tree checkbox (hiding it) must not forget its
    saved canvas position — re-checking it later should restore the same
    spot, not drop it back into auto-layout."""

    RENDER_TREE_ELEM_JS = None

    @classmethod
    def setUpClass(cls):
        cls.RENDER_TREE_ELEM_JS = viewer_js(
            "function renderTreeElem", "function allElemsUnder")

    def toggle_checkbox(self, checked):
        setup = (
            'let mode = "bdd";\n'
            'let activeView = { elements: ["TestPkg::Motor"],\n'
            '                    nodes: { "TestPkg::Motor": { x: 111, y: 222 } } };\n'
            'let nodes = {};\n'
            'function posMap() { return activeView.nodes; }\n'
            'function rebuild() {}\n'
            'function setDirty() {}\n'
            'function treeDotClass() { return ""; }\n'
            'function selectNode() {}\n'
            'function centerOn() {}\n'
            + self.RENDER_TREE_ELEM_JS
            + '\nrenderTreeElem({ id: "TestPkg::Motor", name: "Motor", kind: "part" },'
              ' document.body);\n'
              'const cb = document.querySelector(\'input[type="checkbox"]\');\n'
            + f'cb.checked = {"true" if checked else "false"};\n'
            + 'cb.dispatchEvent(new Event("change"));\n'
        )
        return run_js(setup, "activeView.nodes")

    def test_unchecking_keeps_the_saved_position(self):
        nodes = self.toggle_checkbox(checked=False)
        self.assertEqual(nodes.get("TestPkg::Motor"), {"x": 111, "y": 222})

    def test_rechecking_also_keeps_the_saved_position(self):
        # checking an already-checked box (no membership change) must be a
        # no-op on the stored position too
        nodes = self.toggle_checkbox(checked=True)
        self.assertEqual(nodes.get("TestPkg::Motor"), {"x": 111, "y": 222})


CONNECTOR_SAMPLE = """
package ConnPkg {
    part def Pump;
    part def Valve;
    part def Box {
        part pump : Pump;
        part valve : Valve;
        connection flowRate : pump.out to valve.in;
    }
}
"""


@unittest.skipUnless(EDGE, "Microsoft Edge not found; skipping rendering tests")
class ConnectorRenderingTests(unittest.TestCase):
    """A `connect`/`connection` statement inside a part def is really a
    relationship between the part defs it wires together, so it surfaces as
    a connector edge directly in the block definition diagram — no separate
    drilldown mode needed to see it."""

    @classmethod
    def setUpClass(cls):
        cls.srv = ServerFixture(text=CONNECTOR_SAMPLE)

    @classmethod
    def tearDownClass(cls):
        cls.srv.close()

    def test_connector_edge_and_legend_row_shown_in_bdd_view(self):
        dom = dump_dom(self.srv.url)
        self.assertIn('class="edge connector"', dom)
        legend = dom.split('id="legend"')[1].split('<svg id="canvas"')[0]
        self.assertIn("connector", legend)


@unittest.skipUnless(EDGE, "Microsoft Edge not found; skipping rendering tests")
class UcdRenderingTests(unittest.TestCase):
    """Use case diagram mode, entered via the persisted layout
    (mode/ucdOwner)."""

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
        self.assertIn("none", self.button_tag(bdd_dom, "drilldownBackBtn"))
        self.assertNotIn("none", self.button_tag(ucd_dom, "drilldownBackBtn"))

    def test_unknown_ucd_owner_falls_back_to_bdd(self):
        dom = self.render({"nodes": {}, "selectedPackage": None,
                           "mode": "ucd", "ucdOwner": "UcdPkg::NoSuchSubject"})
        self.assertIn("none", self.button_tag(dom, "drilldownBackBtn"))

    def test_tree_disabled_while_in_ucd_mode(self):
        classes = tree_classes(self.render(self.UCD_LAYOUT))
        self.assertIn("disabled", classes)

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


@unittest.skipUnless(EDGE, "Microsoft Edge not found; skipping rendering tests")
class ActivityRenderingTests(unittest.TestCase):
    """Activity diagram mode, entered via the persisted layout
    (mode/activityOwner)."""

    @classmethod
    def setUpClass(cls):
        cls.srv = ServerFixture(ACTIVITY_SAMPLE)

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

    ACTIVITY_LAYOUT = {"nodes": {}, "selectedPackage": None,
                       "mode": "activity", "activityOwner": "ActPkg::Interaction"}
    BDD_LAYOUT = {"nodes": {}, "selectedPackage": None}

    def test_activity_shows_action_and_control_boxes_not_the_owner(self):
        dom = self.render(self.ACTIVITY_LAYOUT)
        self.assertIn(">stepOne</text>", dom)
        self.assertIn(">stepTwo</text>", dom)
        self.assertIn(">▶ start</text>", dom)
        self.assertNotIn(">Interaction</text>", dom)

    def test_flow_edges_connect_the_succession_chain(self):
        # start->stepOne, stepOne->stepTwo, stepTwo->done
        dom = self.render(self.ACTIVITY_LAYOUT)
        self.assertEqual(dom.count('class="edge flow"'), 3)

    def test_decision_diamond_and_yes_no_labels(self):
        sample = """
        package DecPkg {
            part def Interaction {
                perform action go {
                    action yesPath;
                    then done;
                    first start;
                    then decide;
                      if yes then yesPath;
                      else done;
                }
            }
        }
        """
        srv = ServerFixture(sample)
        try:
            srv.layout_path.write_text(json.dumps({
                "nodes": {}, "selectedPackage": None,
                "mode": "activity", "activityOwner": "DecPkg::Interaction",
            }), encoding="utf-8")
            dom = dump_dom(srv.url)
            self.assertIn('class="node decision', dom)
            self.assertIn(">yes</text>", dom)
            self.assertIn(">no</text>", dom)
            # start->decide, decide->yesPath, decide->done, yesPath->done
            self.assertEqual(dom.count('class="edge flow"'), 4)
        finally:
            srv.close()

    def test_lane_labels_shown_for_performing_roles(self):
        dom = self.render(self.ACTIVITY_LAYOUT)
        self.assertIn(">alice<", dom)
        self.assertIn(">bob<", dom)

    def test_lanes_are_vertical_columns(self):
        # each swimlane is a tall column (height > width), not a wide row
        dom = self.render(self.ACTIVITY_LAYOUT)
        rects = re.findall(
            r'<g class="lane">\s*<rect[^>]*\bwidth="([^"]+)"[^>]*\bheight="([^"]+)"'
            r'|<g class="lane">\s*<rect[^>]*\bheight="([^"]+)"[^>]*\bwidth="([^"]+)"',
            dom,
        )
        self.assertGreaterEqual(len(rects), 2, "expected alice and bob lanes")
        for m in rects:
            w = float(m[0] or m[3])
            h = float(m[1] or m[2])
            self.assertGreater(h, w, f"lane should be vertical (h={h} w={w})")

    def test_actions_locked_to_distinct_lane_x(self):
        # alice/stepOne and bob/stepTwo get different data-lane-x; drag code
        # keeps x at that value so actions cannot change swimlane
        dom = self.render(self.ACTIVITY_LAYOUT)
        step_one = node_segment(dom, "ActPkg::Interaction::act::stepOne")
        step_two = node_segment(dom, "ActPkg::Interaction::act::stepTwo")
        x1 = re.search(r'data-lane-x="([^"]+)"', step_one)
        x2 = re.search(r'data-lane-x="([^"]+)"', step_two)
        self.assertIsNotNone(x1, step_one)
        self.assertIsNotNone(x2, step_two)
        self.assertNotEqual(x1.group(1), x2.group(1))

    def test_back_button_shown_only_in_activity_mode(self):
        bdd_dom = self.render(self.BDD_LAYOUT)
        act_dom = self.render(self.ACTIVITY_LAYOUT)
        self.assertIn("none", self.button_tag(bdd_dom, "drilldownBackBtn"))
        self.assertNotIn("none", self.button_tag(act_dom, "drilldownBackBtn"))

    def test_unknown_activity_owner_falls_back_to_bdd(self):
        dom = self.render({"nodes": {}, "selectedPackage": None,
                           "mode": "activity", "activityOwner": "ActPkg::NoSuch"})
        self.assertIn("none", self.button_tag(dom, "drilldownBackBtn"))

    def test_activity_icon_shown_on_owner_element(self):
        dom = self.render(self.BDD_LAYOUT)
        self.assertIn('class="activityicon"',
                       node_segment(dom, "ActPkg::Interaction"))

    def test_activity_icon_not_shown_on_element_without_activity(self):
        dom = self.render(self.BDD_LAYOUT)
        self.assertNotIn('class="activityicon"', node_segment(dom, "ActPkg::Alice"))


VIEWER_HTML = Path(__file__).parent / "src" / "sysml_explorer" / "viewer.html"


def viewer_js(start_marker, end_marker):
    """The slice of viewer.html's script between two source markers.

    Lets a test run a piece of the viewer's own JavaScript standalone,
    against stubs, instead of only asserting that its source is shipped.
    """
    src = VIEWER_HTML.read_text(encoding="utf-8")
    start = src.index(start_marker)
    return src[start:src.index(end_marker, start)]


def run_js(setup, expr):
    """Evaluate `expr` in a headless page with `setup` JS run first.

    Returns the parsed JSON of `expr`. The page is a local file, so no
    server is involved — used for viewer logic that a right-click would
    normally drive (which --dump-dom can't simulate).
    """
    page = (
        "<!doctype html><body><pre id=\"out\"></pre><script>\n"
        + setup
        + "\ndocument.getElementById('out').textContent = "
        + f"JSON.stringify({expr});\n</script></body>"
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "harness.html"
        path.write_text(page, encoding="utf-8")
        dom = dump_dom(path.resolve().as_uri())
    body = re.search(r'<pre id="out">(.*?)</pre>', dom, re.S).group(1)
    for esc, ch in (("&quot;", '"'), ("&lt;", "<"), ("&gt;", ">"), ("&amp;", "&")):
        body = body.replace(esc, ch)
    return json.loads(body)


@unittest.skipUnless(EDGE, "Microsoft Edge not found; skipping rendering tests")
class RelatedElementsMenuTests(unittest.TestCase):
    """The element context menu's "Show ..." actions, which pull an
    element's decomposition / specializations / satisfy links into the
    active View. The menu-building code runs standalone against stubs."""

    RELATED_JS = None   # filled in by setUpClass

    @classmethod
    def setUpClass(cls):
        cls.RELATED_JS = viewer_js("// ------------------------------------------------- related-element lookup",
                                   "// future element actions")
        cls.model_json = json.dumps(parse_sysml(SAMPLE))

    def setup_js(self, members):
        return (
            f"const model = {self.model_json};\n"
            f"let activeView = {{ elements: {json.dumps(members)} }};\n"
            "function visibleIds() { return new Set(activeView.elements); }\n"
            "function rebuild() {}\n"
            "function setDirty() {}\n"
            + self.RELATED_JS
        )

    def groups(self, id_, members=()):
        return run_js(self.setup_js(list(members)), f"relatedGroups({json.dumps(id_)})")

    def labels(self, id_, members=()):
        items = run_js(self.setup_js(list(members)),
                       f"relatedMenuItems({json.dumps(id_)})"
                       ".map(i => [i.label, !!i.disabled])")
        return items

    def test_decomposition_group_is_transitive(self):
        [decomp, _, _, _] = self.groups("TestPkg::Robot")
        self.assertEqual(decomp["label"], "decomposition")
        # Robot -> BigMotor, Chassis -> Wheel (a level below Chassis)
        self.assertEqual(sorted(decomp["ids"]),
                         ["TestPkg::BigMotor", "TestPkg::Chassis", "TestPkg::Wheel"])

    def test_specializations_group_lists_subtypes_not_supertypes(self):
        [_, _, spec, _] = self.groups("TestPkg::Motor")
        self.assertEqual(spec["ids"], ["TestPkg::BigMotor"])
        # the other direction stays empty: BigMotor has no subtypes
        self.assertEqual(self.groups("TestPkg::BigMotor")[2]["ids"], [])

    def test_satisfy_group_lists_the_requirement_a_part_satisfies(self):
        [_, _, _, sat] = self.groups("TestPkg::Motor")
        self.assertEqual(sat["label"], "satisfied requirements")
        self.assertEqual(sat["ids"], ["TestPkg::Reqs::Fast"])

    def test_satisfy_group_on_a_requirement_lists_its_satisfiers(self):
        [_, _, _, sat] = self.groups("TestPkg::Reqs::Fast")
        self.assertEqual(sat["label"], "satisfying elements")
        self.assertEqual(sat["ids"], ["TestPkg::Motor"])

    def test_unrelated_edge_kinds_are_ignored(self):
        # Wheel is only ever a composition target; robot1 types Robot and
        # BigMotor has a connector to Chassis — neither is "related"
        self.assertEqual([g["ids"] for g in self.groups("TestPkg::Wheel")],
                         [[], [], [], []])
        self.assertEqual(self.groups("TestPkg::BigMotor")[0]["ids"], [])

    def test_menu_counts_only_what_the_view_is_missing(self):
        labels = dict(self.labels("TestPkg::Robot", ["TestPkg::Robot"]))
        self.assertIn("Show decomposition (3)", labels)
        labels = dict(self.labels("TestPkg::Robot",
                                  ["TestPkg::Robot", "TestPkg::Chassis"]))
        self.assertIn("Show decomposition (2)", labels)

    def test_menu_item_disabled_when_nothing_to_add(self):
        labels = dict(self.labels("TestPkg::Wheel", ["TestPkg::Wheel"]))
        self.assertTrue(labels["Show decomposition (0)"])
        self.assertTrue(labels["Show all related (0)"])

    def test_show_all_related_unions_the_groups_without_duplicates(self):
        labels = [l for l, _ in self.labels("TestPkg::Motor", ["TestPkg::Motor"])]
        self.assertEqual(labels[-1], "Show all related (2)")   # BigMotor + Fast

    def test_action_adds_the_missing_ids_to_the_view(self):
        elements = run_js(
            self.setup_js(["TestPkg::Robot"]),
            "(() => { relatedMenuItems('TestPkg::Robot')"
            ".find(i => i.label.startsWith('Show decomposition')).action();"
            " return activeView.elements; })()",
        )
        self.assertEqual(sorted(elements),
                         ["TestPkg::BigMotor", "TestPkg::Chassis",
                          "TestPkg::Robot", "TestPkg::Wheel"])


EXAMPLE_DIR = Path(__file__).resolve().parents[2] / "examples" / "MedicalDevice"


class DefaultViewTests(unittest.TestCase):
    """The three standard Views (Context / Decomposition /
    Interconnections). They are hand-authored JSON today;
    build_default_views() is the placeholder that will generate them from
    the parsed model, and sync_default_views() the hook that writes them."""

    def test_specs_are_the_three_standard_views(self):
        self.assertEqual([s["id"] for s in DEFAULT_VIEW_SPECS],
                         ["context", "decomposition", "interconnections"])
        self.assertEqual([s["name"] for s in DEFAULT_VIEW_SPECS],
                         ["1 Context", "2 Decomposition", "3 Interconnections"])

    def test_every_spec_documents_what_the_view_shows(self):
        for spec in DEFAULT_VIEW_SPECS:
            self.assertTrue(spec["doc"].strip(), spec["id"])

    def test_build_is_still_a_placeholder(self):
        # update this test together with the implementation
        self.assertEqual(build_default_views({"nodes": [], "edges": []}), [])

    def test_sync_writes_nothing_while_build_is_a_placeholder(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            self.assertEqual(sync_default_views(folder, {"nodes": [], "edges": []}), [])
            self.assertFalse((folder / "views").exists())

    def test_sync_writes_generated_views(self):
        generated = [{"id": "context", "name": "1 Context", "elements": ["P::A"],
                      "nodes": {}, "hiddenEdges": [], "view": None, "options": {}}]
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            orig = app_mod.build_default_views
            app_mod.build_default_views = lambda model, f=None: generated
            try:
                self.assertEqual(sync_default_views(folder, {}), ["context"])
            finally:
                app_mod.build_default_views = orig
            written = json.loads((folder / "views" / "context.json").read_text())
            self.assertEqual(written["name"], "1 Context")
            self.assertEqual(written["version"], 1)   # stamped if absent
            self.assertNotIn("id", written)           # id names the file only

    def test_sync_never_clobbers_a_hand_made_view(self):
        # only ids listed in DEFAULT_VIEW_SPECS may be written, so a
        # generator bug can't overwrite a View the user built by hand
        generated = [{"id": "my-own-view", "name": "Mine", "elements": [],
                      "nodes": {}, "hiddenEdges": [], "view": None, "options": {}}]
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "views").mkdir()
            mine = folder / "views" / "my-own-view.json"
            mine.write_text('{"name": "Mine", "elements": ["keep::me"]}')
            orig = app_mod.build_default_views
            app_mod.build_default_views = lambda model, f=None: generated
            try:
                self.assertEqual(sync_default_views(folder, {}), [])
            finally:
                app_mod.build_default_views = orig
            self.assertEqual(json.loads(mine.read_text())["elements"], ["keep::me"])


@unittest.skipUnless(EXAMPLE_DIR.is_dir(), "MedicalDevice example not present")
class MedicalDeviceDefaultViewTests(unittest.TestCase):
    """The hand-authored default Views shipped with the example must stay in
    sync with the model — every member has to resolve to a real element, and
    every hidden-edge key to a real edge (viewer.html's edgeKey format:
    kind|from|to|label)."""

    @classmethod
    def setUpClass(cls):
        paths = sorted(EXAMPLE_DIR.glob("*.sysml"), key=lambda p: p.name)
        cls.model = parse_models([p.read_text(encoding="utf-8") for p in paths],
                                 [p.name for p in paths])
        cls.ids = {n["id"] for n in cls.model["nodes"]}
        cls.edge_keys = {
            f"{e['kind']}|{e['from']}|{e['to']}|{e.get('label') or ''}"
            for e in cls.model["edges"]
        }

    def view(self, view_id):
        return json.loads((EXAMPLE_DIR / "views" / f"{view_id}.json")
                          .read_text(encoding="utf-8"))

    def test_all_three_default_views_exist_with_the_spec_names(self):
        for spec in DEFAULT_VIEW_SPECS:
            self.assertEqual(self.view(spec["id"])["name"], spec["name"])

    def test_view_members_resolve_to_model_elements(self):
        for spec in DEFAULT_VIEW_SPECS:
            for el in self.view(spec["id"])["elements"]:
                self.assertIn(el, self.ids, f"{spec['id']}: stale member {el}")

    def test_hidden_edges_resolve_to_model_edges(self):
        for spec in DEFAULT_VIEW_SPECS:
            for key in self.view(spec["id"])["hiddenEdges"]:
                self.assertIn(key, self.edge_keys,
                              f"{spec['id']}: stale hidden edge {key}")

    def test_every_member_has_a_saved_position(self):
        for spec in DEFAULT_VIEW_SPECS:
            v = self.view(spec["id"])
            self.assertEqual(sorted(v["nodes"]), sorted(v["elements"]), spec["id"])

    def test_context_view_shows_the_context_block_unconnected(self):
        v = self.view("context")
        self.assertIn("CoolSpineSystemContext::Kontext", v["elements"])
        block = "CoolSpineSystemContext::Kontext"
        # the context block is topmost...
        top = min(n["y"] for n in v["nodes"].values())
        self.assertEqual(v["nodes"][block]["y"], top)
        self.assertTrue(all(n["y"] > top for i, n in v["nodes"].items() if i != block))
        # ...and every edge touching it is hidden
        touching = {k for k in self.edge_keys
                    if k.split("|")[1] == block or k.split("|")[2] == block}
        visible = touching - set(v["hiddenEdges"])
        members = set(v["elements"])
        self.assertEqual(
            [k for k in visible
             if k.split("|")[1] in members and k.split("|")[2] in members], [])

    def test_context_view_keeps_connections_between_members(self):
        v = self.view("context")
        self.assertIn(
            "connector|CoolSpineSystemContext::Patient|"
            "CoolSpineSystemContext::CsfDrain|drainPatientCsf",
            self.edge_keys)
        self.assertNotIn(
            "connector|CoolSpineSystemContext::Patient|"
            "CoolSpineSystemContext::CsfDrain|drainPatientCsf",
            v["hiddenEdges"])

    def test_decomposition_view_is_a_three_level_pyramid(self):
        v = self.view("decomposition")
        ys = sorted({n["y"] for n in v["nodes"].values()})
        self.assertEqual(len(ys), 3)
        rows = [[i for i, n in v["nodes"].items() if n["y"] == y] for y in ys]
        self.assertEqual(rows[0], ["CoolSpineSystem::CoolSpineDevice"])
        # each level is wider than the one above it — that's the pyramid
        self.assertLess(len(rows[0]), len(rows[1]))
        # level 2 is exactly the direct parts of the system block
        # the part *defs* the system is composed of: the role-labelled
        # composition edges (the unlabelled ones point at usage nodes)
        direct = {e["to"] for e in self.model["edges"]
                  if e["kind"] == "composition" and e["label"]
                  and e["from"] == "CoolSpineSystem::CoolSpineDevice"}
        self.assertEqual(set(rows[1]), direct)

    def test_decomposition_view_hides_connectors(self):
        v = self.view("decomposition")
        members = set(v["elements"])
        for key in self.edge_keys:
            kind, frm, to, _ = key.split("|", 3)
            if kind == "connector" and frm in members and to in members:
                self.assertIn(key, v["hiddenEdges"])

    def test_decomposition_view_shows_docs_not_parts_or_attributes(self):
        opts = self.view("decomposition")["options"]
        self.assertTrue(opts["docsOnNode"])
        self.assertFalse(opts["parts"])
        self.assertFalse(opts["attrs"])

    def test_interconnections_view_is_the_first_level_parts_only(self):
        v = self.view("interconnections")
        # the part *defs* the system is composed of: the role-labelled
        # composition edges (the unlabelled ones point at usage nodes)
        direct = {e["to"] for e in self.model["edges"]
                  if e["kind"] == "composition" and e["label"]
                  and e["from"] == "CoolSpineSystem::CoolSpineDevice"}
        self.assertEqual(set(v["elements"]), direct)
        # the system block itself is not a member, so no composition edge
        # competes with the connectors
        self.assertNotIn("CoolSpineSystem::CoolSpineDevice", v["elements"])

    def test_interconnections_view_hides_nothing(self):
        self.assertEqual(self.view("interconnections")["hiddenEdges"], [])


if __name__ == "__main__":
    unittest.main()
