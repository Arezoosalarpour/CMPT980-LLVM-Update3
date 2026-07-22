#!/usr/bin/env bash
# Step 4A1 — static code / object-size comparison for @combine_and_pshufb.
# Does NOT modify the LLVM patch, lit tests, or source tree. Does NOT rebuild.
#
# Required:
#   export LLVM_UNPATCHED_LLC=...
#   export LLVM_PATCHED_LLC=...
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUT="$ROOT/results/update3/step4a1"
LLVM_BIN="/opt/homebrew/opt/llvm/bin"
OBJDUMP="${LLVM_OBJDUMP:-$LLVM_BIN/llvm-objdump}"
READOBJ="${LLVM_READOBJ:-$LLVM_BIN/llvm-readobj}"
NM="${LLVM_NM:-$LLVM_BIN/llvm-nm}"
SIZE="${LLVM_SIZE:-$LLVM_BIN/llvm-size}"
IR="$ROOT/tests/step4a1_combine_and_pshufb.ll"
TRIPLE="x86_64-unknown"
ATTR="+avx2"
LLC_FLAGS=(-mtriple="$TRIPLE" -mattr="$ATTR")

mkdir -p "$OUT/baseline" "$OUT/patched"

require_distinct_llc_roles
LLC_UNPATCHED="$LLVM_UNPATCHED_LLC"
LLC_PATCHED="$LLVM_PATCHED_LLC"

log() { echo "$@" | tee -a "$OUT/commands.log"; }

{
  echo "# Step 4A1 measurement commands ($(date -u '+%Y-%m-%dT%H:%M:%SZ'))"
  echo "LLVM_UNPATCHED_LLC=$LLC_UNPATCHED"
  echo "LLVM_PATCHED_LLC=$LLC_PATCHED"
  echo "IR: $IR"
  echo "TRIPLE=$TRIPLE ATTR=$ATTR"
  echo
} > "$OUT/commands.log"

gen_variant() {
  local variant=$1
  local llc=$2
  local dir="$OUT/$variant"
  log ""
  log "## Generate $variant (llc=$llc)"
  log "$llc ${LLC_FLAGS[*]} $IR -o $dir/combine_and_pshufb.s"
  "$llc" "${LLC_FLAGS[@]}" "$IR" -o "$dir/combine_and_pshufb.s"
  log "$llc ${LLC_FLAGS[*]} -filetype=obj $IR -o $dir/combine_and_pshufb.o"
  "$llc" "${LLC_FLAGS[@]}" -filetype=obj "$IR" -o "$dir/combine_and_pshufb.o"
  log "$OBJDUMP --triple=$TRIPLE -d --no-leading-addr --demangle $dir/combine_and_pshufb.o"
  "$OBJDUMP" --triple="$TRIPLE" -d --no-leading-addr --demangle "$dir/combine_and_pshufb.o" \
    > "$dir/disassembly.txt"
  log "$OBJDUMP --triple=$TRIPLE -h --section-headers $dir/combine_and_pshufb.o"
  "$OBJDUMP" --triple="$TRIPLE" -h --section-headers "$dir/combine_and_pshufb.o" \
    > "$dir/section_headers.txt"
  log "$READOBJ --sections $dir/combine_and_pshufb.o"
  "$READOBJ" --sections "$dir/combine_and_pshufb.o" \
    > "$dir/readobj_sections.txt" 2>&1 || true
  log "$NM --print-size --size-sort $dir/combine_and_pshufb.o"
  "$NM" --print-size --size-sort "$dir/combine_and_pshufb.o" \
    > "$dir/nm_symbols.txt" 2>&1 || true
  log "$SIZE -A $dir/combine_and_pshufb.o"
  "$SIZE" -A "$dir/combine_and_pshufb.o" > "$dir/size_A.txt" 2>&1 || true
  log "$SIZE $dir/combine_and_pshufb.o"
  "$SIZE" "$dir/combine_and_pshufb.o" > "$dir/size_bsd.txt" 2>&1 || true
}

gen_variant baseline "$LLC_UNPATCHED"
gen_variant patched "$LLC_PATCHED"

python3 "$ROOT/update3/step4a1_analyze.py" "$OUT"

echo "Step 4A1 complete. See $OUT/STEP4A1_REPORT.md"
