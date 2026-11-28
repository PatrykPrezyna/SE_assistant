"""Tests for the System Explorer tool.

Run:  python tests/test_system_explorer.py -v

Covers the parser, the HTTP API, and (when Microsoft Edge is available)
end-to-end rendering of the viewer with the compartment filters.
"""

import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stdout
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))
from system_explorer import (  # noqa: E402
    __version__,
    make_handler,
    parse_models,
    parse_sysml,
    publish_site,
)
from system_explorer import app as app_mod  # noqa: E402

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
        # composition edges (CoolSpine Context.csfDrain : CsfDrain [0..1])
        model = parse_sysml("""
        package P {
            part def Drain;
            part def Display;
            part def Context {
                part csfDrain : Drain [0..1];
                part display : Display [0..1];
                part required : Drain [1];
            }
        }
        """)
        self.assertEqual(
            node(model, "Context")["parts"],
            [
                {"text": "csfDrain : Drain [0..1]", "attrs": [], "isPort": False},
                {"text": "display : Display [0..1]", "attrs": [], "isPort": False},
                {"text": "required : Drain [1]", "attrs": [], "isPort": False},
            ],
        )
        comps = [(e["from"], e["to"], e["label"]) for e in edges_of(model, "composition")]
        self.assertIn(("P::Context", "P::Drain", "csfDrain"), comps)
        self.assertIn(("P::Context", "P::Display", "display"), comps)
        self.assertIn(("P::Context", "P::Drain", "required"), comps)

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

    def test_verification_def_verify_edge_resolves_short_name(self):
        # a verification case is its own element (not a requirement) and
        # its `verify` lives in the objective, which is where SysML v2
        # puts it
        model = parse_sysml("""
        package P {
            requirement def <'REQ-CP-003'> OperationWithoutGroundPower;
            part def Device;
            verification def <'VER-CP-003'> InternalElectricalPowerSourceOperatingTime {
                doc /* Bench test of operating time. */
                subject device : Device;
                objective {
                    doc /* Pass at 30 minutes. */
                    verify requirement 'REQ-CP-003';
                }
            }
        }
        """)
        ver = node(model, "InternalElectricalPowerSourceOperatingTime")
        self.assertEqual(ver["kind"], "verification def")
        self.assertEqual(ver["shortName"], "VER-CP-003")
        self.assertEqual(ver["doc"], "Bench test of operating time.")
        vers = edges_of(model, "verify")
        self.assertEqual(
            [(e["from"], e["to"], e["label"]) for e in vers],
            [("P::InternalElectricalPowerSourceOperatingTime",
              "P::OperationWithoutGroundPower", "«verify»")],
        )
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


