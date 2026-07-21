"""Quasi-static servo torque analysis for the desktop robotic arm.

Computes the gravity-dominated holding torque at each servo drive, using
mass properties taken directly from the CadQuery solids in robotic_arm.py
(volume x material density) plus datasheet servo masses and the payload.

Justification for quasi-static: REQ-203 allows a 10-30 s pick-and-place
cycle, so joint accelerations are tiny and gravity torque dominates;
inertial/Coriolis terms are neglected (base-yaw acceleration torque is
estimated separately since gravity produces none about a vertical axis).

Outputs
  - console summary: worst-case torque per joint, servo candidate check
    (REQ-200: 500 g payload) with a 2x safety factor
  - output/torque_workspace.png : |torque| heatmaps over all shoulder /
    elbow angle combinations at full payload
  - output/torque_sequence.png  : torque profile over an example
    pick-and-place movement sequence

Assumptions
  - acrylic plates 1190 kg/m^3, nylon gears 1150 kg/m^3
  - every servo is a standard-size 55 g unit (MG996R class)
  - elbow servo mass acts at the elbow pivot; shoulder servo is on the
    fixed side of the joint and loads only the base bearing
  - the gripper is rigidly attached to the forearm (no wrist pitch DOF)
"""

import math
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# the CAD model lives in ../2_CAD (examples/RoboticArm/2_CAD)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "2_CAD"))

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from robotic_arm import (
    POSE,
    make_arm_link,
    make_claw_finger,
    make_gripper_housing,
    make_spur_gear,
    make_wrist_mount,
    params,
)

G = 9.81                      # m/s^2
DENSITY_ACRYLIC = 1.19e-6     # kg/mm^3
DENSITY_NYLON = 1.15e-6       # kg/mm^3
SERVO_MASS = 0.055            # kg, standard-size (MG996R class)
PAYLOAD_KG = 0.5              # REQ-200 upper bound
FRICTION_MU = 0.5             # rubber finger pads on dry object

# datasheet STALL torque, N*m at ~5-6 V; continuous holding capability is
# only ~25-30% of stall, which is part of what SAFETY_FACTOR covers
SERVO_CANDIDATES = {
    "SG90 (1.6 kg*cm)": 0.157,
    "MG90S (2.2 kg*cm)": 0.216,
    "MG996R (9.4 kg*cm)": 0.92,
    "DS3218 (19 kg*cm)": 1.86,
    "DS5160 (60 kg*cm)": 5.88,
}
SAFETY_FACTOR = 2.0

# chart colors: validated categorical palette slots 1-2 (dataviz skill)
C_SHOULDER = "#2a78d6"
C_ELBOW = "#008300"


def mass_and_com(workplane, density):
    """Mass (kg) and center of mass (mm, part-local) of a CadQuery solid."""
    shape = workplane.val()
    return shape.Volume() * density, np.array(shape.Center().toTuple())


def build_mass_model(p):
    """Collapse the arm into per-joint lumped masses.

    Returns a dict with:
      upper arm mass, forearm mass (each = 2 plates),
      elbow servo point mass,
      gripper cluster (mass, CoM offset from wrist pivot P3 in the
      forearm-fixed frame) and the payload attachment offset.
    """
    m_ua_plate, _ = mass_and_com(make_arm_link(p, p["shoulder_length"]), DENSITY_ACRYLIC)
    m_fa_plate, _ = mass_and_com(make_arm_link(p, p["forearm_length"]), DENSITY_ACRYLIC)

    # --- gripper cluster: parts rigidly attached beyond the wrist pivot ---
    # placement offsets from P3, gripper-local frame (same math as assembly)
    hx = 16 + p["gripper_length"] / 2          # housing center x
    gear_x = hx + 25                            # finger gear axes x

    cluster = []  # (mass_kg, offset_from_P3_mm)

    m, c = mass_and_com(make_wrist_mount(p), DENSITY_ACRYLIC)
    cluster.append((m, c + np.array([3, 0, -5])))

    m, c = mass_and_com(make_gripper_housing(p), DENSITY_ACRYLIC)
    cluster.append((m, c + np.array([hx, 0, -5])))

    cluster.append((SERVO_MASS, np.array([hx - 10, 16, -10])))  # wrist servo body

    m, c = mass_and_com(make_spur_gear(p, 16, 24), DENSITY_NYLON)
    cluster.append((m, c + np.array([gear_x, 16, 15])))
    cluster.append((m, c + np.array([gear_x, -16, 15])))
    m, c = mass_and_com(make_spur_gear(p, 8, 12), DENSITY_NYLON)
    cluster.append((m, c + np.array([hx, 16, 15])))

    m, c = mass_and_com(make_claw_finger(p), DENSITY_ACRYLIC)
    cluster.append((m, c + np.array([gear_x, 16, 20])))
    cluster.append((m, c + np.array([gear_x, -16, 20])))

    m_cluster = sum(m for m, _ in cluster)
    com_cluster = sum(m * c for m, c in cluster) / m_cluster

    # the CAD pose has the gripper horizontal at forearm angle POSE["forearm_deg"];
    # rotate offsets back into the forearm-fixed frame so they can be re-posed
    def to_forearm_frame(v):
        a = -math.radians(POSE["forearm_deg"])
        x, z = v[0], v[2]
        return np.array([x * math.cos(a) - z * math.sin(a),
                         x * math.sin(a) + z * math.cos(a)])

    r_payload = np.array([gear_x + p["claw_length"], 0, 22.5])  # fingertip

    return {
        "m_upper_arm": 2 * m_ua_plate,
        "m_forearm": 2 * m_fa_plate,
        "m_elbow_servo": SERVO_MASS,
        "m_gripper": m_cluster,
        "r_gripper": to_forearm_frame(com_cluster),   # (x, z) mm from P3
        "r_payload": to_forearm_frame(r_payload),
        # per-part point masses (kg, (x, z) mm from P3, forearm frame) so a
        # dynamic model can compute the cluster's rotary inertia exactly
        "gripper_points": [(m, to_forearm_frame(c)) for m, c in cluster],
    }


