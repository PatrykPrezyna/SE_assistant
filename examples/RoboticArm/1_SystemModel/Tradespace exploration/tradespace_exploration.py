"""Tradespace exploration for the robotic arm logical architecture.

Reads the SysML v2 BDD model (System Model/robotic_arm_bdd.sysml) and
enumerates candidate architectures:

  - servo assignment : one ServoDrive variant per joint  -> 3^5 combinations
  - geometry         : the link lengths from the BDD, swept by a common
                       scale factor (the BDD as-modeled arm is scale 1.0)

For every candidate the script computes
  - reach : horizontal reach = sum of the shoulder..gripper link lengths
            (the base joint is a vertical yaw column and adds height, not
            reach)
  - cost  : sum of the five servo unit costs plus the five mechanical
            assemblies (BDD default cost, scaled by length and material)

and checks static feasibility: each pitch servo must hold the fully
extended, fully loaded arm (0.5 kg payload per REQ-200) with a 2x safety
factor; the base servo must yaw the extended arm; the gripper servo must
grip the payload through the finger friction pair.  Link masses are
estimated as thin-walled square tubes using length / wallThickness /
material straight from the BDD.

Outputs
  - output/tradespace_reach_cost.png : reach (y) vs cost (x) scatter with
    the Pareto front (max reach, min cost) and the as-modeled baseline
  - output/tradespace_points.csv     : every evaluated design point
  - console summary of the Pareto-optimal architectures
"""

import csv
import itertools
import re
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
MODEL_FILE = ROOT / "System Model" / "robotic_arm_bdd.sysml"
OUTPUT_DIR = ROOT / "output"

G = 9.81                 # m/s^2
PAYLOAD_KG = 0.5         # REQ-200 upper bound, carried at the gripper tip
SAFETY_FACTOR = 2.0      # stall vs continuous holding, wear, voltage sag
YAW_ACCEL = 3.0          # rad/s^2 target base acceleration, arm extended
FRICTION_MU = 0.5        # rubber finger pads on dry object
FINGER_LEN_M = 0.030     # grip force lever arm at the fingertip

TUBE_WIDTH_MM = 40.0     # outer width of the square link tube (all links)
DENSITY = {              # kg/mm^3
    "Aluminum": 2.70e-6,
    "CarbonFiber": 1.60e-6,
}
# mechanics cost = BDD default cost x material factor x (length / 100 mm)
MATERIAL_COST_FACTOR = {
    "Aluminum": 1.0,
    "CarbonFiber": 2.5,
}

JOINTS = ["BaseJoint", "ShoulderJoint", "ElbowJoint", "WristJoint", "GripperJoint"]
CHAIN = JOINTS[1:]                      # links that contribute to reach
SCALES = [0.6, 0.8, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0]

# dataviz palette (light mode): surface/ink/grid + categorical slots 1-2
C_SURFACE = "#fcfcfb"
C_INK = "#0b0b0b"
C_INK_2ND = "#52514e"
C_MUTED = "#898781"
C_GRID = "#e1e0d9"
C_FEASIBLE = "#2a78d6"   # slot 1 blue
C_PARETO = "#008300"     # slot 2 green


# ---------------------------------------------------------------------------
# SysML v2 model parsing
# ---------------------------------------------------------------------------

def _blocks(text, header_pattern):
    """Yield (regex match, body) for each definition whose header matches.

    The body is extracted by brace counting so nested blocks (a joint's
    inline mechanics configuration) stay inside their owner.
    """
    for m in re.finditer(header_pattern, text):
        depth, start = 0, text.index("{", m.end() - 1)
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    yield m, text[start + 1:i]
                    break


def _value(token):
    return token.strip('"') if token.startswith('"') else float(token)