USE_CASE_SAMPLE = """
package UcPkg {
    part def System;

    actor def Operator {
        doc /* The human operator. */
    }

    actor def Helper;

    use case def Start {
        doc /* Starts the system. */
        subject system : System;
        actor operator : Operator;
        satisfy R-1;
    }

    use case def Stop {
        actor operator : Operator;
    }

    package Reqs {
        requirement def Req;
        requirement <'R-1'> Fast : Req { doc /* Shall start fast. */ }
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


class UseCaseParserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = parse_sysml(USE_CASE_SAMPLE)

    def test_actor_and_use_case_defs_are_nodes(self):
        self.assertEqual(node(self.model, "Operator")["kind"], "actor def")
        self.assertEqual(node(self.model, "Start")["kind"], "use case def")

    def test_use_case_satisfy_edge_resolves(self):
        sats = edges_of(self.model, "satisfy")
        self.assertEqual(
            [(e["from"], e["to"]) for e in sats],
            [("UcPkg::Start", "UcPkg::Reqs::Fast")],
        )

    def test_sample_associations_and_no_warnings(self):
        self.assertEqual(
            {(e["from"], e["to"]) for e in edges_of(self.model, "association")},
            {("UcPkg::Start", "UcPkg::System"),
             ("UcPkg::Start", "UcPkg::Operator"),
             ("UcPkg::Stop", "UcPkg::Operator")},
        )
        self.assertEqual(self.model["warnings"], [])

    def test_use_diagram_dialect_is_no_longer_parsed(self):
        # `use case useDiagram ... for ...` was an explorer-only diagram
        # block (rejected by the official parser); it's skipped like any
        # other known-keyword construct the explorer doesn't render
        model = parse_sysml("""
        package P {
            actor def A;
            use case def U;
            part def Sys;
            use case useDiagram D for Sys {
                actor a : A;
                use case u : U;
                connection c from a to u;
            }
        }
        """)
        self.assertNotIn("ucds", model)
        self.assertEqual(model["warnings"], [])
        self.assertEqual(edges_of(model, "association"), [])
        self.assertEqual({n["name"] for n in model["nodes"]}, {"A", "U", "Sys"})

    def test_nested_actor_and_subject_in_use_case_become_associations(self):
        model = parse_sysml("""
        package P {
            actor def Surgeon;
            actor def Patient;
            part def Device;
            use case def Cooling {
                subject device : Device;
                actor surgeon : Surgeon;
                actor patient : Patient;
            }
        }
        """)
        self.assertEqual(
            {(e["from"], e["to"], e["label"])
             for e in edges_of(model, "association")},
            {
                ("P::Cooling", "P::Device", "device"),
                ("P::Cooling", "P::Surgeon", "surgeon"),
                ("P::Cooling", "P::Patient", "patient"),
            },
        )
        self.assertEqual(model["warnings"], [])

    def test_ref_part_in_use_case_does_not_become_association(self):
        model = parse_sysml("""
        package P {
            part def Surgeon;
            use case def Cooling {
                ref part surgeon : Surgeon;
            }
        }
        """)
        self.assertEqual(edges_of(model, "association"), [])

    def test_actor_in_part_def_does_not_become_association(self):
        # swimlane role on a part/interaction — not a use-case participant
        model = parse_sysml("""
        package P {
            part def Surgeon;
            part def Interaction {
                actor surgeon : Surgeon;
            }
        }
        """)
        self.assertEqual(edges_of(model, "association"), [])

    def test_two_roles_of_the_same_type_give_one_association(self):
        text = """
        package P {
            actor def A;
            use case def U {
                actor first : A;
                actor second : A;
            }
        }
        """
        assocs = edges_of(parse_sysml(text), "association")
        self.assertEqual([(e["from"], e["to"]) for e in assocs], [("P::U", "P::A")])


class ActivityParserTests(unittest.TestCase):
    """`perform action <name> { ... }` swimlane activity blocks (see
    app.py's dialect notes) — the pattern used in the CoolSpine example's
    CoolSpineSystemContext.sysml."""

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
        # …but inside a use case def they do become associations to the
        # actor/subject types (so the BDD can show who participates)
        self.assertEqual(
            {(e["from"], e["to"], e["label"])
             for e in edges_of(model, "association")},
            {
                ("P::Deliver", "P::Device", "device"),
                ("P::Deliver", "P::Surgeon", "surgeon"),
                ("P::Deliver", "P::Anesthesiologist", "anesthesiologist"),
            },
        )

    def test_ref_part_refers_to_an_instance_owned_elsewhere(self):
        model = parse_sysml("""
        package P {
            part def Surgeon;

            part def Context {
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
            ["P::Context::surgeon"],
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


class StandardActivityTests(unittest.TestCase):
    """A use case owns its process: perform inside each actor, first/then
    for order, fork/join and decide/merge for control, flow for an item."""

    SAMPLE = """
    package Surgery {
        part def Surgeon;
        part def Nurse;
        use case def PerformSurgery {
            actor surgeon : Surgeon {
                perform 'Assess Patient';
                perform 'Perform Surgery';
            }
            actor nurse : Nurse {
                perform 'Prepare OR';
            }
            action 'Prepare OR';
            action 'Assess Patient';
            action 'Perform Surgery';
            action 'Monitor Vital Signs';
            fork fork1;
            join join1;
            decide decide1;
            merge merge1;
            attribute stable : Boolean;
            first start then 'Prepare OR';
            first 'Prepare OR' then 'Assess Patient';
            first 'Assess Patient' then decide1;
            if stable then 'Perform Surgery';
            else 'Monitor Vital Signs';
            first 'Perform Surgery' then merge1;
            first 'Monitor Vital Signs' then merge1;
            first merge1 then fork1;
            first fork1 then 'Perform Surgery';
            first fork1 then 'Monitor Vital Signs';
            first 'Perform Surgery' then join1;
            first 'Monitor Vital Signs' then join1;
            first join1 then done;
            flow 'Assess Patient'.payload to 'Perform Surgery'.payload;
        }
    }
    """

    def test_lanes_fork_decision_and_flow(self):
        model = parse_sysml(self.SAMPLE)
        self.assertEqual(model["warnings"], [])
        act = model["activities"][0]
        self.assertEqual(act["owner"], "Surgery::PerformSurgery")
        self.assertEqual(act["forks"], ["fork1"])
        self.assertEqual(act["joins"], ["join1"])
        self.assertEqual(act["decisions"], ["decide1"])
        self.assertEqual(act["merges"], ["merge1"])
        edges = {(e["from"], e["to"], e["label"]) for e in act["edges"]}
        self.assertIn(("fork1", "Perform Surgery", ""), edges)
        self.assertIn(("fork1", "Monitor Vital Signs", ""), edges)
        self.assertIn(("decide1", "Perform Surgery", "stable"), edges)
        self.assertIn(("decide1", "Monitor Vital Signs", "no"), edges)
        self.assertEqual(act["flows"][0]["from"], "Assess Patient")
        self.assertEqual(act["flows"][0]["to"], "Perform Surgery")
        self.assertIn(("nurse", "Nurse", "Prepare OR"),
                      {(l["role"], l["type"], l["action"]) for l in act["lanes"]})

    def test_editor_builds_the_surgery_scenario_and_check_is_clean(self):
        from system_explorer.activity_edit import apply_edit
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "surgery.sysml").write_text(
                "package Surgery {\n    use case def PerformSurgery {}\n}\n",
                encoding="utf-8",
            )
            owner = "PerformSurgery"
            steps = [
                {"op": "add-lane", "owner": owner, "name": "Surgeon"},
                {"op": "add-lane", "owner": owner, "name": "Nurse"},
                {"op": "add-lane", "owner": owner, "name": "Anesthesiologist"},
                {"op": "add-action", "owner": owner, "name": "Prepare OR",
                 "lane": "Nurse", "after": "start", "splice": True},
                {"op": "add-action", "owner": owner, "name": "Assess Patient",
                 "lane": "Surgeon", "after": "Prepare OR", "splice": True},
                {"op": "add-action", "owner": owner, "name": "Administer Anesthesia",
                 "lane": "Anesthesiologist", "after": "Assess Patient", "splice": True},
                {"op": "add-fork", "owner": owner, "after": "Administer Anesthesia",
                 "branches": [
                     {"name": "Perform Surgery", "lane": "Surgeon"},
                     {"name": "Monitor Vital Signs", "lane": "Anesthesiologist"},
                 ]},
                {"op": "add-action", "owner": owner, "name": "Request Instrument",
                 "lane": "Surgeon", "after": "Perform Surgery", "splice": True},
                {"op": "add-action", "owner": owner, "name": "Provide Instrument",
                 "lane": "Nurse", "after": "Request Instrument", "splice": True},
                {"op": "add-action", "owner": owner, "name": "Close Incision",
                 "lane": "Surgeon", "after": "join1", "splice": True},
                {"op": "add-action", "owner": owner, "name": "Recover Patient",
                 "lane": "Nurse", "after": "Close Incision", "splice": True},
                {"op": "add-flow", "owner": owner, "source": "Request Instrument",
                 "target": "Provide Instrument"},
                {"op": "add-decision", "owner": owner, "after": "Assess Patient",
                 "guard": "stable", "yes": "Administer Anesthesia",
                 "no": "Stabilise Patient", "yesLane": "Anesthesiologist",
                 "noLane": "Surgeon"},
            ]
            for step in steps:
                apply_edit(folder, step)
            text = (folder / "surgery.sysml").read_text(encoding="utf-8")
            self.assertIn("actor surgeon : Surgeon", text)
            self.assertIn("perform 'Perform Surgery'", text)
            self.assertIn("first fork1 then 'Perform Surgery'", text)
            self.assertIn("first fork1 then 'Monitor Vital Signs'", text)
            self.assertIn("if stable then 'Administer Anesthesia'", text)
            self.assertIn("else 'Stabilise Patient'", text)
            self.assertIn("first merge1 then fork1", text)
            self.assertNotIn("perform 'Administer Anesthesia' by", text)
            self.assertNotIn("activity def", text)
            model = parse_sysml(text)
            self.assertEqual(model["warnings"], [])
            edges = {(e["from"], e["to"]) for e in model["activities"][0]["edges"]}
            self.assertIn(("merge1", "fork1"), edges)
            self.assertNotIn(("Administer Anesthesia", "fork1"), edges)
            env = dict(os.environ, PYTHONPATH=str(SRC))
            out = subprocess.run(
                [sys.executable, "-m", "system_explorer", str(folder), "--check"],
                capture_output=True, text=True, timeout=30, env=env,
            )
            self.assertEqual(out.returncode, 0, out.stdout + out.stderr)

    def test_editor_asks_when_the_lane_is_missing(self):
        from system_explorer.activity_edit import ActivityEditError, apply_edit
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "surgery.sysml").write_text(
                "package Surgery {\n    use case def PerformSurgery {}\n}\n",
                encoding="utf-8",
            )
            with self.assertRaises(ActivityEditError) as ctx:
                apply_edit(folder, {
                    "op": "add-action", "owner": "PerformSurgery",
                    "name": "Prepare OR",
                })
            self.assertIn("Who does", str(ctx.exception))
            self.assertNotIn("perform", (folder / "surgery.sysml").read_text())

    def test_http_edit_writes_the_file_and_rejects_a_vague_step(self):
        text = "package Surgery {\n    use case def PerformSurgery {}\n}\n"
        srv = ServerFixture(text, views={})
        try:
            created = json.loads(srv.post("/api/activity", {
                "op": "add-action", "owner": "PerformSurgery",
                "name": "Prepare OR", "lane": "Nurse",
                "after": "start", "splice": True,
            }))
            self.assertTrue(created["ok"])
            written = (srv.folder / "model.sysml").read_text(encoding="utf-8")
            self.assertIn("perform 'Prepare OR'", written)
            self.assertIn("part def Nurse", written)
            snaps = created["snapshots"]
            self.assertEqual([s["name"] for s in snaps], ["model.sysml"])
            self.assertNotIn("Prepare OR", snaps[0]["before"])
            self.assertIn("perform 'Prepare OR'", snaps[0]["after"])
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                srv.post("/api/activity", {
                    "op": "add-action", "owner": "PerformSurgery",
                    "name": "Next step",
                })
            self.assertEqual(ctx.exception.code, 400)
            body = json.loads(ctx.exception.read().decode())
            self.assertIn("Who does", body["error"])
        finally:
            srv.close()


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

    def run_print(self, folder):
        env = dict(os.environ, PYTHONPATH=str(SRC))
        return subprocess.run(
            [sys.executable, "-m", "system_explorer", str(folder), "--print"],
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
        env = dict(os.environ, PYTHONPATH=str(SRC))
        return subprocess.run(
            [sys.executable, "-m", "system_explorer", str(folder), "--check"],
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

    # run by file path: it imports nothing from the package, so the conda
    # env doesn't need system_explorer installed for this test
    SCRIPT = str(SRC / "system_explorer" / "official_check.py")

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


class ValidatorModuleTests(unittest.TestCase):
    """The two external-parser validators ship inside the package and run
    as modules (`python -m system_explorer.<name>`), so a model repo only
    needs the package installed. Their real checks need Node.js + the JamieD
    extension, or the OMG kernel; these tests cover what runs without."""

    def run_module(self, name, *args):
        env = dict(os.environ, PYTHONPATH=str(SRC))
        return subprocess.run(
            [sys.executable, "-m", f"system_explorer.{name}", *args],
            capture_output=True, text=True, timeout=60, env=env,
        )

    def test_jamied_check_without_arguments_prints_usage(self):
        out = self.run_module("jamied_check")
        self.assertEqual(out.returncode, 2)
        self.assertIn("python -m system_explorer.jamied_check", out.stderr)

    def test_official_check_help_runs_without_jupyter(self):
        out = self.run_module("official_check", "--help")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("folder", out.stdout)

    def test_jamied_check_fails_only_on_errors(self):
        from system_explorer.jamied_check import _extract_diags
        # soft warnings (e.g. unused-definition false positives) don't fail
        self.assertEqual(_extract_diags({"valid": True, "semanticIssues": [
            {"severity": "warning", "message": "unused"}]}), [])
        self.assertEqual(
            _extract_diags({"syntaxErrors": [{"message": "bad", "line": 3}]}),
            [{"message": "bad", "line": 3, "severity": "error"}])
        self.assertEqual(len(_extract_diags({"valid": False})), 1)


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

    def test_toolbar_has_projects_and_example(self):
        page = self.srv.get("/")
        self.assertIn('id="projectsBtn"', page)
        self.assertIn('id="exampleBtn"', page)
        self.assertIn(">Example<", page)
        self.assertIn(">Projects<", page)

    def test_version_has_a_single_source(self):
        # pyproject.toml reads the version from version.py, so there is no
        # second copy to keep in sync by hand
        pyproject = (SRC.parent / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('dynamic = ["version"]', pyproject)
        self.assertIn('attr = "system_explorer.version.__version__"', pyproject)
        self.assertRegex(__version__, r"^\d+\.\d+\.\d+$")
        self.assertEqual(app_mod.__version__, __version__)

    def test_toolbar_has_no_title_or_version_chrome(self):
        # the view switcher already names what's on screen, so the toolbar's
        # left edge carries neither an app title nor a version label
        page = self.srv.get("/")
        self.assertNotIn('id="appVersion"', page)
        self.assertNotIn('id="title"', page)
        self.assertNotIn("{{EXPLORER_VERSION}}", page)

    def test_no_auto_layout_command(self):
        # automatic placement still seeds unpositioned elements, but nothing
        # in the UI throws away a hand-arranged View in one click
        page = self.srv.get("/")
        self.assertNotIn('id="autoBtn"', page)
        self.assertNotIn("Auto-layout", page)

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

    def test_root_opens_on_a_view_not_a_home_page(self):
        # The explorer opens on a view. The old landing screen is gone.
        page = self.srv.get("/")
        self.assertIn('id="viewDropdown"', page)
        self.assertNotIn('id="home"', page)
        self.assertNotIn('id="homeBtn"', page)
        self.assertNotIn("function renderHome()", page)

    def test_reader_chrome_matches_the_published_viewer(self):
        # the explorer reads like the published Viewer; Edit is the extra
        page = self.srv.get("/")
        self.assertIn('id="viewTitle"', page)
        self.assertIn('id="zoombar"', page)
        self.assertIn('id="zoomIn"', page)
        self.assertIn('id="zoomOut"', page)
        self.assertIn('id="sheet"', page)
        self.assertIn('id="sheetName"', page)
        self.assertIn('id="viewDropdown"', page)
        self.assertIn(">Edit<", page)
        self.assertIn("function showSheet(id)", page)
        self.assertIn("function zoomBy(factor)", page)
        self.assertIn("function zoomAtClient(", page)
        self.assertIn("body:not(.expert) .edit-only", page)
        # phone: pinch zoom, pan while the detail sheet is open, and the
        # sheet itself never covers more than half the screen
        self.assertIn('name="viewport"', page)
        self.assertIn("touch-action: none", page)
        self.assertIn("max-height: 50%", page)
        self.assertIn("max-height: 50dvh", page)
        self.assertNotIn("72vh", page)
        self.assertIn("function touchDistance(", page)
        self.assertIn("gestureMoved", page)
        for el_id in ("saveBtn", "revertBtn"):
            m = re.search(r'<button[^>]*id="%s"[^>]*>' % el_id, page)
            self.assertIsNotNone(m, el_id)
            self.assertIn("edit-only", m.group(0))

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
        self.assertEqual(created, {"id": "logical-architecture",
                                    "name": "Logical Architecture",
                                    "description": "", "elementCount": 0,
                                    "kind": "bdd", "activityOwner": None})
        self.assertTrue((self.srv.views_dir / "logical-architecture.json").exists())

    def test_listing_carries_home_page_card_fields(self):
        # the home page renders a card per View from this one request
        self.srv.views_dir.mkdir(parents=True, exist_ok=True)
        (self.srv.views_dir / "ctx.json").write_text(json.dumps({
            "version": 1, "name": "Context", "description": "Who uses it.",
            "elements": ["TestPkg::Motor", "TestPkg::Robot"],
        }), encoding="utf-8")
        self.assertEqual(json.loads(self.srv.get("/api/views")), [
            {"id": "ctx", "name": "Context", "description": "Who uses it.",
             "elementCount": 2, "kind": "bdd", "activityOwner": None},
        ])

    def test_listing_defaults_card_fields_for_a_view_without_them(self):
        self.srv.views_dir.mkdir(parents=True, exist_ok=True)
        (self.srv.views_dir / "bare.json").write_text(
            json.dumps({"name": "Bare"}), encoding="utf-8")
        self.assertEqual(json.loads(self.srv.get("/api/views")), [
            {"id": "bare", "name": "Bare", "description": "",
             "elementCount": 0, "kind": "bdd", "activityOwner": None},
        ])

    def test_description_round_trips_through_put(self):
        # no UI writes it (it is authored content), so saving a View from
        # the viewer must not drop it
        created = json.loads(self.srv.post("/api/views", {"name": "V"}))
        content = json.loads(self.srv.get(f"/api/views/{created['id']}"))
        content["description"] = "One sentence on what this View is for."
        self.srv.put(f"/api/views/{created['id']}", content)
        back = json.loads(self.srv.get(f"/api/views/{created['id']}"))
        self.assertEqual(back["description"],
                         "One sentence on what this View is for.")

    def test_create_activity_view_stores_kind_and_owner(self):
        created = json.loads(self.srv.post("/api/views", {
            "name": "Activity — Interaction",
            "kind": "activity",
            "activityOwner": "ActPkg::Interaction",
            "description": "Swimlane activity diagram.",
        }))
        self.assertEqual(created, {
            "id": "activity-interaction",
            "name": "Activity — Interaction",
            "description": "Swimlane activity diagram.",
            "elementCount": 0,
            "kind": "activity",
            "activityOwner": "ActPkg::Interaction",
        })
        view = json.loads(self.srv.get(f"/api/views/{created['id']}"))
        self.assertEqual(view["kind"], "activity")
        self.assertEqual(view["activityOwner"], "ActPkg::Interaction")
        listed = json.loads(self.srv.get("/api/views"))
        self.assertEqual(listed[0]["kind"], "activity")
        self.assertEqual(listed[0]["activityOwner"], "ActPkg::Interaction")

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
    """Headless Chromium for the DOM tests. Edge on Windows, or Chrome."""
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        if base:
            p = Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            if p.exists():
                return str(p)
    # google-chrome-stable before google-chrome: some machines put a wrapper
    # named google-chrome first on PATH that forces a shared profile, and
    # --dump-dom then never returns.
    for name in ("msedge", "microsoft-edge", "microsoft-edge-stable",
                 "google-chrome-stable", "google-chrome", "chromium",
                 "chromium-browser"):
        found = shutil.which(name)
        if found:
            return found
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
        # launch, pre-populated so the canvas isn't blank. SAMPLE has 8
        # def-level elements; robot1 is the only usage of Robot, so the
        # singleton collapse draws just the Robot box for the pair -> 7
        with ServerFixture(views={}) as srv:
            self.assertEqual(dump_dom(srv.url).count('class="node'), 7)
            listed = json.loads(srv.get("/api/views"))
            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0]["id"], "default")
            self.assertEqual(listed[0]["name"], "Default")
            self.assertEqual(listed[0]["kind"], "bdd")


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
    Good enough for a containment check (e.g. "does this node have the
    activity icon") without a full HTML parser."""
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
        # "open" is the default preference, but the panel only reaches the
        # screen in expert mode — see ExpertModeRenderingTests
        classes = tree_classes(self.render({"expertMode": True}))
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
class ExpertModeRenderingTests(unittest.TestCase):
    """Edit (the header button) gates diagram building. Off by default, so
    a first-time reader sees the predefined views and nothing to build
    with."""

    EXPERT_ONLY_IDS = ["treeBtn", "newViewBtn", "renameViewBtn",
                       "deleteViewBtn", "unhideBtn"]

    @classmethod
    def setUpClass(cls):
        cls.srv = ServerFixture()

    @classmethod
    def tearDownClass(cls):
        cls.srv.close()

    def render(self, layout=None):
        if layout is None:
            self.srv.layout_path.unlink(missing_ok=True)
        else:
            self.srv.layout_path.write_text(json.dumps(layout), encoding="utf-8")
        return dump_dom(self.srv.url)

    def body_classes(self, dom):
        m = re.search(r'<body(?: class="([^"]*)")?', dom)
        assert m, "body tag not found"
        return (m.group(1) or "").split()

    def test_expert_mode_off_by_default_and_hides_the_tree(self):
        dom = self.render()
        self.assertNotIn("expert", self.body_classes(dom))
        # the tree is a building control, so it is off screen even though
        # treeOpen (the user's preference) is still true
        self.assertIn("hidden", tree_classes(dom))

    def test_saved_expert_mode_shows_the_tree_again(self):
        dom = self.render({"expertMode": True})
        self.assertIn("expert", self.body_classes(dom))
        self.assertNotIn("hidden", tree_classes(dom))

    def test_expert_mode_respects_the_tree_open_preference(self):
        dom = self.render({"expertMode": True, "treeOpen": False})
        self.assertIn("hidden", tree_classes(dom))

    def test_building_controls_are_marked_expert_only(self):
        dom = self.render()
        for el_id in self.EXPERT_ONLY_IDS:
            m = re.search(r'<button[^>]*id="%s"[^>]*>' % el_id, dom) or                 re.search(r'<button[^>]*class="[^"]*"[^>]*id="%s"' % el_id, dom)
            self.assertIsNotNone(m, f"{el_id} not found")
            self.assertIn("expert-only", m.group(0), el_id)

    def test_reading_controls_stay_available(self):
        dom = self.render()
        for el_id in ["fitBtn", "expertBtn", "zoomIn", "zoomOut",
                      "displayBtn", "moreBtn"]:
            m = re.search(r'<button[^>]*id="%s"[^>]*>' % el_id, dom)
            self.assertIsNotNone(m, f"{el_id} not found")
            self.assertNotIn("expert-only", m.group(0), el_id)
            self.assertNotIn("edit-only", m.group(0), el_id)
        # The header dropdown replaced the home-page overlay, so a reader
        # can change views without turning Edit on.
        drop = re.search(r'<select[^>]*id="viewDropdown"[^>]*>', dom)
        self.assertIsNotNone(drop, "viewDropdown not found")
        self.assertNotIn("expert-only", drop.group(0))
        self.assertNotIn("edit-only", drop.group(0))

    def test_authoring_controls_wait_for_edit(self):
        dom = self.render()
        for el_id in ["saveBtn", "revertBtn"]:
            m = re.search(r'<button[^>]*id="%s"[^>]*>' % el_id, dom)
            self.assertIsNotNone(m, f"{el_id} not found")
            self.assertIn("edit-only", m.group(0), el_id)
        self.assertNotIn("expert", self.body_classes(dom))
        # Display and More stay on the header; their panels are not clipped
        self.assertIn('id="displayMenu"', dom)
        self.assertIn('id="moreMenu"', dom)
        self.assertIn("«part def» keywords", dom)
        self.assertIn("docs on node", dom)
        self.assertNotIn("overflow-x: auto", dom)

    def test_toggle_button_present_and_reflects_state(self):
        off = self.render()
        self.assertIn('id="expertBtn"', off)
        self.assertIn('aria-pressed="false"', off)
        on = self.render({"expertMode": True})
        self.assertIn('aria-pressed="true"', on)

    def test_empty_view_hint_points_at_expert_mode(self):
        views = {"v": {"name": "V", "elements": [], "nodes": {},
                       "hiddenEdges": [], "view": None, "options": {}}}
        with ServerFixture(views=views) as srv:
            srv.layout_path.write_text(json.dumps({"activeView": "v"}),
                                       encoding="utf-8")
            self.assertIn("Turn Edit on to add elements.", dump_dom(srv.url))


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
class UseCaseRenderingTests(unittest.TestCase):
    """Actors, use cases and their associations render in the ordinary
    block definition diagram (there is no separate use case diagram mode)."""

    @classmethod
    def setUpClass(cls):
        cls.srv = ServerFixture(USE_CASE_SAMPLE)
        cls.dom = dump_dom(cls.srv.url)

    @classmethod
    def tearDownClass(cls):
        cls.srv.close()

    def test_nested_actor_and_subject_render_as_association_edges(self):
        # Start->System, Start->Operator, Stop->Operator; Helper has none
        self.assertEqual(self.dom.count('class="edge association"'), 3)

    def test_association_legend_row_shown(self):
        legend = self.dom.split('id="legend"')[1].split('<svg id="canvas"')[0]
        self.assertIn("association (actor/subject ↔ use case)", legend)

    def test_actor_and_usecase_defs_get_distinct_css_classes(self):
        self.assertIn('class="node actor"', self.dom)
        self.assertIn('class="node usecase"', self.dom)

    def test_no_use_case_diagram_chrome(self):
        self.assertNotIn("drilldownBackBtn", self.dom)
        self.assertNotIn("ucdicon", self.dom)


@unittest.skipUnless(EDGE, "Microsoft Edge not found; skipping rendering tests")
class ActivityRenderingTests(unittest.TestCase):
    """Activity diagrams are first-class Views. Tests open one the way a
    saved session does: `activeView` in layout.json names the activity View
    the viewer auto-creates on startup ("Activity — Interaction")."""

    @classmethod
    def setUpClass(cls):
        cls.srv = ServerFixture(ACTIVITY_SAMPLE)

    @classmethod
    def tearDownClass(cls):
        cls.srv.close()

    def render(self, layout):
        self.srv.layout_path.write_text(json.dumps(layout), encoding="utf-8")
        return dump_dom(self.srv.url)

    ACTIVITY_LAYOUT = {"activeView": "activity-interaction"}
    BDD_LAYOUT = {"nodes": {}, "selectedPackage": None}

    def test_activity_shows_action_and_control_boxes_not_the_owner(self):
        dom = self.render(self.ACTIVITY_LAYOUT)
        self.assertIn(">stepOne</text>", dom)
        self.assertIn(">stepTwo</text>", dom)
        self.assertIn('class="node start"', dom)
        self.assertIn('class="node end"', dom)
        self.assertNotIn(">▶ start</text>", dom)
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
            srv.layout_path.write_text(json.dumps(
                {"activeView": "activity-interaction"}), encoding="utf-8")
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
        self.assertIn(">Alice<", dom)
        self.assertIn(">Bob<", dom)

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

    def test_activity_view_listed_and_dropdown_stays_enabled(self):
        # first-class View, not a drilldown: the view picker stays usable
        # and lists the auto-created Activity — <owner> entry
        act_dom = self.render(self.ACTIVITY_LAYOUT)
        m = re.search(r'<select id="viewDropdown"[^>]*>', act_dom)
        self.assertIsNotNone(m, "view dropdown not rendered")
        self.assertNotIn("disabled", m.group(0))
        self.assertIn("Activity — Interaction", act_dom)
        listed = json.loads(self.srv.get("/api/views"))
        self.assertTrue(any(v.get("kind") == "activity" and
                            v.get("activityOwner") == "ActPkg::Interaction"
                            for v in listed))

    def test_unknown_active_view_falls_back_to_the_first_bdd_view(self):
        dom = self.render({"activeView": "no-such-view"})
        self.assertIn('data-id="ActPkg::Interaction"', dom)
        self.assertNotIn('data-id="ActPkg::Interaction::act::', dom)

    def test_activity_icon_shown_on_owner_element(self):
        dom = self.render(self.BDD_LAYOUT)
        self.assertIn('class="activityicon"',
                       node_segment(dom, "ActPkg::Interaction"))

    def test_activity_icon_not_shown_on_element_without_activity(self):
        dom = self.render(self.BDD_LAYOUT)
        self.assertNotIn('class="activityicon"', node_segment(dom, "ActPkg::Alice"))


VIEWER_HTML = SRC / "system_explorer" / "viewer.html"


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
            "function finishHistory() {}\n"
            + self.RELATED_JS
        )

    def groups(self, id_, members=()):
        return run_js(self.setup_js(list(members)), f"relatedGroups({json.dumps(id_)})")

    def labels(self, id_, members=()):
        items = run_js(self.setup_js(list(members)),
                       f"relatedMenuItems({json.dumps(id_)})"
                       ".map(i => [i.label, !!i.disabled])")
        return items

    def test_decomposition_group_is_direct_usage_children(self):
        [decomp, *_] = self.groups("TestPkg::Robot")
        self.assertEqual(decomp["label"], "decomposition")
        # role-level parts (drive, frame), not the shared types and not
        # Wheel (a level below Chassis / frame)
        self.assertEqual(sorted(decomp["ids"]),
                         ["TestPkg::Robot::drive", "TestPkg::Robot::frame"])

    def test_decomposition_separates_two_usages_of_the_same_type(self):
        # FluidReservoir-style: two Thermistors must both appear as roles
        model = parse_sysml("""
        package P {
            part def Thermistor;
            part def Reservoir {
                part inputTempSensor : Thermistor;
                part outputTempSensor : Thermistor;
            }
        }
        """)
        setup = (
            f"const model = {json.dumps(model)};\n"
            "let activeView = { elements: [] };\n"
            "function visibleIds() { return new Set(activeView.elements); }\n"
            "function rebuild() {}\n"
            "function setDirty() {}\n"
            + self.RELATED_JS
        )
        groups = run_js(setup, "relatedGroups('P::Reservoir')")
        self.assertEqual(sorted(groups[0]["ids"]),
                         ["P::Reservoir::inputTempSensor",
                          "P::Reservoir::outputTempSensor"])

    def test_type_group_lists_the_def_a_usage_is_typed_by(self):
        [_, _, typ, _, _] = self.groups("TestPkg::Robot::drive")
        self.assertEqual(typ["label"], "type")
        self.assertEqual(typ["ids"], ["TestPkg::BigMotor"])
        # top-level usage too
        self.assertEqual(self.groups("TestPkg::robot1")[2]["ids"],
                         ["TestPkg::Robot"])
        # a bare part def has no typing edge of its own
        self.assertEqual(self.groups("TestPkg::Wheel")[2]["ids"], [])

    def test_specializations_group_lists_subtypes_not_supertypes(self):
        [_, _, _, spec, _] = self.groups("TestPkg::Motor")
        self.assertEqual(spec["ids"], ["TestPkg::BigMotor"])
        # the other direction stays empty: BigMotor has no subtypes
        self.assertEqual(self.groups("TestPkg::BigMotor")[3]["ids"], [])

    def test_satisfy_group_lists_the_requirement_a_part_satisfies(self):
        [_, _, _, _, sat] = self.groups("TestPkg::Motor")
        self.assertEqual(sat["label"], "satisfied requirements")
        self.assertEqual(sat["ids"], ["TestPkg::Reqs::Fast"])

    def test_satisfy_group_on_a_requirement_lists_its_satisfiers(self):
        [_, _, _, _, sat] = self.groups("TestPkg::Reqs::Fast")
        self.assertEqual(sat["label"], "satisfying elements")
        self.assertEqual(sat["ids"], ["TestPkg::Motor"])

    def test_unrelated_edge_kinds_are_ignored(self):
        # Wheel is only ever a composition target; BigMotor has a connector
        # to Chassis — neither is "related" on those elements
        self.assertEqual([g["ids"] for g in self.groups("TestPkg::Wheel")],
                         [[], [], [], [], []])
        self.assertEqual(self.groups("TestPkg::BigMotor")[0]["ids"], [])

    def test_menu_counts_only_what_the_view_is_missing(self):
        labels = dict(self.labels("TestPkg::Robot", ["TestPkg::Robot"]))
        self.assertIn("Show decomposition (2)", labels)
        labels = dict(self.labels(
            "TestPkg::Robot",
            ["TestPkg::Robot", "TestPkg::Robot::frame"]))
        self.assertIn("Show decomposition (1)", labels)

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
                         ["TestPkg::Robot", "TestPkg::Robot::drive",
                          "TestPkg::Robot::frame"])


@unittest.skipUnless(EDGE, "Microsoft Edge not found; skipping rendering tests")
class RevertTests(unittest.TestCase):
    """**Revert** goes back to the last saved version: it drops the unsaved
    working state and re-runs the boot path, which re-reads layout.json and
    views/*.json from disk. It confirms first, and offers itself only while
    there is something to go back to."""

    REVERT_JS = None
    SET_DIRTY_JS = None

    @classmethod
    def setUpClass(cls):
        cls.REVERT_JS = viewer_js("async function revert", "function fillViewSel")
        cls.SET_DIRTY_JS = viewer_js("function setDirty", "function flash")
        cls.srv = ServerFixture()

    @classmethod
    def tearDownClass(cls):
        cls.srv.close()

    def drive(self, dirty, confirmed):
        """Run the viewer's own revert() against stubs for init/setDirty."""
        js = lambda b: "true" if b else "false"
        setup = "\n".join([
            f"let dirty = {js(dirty)};",
            "let layout = { stale: true };",
            'let mode = "activity";',
            'let activityOwner = "TestPkg::Go";',
            'let hiddenEdges = new Set(["e1"]);',
            "let initCalls = 0, flashed = null, confirmCalls = 0;",
            "window.confirm = () => { confirmCalls++; "
            f"return {js(confirmed)}; }};",
            "async function init() { initCalls++; }",
            "function setDirty(d) { dirty = d; }",
            "function flash(m) { flashed = m; }",
            self.REVERT_JS,
            # revert() settles in a microtask, i.e. after the harness has
            # already written its synchronous result; overwrite it once it
            # does, still long before --dump-dom reads the page back.
            'revert().then(() => {',
            '  document.getElementById("out").textContent = JSON.stringify(',
            "    { initCalls, dirty, flashed, confirmCalls, mode,",
            "      activityOwner, hidden: [...hiddenEdges], layout });",
            "});",
        ])
        return run_js(setup, "null")

    def test_confirmed_revert_reloads_from_disk_and_clears_dirty(self):
        r = self.drive(dirty=True, confirmed=True)
        self.assertEqual(r["initCalls"], 1, "did not re-run the boot path")
        self.assertFalse(r["dirty"])
        self.assertIn("reverted", r["flashed"])
        # the unsaved working state is dropped, so init() repopulates it from
        # the saved files instead of merging into stale values
        self.assertEqual(r["layout"], {})
        self.assertEqual(r["mode"], "bdd")
        self.assertIsNone(r["activityOwner"])
        self.assertEqual(r["hidden"], [])

    def test_declining_the_confirm_changes_nothing(self):
        r = self.drive(dirty=True, confirmed=False)
        self.assertEqual(r["confirmCalls"], 1)
        self.assertEqual(r["initCalls"], 0)
        self.assertTrue(r["dirty"], "unsaved changes were thrown away anyway")
        self.assertEqual(r["layout"], {"stale": True})
        self.assertEqual(r["mode"], "activity")

    def test_clean_state_reverts_without_asking(self):
        # nothing to lose, so no confirm prompt
        r = self.drive(dirty=False, confirmed=False)
        self.assertEqual(r["confirmCalls"], 0)
        self.assertEqual(r["initCalls"], 1)

    def button_disabled(self, dirty):
        js = "true" if dirty else "false"
        setup = "\n".join([
            'const statusEl = document.createElement("span");',
            "let dirty = false;",
            'const btn = document.createElement("button");',
            'btn.id = "revertBtn"; btn.disabled = true;',
            "document.body.appendChild(btn);",
            self.SET_DIRTY_JS,
            f"setDirty({js});",
        ])
        return run_js(setup, 'document.getElementById("revertBtn").disabled')

    def test_button_enables_only_while_there_are_unsaved_changes(self):
        self.assertTrue(self.button_disabled(dirty=False))
        self.assertFalse(self.button_disabled(dirty=True))

    def test_fresh_page_ships_the_button_disabled(self):
        dom = dump_dom(self.srv.url)
        m = re.search(r'<button[^>]*id="revertBtn"[^>]*>', dom)
        self.assertIsNotNone(m, "revertBtn not rendered")
        self.assertIn("disabled", m.group(0))


@unittest.skipUnless(EDGE, "Microsoft Edge not found; skipping rendering tests")
class LayoutSaveTests(unittest.TestCase):
    """save() writes only the current global keys to layout.json and drops
    the ones older versions wrote (IBD / use case diagram drilldowns,
    activity mode), so an old layout.json is cleaned up on the next Save."""

    def test_save_drops_stale_layout_keys(self):
        setup = "\n".join([
            viewer_js("const STALE_LAYOUT_KEYS", "const DISPLAY_DEFAULTS"),
            "const LAYOUT_VERSION = 1, VIEW_VERSION = 1;",
            "let nodes = {}, view = { tx: 0, ty: 0, s: 1 };",
            "let activeViewId = 'v', activeView = { nodes: {} };",
            "let hiddenEdges = new Set();",
            "let treeOpen = true, homeOpen = false, expertMode = true;",
            "let layout = { docs: { 'P::A': 'a.pdf' }, mode: 'ucd',",
            "  ucdOwner: 'P::S', activityOwner: null, ibdOwner: 'P::X',",
            "  drilldownNodes: {}, drilldownHiddenEdges: [], drilldownView: null };",
            "let posted = null;",
            "function posMap() { return activeView.nodes; }",
            "function displayOpts() { return {}; }",
            "function setDirty() {}",
            "function flash() {}",
            "function setSaveStatus() {}",
            "window.fetch = async (url, opts) => {",
            "  if (url === '/api/layout') posted = JSON.parse(opts.body);",
            "  return { ok: true };",
            "};",
            viewer_js("async function save()",
                      '// "Go back to the last saved version"'),
            # save() settles after the harness writes its synchronous result
            "save().then(() => {",
            "  document.getElementById('out').textContent = JSON.stringify(posted);",
            "});",
        ])
        saved = run_js(setup, "null")
        self.assertEqual(sorted(saved), ["activeView", "docs", "expertMode",
                                         "treeOpen", "version"])
        self.assertNotIn("home", saved)
        self.assertEqual(saved["docs"], {"P::A": "a.pdf"})


@unittest.skipUnless(EDGE, "Microsoft Edge not found; skipping rendering tests")
class ViewDropdownTests(unittest.TestCase):
    """The header dropdown replaced the home-page overlay. Readers switch
    views from it, and the page opens on the diagram."""

    @classmethod
    def setUpClass(cls):
        cls.srv = ServerFixture()

    @classmethod
    def tearDownClass(cls):
        cls.srv.close()

    def test_dropdown_lists_the_folder_views(self):
        dom = dump_dom(self.srv.url)
        self.assertIn('id="viewDropdown"', dom)
        self.assertIn(">Default<", dom)
        self.assertNotIn('id="home"', dom)
        self.assertNotIn('id="homeBtn"', dom)


@unittest.skipUnless(EDGE, "Microsoft Edge not found; skipping rendering tests")
class DetailSheetTests(unittest.TestCase):
    """A click while reading opens the same detail sheet as the published
    Viewer. The sheet-filling code runs standalone against a stub model."""

    SHEET_DOM = (
        '<aside id="sheet"><h2 id="sheetName"></h2>'
        '<p id="sheetKind"></p><p id="sheetDoc"></p>'
        '<a id="docLink"></a>'
        '<h3 id="reqHead"></h3><ul id="reqList"></ul>'
        '<h3 id="byHead"></h3><ul id="byList"></ul>'
        '<h3 id="verHead"></h3><ul id="verList"></ul></aside>'
    )

    def test_sheet_shows_doc_link_and_satisfied_requirements(self):
        js = viewer_js(
            "// ------------------------------------------------------- detail sheet",
            "// ------------------------------------------------------- detail sheet end")
        setup = "\n".join([
            'document.body.insertAdjacentHTML("beforeend", '
            + json.dumps(self.SHEET_DOM) + ");",
            "let model = " + json.dumps({
                "nodes": [
                    {"id": "P::Motor", "name": "Motor", "kind": "part def",
                     "doc": "Spins."},
                    {"id": "P::Fast", "name": "Fast", "kind": "requirement",
                     "doc": "Must be fast."},
                ],
                "edges": [{"kind": "satisfy", "from": "P::Motor",
                           "to": "P::Fast"}],
            }) + ";",
            "let layout = { docs: { 'P::Motor': 'motor.pdf' } };",
            "let nodes = {};",
            "function selectNode() {}",
            "function centerOn() {}",
            js,
            "showSheet('P::Motor');",
            "const reqs = [...document.querySelectorAll('#reqList button')]"
            ".map(b => b.textContent);",
        ])
        got = run_js(setup, "({ name: document.getElementById('sheetName').textContent,"
                     " doc: document.getElementById('sheetDoc').textContent,"
                     " href: document.getElementById('docLink').getAttribute('href'),"
                     " link: document.getElementById('docLink').textContent,"
                     " open: document.body.classList.contains('sheet'),"
                     " reqs })")
        self.assertTrue(got["open"])
        self.assertEqual(got["name"], "Motor")
        self.assertEqual(got["doc"], "Spins.")
        self.assertIn("api/doc", got["href"])
        self.assertIn("motor.pdf", got["href"])
        self.assertIn("motor.pdf", got["link"])
        self.assertTrue(any(r.startswith("Fast") for r in got["reqs"]))


# ----------------------------------------------------------------------
# Hosted (cloud) mode
# ----------------------------------------------------------------------

from system_explorer import cloud as cloud_mod  # noqa: E402


def _git(cwd, *args):
    return subprocess.run(
        ["git", "-c", "user.name=Seed", "-c", "user.email=seed@example.com",
         *args],
        cwd=cwd, capture_output=True, text=True, check=True,
    ).stdout


class StubAuth(cloud_mod.GitHubAuth):
    """GitHubAuth with the three GitHub calls stubbed: the OAuth code *is*
    the login, and only "mallory" isn't a collaborator."""

    def exchange_code(self, code):
        return "token-for-" + code

    def fetch_user(self, access_token):
        login = access_token[len("token-for-"):]
        return {"login": login, "name": login.title(), "id": 42}

    def is_allowed(self, login):
        return login != "mallory"


def _stub_auth():
    return StubAuth("cid", "csecret", "session-secret",
                    "https://explorer.example.com", "team/model")


class CloudSessionTests(unittest.TestCase):
    def setUp(self):
        self.auth = _stub_auth()

    def test_session_round_trip(self):
        cookie = self.auth.make_session({"login": "alice", "name": "Alice",
                                         "id": 7})
        user = self.auth.session_user(f"{cloud_mod.SESSION_COOKIE}={cookie}")
        self.assertEqual(user["login"], "alice")
        self.assertEqual(user["id"], 7)

    def test_tampered_session_is_rejected(self):
        cookie = self.auth.make_session({"login": "alice"})
        body, mac = cookie.rsplit(".", 1)
        forged = self.auth.sign({"login": "mallory", "exp": 2**40})
        self.assertIsNone(self.auth.verify(forged.split(".")[0] + "." + mac))
        self.assertIsNone(self.auth.verify(body + "." + "0" * len(mac)))

    def test_session_signed_with_another_secret_is_rejected(self):
        other = cloud_mod.GitHubAuth("c", "s", "other-secret",
                                     "https://x", "team/model")
        cookie = other.make_session({"login": "alice"})
        self.assertIsNone(self.auth.verify(cookie))

    def test_expired_session_is_rejected(self):
        cookie = self.auth.sign({"login": "alice", "exp": 1})
        self.assertIsNone(self.auth.verify(cookie))

    def test_no_or_garbage_cookie_means_signed_out(self):
        self.assertIsNone(self.auth.session_user(None))
        self.assertIsNone(self.auth.session_user("other=1"))
        self.assertIsNone(self.auth.session_user(
            f"{cloud_mod.SESSION_COOKIE}=not-a-session"))

    def test_https_public_url_makes_cookies_secure(self):
        self.assertIn("Secure", self.auth._cookie("a", "b", 1))
        local = cloud_mod.GitHubAuth("c", "s", "k", "http://localhost:8080",
                                     "team/model")
        self.assertNotIn("Secure", local._cookie("a", "b", 1))

    def test_allowed_users_list_overrides_collaborator_check(self):
        auth = cloud_mod.GitHubAuth("c", "s", "k", "https://x", "team/model",
                                    allowed_users=["Alice", " bob ", ""])
        self.assertTrue(auth.is_allowed("alice"))
        self.assertTrue(auth.is_allowed("BOB"))
        self.assertFalse(auth.is_allowed("carol"))


class CloudFixture:
    """A bare git repo standing in for GitHub, with a model folder pushed
    to it, and the hosted server serving a fresh clone of it."""

    def __init__(self, auth="stub"):
        self.dir = tempfile.TemporaryDirectory()
        root = Path(self.dir.name)
        self.bare = root / "remote.git"
        _git(root, "init", "-q", "--bare", "-b", "main", str(self.bare))
        self.seed = root / "seed"
        _git(root, "clone", "-q", str(self.bare), str(self.seed))
        model_dir = self.seed / "model"
        (model_dir / "views").mkdir(parents=True)
        (model_dir / "model.sysml").write_text(SAMPLE, encoding="utf-8")
        (model_dir / "views" / "default.json").write_text(json.dumps(
            {"name": "Default", "elements": [], "nodes": {},
             "hiddenEdges": [], "view": None, "options": {}}), encoding="utf-8")
        (model_dir / "spec.txt").write_text("spec", encoding="utf-8")
        (root / "secret.txt").write_text("outside the repo", encoding="utf-8")
        _git(self.seed, "add", "-A")
        _git(self.seed, "commit", "-q", "-m", "seed")
        _git(self.seed, "push", "-q", "origin", "HEAD:main")

        self.work = root / "work"
        self.sync = cloud_mod.GitSync(str(self.bare), self.work, "main",
                                      pull_interval=0, async_push=False)
        self.sync.clone_or_update()
        self.folder = self.work / "model"
        self.auth = _stub_auth() if auth == "stub" else auth
        ctx = cloud_mod.CloudContext(self.sync, self.auth, self.work)
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            make_handler(self.folder, self.folder / "layout.json", ctx))
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def session(self, login="alice"):
        cookie = self.auth.make_session({"login": login, "name": "Alice",
                                         "id": 42})
        return f"{cloud_mod.SESSION_COOKIE}={cookie}"

    def request(self, method, path, body=None, cookie=None):
        """No redirect following, so 302s can be asserted."""
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Cookie": cookie} if cookie else {}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        conn.request(method, path, body=data, headers=headers)
        r = conn.getresponse()
        result = (r.status, r.headers, r.read().decode("utf-8", "replace"))
        conn.close()
        return result

    def remote_log(self):
        return _git(self.bare, "log", "--format=%an <%ae>|%s", "main")

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        try:
            self.dir.cleanup()
        except OSError:
            pass  # Windows: git may still hold a handle for a moment