def joint_torques(mm, p, th1_deg, th2_deg, payload_kg):
    """Signed quasi-static gravity torque (N*m) at shoulder and elbow.

    th1: upper arm angle above horizontal; th2: forearm angle above
    horizontal (both accept numpy arrays for vectorized sweeps).
    """
    l1, l2 = p["shoulder_length"], p["forearm_length"]
    th1, th2 = np.radians(th1_deg), np.radians(th2_deg)
    c1, c2, s2 = np.cos(th1), np.cos(th2), np.sin(th2)

    def rot_x(r, c, s):
        """Horizontal component of forearm-frame vector r posed at th2."""
        return r[0] * c - r[1] * s

    x_p2 = l1 * c1                                   # elbow pivot
    x_fa = x_p2 + (l2 / 2) * c2                      # forearm CoM
    x_p3 = x_p2 + l2 * c2                            # wrist pivot
    x_grip = x_p3 + rot_x(mm["r_gripper"], c2, s2)   # gripper cluster CoM
    x_pay = x_p3 + rot_x(mm["r_payload"], c2, s2)    # payload at fingertip

    mm_to_m = 1e-3
    tau_shoulder = G * mm_to_m * (
        mm["m_upper_arm"] * (l1 / 2) * c1
        + mm["m_elbow_servo"] * x_p2
        + mm["m_forearm"] * x_fa
        + mm["m_gripper"] * x_grip
        + payload_kg * x_pay
    )
    tau_elbow = G * mm_to_m * (
        mm["m_forearm"] * (x_fa - x_p2)
        + mm["m_gripper"] * (x_grip - x_p2)
        + payload_kg * (x_pay - x_p2)
    )
    return tau_shoulder, tau_elbow


def base_yaw_torque(mm, p):
    """Acceleration torque about the vertical base axis, worst extension.

    Gravity produces no torque about a vertical axis, so the base servo is
    sized by inertia: 90 deg slew in 1.5 s, bang-bang profile (alpha = 4*theta/t^2).
    """
    l1, l2 = p["shoulder_length"], p["forearm_length"]
    radii_mm = {
        "upper arm": l1 / 2,
        "elbow servo": l1,
        "forearm": l1 + l2 / 2,
        "gripper": l1 + l2 + mm["r_gripper"][0],
        "payload": l1 + l2 + mm["r_payload"][0],
    }
    masses = {
        "upper arm": mm["m_upper_arm"],
        "elbow servo": mm["m_elbow_servo"],
        "forearm": mm["m_forearm"],
        "gripper": mm["m_gripper"],
        "payload": PAYLOAD_KG,
    }
    inertia = sum(masses[k] * (radii_mm[k] * 1e-3) ** 2 for k in masses)  # kg*m^2
    alpha = 4 * math.radians(90) / 1.5**2
    return inertia * alpha


