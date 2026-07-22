# Step 3C — Finalize LLVM regression tests (Step 3B3 patch)

## Summary

| Item | Result |
|------|--------|
| Primary lit test (`vector-shuffle-combining-avx2.ll`) — 4 RUN configs | **PASS** (4/4) |
| 71-function asm compare vs unpatched baseline | **1 changed**, **70 unchanged** |
| Intended-only change (`@combine_and_pshufb`) | **PASS** |
| Broader X86 vector-shuffle tests | **PASS** (3 files; `avx2-shuffle.ll` absent in tree) |
| A/B/C semantic verification | **PASS** (all MATCH) |
| **Step 3 complete / ready for Step 4** | **YES** |

---

## Tests added or updated

### Updated CHECK (existing function)

| Function | Change |
|----------|--------|
| `@combine_and_pshufb` | Requires exactly **1× `vpshufb`**; **`CHECK-NOT`** for `vpxor`, `vpand`, `vpblendw` |

### New lit functions (5)

| Function | Purpose |
|----------|---------|
| `@sparse_identity_or_zero_variant_a` | Variant A sparse identity-or-zero mask → 1× `vpshufb`, no blend/xor/and |
| `@sparse_identity_or_zero_variant_b` | Variant B unchanged sparse path → 1× `vpshufb` |
| `@sparse_identity_or_zero_variant_c` | Variant C sparse identity-or-zero mask → 1× `vpshufb` |
| `@sparse_one_zero_word_pair_per_lane` | Only one zero i16 pair/lane: pre-widen still applies (1× `vpshufb`); sparse combine guard (≥2 pairs) not required |
| `@sparse_two_source_cross_lane` | Two-source cross-lane shuffle → **`vpblendw`** path, not single-source sparse fold |

### Confirmed unchanged (existing CHECK retained)

| Function | Expected lowering |
|----------|-------------------|
| `@combine_pshufb_and` | `vpxor` + `vpblendw` (reverse operand order) |
| `@combine_pshufb_as_vzmovl_32` | `vxorps` + `vblendps` |
| `@combine_pshufb_as_vzmovl_64` | `vmovq` |

Lit test diff: [`vector-shuffle-combining-avx2.ll.patch`](vector-shuffle-combining-avx2.ll.patch)

---

## Commands and pass/fail results

### Build / patch artifacts

```bash
git -C ~/llvm-project diff HEAD -- llvm/lib/Target/X86/X86ISelLowering.cpp \
  > results/update3/step3c/X86ISelLowering.patch
```

### Primary lit — 4 RUN configurations

```bash
LLC=~/llvm-project/build-x86/bin/llc
FC=~/llvm-project/build-x86/bin/FileCheck
TEST=~/llvm-project/llvm/test/CodeGen/X86/vector-shuffle-combining-avx2.ll

$LLC < $TEST -mtriple=i686-unknown -mattr=+avx2 -o /tmp/out.s
$FC $TEST --check-prefixes=CHECK,X86,AVX2,X86-AVX2 < /tmp/out.s          # PASS

$LLC < $TEST -mtriple=i686-unknown -mattr=+avx512f -o /tmp/out.s
$FC $TEST --check-prefixes=CHECK,X86,AVX512,X86-AVX512 < /tmp/out.s      # PASS

$LLC < $TEST -mtriple=x86_64-unknown -mattr=+avx2 -o /tmp/out.s
$FC $TEST --check-prefixes=CHECK,X64,AVX2,X64-AVX2 < /tmp/out.s          # PASS

$LLC < $TEST -mtriple=x86_64-unknown -mattr=+avx512f -o /tmp/out.s
$FC $TEST --check-prefixes=CHECK,X64,AVX512,X64-AVX512 < /tmp/out.s      # PASS
```

Log: [`filecheck_runs.log`](filecheck_runs.log)

### Broader X86 vector-shuffle regression tests

