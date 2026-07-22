#!/usr/bin/env bash
# Step 5A2 — search missed lowering opportunities (unpatched LLVM 17.0.6).
# Does NOT modify the LLVM source tree, stash, or rebuild.
#
# Required:
#   export LLVM_UNPATCHED_LLC=...
#   export LLVM_MCA=...
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUT="$ROOT/results/update3/step5a2"

mkdir -p "$OUT"

require_unpatched_llc
require_mca
LLC="$LLVM_UNPATCHED_LLC"
MCA="$LLVM_MCA"

{
  echo "# Step 5A2 commands ($(date -u '+%Y-%m-%dT%H:%M:%SZ'))"
  echo "LLVM_UNPATCHED_LLC=$LLC"
  echo "LLVM_MCA=$MCA"
} > "$OUT/commands.log"

python3 "$ROOT/update3/step5a2_search.py" "$ROOT" "$LLC" "$MCA" | tee -a "$OUT/commands.log"
python3 "$ROOT/update3/step5a2_report.py" "$OUT"

echo "Step 5A2 complete. See $OUT/STEP5A2_REPORT.md"