@unittest.skipUnless(shutil.which("git"), "git not found; skipping cloud tests")
class CloudServerTests(unittest.TestCase):
    def setUp(self):
        self.fx = CloudFixture()
        self.alice = self.fx.session("alice")

    def tearDown(self):
        self.fx.close()

    def test_healthz_needs_no_sign_in(self):
        status, _, body = self.fx.request("GET", "/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"ok": True})

    def test_page_redirects_to_sign_in(self):
        status, headers, _ = self.fx.request("GET", "/")
        self.assertEqual(status, 302)
        self.assertEqual(headers["Location"], "/auth/login")

    def test_api_without_session_is_401(self):
        for method, path in [("GET", "/api/model"), ("GET", "/api/views"),
                             ("PUT", "/api/views/default"),
                             ("DELETE", "/api/views/default"),
                             ("POST", "/api/layout")]:
            status, _, _ = self.fx.request(
                method, path, body={} if method in ("PUT", "POST") else None)
            self.assertEqual(status, 401, (method, path))
        # and nothing was written or committed
        self.assertTrue((self.fx.folder / "views" / "default.json").exists())
        self.assertEqual(self.fx.remote_log().count("\n"), 1)

    def test_signed_in_user_gets_viewer_and_model(self):
        status, _, page = self.fx.request("GET", "/", cookie=self.alice)
        self.assertEqual(status, 200)
        self.assertIn("<svg", page)
        status, _, body = self.fx.request("GET", "/api/model", cookie=self.alice)
        self.assertEqual(status, 200)
        self.assertIn("Motor", [n["name"] for n in json.loads(body)["nodes"]])

    def test_saving_a_view_commits_and_pushes_as_the_user(self):
        view = {"name": "Default", "elements": ["TestPkg::Motor"], "nodes": {},
                "hiddenEdges": [], "view": None, "options": {}}
        status, _, _ = self.fx.request("PUT", "/api/views/default", view,
                                       cookie=self.alice)
        self.assertEqual(status, 200)
        log = self.fx.remote_log().splitlines()
        self.assertEqual(
            log[0], "Alice <42+alice@users.noreply.github.com>|"
                    "Update view 'Default'")
        pushed = _git(self.fx.bare, "show", "main:model/views/default.json")
        self.assertEqual(json.loads(pushed)["elements"], ["TestPkg::Motor"])

    def test_create_delete_and_layout_are_commits_too(self):
        _, _, body = self.fx.request("POST", "/api/views", {"name": "Power"},
                                     cookie=self.alice)
        self.assertEqual(json.loads(body)["id"], "power")
        self.fx.request("POST", "/api/layout", {"docs": {}}, cookie=self.alice)
        self.fx.request("DELETE", "/api/views/power", cookie=self.alice)
        subjects = [line.split("|", 1)[1]
                    for line in self.fx.remote_log().splitlines()]
        self.assertEqual(subjects[:3], ["Delete view 'power'",
                                        "Update explorer layout",
                                        "Create view 'Power'"])

    def test_saving_unchanged_content_makes_no_commit(self):
        _, _, body = self.fx.request("GET", "/api/views/default",
                                     cookie=self.alice)
        before = self.fx.remote_log()
        # same content, same formatting the server writes
        self.fx.request("PUT", "/api/views/default", json.loads(body),
                        cookie=self.alice)
        self.fx.request("PUT", "/api/views/default", json.loads(body),
                        cookie=self.alice)
        self.assertLessEqual(self.fx.remote_log().count("\n"),
                             before.count("\n") + 1)

    def test_reads_pick_up_teammates_pushes(self):
        (self.fx.seed / "model" / "views" / "theirs.json").write_text(
            json.dumps({"name": "Theirs", "elements": []}), encoding="utf-8")
        _git(self.fx.seed, "add", "-A")
        _git(self.fx.seed, "commit", "-q", "-m", "teammate view")
        _git(self.fx.seed, "push", "-q", "origin", "HEAD:main")
        _, _, body = self.fx.request("GET", "/api/views", cookie=self.alice)
        self.assertIn("theirs", [v["id"] for v in json.loads(body)])

    def test_push_after_teammate_push_rebases(self):
        (self.fx.seed / "model" / "other.txt").write_text("x", encoding="utf-8")
        _git(self.fx.seed, "add", "-A")
        _git(self.fx.seed, "commit", "-q", "-m", "teammate change")
        _git(self.fx.seed, "push", "-q", "origin", "HEAD:main")
        self.fx.sync.pull_interval = 3600  # the save must not pull first
        self.fx.sync._last_pull = __import__("time").monotonic()
        status, _, _ = self.fx.request(
            "POST", "/api/views", {"name": "Mine"}, cookie=self.alice)
        self.assertEqual(status, 200)
        subjects = [line.split("|", 1)[1]
                    for line in self.fx.remote_log().splitlines()]
        self.assertEqual(subjects[:2], ["Create view 'Mine'", "teammate change"])

    def test_doc_links_cannot_leave_the_checkout(self):
        status, _, body = self.fx.request("GET", "/api/doc?path=spec.txt",
                                          cookie=self.alice)
        self.assertEqual((status, body), (200, "spec"))
        outside = Path(self.fx.dir.name) / "secret.txt"
        for target in ["../../secret.txt", str(outside)]:
            status, _, _ = self.fx.request(
                "GET", "/api/doc?path=" + urllib.parse.quote(target),
                cookie=self.alice)
            self.assertEqual(status, 404, target)

    def test_login_redirects_to_github_with_state_cookie(self):
        status, headers, _ = self.fx.request("GET", "/auth/login")
        self.assertEqual(status, 302)
        self.assertTrue(headers["Location"].startswith(
            "https://github.com/login/oauth/authorize?"))
        self.assertIn("redirect_uri=https%3A%2F%2Fexplorer.example.com"
                      "%2Fauth%2Fcallback", headers["Location"])
        self.assertIn(cloud_mod.STATE_COOKIE + "=", headers["Set-Cookie"])

    def test_callback_signs_in_a_collaborator(self):
        cookie = f"{cloud_mod.STATE_COOKIE}=abc"
        status, headers, _ = self.fx.request(
            "GET", "/auth/callback?code=bob&state=abc", cookie=cookie)
        self.assertEqual(status, 302)
        self.assertEqual(headers["Location"], "/")
        session = [c for c in headers.get_all("Set-Cookie")
                   if c.startswith(cloud_mod.SESSION_COOKIE + "=")][0]
        value = session.split(";")[0]
        _, _, me = self.fx.request("GET", "/auth/me", cookie=value)
        self.assertEqual(json.loads(me)["login"], "bob")

    def test_callback_rejects_state_mismatch(self):
        status, _, _ = self.fx.request(
            "GET", "/auth/callback?code=bob&state=abc",
            cookie=f"{cloud_mod.STATE_COOKIE}=xyz")
        self.assertEqual(status, 400)

    def test_callback_rejects_non_collaborator(self):
        status, headers, body = self.fx.request(
            "GET", "/auth/callback?code=mallory&state=abc",
            cookie=f"{cloud_mod.STATE_COOKIE}=abc")
        self.assertEqual(status, 403)
        self.assertIn("mallory", body)
        self.assertIsNone(headers["Set-Cookie"])

    def test_logout_clears_the_session(self):
        status, headers, _ = self.fx.request("GET", "/auth/logout",
                                             cookie=self.alice)
        self.assertEqual(status, 302)
        self.assertIn("Max-Age=0", headers["Set-Cookie"])


@unittest.skipUnless(shutil.which("git"), "git not found; skipping cloud tests")
class CloudAnonymousTests(unittest.TestCase):
    def test_anonymous_mode_serves_without_sign_in_and_commits_as_bot(self):
        fx = CloudFixture(auth=None)
        try:
            status, _, _ = fx.request("GET", "/api/model")
            self.assertEqual(status, 200)
            fx.request("POST", "/api/views", {"name": "Anon"})
            self.assertTrue(fx.remote_log().startswith(
                f"{cloud_mod.BOT_NAME} <{cloud_mod.BOT_EMAIL}>|Create view"))
        finally:
            fx.close()


class PublishTests(unittest.TestCase):
    """--publish writes a static view-only site from prepared Views."""

    def write_model(self, folder):
        (folder / "model.sysml").write_text(SAMPLE, encoding="utf-8")
        notes = folder / "notes"
        notes.mkdir()
        (notes / "fast.txt").write_text("requirement note\n", encoding="utf-8")
        outside = folder.parent / "outside.txt"
        outside.write_text("nope\n", encoding="utf-8")
        (folder / "layout.json").write_text(json.dumps({
            "docs": {
                "TestPkg::Motor": "https://example.com/motor",
                "TestPkg::Reqs::Fast": "notes/fast.txt",
                "TestPkg::Wheel": "../outside.txt",
                "TestPkg::Chassis": "notes/missing.txt",
            },
        }), encoding="utf-8")
        views = folder / "views"
        views.mkdir()
        (views / "context.json").write_text(json.dumps({
            "name": "Context",
            "description": "The system and its requirement.",
            "elements": ["TestPkg::Motor", "TestPkg::Reqs::Fast"],
            "nodes": {
                "TestPkg::Motor": {"x": 40, "y": 80},
                "TestPkg::Reqs::Fast": {"x": 280, "y": 80},
            },
            "hiddenEdges": [],
        }), encoding="utf-8")
        (views / "flow.json").write_text(json.dumps({
            "name": "Flow", "kind": "activity", "elements": [], "nodes": {},
        }), encoding="utf-8")
        (views / "arch.json").write_text(json.dumps({
            "name": "Architecture",
            "elements": ["TestPkg::Robot", "TestPkg::robot1"],
            "nodes": {
                "TestPkg::Robot": {"x": -30, "y": -10},
                "TestPkg::robot1": {"x": 300, "y": 10},
            },
        }), encoding="utf-8")
        return outside

    def test_publish_writes_views_docs_and_skips_activity(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d) / "model"
            folder.mkdir()
            self.write_model(folder)
            out = Path(d) / "site"
            info = publish_site(folder, out)
            self.assertEqual(info["views"], 2)
            self.assertEqual(info["skippedActivity"], 1)
            self.assertEqual(info["links"]["TestPkg::Motor"],
                             "https://example.com/motor")
            self.assertEqual(info["links"]["TestPkg::Reqs::Fast"],
                             "files/notes/fast.txt")
            self.assertIn("../outside.txt", info["omitted"])
            self.assertIn("notes/missing.txt", info["omitted"])
            page = (out / "index.html").read_text(encoding="utf-8")
            self.assertNotIn("__VIEWER_DATA__", page)
            self.assertIn("https://example.com/motor", page)
            self.assertNotIn("mousemove", page)
            views = json.loads((out / "views.json").read_text(encoding="utf-8"))
            self.assertEqual([v["id"] for v in views["views"]],
                             ["arch", "context"])
            self.assertEqual(
                (out / "files" / "notes" / "fast.txt").read_text(encoding="utf-8"),
                "requirement note\n")
            model = json.loads((out / "model.json").read_text(encoding="utf-8"))
            self.assertEqual(model["explorerVersion"], __version__)

    def test_cli_publish_and_check_gate(self):
        env = dict(os.environ, PYTHONPATH=str(SRC))
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d) / "model"
            folder.mkdir()
            (folder / "m.sysml").write_text(SAMPLE, encoding="utf-8")
            out = Path(d) / "site"
            proc = subprocess.run(
                [sys.executable, "-m", "system_explorer", str(folder),
                 "--publish", str(out)],
                capture_output=True, text=True, timeout=30, env=env,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("Published 0 view(s)", proc.stdout)
            self.assertTrue((out / "index.html").is_file())

            bad = Path(d) / "bad"
            bad.mkdir()
            (bad / "m.sysml").write_text(
                "package P { part def A { satisfy NOPE; } }", encoding="utf-8")
            blocked = Path(d) / "blocked"
            proc = subprocess.run(
                [sys.executable, "-m", "system_explorer", str(bad),
                 "--check", "--publish", str(blocked)],
                capture_output=True, text=True, timeout=30, env=env,
            )
            self.assertEqual(proc.returncode, 1)
            self.assertFalse(blocked.exists())


def dump_published(url):
    out = subprocess.run(
        [EDGE, "--headless", "--disable-gpu", "--virtual-time-budget=3000",
         "--dump-dom", url],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    return out.stdout


@unittest.skipUnless(EDGE, "Microsoft Edge not found; skipping rendering tests")
class PublishedViewerTests(unittest.TestCase):
    """The generated page draws a prepared View and lists satisfy links."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.folder = root / "model"
        cls.folder.mkdir()
        PublishTests().write_model(cls.folder)
        cls.out = root / "site"
        publish_site(cls.folder, cls.out)

        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(cls.out), **kwargs)

            def log_message(self, fmt, *args):
                pass

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    def test_home_lists_prepared_views(self):
        dom = dump_published(self.url + "/index.html")
        self.assertIn("Context", dom)
        self.assertIn("Architecture", dom)
        self.assertNotIn("Flow", dom)

    def test_sheet_covers_at_most_half_the_screen(self):
        dom = dump_published(
            self.url + "/index.html?v=context&e=TestPkg::Motor")
        self.assertIn("max-height: 50%", dom)
        self.assertIn("max-height: 50dvh", dom)
        self.assertNotIn("72vh", dom)
        self.assertIn("function touchDistance(", dom)
        self.assertIn("gesturePinch", dom)

    def test_view_opens_fitted_with_zoom_controls(self):
        dom = dump_published(self.url + "/index.html?v=context")
        self.assertIn('id="zoomIn"', dom)
        self.assertIn('id="zoomOut"', dom)
        self.assertIn('id="zoomFit"', dom)
        self.assertIn('id="diagram"', dom)
        self.assertIn('preserveAspectRatio="xMidYMid meet"', dom)
        self.assertRegex(dom, r'id="diagram"[^>]*viewBox="0 0 [\d.]+ [\d.]+"')

    def test_view_renders_saved_positions(self):
        dom = dump_published(self.url + "/index.html?v=context")
        # saved (40, 80) and (280, 80) are shifted so the top-left node
        # sits at the page margin; the 240px gap is unchanged
        self.assertIn('transform="translate(24 24)"', dom)
        self.assertIn('transform="translate(264 24)"', dom)
        self.assertIn("Motor", dom)
        self.assertIn("Fast", dom)
        self.assertIn('class="edge satisfy"', dom)

    def test_tap_lists_connected_requirements_and_doc_link(self):
        dom = dump_published(
            self.url + "/index.html?v=context&e=TestPkg::Motor")
        self.assertIn("Robot shall be fast.", dom)
        self.assertIn("https://example.com/motor", dom)
        self.assertIn(">Fast<", dom)

    def test_singleton_usage_stays_off_the_diagram(self):
        dom = dump_published(self.url + "/index.html?v=arch")
        self.assertIn('data-id="TestPkg::Robot"', dom)
        self.assertNotIn('data-id="TestPkg::robot1"', dom)
        # a position above/left of the origin is shifted onto the page
        self.assertIn('transform="translate(24 24)"', dom)
        diagram = dom.split('id="diagram"')[1].split("</svg>")[0]
        self.assertIn("drive : BigMotor", diagram)
        self.assertIn("length = 55.0", diagram)
        self.assertNotIn("«part def»", diagram)

    def test_context_view_matches_explorer_notation(self):
        dom = dump_published(self.url + "/index.html?v=context")
        diagram = dom.split('id="diagram"')[1].split("</svg>")[0]
        self.assertIn(">Motor</text>", diagram)
        self.assertIn("torque : Real", diagram)
        self.assertIn("R-1 Fast", diagram)
        self.assertNotIn("«part def»", diagram)
        self.assertNotIn("«satisfy»", diagram)
        self.assertNotIn("«requirement", diagram)
        legend = dom.split('id="legend"')[1].split('id="canvas"')[0]
        self.assertIn("satisfies requirement", legend)
        self.assertIn('class="docicon"', diagram)


class NotationProfileTests(unittest.TestCase):
    """The values NOTATION.md names, so the profile cannot drift from the pages."""

    @classmethod
    def setUpClass(cls):
        cls.explorer = VIEWER_HTML.read_text(encoding="utf-8")
        cls.published = (
            SRC / "system_explorer" / "publish_viewer.html"
        ).read_text(encoding="utf-8")

    def test_display_defaults_match_the_profile(self):
        # N1, N5, N7, N9: keywords / edge labels / packages / docs off;
        # attribute and parts compartments on.
        block = re.search(
            r"const DISPLAY_DEFAULTS = \{([^}]+)\}", self.explorer).group(1)
        defaults = dict(re.findall(r"(\w+):\s*(true|false)", block))
        self.assertEqual(defaults, {
            "attrs": "true",
            "parts": "true",
            "keywords": "false",
            "edgeLabels": "false",
            "packages": "false",
            "docsOnNode": "false",
        })

    def test_legend_wording_matches_the_profile(self):
        # N6: specialization is "kind of", typing is "is a".
        block = re.search(
            r"const LEGEND_LABELS = \{([^}]+)\}", self.explorer).group(1)
        labels = dict(re.findall(r'(\w+):\s*"([^"]*)"', block))
        self.assertEqual(labels["specialization"], "kind of")
        self.assertEqual(labels["typing"], "is a")

    def test_usage_header_omits_type(self):
        # N3: the name line is the role name. `usageType` stays on the
        # model; it is not appended to the header.
        body = viewer_js("function buildNodeContent(d)", "function fontFor")
        start = body.index('cls: "name"')
        name_line = body[body.rindex("header.push({ text:", 0, start):start]
        self.assertIn("d.name", name_line)
        self.assertNotIn("usageType", name_line)

    def test_singleton_collapse_is_applied(self):
        # N4: the tree drops singleton part usages; the canvas drops one
        # only when its part def is also a member (suppressedSingletonUsages).
        tree = viewer_js("function filterTreeNodes", "function renderTreeElem")
        self.assertIn("singletonPartUsageIds()", tree)
        canvas = viewer_js("function buildBddNodesEdges()", "function packageTree")
        self.assertIn("suppressedSingletonUsages(vis)", canvas)

    def test_published_viewer_uses_explorer_defaults(self):
        # N1, N3, N4, N5, N6, N9 on the published page: no «kind» header,
        # role name only, singleton collapse, connector/flow labels only,
        # the same legend words, attribute and parts compartments.
        self.assertIn("function suppressedSingletonUsages(vis)", self.published)
        self.assertNotIn('"«" + n.data.kind + "»"', self.published)
        self.assertNotIn("usageType", self.published)
        self.assertIn('d.kind === "connector" || d.kind === "flow"', self.published)
        self.assertIn("d.attributes", self.published)
        self.assertIn("d.parts", self.published)
        block = re.search(
            r"const LEGEND_LABELS = \{([^}]+)\}", self.published).group(1)
        labels = dict(re.findall(r'(\w+):\s*"([^"]*)"', block))
        self.assertEqual(labels["specialization"], "kind of")
        self.assertEqual(labels["typing"], "is a")


def _load_stakeholder_tool():
    path = Path(__file__).resolve().parents[1] / "methodology" / "stakeholder_analysis.py"
    spec = importlib.util.spec_from_file_location("stakeholder_analysis", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StakeholderAnalysisTests(unittest.TestCase):
    """The stakeholder-analysis activity: register in, SysML and process state out."""

    @classmethod
    def setUpClass(cls):
        cls.tool = _load_stakeholder_tool()
        cls.root = Path(__file__).resolve().parents[1]
        cls.example = cls.root / "methodology" / "example"
        cls.methodology = cls.root / "methodology" / "product-development.yaml"

    def test_methodology_file_declares_the_three_rules(self):
        methodology_id, activity = self.tool.load_methodology(self.methodology)
        self.assertEqual(methodology_id, "product-development")
        self.assertEqual(activity["order"], 1)
        self.assertEqual(
            [step["id"] for step in activity["method"]["steps"]],
            ["list", "needs", "categorize"],
        )
        self.assertEqual(
            [item["id"] for item in activity["method"]["categories"]],
            ["customer", "internal", "regulatory"],
        )
        self.assertEqual(
            [rule["id"] for rule in activity["method"]["exit"]],
            ["has-stakeholder", "each-has-need", "each-categorized"],
        )

    def test_yaml_keeps_quoted_colons_and_drops_comments(self):
        loaded = self.tool.load_yaml(
            '# heading\n'
            'system: InfusionPump  # the device\n'
            'note: "The surgeon needs: a clear field."\n'
        )
        self.assertEqual(loaded["system"], "InfusionPump")
        self.assertEqual(loaded["note"], "The surgeon needs: a clear field.")

    def test_example_parses_without_warnings(self):
        folder = self.example
        texts = [
            (folder / name).read_text(encoding="utf-8")
            for name in ("stakeholders.sysml", "user_needs.sysml")
        ]
        model = parse_models(texts, ["stakeholders.sysml", "user_needs.sysml"])
        self.assertEqual(model["warnings"], [])
        self.assertEqual(node(model, "Surgeon")["kind"], "part def")
        self.assertTrue(node(model, "Customer")["abstract"])
        specs = {
            (e["from"].split("::")[-1], e["to"].split("::")[-1])
            for e in edges_of(model, "specialization")
        }
        self.assertIn(("Surgeon", "Customer"), specs)
        self.assertIn(("SystemsEngineer", "InternalStakeholder"), specs)
        self.assertIn(("NotifiedBody", "RegulatoryStakeholder"), specs)
        self.assertIn(("Customer", "Stakeholder"), specs)
        need = node(model, "SetTargetTemperature")
        self.assertEqual(need["kind"], "requirement")
        self.assertEqual(need["shortName"], "NEED-1")
        self.assertIn("Stakeholder: Surgeon (Customer).", need["doc"])
        comps = [
            (e["from"].split("::")[-1], e["to"].split("::")[-1], e["label"])
            for e in edges_of(model, "composition")
            if e["label"]
        ]
        self.assertIn(("OperationalContext", "Surgeon", "surgeon"), comps)
        self.assertIn(("OperationalContext", "InfusionPump", "infusionPump"), comps)

    def test_check_example_is_done_and_does_not_write(self):
        before = {
            name: (self.example / name).read_bytes()
            for name in (
                "stakeholders.sysml",
                "user_needs.sysml",
                "process/state.yaml",
                "process/stakeholders.yaml",
            )
        }
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = self.tool.main(["check", str(self.example)])
        self.assertEqual(code, 0)
        self.assertIn("Status: done", buf.getvalue())
        self.assertIn("apply would write", buf.getvalue())
        self.assertNotIn("Wrote ", buf.getvalue())
        after = {
            name: (self.example / name).read_bytes()
            for name in before
        }
        self.assertEqual(after, before)

    def test_apply_reproduces_the_example(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "process").mkdir()
            shutil.copy(
                self.example / "process" / "stakeholders.yaml",
                folder / "process" / "stakeholders.yaml",
            )
            result = self.tool.execute("apply", folder, self.methodology)
            self.assertEqual(result.code, 0)
            self.assertIn("Wrote stakeholders.sysml, user_needs.sysml, process/state.yaml.", result.report)
            for name in ("stakeholders.sysml", "user_needs.sysml", "process/state.yaml"):
                got = (folder / name).read_text(encoding="utf-8").replace("\r\n", "\n")
                expected = (self.example / name).read_text(encoding="utf-8").replace("\r\n", "\n")
                self.assertEqual(got, expected, name)

    def test_missing_need_stays_open_and_still_writes_the_model(self):
        register = """
system: InfusionPump
stakeholders:
  - name: Surgeon
    category: customer
    description: Uses the device on a patient.
    needs:
      - id: NEED-1
        name: SetTargetTemperature
        text: The surgeon needs to set a temperature.
  - name: SystemsEngineer
    category: internal
    description: Develops the product.
"""
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            self._write_register(folder, register)
            result = self.tool.execute("apply", folder, self.methodology)
            self.assertEqual(result.code, 2)
            self.assertIn("SystemsEngineer has no user need.", result.report)
            self.assertIn("Status: open", result.report)
            model = self._parsed(folder)
            self.assertEqual(model["warnings"], [])
            self.assertIn("SystemsEngineer", [n["name"] for n in model["nodes"]])
            self.assertNotIn("TraceableNeeds", [n["name"] for n in model["nodes"]])
            state = self.tool.load_yaml_file(folder / "process" / "state.yaml")
            self.assertEqual(state["status"], "open")
            unmet = [rule["id"] for rule in state["exit"] if not rule["met"]]
            self.assertEqual(unmet, ["each-has-need"])

    def test_missing_category_specializes_the_base_stakeholder(self):
        register = """
system: InfusionPump
stakeholders:
  - name: Surgeon
    description: Uses the device on a patient.
    needs:
      - id: NEED-1
        name: SetTargetTemperature
        text: The surgeon needs to set a temperature.
"""
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            self._write_register(folder, register)
            result = self.tool.execute("apply", folder, self.methodology)
            self.assertEqual(result.code, 2)
            self.assertIn("Surgeon has no category.", result.report)
            model = self._parsed(folder)
            specs = {
                (e["from"].split("::")[-1], e["to"].split("::")[-1])
                for e in edges_of(model, "specialization")
            }
            self.assertIn(("Surgeon", "Stakeholder"), specs)
            self.assertIn("Category: not set.", node(model, "Surgeon")["doc"])

    def test_bad_category_does_not_change_the_model(self):
        register = """
system: InfusionPump
stakeholders:
  - name: Surgeon
    category: client
    description: Uses the device.
    needs:
      - id: NEED-1
        name: SetTargetTemperature
        text: The surgeon needs to set a temperature.
"""
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            self._write_register(folder, register)
            result = self.tool.execute("apply", folder, self.methodology)
            self.assertEqual(result.code, 1)
            self.assertIn("client", result.report)
            self.assertIn("Model files were not changed.", result.report)
            self.assertFalse((folder / "stakeholders.sysml").exists())
            self.assertFalse((folder / "process" / "state.yaml").exists())

    def test_duplicate_need_id_is_an_error(self):
        register = """
system: InfusionPump
stakeholders:
  - name: Surgeon
    category: customer
    needs:
      - id: NEED-1
        name: SetTargetTemperature
        text: One need.
  - name: NotifiedBody
    category: regulatory
    needs:
      - id: NEED-1
        name: ShownConformity
        text: Another need.
"""
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            self._write_register(folder, register)
            result = self.tool.execute("check", folder, self.methodology)
            self.assertEqual(result.code, 1)
            self.assertIn("duplicate need id 'NEED-1'", result.report)
            self.assertFalse((folder / "stakeholders.sysml").exists())

    def test_missing_register_check_writes_nothing_and_apply_creates_a_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            checked = self.tool.execute("check", folder, self.methodology)
            self.assertEqual(checked.code, 2)
            self.assertIn("The register file is missing.", checked.report)
            self.assertIn("apply would write", checked.report)
            self.assertFalse((folder / "process" / "stakeholders.yaml").exists())
            applied = self.tool.execute("apply", folder, self.methodology)
            self.assertEqual(applied.code, 2)
            self.assertIn("Wrote process/stakeholders.yaml, process/state.yaml.", applied.report)
            self.assertFalse((folder / "stakeholders.sysml").exists())
            template = self.tool.load_yaml_file(folder / "process" / "stakeholders.yaml")
            self.assertEqual(template["system"], "SystemOfInterest")
            self.assertEqual(template["stakeholders"], [])
            state = self.tool.load_yaml_file(folder / "process" / "state.yaml")
            self.assertEqual(state["status"], "open")

    def _write_register(self, folder, text):
        path = folder / "process" / "stakeholders.yaml"
        path.parent.mkdir(parents=True)
        path.write_text(text.strip() + "\n", encoding="utf-8")

    def _parsed(self, folder):
        names = ["stakeholders.sysml", "user_needs.sysml"]
        texts = [(folder / name).read_text(encoding="utf-8") for name in names]
        return parse_models(texts, names)


class AssistantTests(unittest.TestCase):
    """Local chat: provider client, stakeholder tools, and the session page."""

    def settings(self, folder, **extra):
        from assistant.config import load_settings
        environ = {
            "ASSISTANT_BASE_URL": "https://example.test/v1",
            "ASSISTANT_API_KEY": "sk-test-secret",
            "ASSISTANT_MODEL": "test-model",
            "MODEL_FOLDER": str(folder),
            "EXPLORER_URL": "http://127.0.0.1:8199/",
            "ASSISTANT_PORT": "8201",
            "ASSISTANT_CHAT_PATH": "/chat/completions",
            "ASSISTANT_AUTH": "bearer",
        }
        environ.update(extra)
        return load_settings(environ=environ, files={})

    def test_environment_wins_over_env_file_and_the_key_is_not_a_setting_label(self):
        from assistant.config import load_settings, read_env_file
        text = "\n".join([
            "# comment",
            "ASSISTANT_MODEL=from-file",
            "ASSISTANT_API_KEY='file-secret'",
            "ASSISTANT_BASE_URL=http://files.example/v1",
            "",
        ])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text(text, encoding="utf-8")
            parsed = read_env_file(path)
        self.assertEqual(parsed["ASSISTANT_API_KEY"], "file-secret")
        settings = load_settings(
            environ={"ASSISTANT_MODEL": "from-env", "MODEL_FOLDER": tmp},
            files={
                "ASSISTANT_MODEL": "from-file",
                "ASSISTANT_API_KEY": "file-secret",
                "ASSISTANT_BASE_URL": "http://files.example/v1",
            },
        )
        self.assertEqual(settings.model, "from-env")
        self.assertEqual(settings.base_url, "http://files.example/v1")
        self.assertEqual(settings.api_key, "file-secret")

    def test_complete_uses_bearer_and_does_not_return_the_key(self):
        from assistant.provider import complete
        captured = {}

        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self):
                return json.dumps({
                    "choices": [{
                        "message": {
                            "content": "Hello there",
                            "tool_calls": [{
                                "id": "c1",
                                "type": "function",
                                "function": {
                                    "name": "stakeholder_check",
                                    "arguments": "{}",
                                },
                            }],
                        },
                    }],
                }).encode()

        def urlopen(request, timeout=0):
            captured["url"] = request.full_url
            captured["auth"] = request.get_header("Authorization")
            return Response()

        with tempfile.TemporaryDirectory() as tmp:
            result = complete(
                [{"role": "user", "content": "Hi"}],
                self.settings(Path(tmp)),
                tools=[{"type": "function"}],
                urlopen=urlopen,
            )
        self.assertEqual(result["content"], "Hello there")
        self.assertEqual(result["tool_calls"][0]["name"], "stakeholder_check")
        self.assertEqual(result["tool_calls"][0]["arguments"], {})
        self.assertEqual(captured["auth"], "Bearer sk-test-secret")
        self.assertTrue(captured["url"].endswith("/chat/completions"))
        self.assertNotIn("sk-test-secret", json.dumps(result))

    def test_api_key_header_mode(self):
        from assistant.provider import complete
        captured = {}

        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self):
                return json.dumps({
                    "choices": [{"message": {"content": "ok"}}],
                }).encode()

        def urlopen(request, timeout=0):
            captured["api_key"] = request.get_header("Api-key")
            captured["auth"] = request.get_header("Authorization")
            return Response()

        with tempfile.TemporaryDirectory() as tmp:
            complete(
                [{"role": "user", "content": "Hi"}],
                self.settings(Path(tmp), ASSISTANT_AUTH="api-key"),
                urlopen=urlopen,
            )
        self.assertEqual(captured["api_key"], "sk-test-secret")
        self.assertIsNone(captured["auth"])

    def test_new_folder_opens_with_the_greeting(self):
        from assistant.agent import GREETING, opening_text
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(opening_text(Path(tmp)), GREETING)

    def test_open_activity_skips_the_greeting(self):
        from assistant.agent import GREETING, opening_text
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            path = folder / "process" / "state.yaml"
            path.parent.mkdir()
            path.write_text(
                "activity: stakeholder-analysis\n"
                "status: open\n"
                "exit:\n"
                "  - id: each-has-need\n"
                "    met: false\n"
                "    text: Every stakeholder has at least one user need.\n"
                "    detail:\n"
                "      - Surgeon has no user need.\n",
                encoding="utf-8",
            )
            text = opening_text(folder)
        self.assertNotIn(GREETING, text)
        self.assertIn("still open", text)
        self.assertIn("Surgeon has no user need.", text)

    def test_apply_writes_the_model_and_a_bad_category_does_not(self):
        from assistant.tools import run_tool
        register = {
            "system": "InfusionPump",
            "stakeholders": [
                {
                    "name": "Surgeon",
                    "category": "customer",
                    "description": "Uses the device.",
                    "needs": [{
                        "id": "NEED-1",
                        "name": "SetTargetTemperature",
                        "text": "The surgeon needs to set a temperature.",
                    }],
                },
                {
                    "name": "SystemsEngineer",
                    "category": "Internal Stakeholder",
                    "description": "Develops the product.",
                    "needs": [{
                        "id": "NEED-2",
                        "name": "TraceableNeeds",
                        "text": "The engineer needs a trace to each need.",
                    }],
                },
                {
                    "name": "NotifiedBody",
                    "category": "regulatory",
                    "description": "Reviews the file.",
                    "needs": [{
                        "id": "NEED-3",
                        "name": "ShownConformity",
                        "text": "The body needs evidence of conformity.",
                    }],
                },
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            settings = self.settings(folder)
            report = run_tool("stakeholder_apply", register, settings)
            self.assertIn("Status: done", report)
            model = parse_models(
                [(folder / name).read_text(encoding="utf-8")
                 for name in ("stakeholders.sysml", "user_needs.sysml")],
                ["stakeholders.sysml", "user_needs.sysml"],
            )
            self.assertEqual(model["warnings"], [])
            self.assertIn("Surgeon", [node["name"] for node in model["nodes"]])
            rejected = run_tool("stakeholder_apply", {
                "system": "InfusionPump",
                "stakeholders": [{
                    "name": "Surgeon",
                    "category": "client",
                    "needs": [{
                        "id": "NEED-9",
                        "name": "OtherNeed",
                        "text": "A need that must not be written.",
                    }],
                }],
            }, settings)
            self.assertIn("not written", rejected.lower())
            self.assertNotIn("OtherNeed", (folder / "user_needs.sysml").read_text(encoding="utf-8"))
            self.assertIn(
                "Rejected unknown tool",
                run_tool("delete_model", {}, settings),
            )

    def test_turn_calls_check_then_answers(self):
        from assistant.agent import run_turn

        def fake(messages, tools):
            if not any(item["role"] == "tool" for item in messages):
                names = [tool["function"]["name"] for tool in tools]
                self.assertIn("stakeholder_check", names)
                self.assertIn("stakeholder_apply", names)
                return {
                    "content": "",
                    "tool_calls": [{
                        "id": "1",
                        "name": "stakeholder_check",
                        "arguments": {},
                    }],
                }
            self.assertIn("Stakeholder analysis", messages[-1]["content"])
            return {"content": "What is the product called?", "tool_calls": []}

        with tempfile.TemporaryDirectory() as tmp:
            updated, notes = run_turn(
                [{"role": "user", "content": "We are just starting."}],
                self.settings(Path(tmp)),
                fake,
            )
        self.assertEqual(updated[-1]["content"], "What is the product called?")
        self.assertEqual(notes, ["Checked the stakeholder register."])

    def test_turn_stops_when_tools_do_not_finish(self):
        from assistant.agent import run_turn

        def fake(messages, tools):
            return {
                "content": "",
                "tool_calls": [{"id": "1", "name": "nope", "arguments": {}}],
            }

        with tempfile.TemporaryDirectory() as tmp:
            updated, notes = run_turn(
                [{"role": "user", "content": "Hello"}],
                self.settings(Path(tmp)),
                fake,
            )
        self.assertIn("stopped", updated[-1]["content"])
        self.assertTrue(all(note.startswith("Rejected") for note in notes))

    def test_prompt_includes_shared_text_and_not_the_key(self):
        from assistant.agent import system_message
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "notes.txt").write_text(
                "The surgeon needs a quiet pump.", encoding="utf-8"
            )
            (folder / "brief.pdf").write_bytes(b"%PDF")
            content = system_message(self.settings(folder))["content"]
        self.assertIn("The surgeon needs a quiet pump.", content)
        self.assertIn("brief.pdf (PDF, not read)", content)
        self.assertIn("only after the team has confirmed", content)
        self.assertNotIn("sk-test-secret", content)

    def test_session_and_chat_hide_the_key(self):
        from assistant.agent import GREETING
        from assistant.server import make_handler
        from http.server import ThreadingHTTPServer

        def fake(messages, tools):
            return {"content": "What is the product called?", "tool_calls": []}

        with tempfile.TemporaryDirectory() as tmp:
            settings = self.settings(Path(tmp))
            server = ThreadingHTTPServer(
                ("127.0.0.1", 0), make_handler(settings, fake)
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                base = f"http://127.0.0.1:{port}"
                page = urllib.request.urlopen(base + "/").read().decode()
                self.assertIn("SE assistant", page)
                session = json.load(urllib.request.urlopen(base + "/api/session"))
                self.assertEqual(session["messages"][0]["content"], GREETING)
                self.assertNotIn("sk-test-secret", json.dumps(session))
                body = json.dumps({
                    "messages": session["messages"] + [
                        {"role": "user", "content": "We are starting a pump."}
                    ],
                }).encode()
                request = urllib.request.Request(
                    base + "/api/chat", data=body,
                    headers={"Content-Type": "application/json"},
                )
                payload = json.load(urllib.request.urlopen(request))
                self.assertEqual(
                    payload["messages"][-1]["content"],
                    "What is the product called?",
                )
                self.assertNotIn("sk-test-secret", json.dumps(payload))
            finally:
                server.shutdown()
                server.server_close()

    def test_health_check_returns_ok(self):
        from assistant.server import make_handler
        from http.server import ThreadingHTTPServer
        with tempfile.TemporaryDirectory() as tmp:
            settings = self.settings(Path(tmp))
            server = ThreadingHTTPServer(
                ("127.0.0.1", 0), make_handler(settings)
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                base = f"http://127.0.0.1:{port}"
                response = json.load(urllib.request.urlopen(base + "/healthz"))
                self.assertEqual(response["status"], "ok")
            finally:
                server.shutdown()
                server.server_close()

    def test_basic_auth_protects_endpoints(self):
        from assistant.server import make_handler
        from http.server import ThreadingHTTPServer
        import base64
        with tempfile.TemporaryDirectory() as tmp:
            settings = self.settings(
                Path(tmp),
                SE_AUTH_USER="testuser",
                SE_AUTH_PASSWORD="testpass",
            )
            server = ThreadingHTTPServer(
                ("127.0.0.1", 0), make_handler(settings)
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                base = f"http://127.0.0.1:{port}"
                
                try:
                    urllib.request.urlopen(base + "/api/session")
                    self.fail("Expected 401 without auth")
                except urllib.error.HTTPError as exc:
                    self.assertEqual(exc.code, 401)
                    self.assertIn("WWW-Authenticate", exc.headers)
                
                auth_string = base64.b64encode(b"testuser:testpass").decode()
                request = urllib.request.Request(
                    base + "/api/session",
                    headers={"Authorization": f"Basic {auth_string}"},
                )
                response = json.load(urllib.request.urlopen(request))
                self.assertIn("messages", response)
                
                bad_auth = base64.b64encode(b"wrong:wrong").decode()
                request = urllib.request.Request(
                    base + "/api/session",
                    headers={"Authorization": f"Basic {bad_auth}"},
                )
                try:
                    urllib.request.urlopen(request)
                    self.fail("Expected 401 with wrong credentials")
                except urllib.error.HTTPError as exc:
                    self.assertEqual(exc.code, 401)
            finally:
                server.shutdown()
                server.server_close()

    def test_health_check_bypasses_auth(self):
        from assistant.server import make_handler
        from http.server import ThreadingHTTPServer
        with tempfile.TemporaryDirectory() as tmp:
            settings = self.settings(
                Path(tmp),
                SE_AUTH_USER="testuser",
                SE_AUTH_PASSWORD="testpass",
            )
            server = ThreadingHTTPServer(
                ("127.0.0.1", 0), make_handler(settings)
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                base = f"http://127.0.0.1:{port}"
                response = json.load(urllib.request.urlopen(base + "/healthz"))
                self.assertEqual(response["status"], "ok")
            finally:
                server.shutdown()
                server.server_close()

    def test_port_env_var_takes_precedence(self):
        from assistant.config import load_settings
        settings = load_settings(
            environ={"PORT": "9000", "ASSISTANT_PORT": "8201", "MODEL_FOLDER": "/tmp"},
            files={},
        )
        self.assertEqual(settings.port, 9000)

    def test_se_data_dir_overrides_model_folder(self):
        from assistant.config import load_settings
        settings = load_settings(
            environ={"SE_DATA_DIR": "/data/models", "MODEL_FOLDER": "/tmp"},
            files={},
        )
        self.assertEqual(str(settings.model_folder), "/data/models")

    def test_seed_model_folder_creates_example_model(self):
        from assistant.server import seed_model_folder
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "models"
            seed_model_folder(target)
            self.assertTrue(target.is_dir())
            self.assertTrue((target / "stakeholders.sysml").exists())
            self.assertTrue((target / "user_needs.sysml").exists())
            self.assertTrue((target / "views").is_dir())

    def test_seed_model_folder_does_not_overwrite_existing(self):
        from assistant.server import seed_model_folder
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            existing = target / "my_model.sysml"
            existing.write_text("package MyModel { }", encoding="utf-8")
            seed_model_folder(target)
            self.assertTrue(existing.exists())
            self.assertFalse((target / "stakeholders.sysml").exists())

    def test_edit_activity_tool_writes_and_asks(self):
        from assistant.tools import run_tool
        from assistant.agent import run_turn
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "surgery.sysml").write_text(
                "package Surgery {\n    use case def PerformSurgery {}\n}\n",
                encoding="utf-8",
            )
            settings = self.settings(folder)
            missing = run_tool("edit_activity", {
                "op": "add-decision", "owner": "PerformSurgery",
                "after": "Assess Patient",
            }, settings)
            self.assertTrue(missing.startswith("Not written"))
            self.assertNotIn("decide", (folder / "surgery.sysml").read_text())

            def fake(messages, tools):
                names = [t["function"]["name"] for t in tools]
                self.assertIn("edit_activity", names)
                if not any(m.get("role") == "tool" for m in messages):
                    return {
                        "content": "",
                        "tool_calls": [{
                            "id": "1",
                            "name": "edit_activity",
                            "arguments": {
                                "op": "add-action",
                                "owner": "PerformSurgery",
                                "name": "Assess Patient",
                                "lane": "Surgeon",
                                "after": "start",
                                "splice": True,
                            },
                        }],
                    }
                return {"content": "Assess Patient is on the diagram.", "tool_calls": []}

            updated, notes = run_turn(
                [{"role": "user", "content":
                  "In PerformSurgery, the surgeon assesses the patient first."}],
                settings, fake,
            )
            self.assertIn("Assess Patient is on the diagram.", updated[-1]["content"])
            self.assertTrue(any("sysml" in note.lower() for note in notes))
            written = (folder / "surgery.sysml").read_text(encoding="utf-8")
            self.assertIn("perform 'Assess Patient'", written)
            self.assertIn("part def Surgeon", written)


class EmbeddedAssistantTests(unittest.TestCase):
    """Tests for the embedded assistant in the explorer."""
    
    def test_assistant_error_handling(self):
        """Chat API returns proper errors when things go wrong."""
        from assistant.config import Settings as AssistantSettings
        
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "test.sysml").write_text("part def TestPart {}")
            
            # Test with settings that could fail
            settings = AssistantSettings(
                base_url="http://invalid.example.com/v1",
                api_key="test_key",
                model="test-model",
                model_folder=str(folder),
                explorer_url="http://localhost:8199/",
                methodology=str(folder / "methodology.yaml"),
                host="127.0.0.1",
                port=8201,
                chat_path="/chat/completions",
                auth="bearer",
                auth_user="",
                auth_password="",
            )
            
            handler = make_handler(folder, folder / "layout.json", assistant_settings=settings)
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            
            try:
                port = server.server_address[1]
                base = f"http://127.0.0.1:{port}"
                
                # /api/session should work even with invalid backend
                session = json.load(urllib.request.urlopen(base + "/api/session"))
                self.assertIn("messages", session)
                
            finally:
                server.shutdown()
                server.server_close()
    
    def test_add_model_element_tool(self):
        """The add_model_element tool creates valid SysML following model conventions."""
        from assistant.tools import run_tool
        from assistant.config import Settings as AssistantSettings
        
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            settings = AssistantSettings(
                base_url="http://localhost:8080/v1",
                api_key="test",
                model="test",
                model_folder=str(folder),
                explorer_url="http://localhost:8199/",
                methodology=str(folder / "methodology.yaml"),
                host="127.0.0.1",
                port=8201,
                chat_path="/chat/completions",
                auth="bearer",
                auth_user="",
                auth_password="",
            )
            
            # Add a stakeholder (person) - creates part def, not actor def
            result = run_tool("add_model_element", {
                "element_type": "stakeholder",
                "name": "Nurse",
                "description": "Healthcare professional administering treatment",
            }, settings)
            
            self.assertIn("Added part def", result)
            self.assertIn("Nurse", result)
            
            # Check the file was created with Context naming
            context_file = folder / "SystemContext.sysml"
            self.assertTrue(context_file.exists())
            content = context_file.read_text()
            self.assertIn("part def Nurse", content)
            self.assertIn("Healthcare professional", content)
            self.assertNotIn("actor def", content)  # Should be part def, not actor def
            
            # Try to add duplicate - should fail
            result = run_tool("add_model_element", {
                "element_type": "stakeholder",
                "name": "Nurse",
                "description": "Duplicate",
            }, settings)
            self.assertIn("already exists", result)
            
            # Add another stakeholder
            result = run_tool("add_model_element", {
                "element_type": "stakeholder",
                "name": "Patient",
                "description": "Person receiving care",
            }, settings)
            self.assertIn("Added part def", result)
            
            # Verify both are in the same file
            content = context_file.read_text()
            self.assertIn("part def Nurse", content)
            self.assertIn("part def Patient", content)
    
    def test_hosted_commit_path(self):
        """In hosted mode, assistant edits are committed and pushed."""
        if not shutil.which("git"):
            self.skipTest("git not available")
        
        with tempfile.TemporaryDirectory() as tmp:
            repo_dir = Path(tmp) / "repo"
            repo_dir.mkdir()
            
            # Initialize a bare git repo to simulate the remote
            bare = Path(tmp) / "bare.git"
            subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)
            
            # Initialize the working repo
            subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo_dir, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True)
            subprocess.run(["git", "remote", "add", "origin", str(bare)], cwd=repo_dir, check=True)
            
            # Create initial model
            (repo_dir / "test.sysml").write_text("part def Initial {}")
            subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
            subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_dir, check=True)
            subprocess.run(["git", "push", "-u", "origin", "main"], cwd=repo_dir, check=True)
            
            # Set up sync
            from system_explorer.cloud import GitSync
            sync = GitSync(str(bare), repo_dir, "main", token=None, async_push=False)
            
            # Create a mock user
            user = {"login": "testuser", "name": "Test User", "id": 12345}
            
            # Simulate assistant writing a file
            (repo_dir / "model_elements.sysml").write_text("actor def TestActor {}")
            
            # Commit and push
            sync.commit_and_push([repo_dir / "model_elements.sysml"], "Assistant: add TestActor", user)
            
            # Verify the commit was made with proper authorship
            result = subprocess.run(
                ["git", "log", "-1", "--format=%an|%ae"],
                cwd=repo_dir,
                capture_output=True,
                text=True,
                check=True
            )
            author_line = result.stdout.strip()
            self.assertIn("Test User", author_line)
            self.assertIn("12345+testuser@users.noreply.github.com", author_line)
    
    def test_assistant_routes_in_local_mode(self):
        """Assistant routes work in local mode without auth."""
        from assistant.config import Settings as AssistantSettings
        
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "test.sysml").write_text(
                'package Test { part def Motor; }', encoding="utf-8"
            )
            layout_path = folder / "layout.json"
            
            assistant_settings = AssistantSettings(
                base_url="http://test.com",
                api_key="test-key",
                model="test-model",
                model_folder=str(folder),
                explorer_url="http://localhost:8199",
                methodology=str(folder / "method.yaml"),
                host="127.0.0.1",
                port=8201,
                chat_path="/chat/completions",
                auth="bearer",
                auth_user="",
                auth_password="",
            )
            
            handler = make_handler(folder, layout_path, assistant_settings=assistant_settings)
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            
            try:
                port = server.server_address[1]
                base = f"http://127.0.0.1:{port}"
                
                # Check /api/session
                session = json.load(urllib.request.urlopen(base + "/api/session"))
                self.assertIn("messages", session)
                self.assertIn("configured", session)
                
                # Check assistant panel CSS
                css = urllib.request.urlopen(base + "/assistant_panel.css").read().decode()
                self.assertIn("#assistantPanel", css)
                
                # Check assistant panel JS
                js = urllib.request.urlopen(base + "/assistant_panel.js").read().decode()
                self.assertIn("assistantPanel", js)
            finally:
                server.shutdown()
                server.server_close()
    
    def test_assistant_disabled_when_not_configured(self):
        """Explorer works when assistant is not configured."""
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "test.sysml").write_text(
                'package Test { part def Motor; }', encoding="utf-8"
            )
            layout_path = folder / "layout.json"
            
            # No assistant_settings = assistant disabled
            handler = make_handler(folder, layout_path, assistant_settings=None)
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            
            try:
                port = server.server_address[1]
                base = f"http://127.0.0.1:{port}"
                
                # Explorer should still work
                model = json.load(urllib.request.urlopen(base + "/api/model"))
                self.assertIn("nodes", model)
                
                # Assistant routes return 404
                try:
                    urllib.request.urlopen(base + "/api/session")
                    self.fail("Expected no /api/session route")
                except urllib.error.HTTPError as exc:
                    self.assertEqual(exc.code, 404)
            finally:
                server.shutdown()
                server.server_close()
    
    def test_assistant_basic_auth_in_local_mode(self):
        """Assistant respects Basic Auth in local mode."""
        import base64
        from assistant.config import Settings as AssistantSettings
        
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "test.sysml").write_text(
                'package Test { part def Motor; }', encoding="utf-8"
            )
            layout_path = folder / "layout.json"
            
            assistant_settings = AssistantSettings(
                base_url="http://test.com",
                api_key="test-key",
                model="test-model",
                model_folder=str(folder),
                explorer_url="http://localhost:8199",
                methodology=str(folder / "method.yaml"),
                host="127.0.0.1",
                port=8201,
                chat_path="/chat/completions",
                auth="bearer",
                auth_user="admin",
                auth_password="secret",
            )
            
            handler = make_handler(folder, layout_path, assistant_settings=assistant_settings)
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            
            try:
                port = server.server_address[1]
                base = f"http://127.0.0.1:{port}"
                
                # Without auth, should fail
                try:
                    urllib.request.urlopen(base + "/api/session")
                    self.fail("Expected 401 without auth")
                except urllib.error.HTTPError as exc:
                    self.assertEqual(exc.code, 401)
                
                # With correct auth, should work
                auth_string = base64.b64encode(b"admin:secret").decode()
                request = urllib.request.Request(
                    base + "/api/session",
                    headers={"Authorization": f"Basic {auth_string}"},
                )
                session = json.load(urllib.request.urlopen(request))
                self.assertIn("messages", session)
            finally:
                server.shutdown()
                server.server_close()


    def test_chat_uses_the_tool_methodology_not_the_model_folder(self):
        """A model repo has no methodology file. Chat must still answer.

        Pointing the prompt at <model>/methodology/product-development.yaml
        raised FileNotFoundError inside the request and the socket closed.
        """
        from assistant.config import explorer_settings
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "CoolSpineSystemContext.sysml").write_text(
                "package CoolSpineSystemContext {\n    part def Patient {}\n}\n",
                encoding="utf-8",
            )
            self.assertFalse((folder / "methodology").exists())
            settings = explorer_settings(
                folder, "http://127.0.0.1:8199/", 8199,
                environ={
                    "ASSISTANT_BASE_URL": "https://example.test/v1",
                    "ASSISTANT_MODEL": "test-model",
                    "ASSISTANT_API_KEY": "sk-test",
                },
            )
            self.assertTrue(settings.methodology.is_file())
            self.assertFalse(str(settings.methodology).startswith(str(folder)))
            self.assertIsNone(settings.configuration_error())

            def fake(messages, bound, tools=None, timeout=90, urlopen=None):
                self.assertIn("add_model_element", json.dumps(tools))
                return {"content": "What does the nurse do?", "tool_calls": []}

            handler = make_handler(folder, folder / "layout.json", assistant_settings=settings)
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                body = json.dumps({"messages": [
                    {"role": "user", "content": "Add a nurse to the context"},
                ]}).encode()
                request = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/chat",
                    data=body,
                    headers={"Content-Type": "application/json"},
                )
                with patch("assistant.provider.complete", fake):
                    payload = json.load(urllib.request.urlopen(request, timeout=10))
                self.assertEqual(payload.get("error"), "")
                self.assertEqual(
                    payload["messages"][-1]["content"], "What does the nurse do?"
                )
            finally:
                server.shutdown()
                server.server_close()

    def test_chat_round_trip_adds_nurse_part_def(self):
        """A mocked provider calls add_model_element; the file and the reply update."""
        from assistant.config import explorer_settings
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "CoolSpineSystemContext.sysml").write_text(
                "package CoolSpineSystemContext {\n    part def Patient {}\n}\n",
                encoding="utf-8",
            )
            settings = explorer_settings(
                folder, "http://127.0.0.1:8199/", 8199,
                environ={
                    "ASSISTANT_BASE_URL": "https://example.test/v1",
                    "ASSISTANT_MODEL": "test-model",
                    "ASSISTANT_API_KEY": "sk-test",
                },
            )

            def fake(messages, bound, tools=None, timeout=90, urlopen=None):
                if messages and messages[-1].get("role") == "tool":
                    return {"content": "Added Nurse to the context.", "tool_calls": []}
                return {
                    "content": "",
                    "tool_calls": [{
                        "id": "call-1",
                        "name": "add_model_element",
                        "arguments": {
                            "element_type": "stakeholder",
                            "name": "Nurse",
                            "description": (
                                "Monitors the patient during cooling. "
                                "Works beside the anesthesiologist."
                            ),
                        },
                    }],
                }

            handler = make_handler(folder, folder / "layout.json", assistant_settings=settings)
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                body = json.dumps({"messages": [
                    {"role": "user", "content": "She monitors the patient during cooling."},
                ]}).encode()
                request = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/chat",
                    data=body,
                    headers={"Content-Type": "application/json"},
                )
                with patch("assistant.provider.complete", fake):
                    payload = json.load(urllib.request.urlopen(request, timeout=10))
                self.assertEqual(payload.get("error"), "")
                self.assertEqual(payload["messages"][-1]["content"], "Added Nurse to the context.")
                self.assertTrue(any("model" in note.lower() for note in payload["notes"]))
                text = (folder / "CoolSpineSystemContext.sysml").read_text(encoding="utf-8")
                self.assertIn("part def Nurse", text)
                self.assertNotIn("actor def", text)
                self.assertNotIn("..", text)
                self.assertIn("Works beside the anesthesiologist.", text)
            finally:
                server.shutdown()
                server.server_close()

    def test_chat_failure_is_json_not_a_dropped_connection(self):
        from assistant.config import explorer_settings
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "m.sysml").write_text("package M { part def A {} }\n", encoding="utf-8")
            settings = explorer_settings(
                folder, "http://127.0.0.1/", 1,
                environ={
                    "ASSISTANT_BASE_URL": "https://example.test/v1",
                    "ASSISTANT_MODEL": "test-model",
                },
            )
            handler = make_handler(folder, folder / "layout.json", assistant_settings=settings)
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]

                def explode(messages, bound, tools=None, timeout=90, urlopen=None):
                    raise RuntimeError("provider boom")

                body = json.dumps({"messages": [
                    {"role": "user", "content": "Hello"},
                ]}).encode()
                request = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/chat",
                    data=body,
                    headers={"Content-Type": "application/json"},
                )
                with patch("assistant.provider.complete", explode):
                    try:
                        urllib.request.urlopen(request, timeout=10)
                        self.fail("expected an HTTP error with a JSON body")
                    except urllib.error.HTTPError as exc:
                        payload = json.loads(exc.read().decode())
                self.assertIn("provider boom", payload["error"])
                self.assertNotIn("sk-", json.dumps(payload))
            finally:
                server.shutdown()
                server.server_close()

    def test_hosted_session_cookie_can_call_chat(self):
        """Hosted mode accepts the signed session cookie. The cookie is not why chat failed."""
        from assistant.config import explorer_settings
        from system_explorer.cloud import SESSION_COOKIE, CloudContext, GitHubAuth
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "m.sysml").write_text("package M { part def A {} }\n", encoding="utf-8")
            settings = explorer_settings(
                folder, "", 8080,
                environ={
                    "ASSISTANT_BASE_URL": "https://example.test/v1",
                    "ASSISTANT_MODEL": "test-model",
                },
            )

            class Sync:
                def pull(self):
                    return None

                def commit_and_push(self, paths, message, user=None):
                    return None

            auth = GitHubAuth(
                "cid", "csec", "session-secret", "https://explorer.example",
                "PatrykPrezyna/spine-cooling-model", allowed_users=["ada"],
            )
            cloud = CloudContext(Sync(), auth, folder)
            handler = make_handler(
                folder, folder / "layout.json", cloud, assistant_settings=settings
            )
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                base = f"http://127.0.0.1:{port}"
                try:
                    urllib.request.urlopen(base + "/api/session", timeout=10)
                    self.fail("expected 401 without a session")
                except urllib.error.HTTPError as exc:
                    self.assertEqual(exc.code, 401)

                cookie = SESSION_COOKIE + "=" + auth.make_session(
                    {"login": "ada", "name": "Ada", "id": 7}
                )

                def fake(messages, bound, tools=None, timeout=90, urlopen=None):
                    return {"content": "What does the nurse do?", "tool_calls": []}

                body = json.dumps({"messages": [
                    {"role": "user", "content": "Add a nurse to the context"},
                ]}).encode()
                request = urllib.request.Request(
                    base + "/api/chat",
                    data=body,
                    headers={
                        "Content-Type": "application/json",
                        "Cookie": cookie,
                    },
                )
                with patch("assistant.provider.complete", fake):
                    payload = json.load(urllib.request.urlopen(request, timeout=10))
                self.assertEqual(payload["messages"][-1]["content"], "What does the nurse do?")
            finally:
                server.shutdown()
                server.server_close()

    def test_hosted_anonymous_access_can_call_chat(self):
        """ALLOW_ANONYMOUS lets the page through, so the assistant must too."""
        from assistant.config import explorer_settings
        from system_explorer.cloud import CloudContext
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "m.sysml").write_text("package M { part def A {} }\n", encoding="utf-8")
            settings = explorer_settings(
                folder, "", 8080,
                environ={
                    "ASSISTANT_BASE_URL": "https://example.test/v1",
                    "ASSISTANT_MODEL": "test-model",
                },
            )

            class Sync:
                def pull(self):
                    return None

                def commit_and_push(self, paths, message, user=None):
                    return None

            cloud = CloudContext(Sync(), None, folder)
            handler = make_handler(
                folder, folder / "layout.json", cloud, assistant_settings=settings
            )
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]

                def fake(messages, bound, tools=None, timeout=90, urlopen=None):
                    return {"content": "pong", "tool_calls": []}

                body = json.dumps({"messages": [
                    {"role": "user", "content": "Say pong"},
                ]}).encode()
                request = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/chat",
                    data=body,
                    headers={"Content-Type": "application/json"},
                )
                with patch("assistant.provider.complete", fake):
                    payload = json.load(urllib.request.urlopen(request, timeout=10))
                self.assertEqual(payload["messages"][-1]["content"], "pong")
            finally:
                server.shutdown()
                server.server_close()

    def test_panel_assets_are_in_the_wheel(self):
        """pip install (the Docker image) must ship the chat panel files."""
        import zipfile
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "wheel", "--no-deps", "-w", tmp, str(root)],
                stdout=subprocess.DEVNULL,
            )
            wheels = list(Path(tmp).glob("*.whl"))
            self.assertEqual(len(wheels), 1)
            names = zipfile.ZipFile(wheels[0]).namelist()
        self.assertIn("system_explorer/assistant_panel.js", names)
        self.assertIn("system_explorer/assistant_panel.css", names)
        self.assertIn(
            "system_explorer/examples/insulin-pump/InsulinPumpContext.sysml",
            names,
        )
        self.assertIn(
            "system_explorer/examples/insulin-pump/views/occlusion.json",
            names,
        )
        self.assertIn(
            "system_explorer/examples/insulin-pump/project.json", names,
        )
        page = (root / "src" / "system_explorer" / "viewer.html").read_text(encoding="utf-8")
        self.assertIn("function refreshAfterAssistantEdit", page)


class TraceLinkParserTests(unittest.TestCase):
    """Stakeholder features and derivation dependencies are trace edges."""

    def test_stakeholder_feature_and_derivation_dependency(self):
        model = parse_sysml("""
        package P {
            part def Surgeon;
            requirement def UserNeed;
            requirement <'NEED-1'> Warm : UserNeed {
                stakeholder surgeon : Surgeon;
            }
            requirement <'REQ-1'> Heat;
            #derivation dependency deriveHeat from 'REQ-1' to 'NEED-1';
        }
        """)
        self.assertEqual(model["warnings"], [])
        stakeholders = edges_of(model, "stakeholder")
        self.assertEqual(
            [(e["from"], e["to"], e["label"]) for e in stakeholders],
            [("P::Warm", "P::Surgeon", "surgeon")],
        )
        derived = edges_of(model, "derive")
        self.assertEqual(
            [(e["from"], e["to"], e["label"]) for e in derived],
            [("P::Heat", "P::Warm", "«derive»")],
        )

    def test_second_stakeholder_role_of_the_same_type_is_one_edge(self):
        model = parse_sysml("""
        package P {
            part def Surgeon;
            requirement def Need {
                stakeholder lead : Surgeon;
                stakeholder backup : Surgeon;
            }
        }
        """)
        self.assertEqual(len(edges_of(model, "stakeholder")), 1)
        self.assertEqual(model["warnings"], [])

    def test_unresolved_stakeholder_and_derive_warn(self):
        model = parse_sysml("""
        package P {
            requirement def Need {
                stakeholder ghost : Nobody;
            }
            #derivation dependency d from Missing to Need;
        }
        """)
        self.assertEqual(edges_of(model, "stakeholder"), [])
        self.assertEqual(edges_of(model, "derive"), [])
        text = " ".join(model["warnings"])
        self.assertIn("Nobody", text)
        self.assertIn("Missing", text)


class ModelEditTests(unittest.TestCase):
    """Quick-add writes standard SysML and the explorer's own check accepts it."""

    def test_stakeholder_use_case_and_actor_round_trip(self):
        from system_explorer.model_edit import apply_edit
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "CoolSpineSystemContext.sysml").write_text(
                "package CoolSpineSystemContext {\n    part def Patient;\n}\n",
                encoding="utf-8",
            )
            added = apply_edit(folder, {
                "action": "add_stakeholder",
                "name": "the nurse",
                "description": "Watches the patient during cooling.",
            })
            self.assertTrue(added["ok"], added)
            self.assertEqual(added["addedIds"], ["CoolSpineSystemContext::TheNurse"])
            text = (folder / "CoolSpineSystemContext.sysml").read_text(encoding="utf-8")
            self.assertIn("part def TheNurse", text)
            self.assertIn("Watches the patient during cooling.", text)
            self.assertNotIn("actor def", text)

            case = apply_edit(folder, {
                "action": "add_use_case",
                "name": "Deliver cooling",
                "description": "Cool the patient to the target.",
            })
            self.assertTrue(case["ok"], case)
            use_text = (folder / "UseCases.sysml").read_text(encoding="utf-8")
            self.assertIn("use case def DeliverCooling", use_text)
            self.assertIn("package UseCases", use_text)

            linked = apply_edit(folder, {
                "action": "link_actor",
                "stakeholder": "TheNurse",
                "useCase": "DeliverCooling",
            })
            self.assertTrue(linked["ok"], linked)
            use_text = (folder / "UseCases.sysml").read_text(encoding="utf-8")
            self.assertIn("actor theNurse : TheNurse;", use_text)
            self.assertIn("private import CoolSpineSystemContext::*;", use_text)
            self.assertIn("CoolSpineSystemContext::TheNurse", linked["showIds"])
            self.assertIn("UseCases::DeliverCooling", linked["showIds"])

            again = apply_edit(folder, {
                "action": "link_actor",
                "stakeholder": "TheNurse",
                "useCase": "DeliverCooling",
            })
            self.assertFalse(again["ok"])
            self.assertIn("already", again["error"])

            dup = apply_edit(folder, {"action": "add_stakeholder", "name": "TheNurse"})
            self.assertFalse(dup["ok"])

            env = os.environ.copy()
            env["PYTHONPATH"] = str(SRC)
            checked = subprocess.run(
                [sys.executable, "-m", "system_explorer", str(folder), "--check"],
                capture_output=True, text=True, env=env,
            )
            self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
            self.assertIn("no warnings", checked.stdout)

    def test_plain_words_and_refused_names(self):
        from system_explorer.model_edit import upper_camel, apply_edit
        self.assertEqual(upper_camel("Nurse"), "Nurse")
        self.assertEqual(upper_camel("notified body"), "NotifiedBody")
        self.assertIsNone(upper_camel("123"))
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "m.sysml").write_text("package M { part def A; }\n", encoding="utf-8")
            refused = apply_edit(folder, {"action": "add_stakeholder", "name": "..."})
            self.assertFalse(refused["ok"])
            self.assertFalse(list(folder.glob("*Context.sysml")))

    def test_restore_rejects_paths_outside_the_folder(self):
        from system_explorer.model_edit import apply_edit
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "m.sysml").write_text("package M { part def A; }\n", encoding="utf-8")
            bad = apply_edit(folder, {"action": "restore_files", "files": [
                {"name": "../evil.sysml", "text": "package X { part def Z; }\n"},
            ]})
            self.assertFalse(bad["ok"])
            self.assertFalse((folder.parent / "evil.sysml").exists())
            wiped = apply_edit(folder, {"action": "restore_files", "files": [
                {"name": "m.sysml", "text": ""},
            ]})
            self.assertTrue(wiped["ok"], wiped)
            self.assertFalse((folder / "m.sysml").exists())

    def test_http_edit_and_hosted_commit(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "SystemContext.sysml").write_text(
                "package SystemContext {\n}\n", encoding="utf-8",
            )
            commits = []

            class Sync:
                def pull(self):
                    return None

                def commit_and_push(self, paths, message, user=None):
                    commits.append((paths, message, user))

            class Auth:
                def session_user(self, cookie):
                    return {"login": "ada", "name": "Ada", "id": 7}

            cloud = SimpleNamespace(sync=Sync(), auth=Auth(), repo_root=folder)
            handler = make_handler(folder, folder / "layout.json", cloud)
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                body = json.dumps({
                    "action": "add_stakeholder",
                    "name": "Surgeon",
                    "description": "Uses the device.",
                }).encode()
                request = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/model/edit",
                    data=body,
                    headers={"Content-Type": "application/json"},
                )
                payload = json.load(urllib.request.urlopen(request, timeout=10))
                self.assertTrue(payload["ok"], payload)
                self.assertEqual(commits[0][1], "Add stakeholder Surgeon")
                self.assertEqual(commits[0][2]["login"], "ada")
                text = (folder / "SystemContext.sysml").read_text(encoding="utf-8")
                self.assertIn("part def Surgeon", text)
            finally:
                server.shutdown()
                server.server_close()


