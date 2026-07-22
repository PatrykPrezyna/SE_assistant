"""Sweep ElbowServo.mo over servo stall ratings; write metrics to CSV.

For each servo candidate records:
  - max |torque| over the run [N·m]
  - move_time_s — time when the last waypoint (p4) was reached
    (empty if the sequence did not finish within StopTime)

Requires OpenModelica (OPENMODELICAHOME or omc on PATH). Builds the model once,
then re-runs the executable with -override for each candidate — no OMPython.

Usage (from anywhere):
  python examples/RoboticArm/Simulation/run_elbow_servo_sweep.py
"""

from __future__ import annotations

import csv
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
MODEL_FILE = HERE / "ElbowServo.mo"
MODEL_NAME = "ElbowServo.ElbowServoSimulation"
WORK = HERE.parent / "output" / "om_elbow_sweep"
OUT_CSV = HERE.parent / "output" / "elbow_servo_sweep.csv"

# Same stall table as torque_analysis.py (N·m at ~5–6 V)
SERVO_CANDIDATES = {
    "SG90 (1.6 kg*cm)": 0.157,
    "MG90S (2.2 kg*cm)": 0.216,
    "AD002 (2.0 kg*cm)": 0.196,
    "MG996R (9.4 kg*cm)": 0.92,
    "DS3218 (19 kg*cm)": 1.86,
    "DS5160 (60 kg*cm)": 5.88,
}

TORQUE_VAR = "5_actual_torque"
MOVE_TIME_VAR = "6_move_time"
EXE_PREFIX = "ElbowServoSimulation"


def find_omc() -> Path:
    home = os.environ.get("OPENMODELICAHOME")
    if home:
        bin_dir = Path(home) / "bin"
        # Windows sim exe needs OM libs on PATH
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


def run(cmd: list[str], cwd: Path) -> None:
    print("+", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        sys.exit(f"Command failed ({proc.returncode}): {' '.join(cmd)}")
    if proc.stdout.strip():
        print(proc.stdout.strip())


def build_model(omc: Path) -> Path:
    """Compile once; returns path to the simulation executable."""
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
                'stopTime=10, outputFormat="csv", '
                'numberOfIntervals=1000, tolerance=1e-6);',
                "getErrorString();",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    run([str(omc), str(mos.name)], cwd=WORK)

    exe = WORK / (EXE_PREFIX + (".exe" if os.name == "nt" else ""))
    if not exe.is_file():
        matches = list(WORK.glob(EXE_PREFIX + "*"))
        sys.exit(f"Simulation executable not found after build. Saw: {matches}")
    return exe


def _find_column(fieldnames: list[str], var: str) -> str:
    for name in fieldnames:
        key = name.strip().strip("'\"")
        if key == var or key.endswith(var):
            return name
    sys.exit(f"Column '{var}' not found. Columns: {fieldnames}")


def read_metrics(csv_path: Path) -> tuple[float, float | None]:
    """Return (max_abs_torque, move_time_s or None if sequence unfinished)."""
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            sys.exit(f"Empty result file: {csv_path}")
        torque_col = _find_column(list(reader.fieldnames), TORQUE_VAR)
        time_col = _find_column(list(reader.fieldnames), MOVE_TIME_VAR)

        torques: list[float] = []
        move_time = 0.0
        for row in reader:
            if row.get(torque_col) not in (None, ""):
                torques.append(float(row[torque_col]))
            if row.get(time_col) not in (None, ""):
                move_time = float(row[time_col])

    if not torques:
        sys.exit(f"No torque samples in {csv_path}")

    max_tau = float(np.max(np.abs(np.asarray(torques))))
    # Model holds 0 until p4 is reached; stays at that stamp afterward
    finished_at = move_time if move_time > 0.0 else None
    return max_tau, finished_at


def simulate_one(
    exe: Path, servo_name: str, tau_stall: float
) -> tuple[float, float | None]:
    safe = "".join(c if c.isalnum() else "_" for c in servo_name)
    result = WORK / f"{safe}_res.csv"
    override = f"_servo_input.tau_stall={tau_stall}"
    cmd = [
        str(exe),
        f"-override={override}",
        f"-r={result.name}",
    ]
    run(cmd, cwd=WORK)
    if not result.is_file():
        fallback = WORK / f"{EXE_PREFIX}_res.csv"
        if fallback.is_file():
            result = fallback
        else:
            sys.exit(f"Result CSV not written for {servo_name}")
    return read_metrics(result)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    omc = find_omc()
    print(f"Using omc: {omc}")
    exe = build_model(omc)

    rows: list[dict[str, object]] = []
    for name, tau_stall in SERVO_CANDIDATES.items():
        print(f"\n=== {name}  tau_stall={tau_stall} N·m ===")
        max_tau, move_time = simulate_one(exe, name, tau_stall)
        rows.append(
            {
                "servo": name,
                "tau_stall_Nm": tau_stall,
                "max_abs_torque_Nm": round(max_tau, 6),
                "move_time_s": "" if move_time is None else round(move_time, 4),
            }
        )
        if move_time is None:
            print(f"max |torque| = {max_tau:.6f} N·m   move_time = (unfinished)")
        else:
            print(
                f"max |torque| = {max_tau:.6f} N·m   "
                f"move_time = {move_time:.4f} s"
            )

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "servo",
                "tau_stall_Nm",
                "max_abs_torque_Nm",
                "move_time_s",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nWrote {OUT_CSV}")


if __name__ == "__main__":
    main()
