#!/usr/bin/env bash
# Step 3C — finalize LLVM regression tests for the narrowed project patch.
#
# Prerequisites:
#   1. ./update3/step1_baseline.sh   → results/update3/baseline/lit_x64_avx2.s
#   2. Canonical patches applied to the patched LLVM tree; tools rebuilt
#   3. export LLVM_PATCHED_LLC LLVM_FILECHECK
#
# Does NOT overwrite results/update3/step3c/X86ISelLowering.patch
# Does NOT read results/update3/step3a/ or step3b*/ artifacts.
# Does NOT stash or rebuild LLVM.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUT="$ROOT/results/update3/step3c"
BASELINE_LIT_ASM="$ROOT/results/update3/baseline/lit_x64_avx2.s"
CANONICAL_PATCH="$OUT/X86ISelLowering.patch"
TESTS="$ROOT/tests"
COMPARE="$ROOT/update3/step3c_compare.py"

mkdir -p "$OUT/asm" "$OUT/filecheck" "$OUT/broader" "$OUT/semantic" "$OUT/generated"

require_patched_llc
require_filecheck
LLC="$LLVM_PATCHED_LLC"
FC="$LLVM_FILECHECK"

if [[ ! -f "$BASELINE_LIT_ASM" ]]; then
  cat >&2 <<EOF
error: missing unpatched lit-module assembly required for the 71-function compare:

  $BASELINE_LIT_ASM

Run Step 1 first (with LLVM_UNPATCHED_LLC set):

  export LLVM_UNPATCHED_LLC=/path/to/unpatched/bin/llc
  ./update3/step1_baseline.sh

That script writes results/update3/baseline/lit_x64_avx2.s.
Do not rely on step3b1/asm/unpatched.s or other uncommitted step3b* artifacts.
EOF
  exit 1
fi

if [[ ! -f "$COMPARE" ]]; then
  echo "error: missing $COMPARE (required for 71-function compare)" >&2
  exit 1
fi

if [[ ! -f "$CANONICAL_PATCH" ]]; then
  echo "error: missing canonical patch $CANONICAL_PATCH" >&2
  echo "This committed file must be present; Step 3C will not regenerate it." >&2
  exit 1
fi

# Optional diagnostic only — never overwrite the canonical committed patch.
if [[ -d "$LLVM_PROJECT/.git" ]]; then
  git -C "$LLVM_PROJECT" diff HEAD -- "$LLVM_SRC" \
    > "$OUT/generated/current_worktree.patch" || true
  echo "Wrote optional worktree diff to $OUT/generated/current_worktree.patch"
  echo "(canonical patch left untouched: $CANONICAL_PATCH)"
fi

{
  echo "# Step 3C validation commands"
  echo "LLVM_PATCHED_LLC=$LLC"
  echo "LLVM_FILECHECK=$FC"
  echo "LIT_TEST=$LIT_TEST"
  echo "BASELINE_LIT_ASM=$BASELINE_LIT_ASM"
  echo "CANONICAL_PATCH=$CANONICAL_PATCH (not overwritten)"
  echo
} > "$OUT/commands.log"

run_filecheck() {
  local name="$1" triple="$2" attr="$3" prefixes="$4"
  local asm="$OUT/filecheck/${name}.s"
  local fc_out="$OUT/filecheck/${name}.fc.log"
  local cmd="$LLC < $LIT_TEST -mtriple=$triple -mattr=$attr | $FC $LIT_TEST --check-prefixes=$prefixes"
  echo "RUN: $cmd" >> "$OUT/commands.log"
  "$LLC" < "$LIT_TEST" -mtriple="$triple" -mattr="$attr" -o "$asm" 2>"$OUT/filecheck/${name}.llc.stderr"
  if "$FC" "$LIT_TEST" --check-prefixes="$prefixes" < "$asm" >"$fc_out" 2>&1; then
    echo "PASS $name" | tee -a "$OUT/filecheck_runs.log"
  else
    echo "FAIL $name (see $fc_out)" | tee -a "$OUT/filecheck_runs.log"
    return 1
  fi
}

: > "$OUT/filecheck_runs.log"
run_filecheck i686_avx2 i686-unknown +avx2 CHECK,X86,AVX2,X86-AVX2
run_filecheck i686_avx512 i686-unknown +avx512f CHECK,X86,AVX512,X86-AVX512
run_filecheck x86_64_avx2 x86_64-unknown +avx2 CHECK,X64,AVX2,X64-AVX2
run_filecheck x86_64_avx512 x86_64-unknown +avx512f CHECK,X64,AVX512,X64-AVX512

