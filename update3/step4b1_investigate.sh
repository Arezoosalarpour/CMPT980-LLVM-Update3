#!/usr/bin/env bash
# Step 4B1 — investigate AVX2 contexts where PSHUFB may beat blend.
# Does NOT modify the LLVM patch, lit tests, or source tree. Does NOT rebuild.
#
# Required:
#   export LLVM_UNPATCHED_LLC=...
#   export LLVM_PATCHED_LLC=...
#   export LLVM_MCA=...
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUT="$ROOT/results/update3/step4b1"

mkdir -p "$OUT/llvm_codegen" "$OUT/inputs" "$OUT/raw" "$OUT/mca_sweep"

require_distinct_llc_roles
require_mca
MCA="$LLVM_MCA"
LLC_PATCHED="$LLVM_PATCHED_LLC"
LLC_UNPATCHED="$LLVM_UNPATCHED_LLC"

{
  echo "# Step 4B1 commands ($(date -u '+%Y-%m-%dT%H:%M:%SZ'))"
  echo "LLVM_MCA=$MCA"
  echo "LLVM_PATCHED_LLC=$LLC_PATCHED"
  echo "LLVM_UNPATCHED_LLC=$LLC_UNPATCHED"
} > "$OUT/commands.log"

# --- LLVM IR: four Variant-A shuffles, same mask, different inputs ---
cat > "$OUT/llvm_codegen/multi_shuffle.ll" << 'EOF'
target datalayout = "e-m:o-i64:64"
target triple = "x86_64-unknown"

define void @four_variant_a_shuffles(ptr %p, <32 x i8> %a, <32 x i8> %b, <32 x i8> %c, <32 x i8> %d) {
  %s0 = shufflevector <32 x i8> %a, <32 x i8> zeroinitializer,
    <32 x i32> <i32 0, i32 1, i32 32, i32 32, i32 32, i32 32, i32 32, i32 32,
                i32 8, i32 9, i32 32, i32 32, i32 32, i32 32, i32 32, i32 32,
                i32 16, i32 17, i32 48, i32 48, i32 48, i32 48, i32 48, i32 48,
                i32 24, i32 25, i32 48, i32 48, i32 48, i32 48, i32 48, i32 48>
  %s1 = shufflevector <32 x i8> %b, <32 x i8> zeroinitializer,
    <32 x i32> <i32 0, i32 1, i32 32, i32 32, i32 32, i32 32, i32 32, i32 32,
                i32 8, i32 9, i32 32, i32 32, i32 32, i32 32, i32 32, i32 32,
                i32 16, i32 17, i32 48, i32 48, i32 48, i32 48, i32 48, i32 48,
                i32 24, i32 25, i32 48, i32 48, i32 48, i32 48, i32 48, i32 48>
  %s2 = shufflevector <32 x i8> %c, <32 x i8> zeroinitializer,
    <32 x i32> <i32 0, i32 1, i32 32, i32 32, i32 32, i32 32, i32 32, i32 32,
                i32 8, i32 9, i32 32, i32 32, i32 32, i32 32, i32 32, i32 32,
                i32 16, i32 17, i32 48, i32 48, i32 48, i32 48, i32 48, i32 48,
                i32 24, i32 25, i32 48, i32 48, i32 48, i32 48, i32 48, i32 48>
  %s3 = shufflevector <32 x i8> %d, <32 x i8> zeroinitializer,
    <32 x i32> <i32 0, i32 1, i32 32, i32 32, i32 32, i32 32, i32 32, i32 32,
                i32 8, i32 9, i32 32, i32 32, i32 32, i32 32, i32 32, i32 32,
                i32 16, i32 17, i32 48, i32 48, i32 48, i32 48, i32 48, i32 48,
                i32 24, i32 25, i32 48, i32 48, i32 48, i32 48, i32 48, i32 48>
  store <32 x i8> %s0, ptr %p
  %p1 = getelementptr i8, ptr %p, i32 32
  store <32 x i8> %s1, ptr %p1
  %p2 = getelementptr i8, ptr %p1, i32 32
  store <32 x i8> %s2, ptr %p2
  %p3 = getelementptr i8, ptr %p2, i32 32
  store <32 x i8> %s3, ptr %p3
  ret void
}
EOF

"$LLC_PATCHED" "$OUT/llvm_codegen/multi_shuffle.ll" -mtriple=x86_64-unknown -mattr=+avx2 -O2 \
  -o "$OUT/llvm_codegen/multi_shuffle_patched.s" 2>>"$OUT/commands.log"
"$LLC_UNPATCHED" "$OUT/llvm_codegen/multi_shuffle.ll" -mtriple=x86_64-unknown -mattr=+avx2 -O2 \
  -o "$OUT/llvm_codegen/multi_shuffle_baseline.s" 2>>"$OUT/commands.log"

python3 "$ROOT/update3/step4b1_mca_sweep.py" "$OUT" "$MCA" >> "$OUT/commands.log"
python3 "$ROOT/update3/step4b1_report.py" "$OUT"

echo "Step 4B1 complete. See $OUT/STEP4B1_REPORT.md"
