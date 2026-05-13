"""Parametric 4-DOF desktop servo robotic arm (CadQuery 2.x).

Educational acrylic-style laser-cut arm: rectangular base plate, elevated
rotating platform on standoffs, shoulder and elbow servo joints driving a
two-link arm, and a horizontal gear-driven two-finger claw gripper.

Structure of this file:
  1. Parameters      — all dimensions in one dict (mm)
  2. Part generators — one function per component
  3. Assembly        — explicit joint math + transforms
  4. Exports         — assembly STEP, per-part STEP + STL (into ./output)

Approximations (educational model, not a production design):
  - Servos are simplified boxes with flange and 3 mm output shaft.
  - Spur gear teeth are simplified rectangular teeth on a pitch cylinder;
    meshing gears are phase-shifted by half a tooth pitch so they interleave.
  - The claw is shown at a nominal opening (POSE["claw_open_deg"]); the
    20-80 mm opening range is reached by rotating the finger gears.
  - Cable routing is approximated by a slot in the platform and a hole in
    the base plate behind the base-rotation servo.
"""

import math
from pathlib import Path

import cadquery as cq

try:
    from ocp_vscode import show
except ImportError:  # viewer extension not installed — exports still work
    show = None

# ---------------------------------------------------------------------------
# 1. Parameters (mm)
# ---------------------------------------------------------------------------

params = {
    "plate_thickness": 5.0,
    "base_length": 220,
    "base_width": 180,
    "upper_platform_size": 120,
    "shoulder_length": 420,      # center-to-center
    "forearm_length": 220,       # center-to-center
    "link_width": 30,
    "servo_width": 20,
    "servo_height": 40,
    "servo_depth": 40,
    "gear_thickness": 5,
    "gripper_length": 70,
    "claw_length": 55,
    "m3_clearance": 3.2,
    "standoff_diameter": 10,
    "standoff_height": 40,
}

# Display pose of the arm (degrees)
POSE = {
    "shoulder_deg": 60,    # upper arm above horizontal
    "forearm_deg": -20,    # forearm below horizontal
    "claw_open_deg": 8,    # nominal finger opening
}

ORANGE = cq.Color(1.00, 0.55, 0.10)   # acrylic plates
BLACK = cq.Color(0.13, 0.13, 0.13)    # standoffs, feet, bracket
SERVO_BLUE = cq.Color(0.15, 0.20, 0.55)
GEAR_WHITE = cq.Color(0.90, 0.90, 0.85)


# ---------------------------------------------------------------------------
# 2. Part generators
# ---------------------------------------------------------------------------

def make_base_plate(p):
    """Rectangular base plate: rounded corners, corner mounting holes,
    suction-cup mounting holes, standoff holes and a cable routing hole."""
    L, W, t = p["base_length"], p["base_width"], p["plate_thickness"]
    m3 = p["m3_clearance"]
    corner_pts = [(sx * (L / 2 - 8), sy * (W / 2 - 8)) for sx in (-1, 1) for sy in (-1, 1)]
    suction_pts = [(sx * 95, sy * 75) for sx in (-1, 1) for sy in (-1, 1)]
    standoff_pts = [(sx * 45, sy * 45) for sx in (-1, 1) for sy in (-1, 1)]

    plate = cq.Workplane("XY").box(L, W, t).edges("|Z").fillet(5)
    plate = plate.faces(">Z").workplane().pushPoints(corner_pts).hole(m3)
    plate = plate.faces(">Z").workplane().pushPoints(suction_pts).hole(4.0)
    plate = plate.faces(">Z").workplane().pushPoints(standoff_pts).hole(m3)
    # cable routing hole behind the base-rotation servo
    plate = plate.faces(">Z").workplane().pushPoints([(-40, 0)]).hole(10)
    return plate


def make_suction_foot(p):
    """Simplified suction-cup foot (flat black cylinder under the base)."""
    return cq.Workplane("XY").circle(9).extrude(6)


def make_standoff(p):
    """Round standoff between base plate and rotating platform."""
    return cq.Workplane("XY").circle(p["standoff_diameter"] / 2).extrude(p["standoff_height"])