echo "Emitting patched lit-module asm for 71-function compare..."
"$LLC" < "$LIT_TEST" -mtriple=x86_64-unknown -mattr=+avx2 \
  -o "$OUT/asm/patched.s" 2>"$OUT/asm/patched.stderr"

echo "Using Step 1 unpatched lit asm: $BASELINE_LIT_ASM"
cp "$BASELINE_LIT_ASM" "$OUT/asm/unpatched.s"

python3 "$COMPARE" "$OUT"

echo "Running broader X86 vector-shuffle regression tests..."
BROADER=(
  "vector-shuffle-combining-avx.ll"
  "vector-shuffle-256-v32.ll"
  "vector-shuffle-combining.ll"
  "avx2-shuffle.ll"
)
: > "$OUT/broader_runs.log"
for t in "${BROADER[@]}"; do
  path="$LLVM_PROJECT/llvm/test/CodeGen/X86/$t"
  if [[ ! -f "$path" ]]; then
    echo "SKIP $t (missing)" | tee -a "$OUT/broader_runs.log"
    continue
  fi
  name="${t%.ll}"
  ok=1
  while IFS= read -r runline; do
    [[ "$runline" =~ ^[[:space:]]*\;[[:space:]]*RUN:[[:space:]]*(.+)$ ]] || continue
    cmd="${BASH_REMATCH[1]}"
    cmd="${cmd//llc/$LLC}"
    cmd="${cmd//FileCheck/$FC}"
    cmd="${cmd//\%s/$path}"
    log="$OUT/broader/${name}.log"
    echo "RUN: $cmd" >> "$OUT/commands.log"
    if eval "$cmd" >>"$log" 2>&1; then
      echo "  PASS run line" >> "$OUT/broader_runs.log"
    else
      echo "  FAIL run line (see $log)" >> "$OUT/broader_runs.log"
      ok=0
    fi
  done < "$path"
  if [[ $ok -eq 1 ]]; then
    echo "PASS $t" | tee -a "$OUT/broader_runs.log"
  else
    echo "FAIL $t" | tee -a "$OUT/broader_runs.log"
  fi
done

echo "Rebuilding semantic verifier objects with patched llc..."
WORK="$OUT/semantic/build"
rm -rf "$WORK"
mkdir -p "$WORK"
for v in a b c; do
  "$LLC" -O2 -mattr=+avx2 -mtriple=x86_64-apple-macos -filetype=obj \
    -o "$WORK/sparse_variant_${v}.o" \
    "$TESTS/update2_sparse_variant_${v}.ll" 2>"$OUT/semantic/variant_${v}.stderr"
done
CC="${CC:-clang}"
X86_FLAGS=(-target x86_64-apple-macos -mavx2)
"$CC" "${X86_FLAGS[@]}" -O2 -o "$WORK/verify_patched_codegen" \
  "$TESTS/verify_patched_codegen.c" \
  "$WORK"/sparse_variant_*.o
if arch -x86_64 "$WORK/verify_patched_codegen" | tee "$OUT/semantic/verify.log"; then
  echo "semantic_verification: PASS" | tee -a "$OUT/semantic/verify.log"
else
  echo "semantic_verification: FAIL" | tee -a "$OUT/semantic/verify.log"
  exit 1
fi

# Capture target assembly for combine_and_pshufb and variants.
"$LLC" < "$LIT_TEST" -mtriple=x86_64-unknown -mattr=+avx2 -o "$OUT/asm/lit_x64_avx2.s"
for fn in combine_and_pshufb sparse_identity_or_zero_variant_a sparse_identity_or_zero_variant_b sparse_identity_or_zero_variant_c sparse_one_zero_word_pair_per_lane sparse_two_source_cross_lane combine_pshufb_and combine_pshufb_as_vzmovl_32 combine_pshufb_as_vzmovl_64; do
  sed -n "/^${fn}:/,/\.Lfunc_end/p" "$OUT/asm/lit_x64_avx2.s" > "$OUT/asm/${fn}.s"
done

echo "Step 3C validation complete. See $OUT/STEP3C_REPORT.md"