@unittest.skipUnless(EDGE, "Microsoft Edge not found; skipping rendering tests")
class TraceAndInterviewDomTests(unittest.TestCase):
    """The traceability view dims a thread; interview views show quick-add."""

    TRACE = """
    package Ctx {
        part def Surgeon;
        part def Nurse;
        part def Device;
        use case def Cool {
            actor surgeon : Surgeon;
            subject device : Device;
            satisfy requirement 'REQ-1';
        }
        requirement <'NEED-1'> Warm {
            stakeholder surgeon : Surgeon;
        }
        requirement <'REQ-1'> Heat;
        #derivation dependency d from 'REQ-1' to 'NEED-1';
        verification def Check {
            objective { verify requirement 'REQ-1'; }
        }
    }
    """

    def test_trace_closure_highlights_the_thread_and_dims_the_rest(self):
        model = parse_sysml(self.TRACE)
        js = viewer_js("const TRACE_KINDS", "function selectNode")
        ids = [n["id"] for n in model["nodes"]]
        edge_json = json.dumps([
            {"kind": e["kind"], "from": e["from"], "to": e["to"],
             "label": e.get("label") or ""}
            for e in model["edges"]
        ])
        setup = "\n".join([
            "function edgeKey(d) { return d.kind + '|' + d.from + '|' + d.to + '|' + (d.label || ''); }",
            "function isTraceView(v) {",
            "  if (!v || v.kind === 'activity') return false;",
            "  return ((v.name || '') + ' ' + (v.id || '')).toLowerCase().includes('trace');",
            "}",
            "function makeEl() { const d = document.createElement('div'); document.body.appendChild(d); return d; }",
            f"const ids = {json.dumps(ids)};",
            "let nodes = {};",
            "for (const id of ids) nodes[id] = { el: makeEl() };",
            f"const rawEdges = {edge_json};",
            "let edges = rawEdges.map(data => ({ data, el: makeEl() }));",
            "let selection = null;",
            "let activeView = { id: 'traceability', name: 'Traceability', kind: 'bdd' };",
            "let mode = 'bdd';",
            "function syncActivityBar() {}",
            js,
            "selection = { type: 'node', id: 'Ctx::Heat' };",
            "applySelection();",
        ])
        got = run_js(setup, """({
          focus: document.body.classList.contains('trace-focus'),
          heat: nodes['Ctx::Heat'].el.classList.contains('sel'),
          warm: nodes['Ctx::Warm'].el.classList.contains('hl'),
          surgeon: nodes['Ctx::Surgeon'].el.classList.contains('hl'),
          cool: nodes['Ctx::Cool'].el.classList.contains('hl'),
          check: nodes['Ctx::Check'].el.classList.contains('hl'),
          nurse: nodes['Ctx::Nurse'].el.className,
          derive: edges.find(e => e.data.kind === 'derive').el.classList.contains('hl'),
          satisfy: edges.find(e => e.data.kind === 'satisfy').el.classList.contains('hl')
        })""")
        self.assertTrue(got["focus"])
        self.assertTrue(got["heat"])
        self.assertTrue(got["warm"])
        self.assertTrue(got["surgeon"])
        self.assertTrue(got["cool"])
        self.assertTrue(got["check"])
        self.assertNotIn("hl", got["nurse"])
        self.assertNotIn("sel", got["nurse"])
        self.assertTrue(got["derive"])
        self.assertTrue(got["satisfy"])

    def test_click_on_a_trace_view_does_not_open_the_sheet(self):
        page = VIEWER_HTML.read_text(encoding="utf-8")
        self.assertIn("if (isTraceView(activeView)) hideSheet();", page)
        self.assertIn("else showSheet(nodeEl.dataset.id);", page)

    def test_context_view_shows_quick_add_and_trace_view_does_not(self):
        elements = [n["id"] for n in parse_sysml(self.TRACE)["nodes"]]
        views = {
            "context": {
                "name": "Context", "elements": elements, "nodes": {},
                "hiddenEdges": [], "view": None, "options": {},
            },
        }
        srv = ServerFixture(text=self.TRACE, views=views)
        try:
            srv.layout_path.write_text(
                json.dumps({"activeView": "context", "home": False}),
                encoding="utf-8")
            dom = dump_dom(srv.url)
            self.assertIn('id="quickAdd"', dom)
            self.assertNotRegex(dom, r'<div id="quickAdd"[^>]*class="hidden"')
            self.assertIn("Stakeholder", dom)
            self.assertIn("Use case", dom)
            self.assertNotIn("trace-view", dom.split("<body", 1)[-1][:80])
        finally:
            srv.close()

        views = {
            "traceability": {
                "name": "Traceability", "elements": elements, "nodes": {},
                "hiddenEdges": [], "view": None, "options": {},
            },
        }
        srv = ServerFixture(text=self.TRACE, views=views)
        try:
            srv.layout_path.write_text(
                json.dumps({"activeView": "traceability", "home": False}),
                encoding="utf-8")
            dom = dump_dom(srv.url)
            self.assertIn('id="quickAdd" class="hidden"', dom)
            self.assertRegex(dom, r"<body[^>]*trace-view")
            self.assertNotIn('class="sheet"', dom.split("<body", 1)[0] + "BODY")
            self.assertNotRegex(dom, r"<body[^>]*\bsheet\b")
        finally:
            srv.close()

    def test_activity_view_hides_quick_add(self):
        views = {
            "activity-context": {
                "name": "Context activity", "kind": "activity",
                "activityOwner": "Ctx::Cool",
                "elements": [], "nodes": {}, "hiddenEdges": [],
                "view": None, "options": {},
            },
        }
        srv = ServerFixture(text=self.TRACE, views=views)
        try:
            srv.layout_path.write_text(
                json.dumps({"activeView": "activity-context"}),
                encoding="utf-8")
            dom = dump_dom(srv.url)
            self.assertIn('id="quickAdd" class="hidden"', dom)
            self.assertNotRegex(dom, r"<body[^>]*trace-view")
        finally:
            srv.close()

    def test_save_status_and_undo_buttons_are_on_the_toolbar(self):
        srv = ServerFixture(text=self.TRACE, views={
            "v": {"name": "Plain", "elements": [], "nodes": {},
                  "hiddenEdges": [], "view": None, "options": {}},
        })
        try:
            dom = dump_dom(srv.url)
            self.assertIn('id="undoBtn"', dom)
            self.assertIn('id="redoBtn"', dom)
            self.assertIn(">Saved<", dom)
            self.assertIn("Saving", (SRC / "system_explorer" / "viewer.html").read_text(encoding="utf-8"))
        finally:
            srv.close()