def make_rotating_platform(p):
    """Upper square platform: standoff holes, central rotation-axis hole
    and a cable routing slot."""
    s, t, m3 = p["upper_platform_size"], p["plate_thickness"], p["m3_clearance"]
    standoff_pts = [(sx * 45, sy * 45) for sx in (-1, 1) for sy in (-1, 1)]

    plate = cq.Workplane("XY").box(s, s, t).edges("|Z").fillet(5)
    plate = plate.faces(">Z").workplane().pushPoints(standoff_pts).hole(m3)
    plate = plate.faces(">Z").workplane().hole(m3)          # central rotation axis
    plate = plate.faces(">Z").workplane().center(-40, 0).rect(10, 16).cutThruAll()
    return plate


def make_servo(p):
    """Simplified hobby servo: body, mounting flange, 3 mm output shaft.
    Local frame: body z 0..servo_height, shaft on top at x = +10."""
    d, w, h = p["servo_depth"], p["servo_width"], p["servo_height"]
    body = cq.Workplane("XY").box(d, w, h).translate((0, 0, h / 2))
    flange = cq.Workplane("XY").box(d + 15, w, 2.5).translate((0, 0, h * 0.75))
    shaft = (
        cq.Workplane("XY")
        .workplane(offset=h)
        .center(10, 0)
        .circle(1.5)
        .extrude(5)
    )
    return body.union(flange).union(shaft)


def make_shoulder_plate(p):
    """Vertical side plate carrying the shoulder pivot: rounded top with
    pivot hole at the local origin, rectangular body down to the platform."""
    t, m3 = p["plate_thickness"], p["m3_clearance"]
    plate = (
        cq.Workplane("XY").circle(20).extrude(t)
        .union(cq.Workplane("XY").center(0, -30).rect(40, 60).extrude(t))
        .translate((0, 0, -t / 2))
    )
    plate = (
        plate.faces(">Z").workplane()
        .pushPoints([(0, 0), (-12, -55), (12, -55)])
        .hole(m3)
    )
    return plate


def make_arm_link(p, length):
    """Flat acrylic-style arm link: slot outline with rounded ends, pivot
    holes at +/- length/2 and three lightening holes. Thickness-centered."""
    t, w, m3 = p["plate_thickness"], p["link_width"], p["m3_clearance"]
    link = (
        cq.Workplane("XY").sketch().slot(length, w).finalize()
        .extrude(t).translate((0, 0, -t / 2))
    )
    link = (
        link.faces(">Z").workplane()
        .pushPoints([(-length / 2, 0), (length / 2, 0)])
        .hole(m3)
    )
    link = (
        link.faces(">Z").workplane()
        .pushPoints([(-length / 4, 0), (0, 0), (length / 4, 0)])
        .hole(13)
    )
    return link


def make_wrist_mount(p):
    """Compact bracket joining the forearm pivot to the gripper housing.
    Local frame: box centered at origin, forearm pivot hole at (-3, *, +5)."""
    bracket = cq.Workplane("XY").box(26, 8, 40)
    pivot = cq.Workplane("XZ").center(-3, 5).circle(p["m3_clearance"] / 2).extrude(10, both=True)
    return bracket.cut(pivot)


def make_gripper_housing(p):
    """Box-like servo enclosure, open at the bottom, 5 mm top wall carrying
    the gear axles. Local frame: origin at the wrist axis height, gears on
    top face (local z = +20), gear axles at (25, +/-16), pinion at (0, 16)."""
    t, m3 = p["plate_thickness"], p["m3_clearance"]
    L = p["gripper_length"]
    housing = cq.Workplane("XY").box(L, 56, 45).translate((0, 0, -2.5))
    cavity = cq.Workplane("XY").box(L - 10, 46, 40).translate((0, 0, -5))
    housing = housing.cut(cavity)
    housing = (
        housing.faces(">Z").workplane()
        .pushPoints([(25, 16), (25, -16)])
        .hole(m3)                                   # finger gear axles
    )
    housing = housing.faces(">Z").workplane().pushPoints([(0, 16)]).hole(6)  # servo shaft
    return housing


def make_spur_gear(p, pitch_radius, tooth_count):
    """Simplified spur gear: pitch cylinder plus rectangular teeth
    (3 mm radial x 1.8 mm tangential), M3 bore."""
    gt = p["gear_thickness"]
    body = cq.Workplane("XY").circle(pitch_radius).extrude(gt)
    teeth = (
        cq.Workplane("XY")
        .polarArray(pitch_radius, 0, 360, tooth_count)
        .rect(3, 1.8)
        .extrude(gt)
    )
    gear = body.union(teeth)
    gear = gear.faces(">Z").workplane().hole(p["m3_clearance"])
    return gear


