# CMPT 980 — Update 3: LLVM backend patch for sparse AVX2 shuffles

**Arezoo Salarpour**

Goal: patch LLVM 17.0.6 X86 lowering so sparse zero-fill `shufflevector` variants **A** and **C** emit **1× `vpshufb`** (instead of `vpxor` + `vpblendw`), while **B** stays **1× `vpshufb`**.

Repository root entry point: [`../README.md`](../README.md).  
Exact file lists and dependency table: [`REPOSITORY.md`](REPOSITORY.md).

| Step | Status | Description |
|------|--------|-------------|
| **1** | Complete | Unpatched baseline + `lit_x64_avx2.s` for Step 3C compare |
| **2** | Complete | Patched llc before/after + semantic verify |
| **3C** | Complete | FileCheck updates, broader tests, 71-function compare |
| **4A1** | Complete | Static code / object-size comparison |
| **4A2** | Complete | llvm-mca CPU cost comparison |
| **4B1** | Complete | AVX2 encoding alternatives and mask-reuse investigation |
| **4B2** | Pending | Selective blend-aware pre-widen (not implemented) |
| **5A1** | Complete | AVX2 shuffle helper overlap map (analysis-only) |
| **5A2** | Complete | Missed-lowering search (no implementable miss found) |

Steps 3A / 3B1–3B3 were intermediate only. The final workflow does **not** use those scripts or their result folders.

---

## Quick links

| Item | Location |
|------|----------|
| Repo contents / deps | [`REPOSITORY.md`](REPOSITORY.md) |
| Results index | [`../results/update3/README.md`](../results/update3/README.md) |
| Step 1 report | [`../results/update3/baseline/BASELINE_SUMMARY.md`](../results/update3/baseline/BASELINE_SUMMARY.md) |
| Step 2 report | [`../results/update3/patched/PATCHED_SUMMARY.md`](../results/update3/patched/PATCHED_SUMMARY.md) |
| Step 3C report | [`../results/update3/step3c/STEP3C_REPORT.md`](../results/update3/step3c/STEP3C_REPORT.md) |
| Step 4A1 report | [`../results/update3/step4a1/STEP4A1_REPORT.md`](../results/update3/step4a1/STEP4A1_REPORT.md) |
| Step 4A2 report | [`../results/update3/step4a2/STEP4A2_REPORT.md`](../results/update3/step4a2/STEP4A2_REPORT.md) |
| Step 4B1 report | [`../results/update3/step4b1/STEP4B1_REPORT.md`](../results/update3/step4b1/STEP4B1_REPORT.md) |
| Step 5A1 report | [`../results/update3/step5a1/STEP5A1_REPORT.md`](../results/update3/step5a1/STEP5A1_REPORT.md) |
| Step 5A2 report | [`../results/update3/step5a2/STEP5A2_REPORT.md`](../results/update3/step5a2/STEP5A2_REPORT.md) |
| Canonical LLVM patch | [`../results/update3/step3c/X86ISelLowering.patch`](../results/update3/step3c/X86ISelLowering.patch) |
| Lit FileCheck patch | [`../results/update3/step3c/vector-shuffle-combining-avx2.ll.patch`](../results/update3/step3c/vector-shuffle-combining-avx2.ll.patch) |

---

## Environment (required — no silent same-binary defaults)

```bash
# Stock LLVM 17.0.6 build (NO project patch)
export LLVM_UNPATCHED_LLC=/path/to/unpatched/bin/llc

# After applying canonical patches and rebuilding the patched tree:
export LLVM_PATCHED_LLC=/path/to/patched/bin/llc
export LLVM_FILECHECK=/path/to/patched/bin/FileCheck
export LLVM_MCA=/path/to/patched/bin/llvm-mca

# Optional: where lit tests live (read-only; scripts never stash/rebuild)
export LLVM_PROJECT=/path/to/patched-llvm-project
export LIT_TEST=$LLVM_PROJECT/llvm/test/CodeGen/X86/vector-shuffle-combining-avx2.ll
```

Helpers: [`common.sh`](common.sh). Scripts fail if these variables are unset or if unpatched/patched llc resolve to the same file (unless `ALLOW_SAME_LLC=1`).

---

## Reproduce (clean checkout — correct order)

```bash
# --- A. Unpatched baseline FIRST (before applying project patches) ---
export LLVM_UNPATCHED_LLC=/path/to/unpatched/bin/llc
./update3/step1_baseline.sh
# → results/update3/baseline/sparse_variant_{a,b,c}.s
# → results/update3/baseline/lit_x64_avx2.s   (required by Step 3C)

# --- B. Apply canonical patches to the PATCHED LLVM tree, then rebuild ---
cd /path/to/patched-llvm-project
git apply /path/to/repo/results/update3/step3c/X86ISelLowering.patch
git apply /path/to/repo/results/update3/step3c/vector-shuffle-combining-avx2.ll.patch
ninja -C build-x86 llc FileCheck llvm-mca

# --- C. Configure patched tools ---
export LLVM_PATCHED_LLC=/path/to/patched/bin/llc
export LLVM_FILECHECK=/path/to/patched/bin/FileCheck
export LLVM_MCA=/path/to/patched/bin/llvm-mca
export LLVM_PROJECT=/path/to/patched-llvm-project

# --- D. Patched validation and analysis ---
cd /path/to/repo
./update3/step2_patched.sh
./update3/step3c_finalize.sh    # fails clearly if baseline/lit_x64_avx2.s is missing
./update3/step4a1_measure.sh
./update3/step4a2_mca.sh
./update3/step4b1_investigate.sh
./update3/step5a2_investigate.sh
```

Do **not** apply the patch first and expect Step 1 to stash it. Step 1 never modifies the LLVM tree.

Semantic verification uses **`../tests/verify_patched_codegen.c`** (Steps 2 and 3C).

---

## Outcome summary

| Variant | Unpatched (Step 1) | Patched (Step 2) | Performance note (Steps 4A2/4B1) |
|---------|-------------------|------------------|--------------------------------|
| **A** | `vpxor` + `vpblendw $17` | **1× `vpshufb`** | Blend cheaper in llvm-mca for this mask |
| **B** | 1× `vpshufb` | 1× `vpshufb` (unchanged) | Already optimal |
| **C** | `vpxor` + `vpblendw $170` | **1× `vpshufb`** | Blend cheaper in llvm-mca for this mask |

---

## Directory layout (final workflow)

```
update3/
  README.md                 this file
  REPOSITORY.md             mandatory/optional upload lists + dependency table
  common.sh                 require LLVM_UNPATCHED_LLC / LLVM_PATCHED_LLC
  step1_baseline.sh         unpatched llc → baseline/lit_x64_avx2.s
  step2_patched.sh          patched llc + verify_patched_codegen.c
  step3c_finalize.sh        lit tests + step3c_compare.py
  step3c_compare.py
  step4a1_measure.sh / step4a1_analyze.py
  step4a2_mca.sh / step4a2_analyze.py
  step4b1_investigate.sh / step4b1_mca_sweep.py / step4b1_report.py
  step5a2_investigate.sh / step5a2_search.py / step5a2_report.py
  tools/analyze_shuffle_mask.cpp   optional

results/update3/
  step3c/X86ISelLowering.patch                      commit (canonical)
  step3c/vector-shuffle-combining-avx2.ll.patch     commit (canonical)
  baseline/*.s , step3c/asm/ , …                    regenerate; do not commit

tests/
  update2_sparse_variant_{a,b,c}.ll
  update2_combine_and_pshufb.ll
  step4a1_combine_and_pshufb.ll
  verify_patched_codegen.c
```
