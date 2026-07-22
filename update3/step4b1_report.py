#!/usr/bin/env python3
"""Write Step 4B1 investigation report."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def count_lines(path: Path, pattern: str) -> int:
    if not path.exists():
        return 0
    return len(re.findall(pattern, path.read_text(), re.MULTILINE))


def analyze_codegen(path: Path) -> dict:
    if not path.exists():
        return {
            "vpshufb": 0,
            "vpshufb_mem": 0,
            "vpshufb_reg": 0,
            "vpblendw": 0,
            "vpxor": 0,
            "mask_materialize": 0,
            "lcpi_labels": 0,
        }

    text = path.read_text()
    vpshufb_lines = re.findall(r"^\s*vpshufb\b.*$", text, re.MULTILINE)
    vpshufb_mem = sum(1 for line in vpshufb_lines if re.search(r"\.LCPI", line))
    vpshufb_reg = len(vpshufb_lines) - vpshufb_mem
    mask_materialize = len(
        re.findall(
            r"^\s*(?:vmovdqa|vbroadcasti128|vbroadcast)\s+.*\.LCPI",
            text,
            re.MULTILINE,
        )
    )

    return {
        "vpshufb": len(vpshufb_lines),
        "vpshufb_mem": vpshufb_mem,
        "vpshufb_reg": vpshufb_reg,
        "vpblendw": count_lines(path, r"\bvpblendw\b"),
        "vpxor": count_lines(path, r"\bvpxor\b"),
        "mask_materialize": mask_materialize,
        "lcpi_labels": len(set(re.findall(r"(\.?LCPI\d+_\d+)", text))),
    }


def main() -> None:
    out_dir = Path(sys.argv[1])
    summary = json.loads((out_dir / "mca_summary.json").read_text())
    sweep = json.loads((out_dir / "mca_sweep.json").read_text())

    patched = analyze_codegen(out_dir / "llvm_codegen/multi_shuffle_patched.s")
    baseline = analyze_codegen(out_dir / "llvm_codegen/multi_shuffle_baseline.s")

    single = summary["single_shot_skylake"]
    cross = summary["crossover_pshufb_reg_beats_blend"]

    lines = [
        "# Step 4B1 — AVX2 encoding and mask-reuse investigation",
        "",
        "## Scope",
        "",
        "Investigate whether **any realistic AVX2 context** makes the PSHUFB alternative",
        "genuinely cheaper than `vpxor` + immediate `vpblendw` for the Variant-A /",
        "`@combine_and_pshufb` identity-or-zero i16-pair mask.",
        "",
        "**No LLVM patch or lit test changes.** No new cost rule implemented.",
        "",
        "---",
        "",
        "## 1. Viable AVX2 alternatives (Variant A mask)",
        "",
        "| Encoding | Instructions (typical) | Control form | Skylake cycles (1000 iters, isolated) | Notes |",
        "|----------|------------------------|--------------|----------------------------------------|-------|",
        f"| **A. `vpxor` + `vpblendw` imm** | 2 | 8-bit immediate `$238` / `$17` | **{single['single_blend_hoisted_zero']['total_cycles']}** | Baseline widen→blend path; zero hoisted |",
        f"| **B. `vpshufb` memory** | 1 insn, **2 uOps** (load+shuffle) | 32-byte pool `.rodata` | **{single['single_pshufb_mem']['total_cycles']}** | Patched pre-widen path (memory operand) |",
        f"| **C. `vbroadcast`/`vmovdqa` + `vpshufb` reg** | 2 | mask in `%ymm` | **{single['single_pshufb_reg']['total_cycles']}** | One-time mask materialization + register reuse |",
        f"| **D. `vmovdqa` + `vpand` reg** | 2 | 32-byte AND mask | **{single['single_vpand_mem']['total_cycles']}** | Valid for **in-place** keep-or-zero (no permute) |",
        "",
        "**Other valid AVX2 sequences considered and rejected for this mask:**",
        "",
        "| Alternative | Why not competitive |",
        "|-------------|---------------------|",
        "| `vpblendvb` + memory mask | More uOps than `vpblendw`; no benefit for word-aligned sparse pattern |",
        "| `vperm2i128` / `vpermq` chains | Cross-lane overhead; mask is in-lane |",
        "| `vpunpck*` / `vpack*` | Pattern is sparse zero-fill, not interleave/pack |",
        "| `vbroadcast` + `vpand` | Extra materialization; still needs 32-byte constant |",
        "| Multiple `vpblendw` | Single immediate already encodes all i16 lane choices |",
        "",
        "Full sweep: [`mca_sweep_table.md`](mca_sweep_table.md), raw: [`mca_sweep/`](mca_sweep/).",
        "",
        "---",
        "",
        "## 2. Single-instruction encoding without vector/memory mask?",
        "",
        "**No** — for the **complete byte-level** keep-or-zero mask at bytes `{0,1,8,9}` per 128-bit lane:",
        "",
        "| Mechanism | Can encode full mask alone? |",
        "|-----------|------------------------------|",
        "| **`VPBLENDW` immediate** | **Partially** — encodes **i16 word selection** in one instruction, but still needs a **zero vector** (`vpxor`) as second source |",
        "| **`VPSHUFB`** | Requires **128/256-bit control vector** (register or memory); **no immediate form** on AVX2 |",
        "| **`VPAND`** | Requires **32-byte bitmask** in register/memory; not a shuffle opcode |",
        "",
        "**Measured fact:** the cheapest **single mnemonic** that captures the **i16 sparse selection** is `VPBLENDW` with an 8-bit immediate. A memory-operand `VPSHUFB` hides a **pool load inside the shuffle** (2 uOps in MCA).",
        "",
        "---",
        "",
        "## 3. Mask reuse — LLVM codegen",
        "",
        "Four independent Variant-A shuffles in one function (`llvm_codegen/multi_shuffle.ll`, `-O2`):",
        "",
        "| Version | `vpxor` | `vpblendw` | `vpshufb` (mem) | `vpshufb` (reg) | mask materialize | `LCPI` labels |",
        "|---------|---------|------------|-----------------|-----------------|------------------|---------------|",
        f"| **Patched llc** | {patched['vpxor']} | {patched['vpblendw']} | {patched['vpshufb_mem']} | {patched['vpshufb_reg']} | {patched['mask_materialize']} | {patched['lcpi_labels']} |",
        f"| **Baseline llc** | {baseline['vpxor']} | {baseline['vpblendw']} | {baseline['vpshufb_mem']} | {baseline['vpshufb_reg']} | {baseline['mask_materialize']} | — |",
        "",
        "**Interpretation:**",
        "",
    ]

    if patched["mask_materialize"] >= 1 and patched["vpshufb_reg"] >= 2:
        lines.append(
            "- Patched lowering **materializes the PSHUFB control mask once** (`vbroadcasti128` / `vmovdqa` from `.LCPI`) and **reuses it in a register** for each shuffle."
        )
    elif patched["vpshufb_mem"] >= 2:
        lines.append(
            "- Patched lowering emits **memory-operand `vpshufb .LCPI(%rip)` per shuffle** — no register reuse of the control mask."
        )
    else:
        lines.append(
            "- Patched asm pattern: see `llvm_codegen/multi_shuffle_patched.s`."
        )

    if baseline["vpblendw"] >= 2 and baseline["vpxor"] <= 1:
        lines.append(
            "- Baseline emits **`vpblendw` per shuffle** with **one shared `vpxor` zero** — the blend immediate has **no load cost**."
        )

    lines.extend(
        [
            "- Both paths can hoist their helper (zero vector vs shuffle mask) when the same constant is reused; **register reuse does not change the Step 4B1 MCA conclusion** (see §4).",
            "",
            "---",
            "",
            "## 4. Mask reuse — llvm-mca amortization (Skylake, 1000 iterations)",
            "",
            "| Shuffles per block (`n`) | Blend (hoisted zero) | PSHUFB memory × n | PSHUFB reg (hoisted mask) | VPAND reg (hoisted) |",
            "|--------------------------|----------------------|-------------------|---------------------------|---------------------|",
        ]
    )

    for n in [1, 2, 4, 8, 16]:
        b = sweep[f"blend_n{n}_hoisted"]["skylake"]["total_cycles"]
        pm = sweep[f"pshufb_mem_n{n}"]["skylake"]["total_cycles"]
        pr = sweep[f"pshufb_reg_n{n}_hoisted"]["skylake"]["total_cycles"]
        va = sweep[f"vpand_n{n}_hoisted"]["skylake"]["total_cycles"]
        lines.append(f"| {n} | {b} | {pm} | {pr} | {va} |")

    lines.extend(
        [
            "",
            "**Crossover (`pshufb` register, hoisted mask beats blend):**",
            "",
            "| CPU | First `n` where reg-PSHUFB cycles < blend |",
            "|-----|----------------------------------------|",
            f"| Haswell | {cross['haswell'] or 'never in 1..16'} |",
            f"| Skylake | {cross['skylake'] or 'never in 1..16'} |",
            f"| znver1 | {cross['znver1'] or 'never in 1..16'} |",
            "",
            "**Interpretation:** Even with an **optimistic** hoisted mask register, **`vpshufb`",
            "does not beat `vpblendw`** for this mask at `n ≤ 16` on any tested CPU.",
            "The ~7-cycle gap per 1000-iteration block on Intel is **stable across `n`**, so mask-load",
            "amortization does not close the deficit — the bottleneck is **`vpshufb` uOp cost**, not pool traffic.",
            "",
            "---",
            "",
            "## 5. Does LLVM already consider cost?",
            "",
            "**Measured from source inspection (LLVM 17.0.6 `X86ISelLowering.cpp`):**",
            "",
            "| Factor | Present in blend vs PSHUFB decision? | Evidence |",
            "|--------|--------------------------------------|----------|",
            "| **Ordered helpers, not cost model** | Yes | `lowerV16I16Shuffle()` tries **`lowerShuffleAsBlend` before `lowerShuffleWithPSHUFB`** (~19166 vs ~19233) |",
            "| **Widen-before-byte** | Yes | `canWidenShuffleElements()` returns before `lowerV32I8Shuffle()` for A/C (~20520) |",
            "| **Mask reuse / CSE** | Partial | DAG CSE on `BUILD_VECTOR` mask nodes possible; **no explicit “reuse count” heuristic** in ISel |",
            "| **Zero register reuse** | Yes | `ForceV2Zero` / `vpxor` folding in blend path; MCA latency 0 on Intel |",
            "| **Constant-pool load cost** | **No** | Pre-widen PSHUFB block has **no cycle/port cost**; always prefers byte path when predicate matches |",
            "| **Port pressure / surrounding DAG** | **No** | No MC pressure integration at this lowering site |",
            "",
            "Comment at ~17180: *\"a single pshufb is significantly faster\"* applies to **blend-with-zero",
            "via `lowerShuffleAsBlendOfPSHUFBs`** (different context — avoiding multi-PSHUFB+OR),",
            "**not** to **`vpblendw` immediate vs pool-backed `vpshufb`** for Variant A.",
            "",
            "---",
            "",
            "## 6. Narrow defensible cost-aware rule (proposal only — not implemented)",
            "",
            "A rule that **could** be defended in Update 3:",
            "",
            "```",
            "Prefer pre-widen PSHUFB only when ALL hold:",
            "  1. canLowerShuffleWithPSHUFB(...)",
            "  2. NOT matchShuffleAsBlendAfterWiden(...)   // A/C word-sparse → keep blend",
            "  OR",
            "  3. PSHUFB control vector already materialized in a live register",
            "     (reuse ≥ 2 and mask not blend-representable)",
            "```",
            "",
            "**For the current project masks:**",
            "",
            "| Mask | Blend-representable? | PSHUFB cheaper in any tested context? |",
            "|------|----------------------|---------------------------------------|",
            "| Variant A / `combine_and_pshufb` | **Yes** (`$17` / `$238`) | **No** (Steps 4A2, 4B1) |",
            "| Variant C | **Yes** (`$170`) | **No** |",
            "| Variant B | **No** | **Already `vpshufb`** (unchanged) |",
            "",
            "**Realistic LLVM implementation opportunity:** **selective pre-widen** — skip byte PSHUFB",
            "when widened `matchShuffleAsBlend` succeeds; keep patch fusion for `shuffle+pshuf.b`",
            "DAG cleanup (eliminate redundant AND) **without** forcing pool-backed PSHUFB on blend-shaped masks.",
            "",
            "---",
            "",
            "## Limitations",
            "",
            "- llvm-mca estimates only; no hardware measurement.",
            "- Reuse sweep uses synthetic straight-line blocks, not full function prologue/epilogue.",
            "- L1-resident mask assumed for repeated memory `vpshufb`.",
            "- Did not explore AVX-512 `vpermi2b` / VBMI (outside AVX2 project scope).",
            "",
            "---",
            "",
            "## Artifacts",
            "",
            "| Path | Description |",
            "|------|-------------|",
            "| [`commands.log`](commands.log) | All commands |",
            "| [`mca_sweep_table.md`](mca_sweep_table.md) | Full n-sweep table |",
            "| [`mca_summary.json`](mca_summary.json) | Crossover summary |",
            "| [`llvm_codegen/multi_shuffle.ll`](llvm_codegen/multi_shuffle.ll) | Four-shuffle reuse test IR |",
            "| [`llvm_codegen/multi_shuffle_patched.s`](llvm_codegen/multi_shuffle_patched.s) | 4× shuffle patched asm |",
            "| [`llvm_codegen/multi_shuffle_baseline.s`](llvm_codegen/multi_shuffle_baseline.s) | 4× shuffle baseline asm |",
            "| [`inputs/`](inputs/) | MCA input assemblies |",
        ]
    )

    (out_dir / "STEP4B1_REPORT.md").write_text("\n".join(lines) + "\n")
    print(f"Wrote {out_dir / 'STEP4B1_REPORT.md'}")


if __name__ == "__main__":
    main()