def make_claw_finger(p):
    """Right claw finger: mounting tab over the gear axis (local origin),
    curved hook profile gripping toward local -Y. Mirror for the left."""
    t, m3 = p["plate_thickness"], p["m3_clearance"]
    s = p["claw_length"] / 55.0     # scale profile to claw_length
    pts = [
        (0 * s, 12), (30 * s, 8), (48 * s, 0), (55 * s, -10),
        (46 * s, -14), (38 * s, -9), (24 * s, -3), (0 * s, -12),
    ]
    finger = (
        cq.Workplane("XY").polyline(pts).close().extrude(t)
        .union(cq.Workplane("XY").circle(13).extrude(t))
    )
    finger = finger.faces(">Z").workplane().hole(m3)
    return finger


# ---------------------------------------------------------------------------
# 3. Assembly
# ---------------------------------------------------------------------------

def _loc(x, y, z, rx=0.0, ry=0.0, rz=0.0):
    """Location applying local rotations Rx, then Ry, then Rz, then translate."""
    return (
        cq.Location((x, y, z))
        * cq.Location((0, 0, 0), (0, 0, 1), rz)
        * cq.Location((0, 0, 0), (0, 1, 0), ry)
        * cq.Location((0, 0, 0), (1, 0, 0), rx)
    )


