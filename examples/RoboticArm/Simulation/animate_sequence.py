"""Render the pick-and-place movement sequence as a video.

Side-by-side animation: 3D shaded view of the arm (PyVista, offscreen VTK
rendering of the CadQuery geometry) on the left, the inverse-dynamics servo
torque profile from inverse_dynamics.py with a moving time cursor on the
right. Both panels share the same minimum-jerk WAYPOINTS trajectory, so
video time equals plot time.

Kinematics: the shoulder and elbow joints are re-posed per frame with the
same joint math as robotic_arm.build_arm_assembly. Parts rigidly attached
to a link (elbow servo -> upper arm, gripper cluster -> forearm) are carried
along by rotating their modeled placement about the joint pivot. The payload
(REQ-200, 500 g) appears in the claw between the grip and release waypoints.

Output: examples/RoboticArm/output/sequence_animation.mp4 (GIF fallback
if no ffmpeg backend is available).
"""

import math
import sys
from pathlib import Path

import imageio.v2 as imageio
import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pyvista as pv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "2_CAD"))

import cadquery as cq  # noqa: E402
from robotic_arm import (  # noqa: E402
    POSE,
    make_arm_link,
    make_base_plate,
    make_claw_finger,
    make_gripper_housing,
    make_rotating_platform,
    make_servo,
    make_shoulder_plate,
    make_spur_gear,
    make_standoff,
    make_suction_foot,
    make_wrist_mount,
    params,
)
from inverse_dynamics import (  # noqa: E402
    NOMINAL_SEGMENT_TIME_S,
    build_dynamic_model,
    dynamic_torques,
    make_trajectory,
)
from torque_analysis import (  # noqa: E402
    C_ELBOW,
    C_SHOULDER,
    WAYPOINTS,
    joint_torques,
)

FPS = 16
FRAMES_PER_SEGMENT = 40          # 2.5 s per segment at 16 fps = real time
SEGMENT_TIME_S = NOMINAL_SEGMENT_TIME_S
ROBOT_WINDOW = (900, 720)

RGB = {
    "orange": (1.00, 0.55, 0.10),
    "black": (0.13, 0.13, 0.13),
    "servo": (0.15, 0.20, 0.55),
    "gear": (0.90, 0.90, 0.85),
    "payload": (0.75, 0.15, 0.15),
}


# ---------------------------------------------------------------------------
# transforms (same convention as robotic_arm._loc: T @ Rz @ Ry @ Rx)
# ---------------------------------------------------------------------------

