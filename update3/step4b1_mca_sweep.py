#!/usr/bin/env python3
"""Generate Step 4B1 MCA sweep inputs and summary."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

MASK_A = (
    "0, 1, 255, 255, 255, 255, 255, 255, "
    "8, 9, 255, 255, 255, 255, 255, 255, "
    "0, 1, 255, 255, 255, 255, 255, 255, "
    "8, 9, 255, 255, 255, 255, 255, 255"
)
# vpand byte mask: FF at keep bytes 0,1,8,9 per lane
AND_MASK = (
    "255, 255, 0, 0, 0, 0, 0, 0, "
    "255, 255, 0, 0, 0, 0, 0, 0, "
    "255, 255, 0, 0, 0, 0, 0, 0, "
    "255, 255, 0, 0, 0, 0, 0, 0"
)

CPUS = ["haswell", "skylake", "znver1"]
N_SHUFFLES = [1, 2, 4, 8, 16]


def pool(name: str, bytes_csv: str) -> str:
    vals = [x.strip() for x in bytes_csv.split(",")]
    lines = ["	.section .rodata.cst32,\"aM\",@progbits,32", "	.p2align 5", f"{name}:"]
    for v in vals:
        lines.append(f"	.byte {v}")
    lines.append("	.text")
    return "\n".join(lines)


def blend_block(n: int, hoisted_zero: bool) -> str:
    lines: list[str] = []
    if hoisted_zero:
        lines.append("	vpxor	%xmm1, %xmm1, %xmm1")
    for i in range(n):
        if not hoisted_zero:
            lines.append("	vpxor	%xmm1, %xmm1, %xmm1")
        lines.append("	vpblendw	$238, %ymm1, %ymm0, %ymm0")
    return "\n".join(lines)


def pshufb_mem_block(n: int) -> str:
    return "\n".join(
        ["	vpshufb	.LCPI0_0(%rip), %ymm0, %ymm0" for _ in range(n)]
    )


def pshufb_reg_block(n: int, hoisted: bool) -> str:
    lines: list[str] = []
    if hoisted:
        lines.append("	vmovdqa	.LCPI0_0(%rip), %ymm7")
    for _ in range(n):
        if not hoisted:
            lines.append("	vmovdqa	.LCPI0_0(%rip), %ymm7")
        lines.append("	vpshufb	%ymm7, %ymm0, %ymm0")
    return "\n".join(lines)


def vpand_mem_block(n: int, hoisted: bool) -> str:
    lines: list[str] = []
    if hoisted:
        lines.append("	vmovdqa	.LAND0(%rip), %ymm7")
    for _ in range(n):
        if not hoisted:
            lines.append("	vmovdqa	.LAND0(%rip), %ymm7")
        lines.append("	vpand	%ymm7, %ymm0, %ymm0")
    return "\n".join(lines)


def write_input(path: Path, body: str, pools: list[str]) -> None:
    content = "\n".join(pools + ["	.globl	mca_region", "mca_region:"]) + "\n" + body + "\n"
    path.write_text(content)


def parse_mca(text: str) -> dict:
    out: dict = {}
    for key, pat in {
        "total_cycles": r"^Total Cycles:\s+(\d+)",
        "total_uops": r"^Total uOps:\s+(\d+)",
        "ipc": r"^IPC:\s+([0-9.]+)",
        "block_rthroughput": r"^Block RThroughput:\s+([0-9.]+)",
    }.items():
        m = re.search(pat, text, re.MULTILINE)
        if m:
            out[key] = float(m.group(1)) if "." in m.group(1) else int(m.group(1))
    return out


def main() -> None:
    out_dir = Path(sys.argv[1])
    mca = Path(sys.argv[2])
    inputs = out_dir / "inputs"
    raw = out_dir / "mca_sweep"
    inputs.mkdir(parents=True, exist_ok=True)
    raw.mkdir(parents=True, exist_ok=True)

    pools_a = [pool(".LCPI0_0", MASK_A)]
    pools_and = [pool(".LCPI0_0", MASK_A), pool(".LAND0", AND_MASK)]

    scenarios: list[tuple[str, str, list[str]]] = []

    # Single-shot encodings
    scenarios.append(
        (
            "single_blend_hoisted_zero",
            blend_block(1, True),
            pools_a[:1],
        )
    )
    scenarios.append(("single_pshufb_mem", pshufb_mem_block(1), pools_a[:1]))
    scenarios.append(("single_pshufb_reg", pshufb_reg_block(1, True), pools_a[:1]))
    scenarios.append(("single_vpand_mem", vpand_mem_block(1, True), pools_and))

    for n in N_SHUFFLES:
        scenarios.append((f"blend_n{n}_hoisted", blend_block(n, True), pools_a[:1]))
        scenarios.append((f"pshufb_mem_n{n}", pshufb_mem_block(n), pools_a[:1]))
        scenarios.append((f"pshufb_reg_n{n}_hoisted", pshufb_reg_block(n, True), pools_a[:1]))
        scenarios.append((f"vpand_n{n}_hoisted", vpand_mem_block(n, True), pools_and))

    results: dict = {}
    commands: list[str] = []
    for name, body, pools in scenarios:
        path = inputs / f"{name}.s"
        write_input(path, body, pools)
        results[name] = {}
        for cpu in CPUS:
            cmd = [
                str(mca),
                "-mtriple=x86_64-unknown",
                f"-mcpu={cpu}",
                "-iterations=1000",
                str(path),
            ]
            commands.append(" ".join(cmd))
            proc = subprocess.run(cmd, capture_output=True, text=True)
            (raw / f"{name}_{cpu}.txt").write_text(proc.stdout)
            results[name][cpu] = parse_mca(proc.stdout)

    # Find crossover: pshufb_reg vs blend per cpu (skylake primary)
    crossovers: dict = {}
    for cpu in CPUS:
        threshold = None
        for n in N_SHUFFLES:
            b = results[f"blend_n{n}_hoisted"][cpu]["total_cycles"]
            p = results[f"pshufb_reg_n{n}_hoisted"][cpu]["total_cycles"]
            if p < b:
                threshold = n
                break
        crossovers[cpu] = threshold

    single_skylake = {
        k: results[k]["skylake"]
        for k in (
            "single_blend_hoisted_zero",
            "single_pshufb_mem",
            "single_pshufb_reg",
            "single_vpand_mem",
        )
    }

    (out_dir / "mca_sweep.json").write_text(json.dumps(results, indent=2) + "\n")
    (out_dir / "mca_commands.log").write_text("\n".join(commands) + "\n")

    md = ["| Scenario | n | Haswell cycles | Skylake cycles | znver1 cycles |",
          "|----------|---|----------------|----------------|---------------|"]
    for n in N_SHUFFLES:
        for kind, prefix in (
            ("blend", "blend_n"),
            ("pshufb mem", "pshufb_mem_n"),
            ("pshufb reg", "pshufb_reg_n"),
            ("vpand", "vpand_n"),
        ):
            key = f"{prefix}{n}_hoisted" if kind != "pshufb mem" else f"{prefix}{n}"
            if key not in results:
                key = f"{prefix}{n}"
            row = results[key]
            md.append(
                f"| {kind} | {n} | {row['haswell']['total_cycles']} | "
                f"{row['skylake']['total_cycles']} | {row['znver1']['total_cycles']} |"
            )

    (out_dir / "mca_sweep_table.md").write_text("\n".join(md) + "\n")

    summary = {
        "single_shot_skylake": single_skylake,
        "crossover_pshufb_reg_beats_blend": crossovers,
    }
    (out_dir / "mca_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