# ----------------------------------------------------------------------
# Projects (spec 0003) and the bundled insulin pump
# ----------------------------------------------------------------------

from system_explorer import projects as projects_mod  # noqa: E402

SPINE_SENTINEL = (
    "package Spine {\n"
    "    part def DoNotTouch {\n"
    "        doc /* sentinel-spine-cooling */\n"
    "    }\n"
    "}\n"
)


def _cookie_pair(set_cookie):
    return set_cookie.split(";", 1)[0]


def _http(port, method, path, body=None, cookie=None):
    import http.client
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    headers = {}
    if cookie:
        headers["Cookie"] = cookie
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    conn.request(method, path, body=data, headers=headers)
    response = conn.getresponse()
    result = (response.status, response.headers, response.read().decode("utf-8", "replace"))
    conn.close()
    return result


class ProjectLibraryTests(unittest.TestCase):
    def test_empty_project_is_a_package_and_a_context_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = projects_mod.ProjectLibrary(Path(tmp))
            info = library.create_empty(owner="ada")
            model, paths = app_mod.load_folder(info["dir"])
            self.assertEqual(model["warnings"], [])
            self.assertEqual(model["nodes"], [])
            self.assertEqual(
                {p.name for p in paths},
                {"NewProject.sysml", "NewProjectContext.sysml"},
            )
            context = (info["dir"] / "NewProjectContext.sysml").read_text(encoding="utf-8")
            self.assertIn("package NewProjectContext", context)
            self.assertIn("private import NewProject::*;", context)

    def test_list_is_newest_first_and_root_model_is_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "CoolSpineSystemContext.sysml").write_text(
                SPINE_SENTINEL, encoding="utf-8"
            )
            before = (root / "CoolSpineSystemContext.sysml").read_bytes()
            library = projects_mod.ProjectLibrary(root)
            older = library.create_empty()
            newer = library.create_empty()
            for info, stamp in (
                (older, "2020-01-01T00:00:00Z"),
                (newer, "2021-06-01T00:00:00Z"),
            ):
                meta_path = info["dir"] / "project.json"
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                meta["created"] = stamp
                meta_path.write_text(json.dumps(meta), encoding="utf-8")
            listed = library.list_projects()
            self.assertEqual(
                [item["id"] for item in listed],
                [newer["id"], older["id"], "repository"],
            )
            self.assertTrue(listed[-1]["readOnly"])
            self.assertEqual(listed[-1]["name"], "Repository model")
            with self.assertRaises(PermissionError):
                library.assert_project_file(root / "CoolSpineSystemContext.sysml")
            self.assertEqual(
                (root / "CoolSpineSystemContext.sysml").read_bytes(), before
            )

    def test_example_model_checks_clean_and_has_the_requested_content(self):
        folder = projects_mod.example_dir()
        model, _paths = app_mod.load_folder(folder)
        self.assertEqual(model["warnings"], [])
        names = {n["name"] for n in model["nodes"]}
        for stakeholder in (
            "Patient", "Caregiver", "Endocrinologist", "Regulator", "Manufacturer",
        ):
            self.assertIn(stakeholder, names)
        for use_case in (
            "DeliverBasalInsulin", "DeliverBolus", "HandleOcclusionAlarm",
        ):
            self.assertIn(use_case, names)
        # The occlusion steps are standard SysML v2 (actions on the use
        # case, perform inside each actor, first/then, decide/if/else,
        # merge). This branch's parser accepts that text and does not
        # require the swimlane parser to be present. The source is what
        # that view reads once it lands.
        text = (folder / "InsulinPumpUseCases.sysml").read_text(encoding="utf-8")
        self.assertNotIn("perform action", text)
        for snippet in (
            "actor pump : InsulinPump",
            "perform 'Raise Alarm'",
            "perform 'Notice Alarm'",
            "perform 'Check Line'",
            "action 'Raise Alarm'",
            "first start then 'Raise Alarm'",
            "decide decide1",
            "if clear then 'Clear Line'",
            "else 'Hold Delivery'",
            "merge merge1",
            "first merge1 then done",
        ):
            self.assertIn(snippet, text)
        kinds = {e["kind"] for e in model["edges"]}
        self.assertIn("satisfy", kinds)
        self.assertIn("verify", kinds)
        proc = subprocess.run(
            [sys.executable, "-m", "system_explorer", str(folder), "--check"],
            cwd=SRC, capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("no warnings", proc.stdout)

    def test_example_files_are_package_data_in_the_wheel(self):
        # Same install path as the Docker image (`pip install .`). A previous
        # bug shipped the package without its data files.
        import zipfile
        root = Path(__file__).resolve().parents[1]
        pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("examples/insulin-pump/*.sysml", pyproject)
        self.assertIn("examples/insulin-pump/views/*.json", pyproject)
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "wheel", "--no-deps", "-w", tmp, str(root)],
                stdout=subprocess.DEVNULL,
            )
            wheels = list(Path(tmp).glob("*.whl"))
            self.assertEqual(len(wheels), 1)
            names = zipfile.ZipFile(wheels[0]).namelist()
        for rel in (
            "system_explorer/examples/insulin-pump/InsulinPumpContext.sysml",
            "system_explorer/examples/insulin-pump/InsulinPumpUseCases.sysml",
            "system_explorer/examples/insulin-pump/views/context.json",
            "system_explorer/examples/insulin-pump/views/occlusion.json",
            "system_explorer/examples/insulin-pump/layout.json",
        ):
            self.assertIn(rel, names)


