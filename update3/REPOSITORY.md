# Update 3 — repository contents and reproducibility

This document lists what belongs in the **final GitHub repository**, script
dependencies, and the clean-checkout workflow.

Root entry: [`../README.md`](../README.md). Hub: [`README.md`](README.md).

## Critical reproducibility rules

1. **Separate llc binaries.** `LLVM_UNPATCHED_LLC` and `LLVM_PATCHED_LLC` must be
   configured explicitly. `common.sh` does **not** default them to the same path.
2. **Step 1 never stashes or rebuilds.** It only uses `LLVM_UNPATCHED_LLC`.
3. **Canonical patch is read-only.** Scripts must not overwrite
   `results/update3/step3c/X86ISelLowering.patch`. Optional worktree diffs go to
   `*/generated/current_worktree.patch` (do not commit).
4. **Step 3C input:** `results/update3/baseline/lit_x64_avx2.s` from Step 1.
   Missing → hard error.

---

## Exact final repository tree

```
.
├── README.md                              # MANDATORY — root entry
├── update3/
│   ├── README.md                          # MANDATORY — Update 3 hub
│   ├── REPOSITORY.md                      # MANDATORY — this file
│   ├── common.sh                          # MANDATORY
│   ├── STEP3_PLAN.md                      # optional
│   ├── step1_baseline.sh                  # MANDATORY
│   ├── step2_patched.sh                   # MANDATORY
│   ├── step3c_finalize.sh                 # MANDATORY
│   ├── step3c_compare.py                  # MANDATORY
│   ├── step4a1_measure.sh                 # MANDATORY
│   ├── step4a1_analyze.py                 # MANDATORY
│   ├── step4a2_mca.sh                     # MANDATORY
│   ├── step4a2_analyze.py                 # MANDATORY
│   ├── step4b1_investigate.sh             # MANDATORY
│   ├── step4b1_mca_sweep.py               # MANDATORY
│   ├── step4b1_report.py                  # MANDATORY
│   ├── step5a2_investigate.sh             # MANDATORY
│   ├── step5a2_search.py                  # MANDATORY
│   ├── step5a2_report.py                  # MANDATORY
│   └── tools/
│       └── analyze_shuffle_mask.cpp       # OPTIONAL
├── tests/
│   ├── update2_sparse_variant_a.ll        # MANDATORY
│   ├── update2_sparse_variant_b.ll        # MANDATORY
│   ├── update2_sparse_variant_c.ll        # MANDATORY
│   ├── update2_combine_and_pshufb.ll      # MANDATORY
│   ├── step4a1_combine_and_pshufb.ll      # MANDATORY
│   └── verify_patched_codegen.c           # MANDATORY
└── results/update3/
    ├── README.md                          # MANDATORY
    ├── baseline/*.md                      # optional reports
    ├── patched/*.md                       # optional reports
    ├── step3c/
    │   ├── STEP3C_REPORT.md               # optional
    │   ├── X86ISelLowering.patch          # MANDATORY (canonical; never overwrite)
    │   └── vector-shuffle-combining-avx2.ll.patch  # MANDATORY
    ├── step4a1/STEP4A1_REPORT.md          # optional
    ├── step4a2/STEP4A2_REPORT.md          # optional
    ├── step4b1/STEP4B1_REPORT.md          # optional
    ├── step5a1/                           # optional analysis docs
    └── step5a2/STEP5A2_REPORT.md          # optional
```

### Exclude from final upload

| Path | Reason |
|------|--------|
| `update3/step3a_*`, `step3b1_*`, `step3b2_*`, `step3b3_*` | Intermediate |
| `results/update3/step3a/`, `step3b1/`, `step3b2/`, `step3b3/` | Intermediate |
| `update2/` | Not required for Update 3 workflow |
| `tests/verify_sparse_variants.c` | Not used by Update 3 scripts |
| Generated `.s`, `.o`, binaries, `work/`, `asm/`, `filecheck/`, `semantic*`, `generated/` | Regenerate locally |

---

## Clean-checkout workflow

