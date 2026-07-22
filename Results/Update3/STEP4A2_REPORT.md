# Step 4A2 — llvm-mca CPU cost comparison (`@combine_and_pshufb`)

## Method

| Setting | Value |
|---------|-------|
| Tool | LLVM **17.0.6** `build-x86/bin/llvm-mca` |
| Triple | `x86_64-unknown` |
| Iterations | **1000** (same for all runs) |
| CPUs | `haswell`, `skylake`, `znver1` |
| Regions compared | Baseline: `vpxor` + `vpblendw`; Patched: `vpshufb` RIP-relative mask; **`retq` excluded** |

Inputs: [`inputs/`](inputs/). Raw outputs: [`raw/`](raw/). Commands: [`commands.log`](commands.log).

---

## `$0xEE` vs `$0x11` — measured encoding difference

### Measured facts

| Source | `vpblendw` immediate | Operand order (AT&T) |
|--------|----------------------|----------------------|
| Step 4A1 / LLVM 17 `llc` (`x86_64-unknown` ELF) | **`$238` (`0xEE`)** | `$238, %ymm1, %ymm0, %ymm0` (zero in `%ymm1`) |
| Earlier Apple-clang / Mach-O baselines | **`$17` (`0x11`)** | `$17, %ymm0, %ymm1, %ymm0` (zero in `%ymm1`) |
| Same mask via `analyze_shuffle_mask` / variant A reproducer | **`$17`** | `$17, %ymm0, %ymm1, %ymm0` |

Both forms carry the **same LLVM shuffle comment**:
`ymm0 = ymm0[0],ymm1[1,2,3],ymm0[4],ymm1[5,6,7],...`

### Interpretation

`VPBLENDW` selects each 16-bit field from one of two sources using an 8-bit immediate mask (bit *i* selects the first or second source operand in Intel’s encoding). When the two source operands are **swapped**, the immediate must be ** bitwise complemented** to preserve semantics:

```
0x11 XOR 0xFF = 0xEE   (17 XOR 255 = 238)
```

So `$17, %ymm0, %ymm1` (zero vector in `%ymm1`) is semantically equivalent to `$238, %ymm1, %ymm0`.

**llvm-mca confirmation:** `baseline` and `baseline_equiv_17` produce **identical** cycle/uOp totals on all three CPUs (see `comparison.json`). Step 4A1’s `$0xEE` baseline is the correct MCA input for the ELF object measured in Step 4A1.

---

## llvm-mca summary (1000 iterations)

See [`comparison_table.md`](comparison_table.md).

| CPU | Baseline cycles | Patched cycles | Δ cycles | Baseline uOps | Patched uOps | Baseline IPC | Patched IPC | Baseline block RThroughput | Patched block RThroughput | Baseline ≤ patched? |
|-----|-----------------|----------------|----------|---------------|--------------|--------------|-------------|----------------------------|---------------------------|---------------------|
| Haswell | 1003 | 1010 | +7 | 2000 | 2000 | 1.99 | 0.99 | 1.0 | 1.0 | Yes |
| Skylake | 1003 | 1010 | +7 | 2000 | 2000 | 1.99 | 0.99 | 1.0 | 1.0 | Yes |
| AMD Zen (znver1) | 1004 | 1009 | +5 | 3000 | 2000 | 1.99 | 0.99 | 0.8 | 1.0 | Yes |

### Per-instruction detail

#### Haswell — baseline

| Instruction | uOps | Latency | RThroughput | MayLoad |
|-------------|------|---------|-------------|---------|
| `vpxor	%xmm1, %xmm1, %xmm1` | 1 | 0 | 0.25 | No |
| `vpblendw	$238, %ymm1, %ymm0, %ymm0` | 1 | 1 | 1.0 | No |

#### Haswell — patched

| Instruction | uOps | Latency | RThroughput | MayLoad |
|-------------|------|---------|-------------|---------|
| `vpshufb	.LCPI0_0(%rip), %ymm0, %ymm0` | 2 | 8 | 1.0 | Yes |

#### Skylake — baseline

| Instruction | uOps | Latency | RThroughput | MayLoad |
|-------------|------|---------|-------------|---------|
| `vpxor	%xmm1, %xmm1, %xmm1` | 1 | 0 | 0.17 | No |
| `vpblendw	$238, %ymm1, %ymm0, %ymm0` | 1 | 1 | 1.0 | No |

#### Skylake — patched

| Instruction | uOps | Latency | RThroughput | MayLoad |
|-------------|------|---------|-------------|---------|
| `vpshufb	.LCPI0_0(%rip), %ymm0, %ymm0` | 2 | 8 | 1.0 | Yes |

#### AMD Zen (znver1) — baseline

