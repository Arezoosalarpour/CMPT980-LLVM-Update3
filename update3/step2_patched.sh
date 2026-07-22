#!/usr/bin/env bash
# Step 2: compile A/B/C with patched LLVM 17.0.6 llc and save artifacts.
#
# Required:
#   export LLVM_PATCHED_LLC=/path/to/patched/bin/llc
#   Step 1 baseline: results/update3/baseline/sparse_variant_{a,b,c}.s
#
# Does NOT rebuild LLVM. Does NOT modify the LLVM source tree.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUT="$ROOT/results/update3/patched"
TESTDIR="$ROOT/tests"
BASE="$ROOT/results/update3/baseline"
CANONICAL_PATCH="$ROOT/results/update3/step3c/X86ISelLowering.patch"

mkdir -p "$OUT" "$OUT/generated"

require_patched_llc
LLC="$LLVM_PATCHED_LLC"

for v in a b c; do
  if [[ ! -f "$BASE/sparse_variant_${v}.s" ]]; then
    echo "error: missing baseline asm $BASE/sparse_variant_${v}.s" >&2
    echo "Run ./update3/step1_baseline.sh first (with LLVM_UNPATCHED_LLC)." >&2
    exit 1
  fi
done

{
  echo "# Patched llc compile commands ($(date -u '+%Y-%m-%dT%H:%M:%SZ'))"
  echo "LLVM_PATCHED_LLC=$LLC"
  for v in a b c; do
    echo "$LLC -O2 -mattr=+avx2 -mtriple=x86_64-apple-macos \\"
    echo "  $TESTDIR/update2_sparse_variant_${v}.ll \\"
    echo "  -o $OUT/sparse_variant_${v}.s"
  done
} > "$OUT/commands.log"

for v in a b c; do
  "$LLC" -O2 -mattr=+avx2 -mtriple=x86_64-apple-macos \
    "$TESTDIR/update2_sparse_variant_${v}.ll" \
    -o "$OUT/sparse_variant_${v}.s"
done

"$LLC" --version > "$OUT/llc_version.txt" 2>&1 || true

# Optional diagnostic only — never overwrite the canonical committed patch.
if [[ -d "$LLVM_PROJECT/.git" ]]; then
  git -C "$LLVM_PROJECT" diff -- "$LLVM_SRC" \
    > "$OUT/generated/current_worktree.patch" || true
  echo "Wrote optional worktree diff to $OUT/generated/current_worktree.patch"
  echo "(canonical patch remains $CANONICAL_PATCH)"
fi

{
  echo "# Before/after instruction summary (baseline vs patched)"
  echo
  for v in a b c; do
    VUP=$(echo "$v" | tr '[:lower:]' '[:upper:]')
    echo "## Variant $VUP"
    echo "Baseline:"
    grep -E 'vpxor|vpblend|vpshufb' "$BASE/sparse_variant_${v}.s" || echo "(none)"
    echo "Patched:"
    grep -E 'vpxor|vpblend|vpshufb' "$OUT/sparse_variant_${v}.s" || echo "(none)"
    echo
  done
} > "$OUT/comparison.md"

# Semantic verification against patched object code.
WORK="$OUT/semantic_build"
rm -rf "$WORK"
mkdir -p "$WORK"
for v in a b c; do
  "$LLC" -O2 -mattr=+avx2 -mtriple=x86_64-apple-macos -filetype=obj \
    -o "$WORK/sparse_variant_${v}.o" \
    "$TESTDIR/update2_sparse_variant_${v}.ll"
done

CC="${CC:-clang}"
X86_FLAGS=(-target x86_64-apple-macos -mavx2)
"$CC" "${X86_FLAGS[@]}" -O2 -o "$WORK/verify_patched_codegen" \
  "$ROOT/tests/verify_patched_codegen.c" \
  "$WORK"/sparse_variant_*.o

if arch -x86_64 "$WORK/verify_patched_codegen" | tee "$OUT/semantic_verification.log"; then
  echo "semantic_verification: PASS" >> "$OUT/semantic_verification.log"
else
  echo "semantic_verification: FAIL" >> "$OUT/semantic_verification.log"
  exit 1
fi

echo "Step 2 patched artifacts written to $OUT"