def gripper_servo_torque(p):
    """Wrist servo torque needed to hold the REQ-200 payload in the claw.

    Grip: F_n per finger >= m*g/(2*mu). Torque path: servo pinion (r=8) ->
    finger gear (r=16) doubles torque, split across the two meshed finger
    gears -> per-finger torque equals servo torque. Contact assumed near
    the fingertip (0.8 x claw length), the worst case.
    """
    f_n = PAYLOAD_KG * G / (2 * FRICTION_MU)
    contact_arm_m = (p["claw_length"] * 0.8) * 1e-3
    return f_n * contact_arm_m


# ---------------------------------------------------------------------------
# Example pick-and-place movement sequence (REQ-203: cycle within 10-30 s)
# ---------------------------------------------------------------------------

WAYPOINTS = [
    # (name, shoulder deg, forearm deg, payload kg after reaching it)
    ("home", 80, -60, 0.0),
    ("approach", 25, -35, 0.0),
    ("grip", 25, -35, PAYLOAD_KG),
    ("lift", 65, 10, PAYLOAD_KG),
    ("place", 30, -30, PAYLOAD_KG),
    ("release", 30, -30, 0.0),
    ("home", 80, -60, 0.0),
]
SEGMENT_TIME_S = 2.5
STEPS_PER_SEGMENT = 40


def sequence_profile(mm, p):
    """Interpolate the waypoint sequence and evaluate torques along it."""
    times, tau_sh, tau_el, names = [], [], [], []
    t0 = 0.0
    for (n0, a0, b0, pl0), (n1, a1, b1, pl1) in zip(WAYPOINTS, WAYPOINTS[1:]):
        s = np.linspace(0, 1, STEPS_PER_SEGMENT)
        th1 = a0 + (a1 - a0) * s
        th2 = b0 + (b1 - b0) * s
        payload = min(pl0, pl1)  # payload is carried only between grip and release
        ts, te = joint_torques(mm, p, th1, th2, payload)
        times.append(t0 + s * SEGMENT_TIME_S)
        tau_sh.append(ts)
        tau_el.append(te)
        names.append((t0, n0))
        t0 += SEGMENT_TIME_S
    names.append((t0, WAYPOINTS[-1][0]))
    return np.concatenate(times), np.concatenate(tau_sh), np.concatenate(tau_el), names


# ---------------------------------------------------------------------------
# Plots
# ---------------------------------------------------------------------------

