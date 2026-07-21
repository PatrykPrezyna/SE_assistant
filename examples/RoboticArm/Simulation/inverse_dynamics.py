"""Planar inverse dynamics for the robotic arm — the quasi-static model
from torque_analysis.py made realistic.

What this adds over the quasi-static analysis:
  - minimum-jerk (quintic) joint trajectories instead of linear
    interpolation, so velocity and acceleration are finite, smooth and
    zero at every waypoint — like a real servo motion profile
  - full rigid-body torque: inertial (I*alpha), centripetal (omega^2) and
    the shoulder<->elbow coupling terms, not just gravity moments
  - true link rotary inertia taken from the CAD solids via OCC mass
    properties (matrixOfInertia, scaled by material density); the gripper
    cluster's inertia comes from its per-part point masses

Model: 2-DOF planar chain in the vertical x-z plane (base yaw is treated
separately in torque_analysis; a yaw rate adds no gravity torque and its
inertial effect on shoulder/elbow is second order at these speeds).
Angles are absolute (measured from horizontal), CCW positive.

Validation built in: run with a very long segment time and the dynamic
torques converge to the quasi-static values — checked automatically.

Outputs
  - console: peak dynamic vs quasi-static torque, and the segment time
    below which the quasi-static assumption breaks (>10% error)
  - output/torque_dynamic_sequence.png : dynamic vs quasi-static profile
  - output/torque_vs_speed.png         : peak torque vs motion speed
"""

import math
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "2_CAD"))

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

import cadquery as cq
from robotic_arm import make_arm_link, params
from torque_analysis import (
    C_ELBOW,
    C_SHOULDER,
    DENSITY_ACRYLIC,
    WAYPOINTS,
    build_mass_model,
    joint_torques,
)

G_MM = 9810.0                 # gravity in mm/s^2 (model works in mm and kg)
NM = 1e-6                     # kg*mm^2/s^2 -> N*m
NOMINAL_SEGMENT_TIME_S = 2.5  # same pacing as torque_analysis / the video
STEPS_PER_SEGMENT = 200


def plate_inertia_kgmm2(p, length):
    """Rotary inertia of one arm-link plate about its CoM, spin axis =
    plate normal (the joint axis once posed). From the CAD solid."""
    solid = make_arm_link(p, length).val()
    i_vol = np.array(cq.Shape.matrixOfInertia(solid))  # mm^5, unit density
    return i_vol[2][2] * DENSITY_ACRYLIC               # local z = plate normal


def build_dynamic_model(p):
    """Bodies for the 2-DOF chain, all lengths in mm, masses in kg.

    Body A rotates with th1 about the shoulder: upper-arm plates
    (distributed) + elbow servo (point at the elbow).
    Body B rotates with th2 about the elbow: forearm plates (distributed)
    + gripper cluster per-part points + optional payload point.
    """
    mm = build_mass_model(p)
    l1, l2 = p["shoulder_length"], p["forearm_length"]

    points_a = [(mm["m_upper_arm"], (l1 / 2, 0.0)),
                (mm["m_elbow_servo"], (l1, 0.0))]
    points_b = [(mm["m_forearm"], (l2 / 2, 0.0))]
    points_b += [(m, (l2 + r[0], r[1])) for m, r in mm["gripper_points"]]

    return {
        "l1": l1,
        "l2": l2,
        "points_a": points_a,
        "points_b": points_b,
        "r_payload": (l2 + mm["r_payload"][0], mm["r_payload"][1]),
        "I_a": 2 * plate_inertia_kgmm2(p, l1),   # both plates, about CoM
        "I_b": 2 * plate_inertia_kgmm2(p, l2),
        "mass_model": mm,
    }