def parse_model(path):
    text = path.read_text(encoding="utf-8")

    servo_variants = {}
    for m, body in _blocks(text, r"part def (\w+) :> ServoDrive\s*\{"):
        attrs = re.findall(r"attribute\s+:>>\s+(\w+)\s*=\s*(\"[^\"]*\"|[-\d.]+)", body)
        servo_variants[m.group(1)] = {k: _value(v) for k, v in attrs}

    mech_defaults = {}
    for _, body in _blocks(text, r"part def MechanicalAssembly\s*\{"):
        attrs = re.findall(r"attribute\s+(\w+)\s*:\s*\w+\s+default\s+(\"[^\"]*\"|[-\d.]+)", body)
        mech_defaults = {k: _value(v) for k, v in attrs}

    joints = {}
    for m, body in _blocks(text, r"part def (\w+) :> Joint\s*\{"):
        servo_type = re.search(r"part\s+:>>\s+servo\s*:\s*(\w+)", body).group(1)
        attrs = re.findall(r"attribute\s+:>>\s+(\w+)\s*=\s*(\"[^\"]*\"|[-\d.]+)", body)
        mechanics = dict(mech_defaults)
        mechanics.update({k: _value(v) for k, v in attrs})
        joints[m.group(1)] = {"servo": servo_type, "mechanics": mechanics}

    missing = [j for j in JOINTS if j not in joints]
    if missing or not servo_variants:
        raise SystemExit(f"model parse failed: servos={list(servo_variants)}, missing joints={missing}")
    return servo_variants, joints


# ---------------------------------------------------------------------------
# Architecture evaluation
# ---------------------------------------------------------------------------

def link_mass_kg(mechanics, scale):
    """Thin-walled square tube: shell area ~ 4 * width * wall."""
    volume_mm3 = 4.0 * TUBE_WIDTH_MM * mechanics["wallThickness"] * mechanics["length"] * scale
    return volume_mm3 * DENSITY[mechanics["material"]]


def evaluate(servo_assignment, servo_variants, joints, scale):
    """Return (reach_mm, cost, feasible) for one candidate architecture."""
    lengths_m = [joints[j]["mechanics"]["length"] * scale / 1000.0 for j in CHAIN]
    link_m = [link_mass_kg(joints[j]["mechanics"], scale) for j in CHAIN]
    servo_m = [servo_variants[servo_assignment[j]]["weight"] for j in CHAIN]

    reach_mm = sum(lengths_m) * 1000.0

    cost = sum(servo_variants[servo_assignment[j]]["cost"] for j in JOINTS)
    for j in JOINTS:
        mech = joints[j]["mechanics"]
        cost += mech["cost"] * MATERIAL_COST_FACTOR[mech["material"]] * (mech["length"] * scale / 100.0)

    feasible = True

    # pitch joints (shoulder, elbow, wrist): hold the horizontal arm
    for k, joint in enumerate(CHAIN[:3]):
        tau = PAYLOAD_KG * sum(lengths_m[k:])
        for j in range(k, len(CHAIN)):
            d_pivot = sum(lengths_m[k:j])          # pivot k -> pivot j
            if j > k:
                tau += servo_m[j] * d_pivot        # downstream servo at its pivot
            tau += link_m[j] * (d_pivot + lengths_m[j] / 2.0)
        tau *= G
        if servo_variants[servo_assignment[joint]]["torque"] < SAFETY_FACTOR * tau:
            feasible = False

    # base yaw: accelerate the fully extended arm about the vertical axis
    inertia = PAYLOAD_KG * sum(lengths_m) ** 2
    for j in range(len(CHAIN)):
        d_pivot = sum(lengths_m[:j])
        inertia += servo_m[j] * d_pivot ** 2
        inertia += link_m[j] * (d_pivot + lengths_m[j] / 2.0) ** 2
    if servo_variants[servo_assignment["BaseJoint"]]["torque"] < SAFETY_FACTOR * inertia * YAW_ACCEL:
        feasible = False

    # gripper: friction grip on the payload
    tau_grip = (PAYLOAD_KG * G / (2.0 * FRICTION_MU)) * FINGER_LEN_M
    if servo_variants[servo_assignment["GripperJoint"]]["torque"] < SAFETY_FACTOR * tau_grip:
        feasible = False

    return reach_mm, cost, feasible


