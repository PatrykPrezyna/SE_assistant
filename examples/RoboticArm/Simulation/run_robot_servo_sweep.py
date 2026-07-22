"""Sweep the two critical joints in RoboticArm.mo over shoulder×elbow servo pairs.

The current model focuses on the two highest-risk joints, shoulder and elbow,
but the structure is easy to extend later if more joints are added.

Builds once with OpenModelica, then runs each (servo_sh, servo_el) pair from
SERVO_CANDIDATES and writes movement time to CSV.

Output: examples/RoboticArm/output/robot_servo_sweep.csv

Usage:
  python examples/RoboticArm/Simulation/run_robot_servo_sweep.py
"""

from __future__ import annotations

import csv
import itertools
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODEL_FILE = HERE / "RoboticArm.mo"
MODEL_NAME = "RoboticArm.RoboticArmSimulation"
WORK = HERE.parent / "output" / "om_robot_sweep"
OUT_CSV = HERE.parent / "output" / "robot_servo_sweep.csv"

# Same stall table as torque_analysis / elbow sweep (N·m at ~5–6 V)
SERVO_CANDIDATES = {
    "SG90 (1.6 kg*cm)": 0.157,
    "MG90S (2.2 kg*cm)": 0.216,
    "AD002 (2.0 kg*cm)": 0.196,
    "MG996R (9.4 kg*cm)": 0.92,
    "DS3218 (19 kg*cm)": 1.86,
    "DS5160 (60 kg*cm)": 5.88,
}

MOVE_TIME_VAR = "move_time"
EXE_PREFIX = "RoboticArmSimulation"
STOP_TIME_S = 20


def find_omc() -> Path:
    home = os.environ.get("OPENMODELICAHOME")
    if home:
        bin_dir = Path(home) / "bin"
        os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
        candidate = bin_dir / ("omc.exe" if os.name == "nt" else "omc")
        if candidate.is_file():
            return candidate
    which = shutil.which("omc")
    if which:
        return Path(which)
    sys.exit(
        "OpenModelica 'omc' not found. Install OpenModelica and set "
        "OPENMODELICAHOME, or put omc on PATH."
    )


def run(cmd: list[str], cwd: Path, quiet: bool = False) -> None:
    if not quiet:
        print("+", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        sys.exit(f"Command failed ({proc.returncode}): {' '.join(cmd)}")
    if not quiet and proc.stdout.strip():
        print(proc.stdout.strip())


def build_model(omc: Path) -> Path:
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)
    shutil.copy2(MODEL_FILE, WORK / MODEL_FILE.name)

    mos = WORK / "build.mos"
    mos.write_text(
        "\n".join(
            [
                f'cd("{WORK.as_posix()}");',
                f'loadFile("{MODEL_FILE.name}");',
                "getErrorString();",
                f'buildModel({MODEL_NAME}, fileNamePrefix="{EXE_PREFIX}", '
                f"stopTime={STOP_TIME_S}, outputFormat=\"csv\", "
                "numberOfIntervals=1500, tolerance=1e-6);",
                "getErrorString();",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    run([str(omc), str(mos.name)], cwd=WORK)

    exe = WORK / (EXE_PREFIX + (".exe" if os.name == "nt" else ""))
    if not exe.is_file():
        sys.exit(f"Simulation executable not found after build in {WORK}")
    return exe


def _find_column(fieldnames: list[str], var: str) -> str:
    for name in fieldnames:
        key = name.strip().strip("'\"")
        if key == var or key.endswith(var):
            return name
    sys.exit(f"Column '{var}' not found. Columns: {fieldnames}")


def read_move_time(csv_path: Path) -> float | None:
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            sys.exit(f"Empty result file: {csv_path}")
        col = _find_column(list(reader.fieldnames), MOVE_TIME_VAR)
        move_time = 0.0
        for row in reader:
            if row.get(col) not in (None, ""):
                move_time = float(row[col])
    return move_time if move_time > 0.0 else None


def simulate_one(
    exe: Path,
    name_sh: str,
    tau_sh: float,
    name_el: str,
    tau_el: float,
    index: int,
) -> float | None:
    result = WORK / f"combo_{index:03d}_res.csv"
    override = (
        f"tau_stall_shoulder={tau_sh},"
        f"tau_stall_elbow={tau_el}"
    )
    run(
        [str(exe), f"-override={override}", f"-r={result.name}"],
        cwd=WORK,
        quiet=True,
    )
    if not result.is_file():
        fallback = WORK / f"{EXE_PREFIX}_res.csv"
        if fallback.is_file():
            result = fallback
        else:
            sys.exit(f"Result CSV missing for combo {index}")
    return read_move_time(result)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    omc = find_omc()
    print(f"Using omc: {omc}")
    exe = build_model(omc)

    names = list(SERVO_CANDIDATES.keys())
    combos = list(itertools.product(names, names))
    print(f"\nSweeping {len(combos)} combinations "
          f"({len(names)}^2 joints×servos)...\n")

    rows: list[dict[str, object]] = []
    for i, (n_sh, n_el) in enumerate(combos):
        tau_sh = SERVO_CANDIDATES[n_sh]
        tau_el = SERVO_CANDIDATES[n_el]
        print(
            f"[{i + 1}/{len(combos)}]  "
            f"sh={n_sh}  el={n_el}"
        )
        move_time = simulate_one(exe, n_sh, tau_sh, n_el, tau_el, i)
        rows.append(
            {
                "servo_shoulder": n_sh,
                "servo_elbow": n_el,
                "tau_shoulder_Nm": tau_sh,
                "tau_elbow_Nm": tau_el,
                "move_time_s": "" if move_time is None else round(move_time, 4),
            }
        )
        if move_time is None:
            print("  → unfinished")
        else:
            print(f"  → move_time = {move_time:.4f} s")

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "servo_shoulder",
                "servo_elbow",
                "tau_shoulder_Nm",
                "tau_elbow_Nm",
                "move_time_s",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    finished = sum(1 for r in rows if r["move_time_s"] != "")
    print(f"\nWrote {OUT_CSV}")
    print(f"Finished {finished}/{len(rows)} combinations within {STOP_TIME_S} s")


if __name__ == "__main__":
    main()
