#!/usr/bin/env bash
# Update 3 Step 1 — unpatched llc baseline for sparse variants A/B/C
# and the full lit-module assembly used by Step 3C's 71-function compare.
#
# Does NOT modify the LLVM source tree, stash, or rebuild LLVM.
# Does NOT depend on step3a/step3b* artifacts.
#
# Required:
#   export LLVM_UNPATCHED_LLC=/path/to/stock-llvm-17.0.6/bin/llc
#
# Optional:
#   LLVM_PROJECT, LIT_TEST (for reading upstream lit IR only; never modified)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

PROJ="$(cd "$SCRIPT_DIR/.." && pwd)"
BASE="$PROJ/results/update3/baseline"
LIT_PATCH="$PROJ/results/update3/step3c/vector-shuffle-combining-avx2.ll.patch"
LLC_FLAGS=(-O2 -mattr=+avx2 -mtriple=x86_64-apple-macos)
LIT_ASM_FLAGS=(-mtriple=x86_64-unknown -mattr=+avx2)

mkdir -p "$BASE"
: > "$BASE/commands.log"

require_unpatched_llc
LLC="$LLVM_UNPATCHED_LLC"

echo "=== Update 3 Step 1 baseline (unpatched llc) ===" | tee "$BASE/run.log"
echo "LLVM_UNPATCHED_LLC=$LLC" | tee -a "$BASE/run.log"
"$LLC" --version | head -3 | tee -a "$BASE/run.log"
echo | tee -a "$BASE/run.log"

compile_ir() {
  local src=$1 out=$2
  echo "$LLC ${LLC_FLAGS[*]} $src -o $out" >> "$BASE/commands.log"
  "$LLC" "${LLC_FLAGS[@]}" "$src" -o "$out"
}

for v in a b c; do
  compile_ir "$PROJ/tests/update2_sparse_variant_${v}.ll" \
    "$BASE/sparse_variant_${v}.s"
done
compile_ir "$PROJ/tests/update2_combine_and_pshufb.ll" \
  "$BASE/combine_and_pshufb_preopt.s"

# --- Lit-module assembly for Step 3C 71-function compare ---
# Prefer upstream lit IR (without Step 3C CHECK/new-test additions) so the
# baseline function set matches the historical 71-function compare.
# Reverse-apply runs only on a temp copy; the LLVM tree is never modified.
prepare_upstream_lit() {
  local dest=$1
  mkdir -p "$(dirname "$dest")"
  if [[ ! -f "$LIT_TEST" ]]; then
    echo "error: lit test not found: $LIT_TEST" >&2
    echo "Set LIT_TEST to llvm/test/CodeGen/X86/vector-shuffle-combining-avx2.ll" >&2
    echo "(preferably from an unpatched LLVM 17.0.6 tree)." >&2
    exit 1
  fi

  if [[ -f "$LIT_PATCH" ]]; then
    local work
    work=$(mktemp -d)
    mkdir -p "$work/llvm/test/CodeGen/X86"
    cp "$LIT_TEST" "$work/llvm/test/CodeGen/X86/vector-shuffle-combining-avx2.ll"
    if patch -R -p1 -d "$work" --dry-run < "$LIT_PATCH" >/dev/null 2>&1; then
      patch -R -p1 -d "$work" < "$LIT_PATCH" >> "$BASE/commands.log" 2>&1
      echo "Prepared upstream lit IR by reverse-applying $LIT_PATCH (temp copy only)" \
        | tee -a "$BASE/run.log"
    else
      echo "Note: lit patch does not reverse-apply (lit may already be upstream); using $LIT_TEST as-is." \
        | tee -a "$BASE/run.log"
    fi
    cp "$work/llvm/test/CodeGen/X86/vector-shuffle-combining-avx2.ll" "$dest"
    rm -rf "$work"
  else
    echo "Note: $LIT_PATCH missing; compiling current LIT_TEST for baseline lit asm." \
      | tee -a "$BASE/run.log"
    cp "$LIT_TEST" "$dest"
  fi
}

LIT_IR="$BASE/work/vector-shuffle-combining-avx2.upstream.ll"
prepare_upstream_lit "$LIT_IR"
echo "$LLC ${LIT_ASM_FLAGS[*]} < $LIT_IR -o $BASE/lit_x64_avx2.s" >> "$BASE/commands.log"
"$LLC" "${LIT_ASM_FLAGS[@]}" < "$LIT_IR" -o "$BASE/lit_x64_avx2.s" \
  2>"$BASE/lit_x64_avx2.stderr"
echo "Wrote unpatched lit-module asm: results/update3/baseline/lit_x64_avx2.s" \
  | tee -a "$BASE/run.log"

# Optional mask analysis (Update-3-local tool; not required for later steps).
MASK_SRC="$PROJ/update3/tools/analyze_shuffle_mask.cpp"
MASK_BIN="$PROJ/update3/tools/analyze_shuffle_mask"
if [[ -f "$MASK_SRC" ]]; then
  /usr/bin/clang++ -std=c++17 -O2 "$MASK_SRC" -o "$MASK_BIN"
  "$MASK_BIN" "$PROJ" --markdown "$BASE/mask_analysis.md" \
    > "$BASE/mask_analysis_stdout.txt"
fi

echo "--- Baseline asm (shuffle ops only) ---" | tee -a "$BASE/run.log"
for f in sparse_variant_a sparse_variant_b sparse_variant_c; do
  printf "  %-20s " "$f" | tee -a "$BASE/run.log"
  grep -E '^\t(vpxor|vpblendw|vpshufb)' "$BASE/${f}.s" \
    | tr '\n' ' ' | sed 's/ $/\n/' | tee -a "$BASE/run.log"
done

echo "Done. See results/update3/baseline/ (includes lit_x64_avx2.s for Step 3C)."
echo "Next: apply canonical patches to the patched LLVM tree, rebuild tools,"
echo "      set LLVM_PATCHED_LLC / LLVM_FILECHECK / LLVM_MCA, then run step2_patched.sh."