def _rot(axis, deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    m = np.eye(4)
    i, j = {"x": (1, 2), "y": (2, 0), "z": (0, 1)}[axis]
    m[i, i] = m[j, j] = c
    m[i, j], m[j, i] = -s, s
    return m


def _trans(x, y, z):
    m = np.eye(4)
    m[:3, 3] = (x, y, z)
    return m


def loc(x=0.0, y=0.0, z=0.0, rx=0.0, ry=0.0, rz=0.0):
    return _trans(x, y, z) @ _rot("z", rz) @ _rot("y", ry) @ _rot("x", rx)


# ---------------------------------------------------------------------------
# meshes: tessellate the CadQuery parts fresh each run (params may change)
# ---------------------------------------------------------------------------

def load_meshes(p):
    mesh_dir = ROOT / "output" / "meshes"
    mesh_dir.mkdir(parents=True, exist_ok=True)
    solids = {
        "base_plate": make_base_plate(p),
        "suction_foot": make_suction_foot(p),
        "standoff": make_standoff(p),
        "rotating_platform": make_rotating_platform(p),
        "servo": make_servo(p),
        "shoulder_plate": make_shoulder_plate(p),
        "upper_arm_link": make_arm_link(p, p["shoulder_length"]),
        "forearm_link": make_arm_link(p, p["forearm_length"]),
        "wrist_mount": make_wrist_mount(p),
        "gripper_housing": make_gripper_housing(p),
        "finger_gear": make_spur_gear(p, 16, 24),
        "pinion_gear": make_spur_gear(p, 8, 12),
        "claw_finger": make_claw_finger(p),
    }
    meshes = {}
    for name, solid in solids.items():
        path = mesh_dir / f"{name}.stl"
        cq.exporters.export(solid, str(path))
        meshes[name] = pv.read(path)
    meshes["claw_finger_l"] = meshes["claw_finger"].reflect((0, 1, 0), point=(0, 0, 0))
    return meshes


# ---------------------------------------------------------------------------
# scene: static actors once, moving actors re-posed per frame via user_matrix
# ---------------------------------------------------------------------------

class ArmScene:
    def __init__(self, p):
        self.p = p
        t = p["plate_thickness"]
        self.l1, self.l2 = p["shoulder_length"], p["forearm_length"]
        self.p1 = np.array([0.0, 0.0, 2 * t + p["standoff_height"] + 60])
        self.th1_m = POSE["shoulder_deg"]     # angles the CAD placements assume
        self.th2_m = POSE["forearm_deg"]
        p2_m = self.p1 + self.l1 * np.array(
            [math.cos(math.radians(self.th1_m)), 0, math.sin(math.radians(self.th1_m))])
        self.p3_m = p2_m + self.l2 * np.array(
            [math.cos(math.radians(self.th2_m)), 0, math.sin(math.radians(self.th2_m))])

        meshes = load_meshes(p)
        self.plotter = pv.Plotter(off_screen=True, window_size=ROBOT_WINDOW)
        self.plotter.set_background("white")

        def add(mesh_name, color, matrix):
            actor = self.plotter.add_mesh(
                meshes[mesh_name], color=RGB[color], smooth_shading=False)
            actor.user_matrix = matrix
            return actor

        # ---- static structure (base yaw is not part of the sequence) ----
        add("base_plate", "orange", loc(z=t / 2))
        for sx, sy in [(-1, -1), (-1, 1), (1, -1), (1, 1)]:
            add("suction_foot", "black", loc(sx * 95, sy * 75, -6))
            add("standoff", "black", loc(sx * 45, sy * 45, t))
        add("rotating_platform", "orange", loc(z=t + p["standoff_height"] + t / 2))
        add("servo", "servo", loc(-10, 0, t))
        for sy in (1, -1):
            add("shoulder_plate", "orange", loc(0, sy * 18.5, self.p1[2], rx=90))
        y_servo_sh = 18.5 + 2.5 + p["servo_height"]
        add("servo", "servo", loc(-10, y_servo_sh, self.p1[2], rx=90))

        # ---- moving parts: (actor, joint, local placement) ----
        # joint "ua": pose = T(p1) @ Ry(-th1) @ local          (upper arm frame)
        # joint "fa": pose = T(p2) @ Ry(-th2) @ local          (forearm frame)
        # joint "wr": pose = T(p3) @ Ry(-(th2-th2_m)) @ local  (gripper, rigid
        #             with the forearm; local = modeled placement about p3_m)
        self.moving = []
        for sy in (1, -1):
            self.moving.append((add("upper_arm_link", "orange", np.eye(4)),
                                "ua", loc(self.l1 / 2, sy * 13, 0, rx=90)))
            self.moving.append((add("forearm_link", "orange", np.eye(4)),
                                "fa", loc(self.l2 / 2, sy * 7, 0, rx=90)))
        # elbow servo rides on the upper arm at the elbow pivot
        y_servo_el = 13 + 2.5 + p["servo_height"]
        self.moving.append((add("servo", "servo", np.eye(4)),
                            "ua_el", loc(-10, y_servo_el, 0, rx=90)))

        # gripper cluster: modeled placements relative to the wrist pivot p3_m
        hx = 16 + p["gripper_length"] / 2
        gx = hx + 25
        grip_parts = [
            ("wrist_mount", "black", loc(3, 0, -5)),
            ("gripper_housing", "orange", loc(hx, 0, -5)),
            ("servo", "servo", loc(hx - 10, 16, -30)),
            ("finger_gear", "gear", loc(gx, 16, 15)),
            ("finger_gear", "gear", loc(gx, -16, 15, rz=360 / 24 / 2)),
            ("pinion_gear", "gear", loc(hx, 16, 15, rz=360 / 12 / 2)),
            ("claw_finger", "orange", loc(gx, 16, 20, rz=POSE["claw_open_deg"])),
            ("claw_finger_l", "orange", loc(gx, -16, 20, rz=-POSE["claw_open_deg"])),
        ]
        for name, color, local in grip_parts:
            self.moving.append((add(name, color, np.eye(4)), "wr", local))

        # payload cube shown while carried (REQ-200)
        payload = pv.Cube(x_length=32, y_length=32, z_length=32)
        self.payload_actor = self.plotter.add_mesh(payload, color=RGB["payload"])
        self.moving.append((self.payload_actor, "wr",
                            loc(gx + p["claw_length"] * 0.8, 0, 27)))

        reach = self.l1 + self.l2 + 150
        self.plotter.camera_position = [
            (reach * 1.5, -reach * 1.6, reach * 1.1),
            (reach * 0.35, 0, 160),
            (0, 0, 1),
        ]

    def pose(self, th1, th2, payload_carried):
        c1, s1 = math.cos(math.radians(th1)), math.sin(math.radians(th1))
        p2 = self.p1 + self.l1 * np.array([c1, 0, s1])
        c2, s2 = math.cos(math.radians(th2)), math.sin(math.radians(th2))
        p3 = p2 + self.l2 * np.array([c2, 0, s2])

        frames = {
            "ua": _trans(*self.p1) @ _rot("y", -th1),
            "ua_el": _trans(*p2) @ _rot("y", -(th1 - self.th1_m)),
            "fa": _trans(*p2) @ _rot("y", -th2),
            "wr": _trans(*p3) @ _rot("y", -(th2 - self.th2_m)),
        }
        for actor, joint, local in self.moving:
            actor.user_matrix = frames[joint] @ local
        self.payload_actor.visibility = bool(payload_carried)

    def render(self):
        self.plotter.render()
        return self.plotter.screenshot(return_img=True)


# ---------------------------------------------------------------------------
# trajectory shared by both panels (minimum-jerk + inverse dynamics)
# ---------------------------------------------------------------------------

def waypoint_marks(segment_time_s):
    """(time, name) labels at each WAYPOINT for the torque chart."""
    marks = [(i * segment_time_s, name)
             for i, (name, *_) in enumerate(WAYPOINTS[:-1])]
    marks.append((len(WAYPOINTS[:-1]) * segment_time_s, WAYPOINTS[-1][0]))
    return marks


def build_trajectory():
    """Frame-wise min-jerk path, dynamic torques, and waypoint marks."""
    dm = build_dynamic_model(params)
    t, th1, om1, al1, th2, om2, al2, payload = make_trajectory(
        SEGMENT_TIME_S, steps_per_segment=FRAMES_PER_SEGMENT)
    tau_sh, tau_el = dynamic_torques(dm, th1, om1, al1, th2, om2, al2, payload)
    tau_sh_s, tau_el_s = joint_torques(
        dm["mass_model"], params, np.degrees(th1), np.degrees(th2), payload)
    return (t, np.degrees(th1), np.degrees(th2), payload,
            tau_sh, tau_el, tau_sh_s, tau_el_s, waypoint_marks(SEGMENT_TIME_S))


# ---------------------------------------------------------------------------
# composite video
# ---------------------------------------------------------------------------

def main():
    p = params
    (t, th1, th2, payload, tau_sh, tau_el,
     tau_sh_s, tau_el_s, marks) = build_trajectory()

    scene = ArmScene(p)

    # chart panel built once; only cursor and markers move per frame
    fig, (ax_img, ax) = plt.subplots(
        1, 2, figsize=(12.8, 4.8), dpi=100, width_ratios=[1.05, 1],
        constrained_layout=True)
    ax_img.axis("off")
    im = ax_img.imshow(np.zeros((ROBOT_WINDOW[1], ROBOT_WINDOW[0], 3), dtype=np.uint8))

    t_grip = next(tm for tm, n in marks if n == "grip")
    t_rel = next(tm for tm, n in marks if n == "release")
    ax.axvspan(t_grip, t_rel, color="#f2f0e9", zorder=0)
    ax.plot(t, tau_sh_s, color=C_SHOULDER, lw=1.2, ls="--",
            label="shoulder quasi-static")
    ax.plot(t, tau_el_s, color=C_ELBOW, lw=1.2, ls="--",
            label="elbow quasi-static")
    ax.plot(t, tau_sh, color=C_SHOULDER, lw=2, label="shoulder dynamic")
    ax.plot(t, tau_el, color=C_ELBOW, lw=2, label="elbow dynamic")
    for tm, name in marks:
        ax.axvline(tm, color="#c3c2b7", lw=0.8, zorder=0)
        ax.text(tm, ax.get_ylim()[0], f" {name}", fontsize=8, color="#6b6a60",
                rotation=90, va="bottom")
    cursor = ax.axvline(0, color="#1a1a19", lw=1.2)
    dot_sh, = ax.plot([], [], "o", ms=7, color=C_SHOULDER)
    dot_el, = ax.plot([], [], "o", ms=7, color=C_ELBOW)
    ax.set_xlabel("time (s)")
    ax.set_ylabel("torque (N·m)")
    ax.set_title("Inverse dynamics (shaded: carrying 500 g payload)", fontsize=11)
    ax.legend(frameon=False, loc="upper right", fontsize=8, ncols=2)
    ax.grid(axis="y", color="#eceae2", lw=0.8)
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)

    out_dir = ROOT / "output"
    out_dir.mkdir(exist_ok=True)
    try:
        out_path = out_dir / "sequence_animation.mp4"
        writer = imageio.get_writer(out_path, fps=FPS, quality=8)
    except Exception:
        out_path = out_dir / "sequence_animation.gif"
        writer = imageio.get_writer(out_path, fps=FPS)

    for i in range(len(t)):
        scene.pose(th1[i], th2[i], payload[i] > 0)
        im.set_data(scene.render())
        cursor.set_xdata([t[i], t[i]])
        dot_sh.set_data([t[i]], [tau_sh[i]])
        dot_el.set_data([t[i]], [tau_el[i]])
        fig.canvas.draw()
        frame = np.asarray(fig.canvas.buffer_rgba())[:, :, :3]
        writer.append_data(frame)
        if i % FRAMES_PER_SEGMENT == 0:
            print(f"  frame {i}/{len(t)}")

    writer.close()
    plt.close(fig)
    print(f"Wrote {out_path} ({len(t)} frames, {len(t) / FPS:.1f} s)")


if __name__ == "__main__":
    main()