def plot_workspace(mm, p, out_dir):
    th1 = np.linspace(0, 90, 91)
    th2 = np.linspace(-90, 90, 181)
    t1, t2 = np.meshgrid(th1, th2)
    tau_sh, tau_el = joint_torques(mm, p, t1, t2, PAYLOAD_KG)

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4), constrained_layout=True)
    vmax = max(np.abs(tau_sh).max(), np.abs(tau_el).max())
    for ax, tau, title in ((axes[0], tau_sh, "Shoulder servo"),
                           (axes[1], tau_el, "Elbow servo")):
        im = ax.pcolormesh(t1, t2, np.abs(tau), cmap="Blues", vmin=0, vmax=vmax)
        j = np.unravel_index(np.abs(tau).argmax(), tau.shape)
        ax.plot(t1[j], t2[j], "o", ms=8, mfc="none", mec="#1a1a19", mew=1.5)
        ax.annotate(f"peak {np.abs(tau).max():.2f} N·m",
                    (t1[j], t2[j]), textcoords="offset points", xytext=(8, 8),
                    fontsize=9, color="#1a1a19")
        ax.set_title(title, fontsize=11)
        ax.set_xlabel("shoulder angle θ₁ (deg above horizontal)")
        ax.tick_params(length=0)
        for s in ax.spines.values():
            s.set_visible(False)
    axes[0].set_ylabel("forearm angle θ₂ (deg above horizontal)")
    cbar = fig.colorbar(im, ax=axes, shrink=0.85)
    cbar.set_label("|holding torque| (N·m), payload 500 g")
    fig.suptitle("Quasi-static holding torque over the joint workspace", fontsize=12)
    path = out_dir / "torque_workspace.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def plot_sequence(mm, p, out_dir):
    t, tau_sh, tau_el, marks = sequence_profile(mm, p)

    fig, ax = plt.subplots(figsize=(10, 4.2), constrained_layout=True)
    # shade the payload-carrying interval (grip -> release)
    t_grip = next(tm for tm, n in marks if n == "grip")
    t_rel = next(tm for tm, n in marks if n == "release")
    ax.axvspan(t_grip, t_rel, color="#f2f0e9", zorder=0)
    ax.text((t_grip + t_rel) / 2, ax.get_ylim()[1], "", fontsize=9)

    ax.plot(t, tau_sh, color=C_SHOULDER, lw=2, label="shoulder")
    ax.plot(t, tau_el, color=C_ELBOW, lw=2, label="elbow")

    for tau, color in ((tau_sh, C_SHOULDER), (tau_el, C_ELBOW)):
        i = np.abs(tau).argmax()
        ax.plot(t[i], tau[i], "o", ms=8, color=color)
        ax.annotate(f"{tau[i]:.2f} N·m", (t[i], tau[i]),
                    textcoords="offset points", xytext=(8, 6),
                    fontsize=9, color="#1a1a19")

    for tm, name in marks:
        ax.axvline(tm, color="#c3c2b7", lw=0.8, zorder=0)
        ax.text(tm, ax.get_ylim()[0], f" {name}", fontsize=8, color="#6b6a60",
                rotation=90, va="bottom")

    ax.set_xlabel("time (s)")
    ax.set_ylabel("holding torque (N·m)")
    ax.set_title("Servo torque over the pick-and-place sequence "
                 "(shaded: carrying 500 g payload)", fontsize=11)
    ax.legend(frameon=False, loc="upper right")
    ax.grid(axis="y", color="#eceae2", lw=0.8)
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    path = out_dir / "torque_sequence.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def main():
    p = params
    mm = build_mass_model(p)
    out_dir = ROOT / "output"
    out_dir.mkdir(exist_ok=True)

    print("Lumped masses from CAD geometry:")
    print(f"  upper arm (2 plates) : {mm['m_upper_arm'] * 1000:7.1f} g")
    print(f"  forearm  (2 plates)  : {mm['m_forearm'] * 1000:7.1f} g")
    print(f"  elbow servo          : {mm['m_elbow_servo'] * 1000:7.1f} g")
    print(f"  gripper cluster      : {mm['m_gripper'] * 1000:7.1f} g "
          f"(CoM {mm['r_gripper'][0]:.0f} mm past wrist pivot)")
    print(f"  payload (REQ-200)    : {PAYLOAD_KG * 1000:7.1f} g "
          f"at {mm['r_payload'][0]:.0f} mm past wrist pivot\n")

    # worst case over the full workspace, with and without payload
    th1 = np.linspace(0, 90, 181)
    th2 = np.linspace(-90, 90, 361)
    t1, t2 = np.meshgrid(th1, th2)
    results = {}
    for label, payload in (("500 g payload", PAYLOAD_KG), ("no payload", 0.0)):
        tau_sh, tau_el = joint_torques(mm, p, t1, t2, payload)
        results[label] = (np.abs(tau_sh).max(), np.abs(tau_el).max())
        print(f"Worst-case holding torque ({label}):")
        for joint, tau in (("shoulder", tau_sh), ("elbow", tau_el)):
            i = np.unravel_index(np.abs(tau).argmax(), tau.shape)
            print(f"  {joint:9s}: {np.abs(tau).max():6.2f} N·m  "
                  f"at θ₁={t1[i]:.0f}°, θ₂={t2[i]:.0f}°")
        print()

    tau_base = base_yaw_torque(mm, p)
    tau_grip = gripper_servo_torque(p)
    print(f"Base yaw servo (inertia only, 90° in 1.5 s): {tau_base:.2f} N·m")
    print(f"Wrist/gripper servo (hold 500 g, mu={FRICTION_MU}): {tau_grip:.2f} N·m\n")

    print(f"Servo selection check (stall torque vs required x SF {SAFETY_FACTOR}):")
    required = {
        "shoulder": results["500 g payload"][0],
        "elbow": results["500 g payload"][1],
        "base yaw": tau_base,
        "gripper": tau_grip,
    }
    header = f"  {'joint':10s} {'required':>9s} {'w/ SF':>7s}  " + "  ".join(
        f"{name.split(' ')[0]:>7s}" for name in SERVO_CANDIDATES)
    print(header)
    for joint, req in required.items():
        row = f"  {joint:10s} {req:6.2f} N·m {req * SAFETY_FACTOR:5.2f}  "
        row += "  ".join(
            f"{'ok' if rating >= req * SAFETY_FACTOR else '--':>7s}"
            for rating in SERVO_CANDIDATES.values())
        print(row)
    print("  candidates: " + ", ".join(SERVO_CANDIDATES))

    p1 = plot_workspace(mm, p, out_dir)
    p2 = plot_sequence(mm, p, out_dir)
    print(f"\nPlots written to:\n  {p1}\n  {p2}")


if __name__ == "__main__":
    main()
