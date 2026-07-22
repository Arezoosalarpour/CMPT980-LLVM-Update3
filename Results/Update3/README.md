# Update 3 results

Experimental LLVM 17.0.6 X86 backend patch for sparse AVX2 `shufflevector` lowering.

- Root: [`../../README.md`](../../README.md)
- Hub: [`../../update3/README.md`](../../update3/README.md)
- Contents / deps: [`../../update3/REPOSITORY.md`](../../update3/REPOSITORY.md)

| Directory | Purpose | Modify? |
|-----------|---------|---------|
| [`baseline/`](baseline/) | Unpatched llc output; includes `lit_x64_avx2.s` for Step 3C | Regenerate via `step1_baseline.sh` (do not commit `.s`) |
| [`patched/`](patched/) | Step 2 patched llc output + verification | Regenerate via `step2_patched.sh` |
| [`step3c/`](step3c/) | FileCheck + 71-fn compare; **commit the `.patch` files only** | Via `step3c_finalize.sh` (does **not** overwrite canonical patches) |
| [`step4a1/`](step4a1/) | Static code / object-size comparison | Via `step4a1_measure.sh` |
| [`step4a2/`](step4a2/) | llvm-mca CPU cost comparison | Via `step4a2_mca.sh` |
| [`step4b1/`](step4b1/) | AVX2 encoding + mask-reuse investigation | Via `step4b1_investigate.sh` |
| [`step5a1/`](step5a1/) | AVX2 shuffle helper overlap map (analysis-only) | Source inspection |
| [`step5a2/`](step5a2/) | Missed-lowering search | Via `step5a2_investigate.sh` |

`step3a/` / `step3b1/` / `step3b2/` / `step3b3/` are historical intermediates — do not upload for an Update-3-only repo.

---

## Step 1 — baseline

Unpatched assembly (regenerate): `baseline/sparse_variant_{a,b,c}.s`, **`baseline/lit_x64_avx2.s`**.

Reports (optional to commit): [`BASELINE_SUMMARY.md`](baseline/BASELINE_SUMMARY.md), [`toolchain.md`](baseline/toolchain.md), [`lowering_path_analysis.md`](baseline/lowering_path_analysis.md), [`patch_recommendation.md`](baseline/patch_recommendation.md).

## Step 2 — patched

Uses `tests/verify_patched_codegen.c`. Reports: [`PATCHED_SUMMARY.md`](patched/PATCHED_SUMMARY.md), [`patch_implementation.md`](patched/patch_implementation.md), [`comparison.md`](patched/comparison.md).

## Step 3C

| Artifact | Path |
|----------|------|
| Report | [`step3c/STEP3C_REPORT.md`](step3c/STEP3C_REPORT.md) |
| Canonical LLVM patch | [`step3c/X86ISelLowering.patch`](step3c/X86ISelLowering.patch) |
| Lit FileCheck patch | [`step3c/vector-shuffle-combining-avx2.ll.patch`](step3c/vector-shuffle-combining-avx2.ll.patch) |

Unpatched lit asm for the 71-function compare: **`baseline/lit_x64_avx2.s`** (from Step 1).

## Steps 4–5

| Step | Report |
|------|--------|
| 4A1 | [`step4a1/STEP4A1_REPORT.md`](step4a1/STEP4A1_REPORT.md) |
| 4A2 | [`step4a2/STEP4A2_REPORT.md`](step4a2/STEP4A2_REPORT.md) |
| 4B1 | [`step4b1/STEP4B1_REPORT.md`](step4b1/STEP4B1_REPORT.md) |
| 5A1 | [`step5a1/STEP5A1_REPORT.md`](step5a1/STEP5A1_REPORT.md) |
| 5A2 | [`step5a2/STEP5A2_REPORT.md`](step5a2/STEP5A2_REPORT.md) |
