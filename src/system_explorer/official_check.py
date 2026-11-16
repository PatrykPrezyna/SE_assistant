"""Validate a folder of .sysml files with the OFFICIAL SysML v2 parser.

Drives the OMG pilot implementation (the reference Xtext parser, with the
full standard library) through its Jupyter kernel, `jupyter-sysml-kernel`.
Complementary to `system-explorer --check`: that one is a fast, dependency-
free sanity check; this one gives spec-grade syntax and semantic
diagnostics, but needs Java 21+ and the kernel installed (see the
"Setting up the validation parsers" section of the README).

Every .sysml file directly inside <folder> (not recursive, name-sorted —
the same set system-explorer serves) is evaluated in one kernel session, so
cross-file references resolve. Exits nonzero if the parser reports any
ERROR/WARNING lines.

Ships with the system_explorer package but imports nothing from it, and
imports jupyter_client only when run, so the explorer itself stays
stdlib-only. It must run under a python that HAS jupyter_client (the conda
env with the kernel), so invoke that env's python DIRECTLY — as a module
once this package is installed into that env, or by file path:

    %USERPROFILE%\\miniconda3\\envs\\sysml\\python.exe -u -m system_explorer.official_check <folder>

Do not run it through `conda run`: that never drains the kernel JVM's
console output, the pipe fills, and the run deadlocks (short probe
one-liners like `conda run -n sysml python -c "import sys; ..."` are fine).
"""

import argparse
import sys
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("folder", help="folder containing .sysml files")
    ap.add_argument("--kernel", default="sysml", help="Jupyter kernel name")
    ap.add_argument(
        "--timeout", type=int, default=900,
        help="seconds to allow for kernel startup and for each file. "
             "Startup includes loading the ~200-file standard library, "
             "which can take >10 minutes cold (antivirus scanning) but "
             "runs in a couple of minutes once the OS file cache is warm",
    )
    args = ap.parse_args()

    try:
        from jupyter_client.manager import start_new_kernel
    except ImportError:
        sys.exit(
            "jupyter_client is not installed in this python.\n"
            "Invoke the conda env's python directly (NOT via `conda run`,\n"
            "which deadlocks on the kernel's console output), e.g.:\n"
            f"  %USERPROFILE%\\miniconda3\\envs\\sysml\\python.exe -u "
            f"-m system_explorer.official_check {args.folder}"
        )

    folder = Path(args.folder).resolve()
    if not folder.is_dir():
        sys.exit(f"not a folder: {folder}")
    files = sorted(folder.glob("*.sysml"), key=lambda p: p.name)
    if not files:
        sys.exit(f"no .sysml files found directly in {folder}")

    print(f"Starting kernel '{args.kernel}' (JVM startup takes a moment)...")
    km, kc = start_new_kernel(
        kernel_name=args.kernel, startup_timeout=args.timeout
    )
    problems = 0
    try:
        for p in files:
            chunks = []

            def collect(msg):
                mtype = msg["msg_type"]
                content = msg["content"]
                if mtype == "stream":
                    chunks.append(content["text"])
                elif mtype == "execute_result":
                    chunks.append(content["data"].get("text/plain", ""))
                elif mtype == "error":
                    chunks.append("\n".join(content.get("traceback", [])))

            kc.execute_interactive(
                p.read_text(encoding="utf-8"),
                output_hook=collect, allow_stdin=False, timeout=args.timeout,
            )
            bad = [
                ln.strip() for ln in "".join(chunks).splitlines()
                if "ERROR" in ln or "WARNING" in ln
            ]
            if bad:
                problems += len(bad)
                for ln in bad:
                    print(f"{p.name}: {ln}")
            else:
                print(f"{p.name}: OK")
    finally:
        kc.stop_channels()
        km.shutdown_kernel(now=True)

    if problems:
        sys.exit(f"{problems} problem(s) reported by the official parser")
    print(f"OK - official parser reports no problems in {len(files)} file(s)")


if __name__ == "__main__":
    main()