| Instruction | uOps | Latency | RThroughput | MayLoad |
|-------------|------|---------|-------------|---------|
| `vpxor	%xmm1, %xmm1, %xmm1` | 1 | 1 | 0.25 | No |
| `vpblendw	$238, %ymm1, %ymm0, %ymm0` | 2 | 1 | 0.67 | No |

#### AMD Zen (znver1) — patched

| Instruction | uOps | Latency | RThroughput | MayLoad |
|-------------|------|---------|-------------|---------|
| `vpshufb	.LCPI0_0(%rip), %ymm0, %ymm0` | 2 | 8 | 1.0 | Yes |

---

## Question checklist

| # | Topic | Finding |
|---|-------|---------|
| 1 | Instruction / uOp counts | Baseline: **2 instructions**, **2 uOps/iter** (Intel) or **3 uOps/iter** (znver1 blend expansion). Patched: **1 instruction**, **2 uOps/iter** (1 load + 1 shuffle). |
| 2 | Latency | Baseline bottleneck: `vpblendw` latency **1**. Patched: `vpshufb` reported latency **8** (memory form). |
| 3 | Reciprocal throughput | Baseline block RThroughput **1.0** (Intel), **0.8** (znver1). Patched block RThroughput **1.0** on all CPUs. |
| 4 | Port pressure | Baseline: `vpblendw` on port 5 (Skylake/HW). Patched: load split across ports 2+3 (**0.5 each**) plus shuffle on port 5. |
| 5 | `vpxor` zero idiom | **Haswell/Skylake:** latency **0**, no port pressure row (llvm-mca treats as eliminated/zero-idom). **znver1:** latency **1**, **1 uOp**, FPU pipe pressure — **not** fully eliminated. |
| 6 | `vpshufb` memory uOp cost | **2 uOps**, **MayLoad=Yes**, load ports + shuffle port; models a **RIP-relative 32-byte mask** fetch each iteration. |
| 7 | L1 cache assumption | llvm-mca's default memory model assumes **tight-loop locality**; repeated `(%rip)` access to `.LCPI0_0` is modeled as **L1-resident** (not explicit DRAM latency). |
| 8 | CPUs where baseline ≥ patched | **All three tested CPUs** (Haswell, Skylake, znver1): baseline total cycles **≤** patched (+7, +7, +5 cycles). |

---

## Interpretation

- **Static / ISA level:** patched removes one instruction (Step 4A1).
- **llvm-mca microarch estimate (this isolated loop, L1-resident mask):** baseline **`vpxor`+`vpblendw` is equal or slightly better** than patched **`vpshufb`+load** on every CPU tested.
- Patched path pays an explicit **load port** tax that baseline avoids; `vpblendw` uses an **immediate** blend mask.
- On Intel models, `vpxor` zeroing is essentially free in the dependency chain; on **znver1** it still costs **1 uOp** and FPU pipes.

**Strongest defensible performance conclusion for the report:**

> For the isolated `@combine_and_pshufb` kernel, LLVM 17 `llvm-mca` estimates that the **patched single-`vpshufb` sequence does not improve throughput** relative to the baseline **`vpxor`+`vpblendw`** sequence on Haswell, Skylake, or Zen1 when the 32-byte control mask is served from L1. The patch’s primary verified win in this project remains **static instruction count and object-layout simplification in the hot `.text` slice** (Step 4A1), **not** a universally predicted runtime speedup. Any real-world benefit would require measurement in full calling context (inlining, I-cache effects, surrounding port pressure, mask residency) and must not be extrapolated from this MCA slice alone.

---

## Limitations

- **llvm-mca estimates ≠ measured runtime.** No hardware benchmarks were run in Step 4A2.
- Isolated two/one-instruction loop; no prologue/epilogue, no surrounding DAG neighbors.
- Assumes `%ymm0` input is ready; no register-pressure comparison.
- Default load latency model favors **repeated constant-pool access in a tight loop** (L1 hit). Cold I-cache / first-touch mask cost not represented.
- Zen model is **`znver1`** (first-gen Zen) — newer Zen cores may differ.
- Did **not** modify the LLVM patch or lit tests.

## Artifacts

| Path | Description |
|------|-------------|
| [`comparison_table.md`](comparison_table.md) | Summary table |
| [`comparison.json`](comparison.json) | Parsed metrics |
| [`inputs/baseline.s`](inputs/baseline.s) | MCA input (ELF `$238` form) |
| [`inputs/baseline_equiv_17.s`](inputs/baseline_equiv_17.s) | Equivalent `$17` form |
| [`inputs/patched.s`](inputs/patched.s) | MCA input (patched) |
| [`raw/*.txt`](raw/) | Full llvm-mca stdout |