class ProjectServerTests(unittest.TestCase):
    """Local workspace: new project, list, example, and the read-only root."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.sentinel = self.root / "CoolSpineSystemContext.sysml"
        self.sentinel.write_text(SPINE_SENTINEL, encoding="utf-8")
        self.before = self.sentinel.read_bytes()
        self.example_before = (
            projects_mod.example_dir() / "InsulinPumpContext.sysml"
        ).read_bytes()
        self.library = projects_mod.ProjectLibrary(self.root)
        info = self.library.create_empty()
        self.library.default_id = info["id"]
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            make_handler(self.root, self.root / "layout.json", library=self.library),
        )
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def request(self, method, path, body=None, cookie=None):
        return _http(self.port, method, path, body, cookie)

    def test_startup_project_is_empty_and_root_model_is_unchanged(self):
        status, headers, body = self.request("GET", "/api/model")
        self.assertEqual(status, 200)
        model = json.loads(body)
        self.assertEqual(model["warnings"], [])
        self.assertNotIn("DoNotTouch", [n["name"] for n in model["nodes"]])
        self.assertIn("NewProject", model["package"])
        self.assertIn("NewProjectContext", model["package"])
        pinned = headers["Set-Cookie"]
        self.assertTrue(pinned.startswith(projects_mod.PROJECT_COOKIE + "="))
        status, _, listed = self.request("GET", "/api/projects", cookie=_cookie_pair(pinned))
        self.assertEqual(status, 200)
        payload = json.loads(listed)
        self.assertEqual(payload["current"]["name"], "New project")
        self.assertTrue(payload["canCreate"])
        ids = [item["id"] for item in payload["projects"]]
        self.assertIn(payload["current"]["id"], ids)
        self.assertIn("repository", ids)
        self.assertEqual(self.sentinel.read_bytes(), self.before)

    def test_new_project_is_listed_and_can_be_opened(self):
        _, headers, _ = self.request("GET", "/api/projects")
        cookie = _cookie_pair(headers["Set-Cookie"])
        status, headers, body = self.request("POST", "/api/projects", {}, cookie)
        self.assertEqual(status, 200)
        created = json.loads(body)
        self.assertEqual(created["name"], "New project")
        opened = _cookie_pair(headers["Set-Cookie"])
        status, _, listed = self.request("GET", "/api/projects", cookie=opened)
        payload = json.loads(listed)
        self.assertEqual(payload["current"]["id"], created["id"])
        self.assertGreaterEqual(len(payload["projects"]), 2)
        self.assertEqual(self.sentinel.read_bytes(), self.before)

    def test_example_loads_and_a_write_copies_it(self):
        status, headers, body = self.request("POST", "/api/projects/example", {})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["id"], "example")
        cookie = _cookie_pair(headers["Set-Cookie"])
        status, _, body = self.request("GET", "/api/model", cookie=cookie)
        self.assertEqual(status, 200)
        model = json.loads(body)
        names = {n["name"] for n in model["nodes"]}
        self.assertIn("Patient", names)
        self.assertIn("HandleOcclusionAlarm", names)
        self.assertEqual(model["warnings"], [])
        self.assertTrue(any(e["kind"] == "satisfy" for e in model["edges"]))
        status, _, views = self.request("GET", "/api/views", cookie=cookie)
        self.assertEqual(status, 200)
        view_ids = {v["id"] for v in json.loads(views)}
        self.assertIn("context", view_ids)
        self.assertIn("occlusion", view_ids)
        status, headers, _ = self.request(
            "PUT", "/api/views/context",
            {"version": 1, "name": "Context", "elements": [], "nodes": {}},
            cookie,
        )
        self.assertEqual(status, 200)
        copied = _cookie_pair(headers["Set-Cookie"])
        self.assertNotIn("example", copied)
        status, _, body = self.request("GET", "/api/model", cookie=copied)
        self.assertIn("Patient", {n["name"] for n in json.loads(body)["nodes"]})
        self.assertEqual(
            (projects_mod.example_dir() / "InsulinPumpContext.sysml").read_bytes(),
            self.example_before,
        )
        self.assertEqual(self.sentinel.read_bytes(), self.before)

    def test_repository_model_is_readable_and_not_writable(self):
        status, headers, _ = self.request(
            "POST", "/api/projects/open", {"id": "repository"}
        )
        self.assertEqual(status, 200)
        cookie = _cookie_pair(headers["Set-Cookie"])
        status, _, body = self.request("GET", "/api/model", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertIn("DoNotTouch", [n["name"] for n in json.loads(body)["nodes"]])
        self.assertIn("sentinel-spine-cooling", body)
        status, _, _ = self.request(
            "PUT", "/api/views/context", {"name": "Nope", "elements": []}, cookie
        )
        self.assertEqual(status, 403)
        self.assertEqual(self.sentinel.read_bytes(), self.before)
        self.assertFalse((self.root / "layout.json").exists())


class ProjectCloudTests(unittest.TestCase):
    """Hosted mode: login creates a project and does not rewrite the root."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.bare = root / "remote.git"
        _git(root, "init", "-q", "--bare", "-b", "main", str(self.bare))
        seed = root / "seed"
        _git(root, "clone", "-q", str(self.bare), str(seed))
        (seed / "CoolSpineSystemContext.sysml").write_text(
            SPINE_SENTINEL, encoding="utf-8"
        )
        _git(seed, "add", "-A")
        _git(seed, "commit", "-q", "-m", "seed spine model")
        _git(seed, "push", "-q", "origin", "HEAD:main")
        self.work = root / "work"
        self.sync = cloud_mod.GitSync(
            str(self.bare), self.work, "main", pull_interval=0, async_push=False
        )
        self.sync.clone_or_update()
        self.sentinel = self.work / "CoolSpineSystemContext.sysml"
        self.before = self.sentinel.read_bytes()
        self.library = projects_mod.ProjectLibrary(self.work)
        self.auth = _stub_auth()

        def on_login(user, library=self.library, sync=self.sync):
            info = library.create_empty(owner=user.get("login"))
            sync.commit_and_push(
                info["files"], f"Create project '{info['name']}'", user
            )
            return [projects_mod.project_cookie_header(info["id"])]

        self.auth.on_login = on_login
        ctx = cloud_mod.CloudContext(self.sync, self.auth, self.work)
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            make_handler(self.work, self.work / "layout.json", ctx, library=self.library),
        )
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def request(self, method, path, body=None, cookie=None):
        return _http(self.port, method, path, body, cookie)

    def login(self, code="alice"):
        status, headers, _ = self.request(
            "GET", f"/auth/callback?code={code}&state=abc",
            cookie=f"{cloud_mod.STATE_COOKIE}=abc",
        )
        self.assertEqual(status, 302, _)
        pairs = [_cookie_pair(c) for c in headers.get_all("Set-Cookie")]
        return "; ".join(pairs)

    def test_login_opens_a_new_project_and_leaves_the_root_model(self):
        cookie = self.login()
        self.assertIn(projects_mod.PROJECT_COOKIE + "=", cookie)
        self.assertIn(cloud_mod.SESSION_COOKIE + "=", cookie)
        status, _, page = self.request("GET", "/", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertIn('id="exampleBtn"', page)
        status, _, body = self.request("GET", "/api/model", cookie=cookie)
        self.assertEqual(status, 200)
        model = json.loads(body)
        self.assertNotIn("DoNotTouch", [n["name"] for n in model["nodes"]])
        self.assertIn("NewProject", model["package"])
        status, _, listed = self.request("GET", "/api/projects", cookie=cookie)
        payload = json.loads(listed)
        self.assertEqual(payload["current"]["name"], "New project")
        self.assertEqual(payload["current"]["owner"], "alice")
        self.assertTrue(any(item["id"] == "repository" for item in payload["projects"]))
        self.assertEqual(self.sentinel.read_bytes(), self.before)
        shown = _git(self.bare, "show", "main:CoolSpineSystemContext.sysml")
        self.assertIn("sentinel-spine-cooling", shown)
        committed = _git(self.work, "log", "-1", "--name-only", "--pretty=format:")
        self.assertNotIn("CoolSpineSystemContext.sysml", committed.split())
        self.assertTrue(any(line.startswith("projects/") for line in committed.split()))

        self.login("alice")
        projects = [
            p for p in self.library.list_projects() if p["id"] != "repository"
        ]
        self.assertEqual(len(projects), 2)
        self.assertEqual(self.sentinel.read_bytes(), self.before)

    def test_forged_session_without_a_project_still_starts_empty(self):
        cookie = self.auth.make_session({"login": "alice", "name": "Alice", "id": 42})
        status, headers, body = self.request(
            "GET", "/api/model", cookie=f"{cloud_mod.SESSION_COOKIE}={cookie}"
        )
        self.assertEqual(status, 200)
        self.assertIn("NewProject", json.loads(body)["package"])
        self.assertNotIn("DoNotTouch", body)
        self.assertTrue(
            headers["Set-Cookie"].startswith(projects_mod.PROJECT_COOKIE + "=")
        )
        self.assertEqual(self.sentinel.read_bytes(), self.before)
        status, _, _ = self.request("GET", "/api/model")
        self.assertEqual(status, 401)

    def test_repository_model_cannot_be_committed(self):
        cookie = self.login()
        status, headers, _ = self.request(
            "POST", "/api/projects/open", {"id": "repository"}, cookie
        )
        self.assertEqual(status, 200)
        opened = _cookie_pair(
            [c for c in headers.get_all("Set-Cookie")
             if c.startswith(projects_mod.PROJECT_COOKIE + "=")][0]
        )
        # keep the session cookie too
        session = [part for part in cookie.split("; ")
                   if part.startswith(cloud_mod.SESSION_COOKIE + "=")][0]
        both = session + "; " + opened
        before_log = _git(self.bare, "log", "--oneline")
        status, _, _ = self.request(
            "POST", "/api/layout", {"docs": {"hacked": True}}, both
        )
        self.assertEqual(status, 403)
        self.assertEqual(self.sentinel.read_bytes(), self.before)
        self.assertEqual(_git(self.bare, "log", "--oneline"), before_log)
        self.assertFalse((self.work / "layout.json").exists())


class ProjectCliTests(unittest.TestCase):
    def _serve(self, folder, *extra):
        import socket
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        env = os.environ.copy()
        env["PYTHONPATH"] = str(SRC)
        proc = subprocess.Popen(
            [sys.executable, "-m", "system_explorer", str(folder),
             "--no-open", "--port", str(port), *extra],
            cwd=str(SRC), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        deadline = time.time() + 20
        last = None
        while time.time() < deadline:
            if proc.poll() is not None:
                self.fail(proc.stdout.read())
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/model", timeout=1
                ) as response:
                    return proc, port, response.read().decode("utf-8")
            except Exception as exc:
                last = exc
                time.sleep(0.1)
        proc.kill()
        self.fail(f"server did not start: {last}")

    def _stop(self, proc):
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)

    def test_workspace_flag_starts_a_new_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sentinel = root / "CoolSpineSystemContext.sysml"
            sentinel.write_text(SPINE_SENTINEL, encoding="utf-8")
            before = sentinel.read_bytes()
            proc, port, body = self._serve(root, "--workspace")
            try:
                model = json.loads(body)
                self.assertIn("NewProject", model["package"])
                self.assertNotIn("DoNotTouch", [n["name"] for n in model["nodes"]])
                listed = json.loads(urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/projects", timeout=5
                ).read().decode("utf-8"))
                self.assertEqual(listed["current"]["name"], "New project")
                self.assertTrue(any(
                    item["id"] == "repository" for item in listed["projects"]
                ))
                self.assertEqual(sentinel.read_bytes(), before)
            finally:
                self._stop(proc)

    def test_empty_folder_starts_a_new_project_without_the_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc, _port, body = self._serve(Path(tmp))
            try:
                model = json.loads(body)
                self.assertIn("NewProject", model["package"])
                self.assertEqual(model["nodes"], [])
                self.assertEqual(model["warnings"], [])
            finally:
                self._stop(proc)


if __name__ == "__main__":
    unittest.main()