def build_arm_assembly(p):
    """Build the full arm at the POSE display pose."""
    t = p["plate_thickness"]
    m3 = p["m3_clearance"]

    # ---- joint kinematics (arm moves in the XZ plane, pivots along Y) ----
    z_platform_top = t + p["standoff_height"] + t          # 50
    p1 = (0.0, 0.0, z_platform_top + 60)                    # shoulder pivot
    a1 = math.radians(POSE["shoulder_deg"])
    a2 = math.radians(POSE["forearm_deg"])
    p2 = (p1[0] + p["shoulder_length"] * math.cos(a1), 0.0,
          p1[2] + p["shoulder_length"] * math.sin(a1))      # elbow pivot
    p3 = (p2[0] + p["forearm_length"] * math.cos(a2), 0.0,
          p2[2] + p["forearm_length"] * math.sin(a2))       # wrist pivot

    # lateral (Y) stacking: forearm inside upper arm inside shoulder plates
    y_forearm = 7.0
    y_upper_arm = 13.0
    y_shoulder_plate = 18.5

    # gripper frame: housing center; gears on its top face
    hc = (p3[0] + 16 + p["gripper_length"] / 2, 0.0, p3[2] - 5)
    z_gear = p3[2] + 15
    gear_r, gear_teeth = 16, 24
    pinion_r, pinion_teeth = 8, 12
    gear_a = (hc[0] + 25, 16.0)     # right finger gear
    gear_b = (hc[0] + 25, -16.0)    # left finger gear
    pinion = (hc[0], 16.0)          # servo pinion, meshes gear_a

    # ---- parts ----
    base_plate = make_base_plate(p)
    foot = make_suction_foot(p)
    standoff = make_standoff(p)
    platform = make_rotating_platform(p)
    servo = make_servo(p)
    shoulder_plate = make_shoulder_plate(p)
    upper_arm = make_arm_link(p, p["shoulder_length"])
    forearm = make_arm_link(p, p["forearm_length"])
    wrist_mount = make_wrist_mount(p)
    housing = make_gripper_housing(p)
    finger_gear = make_spur_gear(p, gear_r, gear_teeth)
    pinion_gear = make_spur_gear(p, pinion_r, pinion_teeth)
    finger_r = make_claw_finger(p)
    finger_l = finger_r.mirror("XZ")

    assy = cq.Assembly(name="robotic_arm")

    # base structure
    assy.add(base_plate, name="base_plate", loc=_loc(0, 0, t / 2), color=ORANGE)
    for i, (sx, sy) in enumerate([(-1, -1), (-1, 1), (1, -1), (1, 1)]):
        assy.add(foot, name=f"suction_foot_{i}",
                 loc=_loc(sx * 95, sy * 75, -6), color=BLACK)
        assy.add(standoff, name=f"standoff_{i}",
                 loc=_loc(sx * 45, sy * 45, t), color=BLACK)
    assy.add(platform, name="rotating_platform",
             loc=_loc(0, 0, t + p["standoff_height"] + t / 2), color=ORANGE)
    assy.add(servo, name="base_servo", loc=_loc(-10, 0, t), color=SERVO_BLUE)

    # shoulder
    for side, sy in (("r", 1), ("l", -1)):
        assy.add(shoulder_plate, name=f"shoulder_plate_{side}",
                 loc=_loc(p1[0], sy * y_shoulder_plate, p1[2], rx=90), color=ORANGE)
    assy.add(servo, name="shoulder_servo",
             loc=_loc(p1[0] - 10, y_shoulder_plate + 2.5 + p["servo_height"], p1[2], rx=90),
             color=SERVO_BLUE)

    # upper arm (two parallel plates)
    c_ua = ((p1[0] + p2[0]) / 2, (p1[2] + p2[2]) / 2)
    for side, sy in (("r", 1), ("l", -1)):
        assy.add(upper_arm, name=f"upper_arm_{side}",
                 loc=_loc(c_ua[0], sy * y_upper_arm, c_ua[1],
                          rx=90, ry=-POSE["shoulder_deg"]), color=ORANGE)

    # elbow
    assy.add(servo, name="elbow_servo",
             loc=_loc(p2[0] - 10, y_upper_arm + 2.5 + p["servo_height"], p2[2], rx=90),
             color=SERVO_BLUE)

    # forearm (two parallel plates)
    c_fa = ((p2[0] + p3[0]) / 2, (p2[2] + p3[2]) / 2)
    for side, sy in (("r", 1), ("l", -1)):
        assy.add(forearm, name=f"forearm_{side}",
                 loc=_loc(c_fa[0], sy * y_forearm, c_fa[1],
                          rx=90, ry=-POSE["forearm_deg"]), color=ORANGE)

    # wrist + gripper
    assy.add(wrist_mount, name="wrist_mount",
             loc=_loc(p3[0] + 3, 0, p3[2] - 5), color=BLACK)
    assy.add(housing, name="gripper_housing",
             loc=_loc(hc[0], hc[1], hc[2]), color=ORANGE)
    assy.add(servo, name="wrist_servo",
             loc=_loc(pinion[0] - 10, pinion[1], p3[2] - 30), color=SERVO_BLUE)

    # gear train: half-tooth phase offsets so simplified teeth interleave
    assy.add(finger_gear, name="finger_gear_r",
             loc=_loc(gear_a[0], gear_a[1], z_gear), color=GEAR_WHITE)
    assy.add(finger_gear, name="finger_gear_l",
             loc=_loc(gear_b[0], gear_b[1], z_gear, rz=360 / gear_teeth / 2),
             color=GEAR_WHITE)
    assy.add(pinion_gear, name="pinion",
             loc=_loc(pinion[0], pinion[1], z_gear, rz=360 / pinion_teeth / 2),
             color=GEAR_WHITE)

    # claw fingers on top of the finger gears
    assy.add(finger_r, name="claw_finger_r",
             loc=_loc(gear_a[0], gear_a[1], z_gear + p["gear_thickness"],
                      rz=POSE["claw_open_deg"]), color=ORANGE)
    assy.add(finger_l, name="claw_finger_l",
             loc=_loc(gear_b[0], gear_b[1], z_gear + p["gear_thickness"],
                      rz=-POSE["claw_open_deg"]), color=ORANGE)

    parts = {
        "base_plate": base_plate,
        "suction_foot": foot,
        "standoff": standoff,
        "rotating_platform": platform,
        "servo": servo,
        "shoulder_plate": shoulder_plate,
        "upper_arm_link": upper_arm,
        "forearm_link": forearm,
        "wrist_mount": wrist_mount,
        "gripper_housing": housing,
        "finger_gear": finger_gear,
        "pinion_gear": pinion_gear,
        "claw_finger": finger_r,
    }
    return assy, parts


# ---------------------------------------------------------------------------
# 4. Exports
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    assembly, parts = build_arm_assembly(params)

    if show is not None:
        try:
            show(assembly)
        except Exception:
            pass  # viewer not open — exports below still run

    out = Path(__file__).parent / "output"
    out.mkdir(exist_ok=True)

    assembly.export(str(out / "robotic_arm_assembly.step"))
    for name, part in parts.items():
        cq.exporters.export(part, str(out / f"{name}.step"))
        cq.exporters.export(part, str(out / f"{name}.stl"))
    print(f"Exported assembly + {len(parts)} parts (STEP/STL) to {out}")
