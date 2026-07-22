#!/usr/bin/env bash
# Step 4A2 — llvm-mca comparison for @combine_and_pshufb baseline vs patched.
# Does NOT modify the LLVM patch or lit tests. Does NOT rebuild LLVM.
#
# Required:
#   export LLVM_MCA=/path/to/bin/llvm-mca
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUT="$ROOT/results/update3/step4a2"
INPUTS="$OUT/inputs"
RAW="$OUT/raw"
TRIPLE="x86_64-unknown"
ITERATIONS=1000

mkdir -p "$INPUTS" "$RAW"
require_mca
MCA="$LLVM_MCA"

{
  echo "# Step 4A2 llvm-mca commands ($(date -u '+%Y-%m-%dT%H:%M:%SZ'))"
  echo "LLVM_MCA=$MCA ($($MCA --version | head -1))"
  echo "TRIPLE=$TRIPLE ITERATIONS=$ITERATIONS"
  echo
} > "$OUT/commands.log"

# Baseline as emitted by LLVM 17 llc (ELF / x86_64-unknown): $238 with swapped operands.
cat > "$INPUTS/baseline.s" << 'EOF'
	.text
	.globl	mca_region
mca_region:
	vpxor	%xmm1, %xmm1, %xmm1
	vpblendw $238, %ymm1, %ymm0, %ymm0
EOF

# Semantically equivalent Mach-O / earlier-reported form: $17 with reversed operands.
cat > "$INPUTS/baseline_equiv_17.s" << 'EOF'
	.text
	.globl	mca_region
mca_region:
	vpxor	%xmm1, %xmm1, %xmm1
	vpblendw $17, %ymm0, %ymm1, %ymm0
EOF

# Patched sequence from Step 4A1 (RIP-relative constant-pool mask).
cat > "$INPUTS/patched.s" << 'EOF'
	.section .rodata.cst32,"aM",@progbits,32
	.p2align 5
.LCPI0_0:
	.byte 0, 1, 255, 255, 255, 255, 255, 255
	.byte 8, 9, 255, 255, 255, 255, 255, 255
	.byte 0, 1, 255, 255, 255, 255, 255, 255
	.byte 8, 9, 255, 255, 255, 255, 255, 255
	.text
	.globl	mca_region
mca_region:
	vpshufb .LCPI0_0(%rip), %ymm0, %ymm0
EOF

CPUS=(haswell skylake znver1)
VARIANTS=(baseline patched)
EQUIV=(baseline_equiv_17)

for cpu in "${CPUS[@]}"; do
  for variant in "${VARIANTS[@]}" "${EQUIV[@]}"; do
    cmd=( "$MCA" -mtriple="$TRIPLE" -mcpu="$cpu" -iterations="$ITERATIONS" "$INPUTS/${variant}.s" )
    printf 'RUN: %q ' "${cmd[@]}" >> "$OUT/commands.log"
    echo >> "$OUT/commands.log"
    "${cmd[@]}" > "$RAW/${variant}_${cpu}.txt" 2>&1
  done
done

python3 "$ROOT/update3/step4a2_analyze.py" "$OUT"

echo "Step 4A2 complete. See $OUT/STEP4A2_REPORT.md"