| Test file | Result |
|-----------|--------|
| `vector-shuffle-combining-avx.ll` | PASS (6 RUN lines) |
| `vector-shuffle-256-v32.ll` | PASS (12 RUN lines) |
| `vector-shuffle-combining.ll` | PASS (7 RUN lines) |
| `avx2-shuffle.ll` | SKIP (not present in LLVM 17.0.6 tree) |

Log: [`broader_runs.log`](broader_runs.log)

### Semantic verification (A/B/C)

```bash
./update3/step3c_finalize.sh   # semantic section
# or manually:
LLC=~/llvm-project/build-x86/bin/llc
for v in a b c; do
  $LLC -O2 -mattr=+avx2 -mtriple=x86_64-apple-macos -filetype=obj \
    -o sparse_variant_${v}.o tests/update2_sparse_variant_${v}.ll
done
clang -target x86_64-apple-macos -mavx2 -O2 -o verify_patched_codegen \
  tests/verify_patched_codegen.c sparse_variant_*.o
arch -x86_64 ./verify_patched_codegen
```

Result: **PASS** — see [`semantic/verify.log`](semantic/verify.log)

### 71-function comparison

```bash
python3 update3/step3c_compare.py results/update3/step3c
```

Result: **1 changed** (`combine_and_pshufb`), **70 unchanged**. Data: [`step3c_compare.json`](step3c_compare.json)

---

## Problems found

1. **Initial semantic harness attempt** tried to `clang -c` GNU `.s` text on macOS host — failed on inline `#` comments. **Fixed** by using `llc -filetype=obj` + `arch -x86_64` (same as Step 2).
2. **`avx2-shuffle.ll`** not present in this LLVM checkout — skipped, not a failure.
3. No other test failures or unexpected codegen changes.

---

## Final assembly for the target (`@combine_and_pshufb`, x86_64 + AVX2)

```
combine_and_pshufb:
	vpshufb	.LCPI4_0(%rip), %ymm0, %ymm0
	retq
```

Full snippet: [`asm/combine_and_pshufb.s`](asm/combine_and_pshufb.s)

Before (unpatched baseline): `vpxor` + `vpblendw $17`.

---

## Final patch scope

| Component | Lines | Description |
|-----------|-------|-------------|
| `llvm/lib/Target/X86/X86ISelLowering.cpp` | +292 / −? (net helpers + pre-widen + narrowed combine guard) | Step 3B3 narrowed patch only |
| `llvm/test/CodeGen/X86/vector-shuffle-combining-avx2.ll` | +89 | Step 3C CHECK updates + 5 new tests |

Backend patch artifact: [`X86ISelLowering.patch`](X86ISelLowering.patch) (346 lines)

**Scope unchanged from Step 3B3:** helpers (`isZmovlStyle*`, `isInLaneIdentityOrZero*`, `isSparseInLane*`), pre-widen path for identity-or-zero byte-pair shuffles, narrowed depth-0 combine early-exit for sparse PSHUFB masks only.

---

## Step 3 completion status

| Step | Status |
|------|--------|
| 3A — regression probe | Complete |
| 3B1 — component isolation | Complete |
| 3B2 — narrowed structural predicate | Complete |
| 3B3 — vpand elimination | Complete |
| **3C — FileCheck + broader tests + semantic + 71-fn compare** | **Complete** |

**Step 3 is fully complete and ready for Step 4** (performance evaluation / presentation — not started per instructions).

---

## Artifact index

| File | Description |
|------|-------------|
| `X86ISelLowering.patch` | Final tested backend patch |
| `vector-shuffle-combining-avx2.ll.patch` | Lit test CHECK + new functions |
| `commands.log` | All validation commands |
| `filecheck_runs.log` | 4/4 PASS |
| `broader_runs.log` | Broader test results |
| `semantic/verify.log` | A/B/C MATCH |
| `step3c_compare.json` | 71-function compare data |
| `asm/*.s` | Per-function assembly snippets |
