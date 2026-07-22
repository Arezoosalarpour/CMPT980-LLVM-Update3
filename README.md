# CMPT980-LLVM-Update3
LLVM AVX2 shuffle-lowering implementation, validation, and cost evaluation for CMPT 980 Update 3.

# CMPT 980 – LLVM AVX2 Shuffle Lowering: Update 3

This repository contains the implementation, validation, and evaluation
completed as part of Project Update 3.

Update 2 identified sparse AVX2 byte-shuffle masks that produced a
`vpxor + vpblendw` sequence instead of a single `vpshufb`. In Update 3,
we implemented and evaluated a targeted LLVM lowering change for this case.

## Repository Structure

- `update3/` – Reproduction, validation, and evaluation scripts.
- `tests/` – LLVM IR inputs and semantic verification code.
- `results/update3/` – Final LLVM patches and result summaries.

## Implementation

The implementation modifies:

`llvm/lib/Target/X86/X86ISelLowering.cpp`

The change adds a non-mutating PSHUFB legality check and attempts PSHUFB
lowering before element widening for the target mask family. It also uses
a targeted condition to prevent a later DAG combine from converting the
legal PSHUFB representation back to a blend.

## Main Results

- Variants A and C lower to a single `vpshufb`.
- Variant B remains unchanged as the control case.
- The final comparison found no assembly changes in 70 unrelated functions.
- The regression and semantic tests passed.
- The function's `.text` size decreased from 11 bytes to 10 bytes.
- The `llvm-mca` results showed that the preferred representation depends
  on the target CPU.
- The broader investigation evaluated 105 additional masks.

## Main Files

- `results/update3/X86ISelLowering.patch` – Final LLVM source patch.
- `results/update3/vector-shuffle-combining-avx2.ll.patch` – Final lit-test patch.
- `update3/step3c_finalize.sh` – Final regression validation.
- `update3/step4a1_measure.sh` – Static-size evaluation.
- `update3/step4a2_mca.sh` – Target-cost evaluation.
- `update3/step5a2_investigate.sh` – Additional mask investigation.

## Environment

- LLVM 17.0.6
- X86-64 target
- AVX2 enabled

## Reproduction

The scripts require paths to both the unmodified and patched LLVM builds.
Check the path variables at the beginning of each script before running it.

Run the main stages in this order:

1. `update3/step1_baseline.sh`
2. `update3/step2_patched.sh`
3. `update3/step3c_finalize.sh`
4. `update3/step4a1_measure.sh`
5. `update3/step4a2_mca.sh`
6. `update3/step5a2_investigate.sh`
