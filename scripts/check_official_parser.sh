#!/usr/bin/env bash
# Validate SysML v2 models with the official OMG Pilot Implementation parser
#
# Prerequisites:
#   - Miniconda or Anaconda installed
#   - conda environment 'sysml' with jupyter-sysml-kernel
#
# Setup (one-time):
#   conda create -n sysml -c conda-forge --override-channels jupyter-sysml-kernel jupyter_client python=3.11
#   conda activate sysml
#   pip install -e .
#
# Usage:
#   ./scripts/check_official_parser.sh <folder>
#
# The official parser is SLOW on first run (~10 min to load standard library).
# Subsequent runs are faster (~3-5 seconds per file).

set -e

# Find conda
if command -v conda &> /dev/null; then
    CONDA_CMD="conda"
elif [ -f "$HOME/miniconda3/bin/conda" ]; then
    CONDA_CMD="$HOME/miniconda3/bin/conda"
elif [ -f "$HOME/anaconda3/bin/conda" ]; then
    CONDA_CMD="$HOME/anaconda3/bin/conda"
else
    echo "Error: conda not found. Install Miniconda or Anaconda first."
    exit 1
fi

# Check if sysml environment exists
if ! $CONDA_CMD env list | grep -q "^sysml "; then
    echo "Error: conda environment 'sysml' not found."
    echo ""
    echo "Create it with:"
    echo "  conda create -n sysml -c conda-forge --override-channels jupyter-sysml-kernel jupyter_client python=3.11"
    exit 1
fi

# Get python path from sysml environment
SYSML_PYTHON=$($CONDA_CMD run -n sysml python -c "import sys; print(sys.executable)")

if [ -z "$SYSML_PYTHON" ]; then
    echo "Error: could not find python in sysml environment"
    exit 1
fi

# Run the official check
# DO NOT use 'conda run' - it deadlocks on kernel output (see README.md)
echo "Using $SYSML_PYTHON"
echo "Validating: $1"
echo "(First run is slow - loads ~200-file standard library)"
echo ""

"$SYSML_PYTHON" -u -m system_explorer.official_check "$@"