def pareto_front(points):
    """Non-dominated set for (min cost, max reach); points = list of dicts."""
    front, best_reach = [], -1.0
    for p in sorted(points, key=lambda p: (p["cost"], -p["reach_mm"])):
        if p["reach_mm"] > best_reach:
            front.append(p)
            best_reach = p["reach_mm"]
    return front


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    servo_variants, joints = parse_model(MODEL_FILE)
    variant_names = sorted(servo_variants, key=lambda v: servo_variants[v]["cost"])
    print(f"model: {MODEL_FILE.name}")
    print(f"servo variants: {', '.join(variant_names)}")
    print(f"exploring {len(variant_names) ** len(JOINTS)} servo assignments x {len(SCALES)} scales\n")

    points = []
    for scale in SCALES:
        for combo in itertools.product(variant_names, repeat=len(JOINTS)):
            assignment = dict(zip(JOINTS, combo))
            reach_mm, cost, feasible = evaluate(assignment, servo_variants, joints, scale)
            points.append({
                "scale": scale, "reach_mm": reach_mm, "cost": cost,
                "feasible": feasible, **{j: assignment[j] for j in JOINTS},
            })

    baseline = dict(zip(JOINTS, (joints[j]["servo"] for j in JOINTS)))
    base_reach, base_cost, base_ok = evaluate(baseline, servo_variants, joints, 1.0)

    feasible = [p for p in points if p["feasible"]]
    infeasible = [p for p in points if not p["feasible"]]
    front = pareto_front(feasible)

    OUTPUT_DIR.mkdir(exist_ok=True)
    csv_path = OUTPUT_DIR / "tradespace_points.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(points[0]))
        writer.writeheader()
        writer.writerows(points)

    # ---- plot: reach (y) vs cost (x) -------------------------------------
    fig, ax = plt.subplots(figsize=(9, 6), facecolor=C_SURFACE)
    ax.set_facecolor(C_SURFACE)

    ax.scatter([p["cost"] for p in infeasible], [p["reach_mm"] for p in infeasible],
               s=22, marker="x", color=C_MUTED, alpha=0.35, linewidths=1.0,
               label=f"infeasible ({len(infeasible)})")
    ax.scatter([p["cost"] for p in feasible], [p["reach_mm"] for p in feasible],
               s=26, color=C_FEASIBLE, alpha=0.55, edgecolors="none",
               label=f"feasible ({len(feasible)})")
    ax.plot([p["cost"] for p in front], [p["reach_mm"] for p in front],
            color=C_PARETO, linewidth=2.0, marker="o", markersize=6,
            markerfacecolor=C_PARETO, markeredgecolor=C_SURFACE, markeredgewidth=1.2,
            label=f"Pareto front ({len(front)})", zorder=4)
    ax.scatter([base_cost], [base_reach], s=170, marker="*",
               facecolor="#eda100", edgecolor=C_INK, linewidths=0.8, zorder=5,
               label="baseline (BDD as-modeled)")
    ax.annotate(f"baseline\n${base_cost:.0f}, {base_reach:.0f} mm",
                (base_cost, base_reach), textcoords="offset points", xytext=(12, 14),
                fontsize=9, color=C_INK_2ND)

    ax.set_xlabel("architecture cost [USD]", color=C_INK_2ND)
    ax.set_ylabel("horizontal reach [mm]", color=C_INK_2ND)
    ax.set_title("Robot arm tradespace: reach vs cost\n"
                 f"servo assignments x arm scale, {PAYLOAD_KG} kg payload, "
                 f"SF {SAFETY_FACTOR:g}", color=C_INK, fontsize=12)
    ax.grid(True, color=C_GRID, linewidth=0.7)
    ax.tick_params(colors=C_MUTED)
    for spine in ax.spines.values():
        spine.set_color(C_GRID)
    ax.legend(loc="lower right", framealpha=0.9, edgecolor=C_GRID,
              labelcolor=C_INK_2ND, fontsize=9)

    fig.tight_layout()
    png_path = OUTPUT_DIR / "tradespace_reach_cost.png"
    fig.savefig(png_path, dpi=150, facecolor=C_SURFACE)

    # ---- console summary --------------------------------------------------
    print(f"feasible: {len(feasible)} / {len(points)} candidates")
    print(f"baseline (as modeled, scale 1.0): reach {base_reach:.0f} mm, "
          f"cost ${base_cost:.0f}, {'feasible' if base_ok else 'INFEASIBLE'}\n")
    print("Pareto-optimal architectures (min cost, max reach):")
    header = f"{'cost $':>7}  {'reach mm':>8}  {'scale':>5}  " + "  ".join(f"{j:<13}" for j in JOINTS)
    print(header)
    print("-" * len(header))
    for p in front:
        servos = "  ".join(f"{p[j].replace('ServoDrive', ''):<13}" for j in JOINTS)
        print(f"{p['cost']:>7.0f}  {p['reach_mm']:>8.0f}  {p['scale']:>5.1f}  {servos}")
    print(f"\nwrote {png_path}")
    print(f"wrote {csv_path}")


if __name__ == "__main__":
    main()