def dynamic_torques(dm, th1, om1, al1, th2, om2, al2, payload_kg):
    """Inverse dynamics: required torque (N*m) at shoulder and elbow.

    th in rad, om in rad/s, al in rad/s^2 (numpy arrays); payload_kg may
    be an array (0 where the claw is empty).

    Newton-Euler about each pivot: tau = sum I_com*al + m * r x (a - g),
    with 2D cross r x f = x*f_z - z*f_x (CCW positive). Setting om = al = 0
    recovers the quasi-static gravity moments exactly.
    """
    c1, s1 = np.cos(th1), np.sin(th1)
    c2, s2 = np.cos(th2), np.sin(th2)
    l1 = dm["l1"]

    tau1 = dm["I_a"] * al1 + (dm["I_b"] * al2)   # plate spin, both joints
    tau2 = dm["I_b"] * al2

    # body A: points on the upper-arm axis at radius d from the shoulder
    for m, (d, _) in dm["points_a"]:
        ax = -d * (al1 * s1 + om1**2 * c1)
        az = d * (al1 * c1 - om1**2 * s1)
        tau1 += m * (d * c1 * (az + G_MM) - d * s1 * ax)

    # elbow pivot position and acceleration
    p2x, p2z = l1 * c1, l1 * s1
    a2x = -l1 * (al1 * s1 + om1**2 * c1)
    a2z = l1 * (al1 * c1 - om1**2 * s1)

    # body B: forearm-frame points rotated to world by th2
    pts = list(dm["points_b"]) + [(payload_kg, dm["r_payload"])]
    for m, (rx, rz) in pts:
        rwx = rx * c2 - rz * s2
        rwz = rx * s2 + rz * c2
        ax = a2x - al2 * rwz - om2**2 * rwx
        az = a2z + al2 * rwx - om2**2 * rwz
        tau2 += m * (rwx * (az + G_MM) - rwz * ax)
        tau1 += m * ((p2x + rwx) * (az + G_MM) - (p2z + rwz) * ax)

    return tau1 * NM, tau2 * NM


# ---------------------------------------------------------------------------
# minimum-jerk trajectory through the WAYPOINTS
# ---------------------------------------------------------------------------

def quintic(u):
    """Minimum-jerk normalized profile s(u) with s', s'' (zero at ends)."""
    s = 10 * u**3 - 15 * u**4 + 6 * u**5
    ds = 30 * u**2 - 60 * u**3 + 30 * u**4
    dds = 60 * u - 180 * u**2 + 120 * u**3
    return s, ds, dds


def make_trajectory(segment_time_s, steps_per_segment=None):
    """Time, joint angles/rates/accelerations (rad) and payload arrays."""
    n = STEPS_PER_SEGMENT if steps_per_segment is None else steps_per_segment
    ts, th1, om1, al1, th2, om2, al2, pls = ([] for _ in range(8))
    t0 = 0.0
    for (_, a0, b0, pl0), (_, a1, b1, pl1) in zip(WAYPOINTS, WAYPOINTS[1:]):
        u = np.linspace(0, 1, n, endpoint=False)
        s, ds, dds = quintic(u)
        d1, d2 = math.radians(a1 - a0), math.radians(b1 - b0)
        th1.append(math.radians(a0) + d1 * s)
        om1.append(d1 * ds / segment_time_s)
        al1.append(d1 * dds / segment_time_s**2)
        th2.append(math.radians(b0) + d2 * s)
        om2.append(d2 * ds / segment_time_s)
        al2.append(d2 * dds / segment_time_s**2)
        pls.append(np.full_like(u, min(pl0, pl1)))
        ts.append(t0 + u * segment_time_s)
        t0 += segment_time_s
    return [np.concatenate(x) for x in (ts, th1, om1, al1, th2, om2, al2, pls)]


def sequence_torques(dm, segment_time_s):
    t, th1, om1, al1, th2, om2, al2, pl = make_trajectory(segment_time_s)
    tau1, tau2 = dynamic_torques(dm, th1, om1, al1, th2, om2, al2, pl)
    # quasi-static reference on the identical path
    ts1, ts2 = joint_torques(dm["mass_model"], params,
                             np.degrees(th1), np.degrees(th2), pl)
    return t, tau1, tau2, ts1, ts2


# ---------------------------------------------------------------------------
# plots
# ---------------------------------------------------------------------------