```bash
# 1. Configure separate UNPATCHED llc; run Step 1
export LLVM_UNPATCHED_LLC=/path/to/unpatched/bin/llc
./update3/step1_baseline.sh

# 2. Apply BOTH canonical patches to the patched LLVM tree; rebuild tools
git -C /path/to/patched-llvm apply results/update3/step3c/X86ISelLowering.patch
git -C /path/to/patched-llvm apply results/update3/step3c/vector-shuffle-combining-avx2.ll.patch
ninja -C /path/to/patched-build llc FileCheck llvm-mca

# 3. Configure patched tools
export LLVM_PATCHED_LLC=/path/to/patched/bin/llc
export LLVM_FILECHECK=/path/to/patched/bin/FileCheck
export LLVM_MCA=/path/to/patched/bin/llvm-mca
export LLVM_PROJECT=/path/to/patched-llvm

# 4. Run Steps 2, 3C, 4, 5
./update3/step2_patched.sh
./update3/step3c_finalize.sh
./update3/step4a1_measure.sh
./update3/step4a2_mca.sh
./update3/step4b1_investigate.sh
./update3/step5a2_investigate.sh
```

---

## Dependency table

| Script | Repo inputs | Python | Verifier / tests | Prior generated | Order |
|--------|-------------|--------|------------------|-----------------|-------|
| `step1_baseline.sh` | `tests/update2_sparse_variant_{a,b,c}.ll`, `tests/update2_combine_and_pshufb.ll`; optional `tools/analyze_shuffle_mask.cpp`; optional lit patch (temp reverse only) | — | External `LIT_TEST` (read-only) | None; needs `LLVM_UNPATCHED_LLC` | **1** |
| `step2_patched.sh` | variant `.ll`, `verify_patched_codegen.c` | — | `verify_patched_codegen.c` | `baseline/sparse_variant_{a,b,c}.s`; `LLVM_PATCHED_LLC` | **2** |
| `step3c_finalize.sh` | lit in llvm-project; variant `.ll`; `verify_patched_codegen.c`; reads (does not write) canonical `.patch` | `step3c_compare.py` | `verify_patched_codegen.c` | **`baseline/lit_x64_avx2.s`**; `LLVM_PATCHED_LLC`, `LLVM_FILECHECK` | **3** |
| `step4a1_measure.sh` | `tests/step4a1_combine_and_pshufb.ll` | `step4a1_analyze.py` | — | Both llc env vars | **4** |
| `step4a2_mca.sh` | — (embeds asm) | `step4a2_analyze.py` | — | `LLVM_MCA` | **5** |
| `step4b1_investigate.sh` | — (embeds IR) | `step4b1_mca_sweep.py`, `step4b1_report.py` | — | Both llc + `LLVM_MCA` | **6** |
| `step5a2_investigate.sh` | — | `step5a2_search.py`, `step5a2_report.py` | — | `LLVM_UNPATCHED_LLC`, `LLVM_MCA` | **7** |

### Verifier

| File | Used? |
|------|-------|
| `tests/verify_patched_codegen.c` | **Yes** — Steps 2 and 3C |
| `tests/verify_sparse_variants.c` | **No** |

---

## Mandatory / optional / do-not-upload

### Mandatory (must exist in the upload)

- Root `README.md`
- `update3/{README,REPOSITORY,common}.sh` + all workflow scripts/helpers listed in the tree above
- `update3/step3c_compare.py`
- Listed `tests/*.ll` and `verify_patched_codegen.c`
- `results/update3/README.md`
- `results/update3/step3c/X86ISelLowering.patch`
- `results/update3/step3c/vector-shuffle-combining-avx2.ll.patch`

### Optional

- Report markdown under `results/update3/**`
- `update3/tools/analyze_shuffle_mask.cpp`
- `update3/STEP3_PLAN.md`
- `results/update3/step5a1/`

### Do not upload

- Generated asm/objects/binaries/`work/`/`generated/`
- `step3a` / `step3b*` scripts and result folders
- `update2/` (for Update-3-only upload)