def plot_sequence(dm, out_dir):
    t, tau1, tau2, ts1, ts2 = sequence_torques(dm, NOMINAL_SEGMENT_TIME_S)

    fig, ax = plt.subplots(figsize=(10, 4.4), constrained_layout=True)
    ax.plot(t, ts1, color=C_SHOULDER, lw=1.2, ls="--", label="shoulder quasi-static")
    ax.plot(t, tau1, color=C_SHOULDER, lw=2, label="shoulder dynamic")
    ax.plot(t, ts2, color=C_ELBOW, lw=1.2, ls="--", label="elbow quasi-static")
    ax.plot(t, tau2, color=C_ELBOW, lw=2, label="elbow dynamic")
    for tau, color in ((tau1, C_SHOULDER), (tau2, C_ELBOW)):
        i = np.abs(tau).argmax()
        ax.plot(t[i], tau[i], "o", ms=7, color=color)
        ax.annotate(f"{tau[i]:.2f} N·m", (t[i], tau[i]),
                    textcoords="offset points", xytext=(8, 6), fontsize=9,
                    color="#1a1a19")
    ax.set_xlabel("time (s)")
    ax.set_ylabel("torque (N·m)")
    ax.set_title("Inverse dynamics vs quasi-static, minimum-jerk profile "
                 f"({NOMINAL_SEGMENT_TIME_S:.1f} s per segment)", fontsize=11)
    ax.legend(frameon=False, ncols=2, fontsize=9)
    ax.grid(axis="y", color="#eceae2", lw=0.8)
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    path = out_dir / "torque_dynamic_sequence.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def plot_speed_sweep(dm, out_dir):
    times = np.geomspace(0.2, 3.0, 30)
    peaks1, peaks2 = [], []
    for st in times:
        _, tau1, tau2, _, _ = sequence_torques(dm, st)
        peaks1.append(np.abs(tau1).max())
        peaks2.append(np.abs(tau2).max())
    _, _, _, ts1, ts2 = sequence_torques(dm, NOMINAL_SEGMENT_TIME_S)
    static1, static2 = np.abs(ts1).max(), np.abs(ts2).max()

    fig, ax = plt.subplots(figsize=(8, 4.4), constrained_layout=True)
    ax.plot(times, peaks1, color=C_SHOULDER, lw=2, label="shoulder dynamic peak")
    ax.plot(times, peaks2, color=C_ELBOW, lw=2, label="elbow dynamic peak")
    ax.axhline(static1, color=C_SHOULDER, lw=1.2, ls="--",
               label="shoulder quasi-static peak")
    ax.axhline(static2, color=C_ELBOW, lw=1.2, ls="--",
               label="elbow quasi-static peak")
    ax.axvline(NOMINAL_SEGMENT_TIME_S, color="#c3c2b7", lw=0.8)
    ax.text(NOMINAL_SEGMENT_TIME_S, ax.get_ylim()[1] * 0.97, " nominal",
            fontsize=8, color="#6b6a60", va="top")
    ax.set_xscale("log")
    ax.set_xticks([0.2, 0.5, 1, 2, 3], ["0.2", "0.5", "1", "2", "3"])
    ax.xaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
    ax.set_xlabel("segment duration (s) — shorter = faster motion")
    ax.set_ylabel("peak torque over sequence (N·m)")
    ax.set_title("When does acceleration matter? Peak torque vs motion speed",
                 fontsize=11)
    ax.legend(frameon=False, fontsize=9)
    ax.grid(axis="y", color="#eceae2", lw=0.8)
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    path = out_dir / "torque_vs_speed.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path, times, np.array(peaks1), static1


# ---------------------------------------------------------------------------

def main():
    dm = build_dynamic_model(params)
    out_dir = ROOT / "output"
    out_dir.mkdir(exist_ok=True)

    print("Rotary inertia from CAD (about link CoM, both plates):")
    print(f"  upper arm: {dm['I_a'] * 1e-6:.2e} kg·m²   "
          f"forearm: {dm['I_b'] * 1e-6:.2e} kg·m²\n")

    # validation: slow-motion limit must reproduce the quasi-static model
    _, tau1, tau2, ts1, ts2 = sequence_torques(dm, 100.0)
    err = max(np.abs(tau1 - ts1).max(), np.abs(tau2 - ts2).max())
    status = "PASS" if err < 1e-3 else "FAIL"
    print(f"Validation vs quasi-static (100 s segments): "
          f"max deviation {err:.2e} N·m  [{status}]\n")

    t, tau1, tau2, ts1, ts2 = sequence_torques(dm, NOMINAL_SEGMENT_TIME_S)
    print(f"Sequence peaks at nominal pace ({NOMINAL_SEGMENT_TIME_S} s/segment):")
    for name, dyn, sta in (("shoulder", tau1, ts1), ("elbow", tau2, ts2)):
        pk_d, pk_s = np.abs(dyn).max(), np.abs(sta).max()
        print(f"  {name:9s}: dynamic {pk_d:5.2f} N·m   quasi-static {pk_s:5.2f} "
              f"N·m   acceleration adds {100 * (pk_d - pk_s) / pk_s:+5.1f}%")

    p1 = plot_sequence(dm, out_dir)
    p2, times, peaks1, static1 = plot_speed_sweep(dm, out_dir)

    # segment time below which quasi-static under-predicts by >10%
    over = times[peaks1 > 1.1 * static1]
    if over.size:
        print(f"\nQuasi-static becomes >10% unconservative below "
              f"~{over.max():.2f} s per segment "
              f"(nominal is {NOMINAL_SEGMENT_TIME_S} s — "
              f"{'inside' if over.max() > NOMINAL_SEGMENT_TIME_S else 'outside'}"
              " the risky range)")
    else:
        print("\nQuasi-static stays within 10% over the whole swept speed range")

    print(f"\nPlots written to:\n  {p1}\n  {p2}")


if __name__ == "__main__":
    main()
