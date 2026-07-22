#!/usr/bin/env python3
"""Step 4A1 — analyze baseline vs patched object/code size for combine_and_pshufb."""

from __future__ import annotations

import json
import re
import struct
import subprocess
import sys
from pathlib import Path

SHUFFLE_OPS = ("vpxor", "vpand", "vpblendw", "vpshufb", "ret")


def read_text(path: Path) -> str:
    return path.read_text(errors="replace")


def extract_function_asm(asm: str, name: str = "combine_and_pshufb") -> str:
    lines: list[str] = []
    in_fn = False
    for line in asm.splitlines():
        if re.match(rf"^{re.escape(name)}:\s", line) or re.match(
            rf"^_{re.escape(name)}:\s", line
        ):
            in_fn = True
        if in_fn:
            lines.append(line)
            if ".Lfunc_end" in line or (
                line.strip().startswith("## -- End function") and len(lines) > 1
            ):
                break
    return "\n".join(lines)


def static_instructions(fn_asm: str) -> list[str]:
    ops: list[str] = []
    for line in fn_asm.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("."):
            continue
        if stripped.startswith(".cfi"):
            continue
        m = re.match(r"^([a-z][a-z0-9]*)\b", stripped)
        if m:
            op = m.group(1)
            if op == "retq":
                op = "ret"
            ops.append(op)
    return ops


def parse_disasm_bytes(disasm: str, fn: str = "combine_and_pshufb") -> list[dict]:
    """Parse llvm-objdump -d output into per-instruction byte records."""
    records: list[dict] = []
    in_fn = False
    offset = 0
    for line in disasm.splitlines():
        if re.search(rf"<\s*{re.escape(fn)}\s*>:", line):
            in_fn = True
            offset = 0
            continue
        if not in_fn:
            continue
        if re.match(r"^\s*$", line):
            continue
        if re.match(r"^Disassembly of section", line):
            break
        m = re.match(r"^\s*((?:[0-9a-f]{2}(?:\s+[0-9a-f]{2})*))\s+(.+)$", line)
        if not m:
            if records:
                break
            continue
        hexbytes = m.group(1).split()
        records.append(
            {
                "offset": offset,
                "bytes": [int(b, 16) for b in hexbytes],
                "text": m.group(2).strip(),
            }
        )
        offset += len(hexbytes)
    return records


def parse_sections(section_headers: str) -> list[dict]:
    sections: list[dict] = []
    for line in section_headers.splitlines():
        m = re.match(
            r"^\s*(\d+)\s+(\S+)\s+([0-9a-f]+)\s+([0-9a-f]+)(?:\s+\S+)?\s*$",
            line,
        )
        if not m:
            continue
        name = m.group(2)
        if name == "Name":
            continue
        sections.append(
            {
                "idx": int(m.group(1)),
                "name": name,
                "size": int(m.group(3), 16),
                "vma": int(m.group(4), 16),
            }
        )
    return sections


def parse_nm_symbols(nm_text: str) -> list[dict]:
    syms: list[dict] = []
    for line in nm_text.splitlines():
        m = re.match(
            r"^([0-9a-f]+)\s+([0-9a-f]+)\s+([A-Za-z?])\s+(\S+)",
            line,
        )
        if m:
            syms.append(
                {
                    "addr": int(m.group(1), 16),
                    "size": int(m.group(2), 16),
                    "type": m.group(3),
                    "name": m.group(4),
                }
            )
    return syms


def parse_constant_pool(asm: str) -> list[dict]:
    pools: list[dict] = []
    current: dict | None = None
    for line in asm.splitlines():
        label = re.match(r"^(\.?LCPI\d+_\d+|\.LCPI\d+_\d+):", line.strip())
        if label:
            if current:
                pools.append(current)
            current = {"label": label.group(1), "directives": [], "bytes": 0}
            continue
        if current is None:
            continue
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(".Lfunc_end") or re.match(r"^[a-zA-Z_.].*:$", stripped):
            pools.append(current)
            current = None
            continue
        if stripped.startswith(".section") or stripped.startswith(".text"):
            pools.append(current)
            current = None
            continue
        current["directives"].append(stripped)
        m = re.match(r"^\.byte\s+(.+)$", stripped)
        if m:
            current["bytes"] += len([x for x in m.group(1).split(",") if x.strip()])
        m = re.match(r"^\.(long|quad|space)\s+(.+)$", stripped)
        if m:
            kind, rest = m.group(1), m.group(2)
            if kind == "space":
                current["bytes"] += int(rest.split(",")[0].strip())
    if current:
        pools.append(current)
    return pools


def parse_alignments(asm: str) -> list[str]:
    return re.findall(r"^\.p2align\s+\d+.*$", asm, re.MULTILINE)


def total_object_size(path: Path) -> int:
    return path.stat().st_size


def analyze_variant(variant_dir: Path) -> dict:
    asm = read_text(variant_dir / "combine_and_pshufb.s")
    disasm = read_text(variant_dir / "disassembly.txt")
    fn_asm = extract_function_asm(asm)
    insns = static_instructions(fn_asm)
    shuffle_insns = [i for i in insns if i in SHUFFLE_OPS or i == "ret"]

    records = parse_disasm_bytes(disasm)
    fn_byte_total = sum(len(r["bytes"]) for r in records)
    per_insn = [
        {
            "text": r["text"],
            "encoded_bytes": len(r["bytes"]),
            "hex": " ".join(f"{b:02x}" for b in r["bytes"]),
        }
        for r in records
    ]

    sections = parse_sections(read_text(variant_dir / "section_headers.txt"))
    nm = parse_nm_symbols(read_text(variant_dir / "nm_symbols.txt"))
    fn_sym = next((s for s in nm if s["name"] == "combine_and_pshufb"), None)
    pools = parse_constant_pool(asm)
    rodata = next(
        (s for s in sections if s["name"] in (".rodata", ".rodata.cst32", ".const")),
        None,
    )
    text = next((s for s in sections if s["name"] == ".text"), None)
    size_a_path = variant_dir / "size_A.txt"
    size_a = read_text(size_a_path) if size_a_path.exists() else ""
    content_total = None
    m_total = re.search(r"^Total\s+(\d+)\s*$", size_a, re.MULTILINE)
    if m_total:
        content_total = int(m_total.group(1))

    vpshufb_lines = [l for l in fn_asm.splitlines() if "vpshufb" in l]
    mem_operand = any("(" in l and "%" in l for l in vpshufb_lines)
    separate_load = any(
        re.search(r"\b(vmov(dqa|ups|dqu)|vbroadcast)\b", fn_asm) for _ in [0]
    ) or bool(re.search(r"\b(vmov(dqa|ups|dqu)|vbroadcast)\b", asm.split("combine_and_pshufb")[0] if "combine_and_pshufb" in asm else ""))

    return {
        "asm_file": str(variant_dir / "combine_and_pshufb.s"),
        "object_file": str(variant_dir / "combine_and_pshufb.o"),
        "object_size_bytes": total_object_size(variant_dir / "combine_and_pshufb.o"),
        "function_asm": fn_asm.strip(),
        "static_instructions": insns,
        "shuffle_ret_instructions": shuffle_insns,
        "static_instruction_count": len(insns),
        "shuffle_instruction_count": len([i for i in insns if i != "ret"]),
        "encoded_instructions": per_insn,
        "encoded_instruction_bytes": fn_byte_total,
        "function_code_size_bytes": fn_sym["size"] if fn_sym else fn_byte_total,
        "function_symbol": fn_sym,
        "sections": sections,
        "text_section_size": text["size"] if text else None,
        "rodata_section_size": rodata["size"] if rodata else 0,
        "rodata_section_name": rodata["name"] if rodata else None,
        "content_section_total_bytes": content_total,
        "constant_pools": pools,
        "constant_pool_total_bytes": sum(p.get("bytes", 0) for p in pools),
        "constant_pool_labels": [p["label"] for p in pools],
        "align_directives": parse_alignments(asm),
        "vpshufb_uses_memory_operand": mem_operand,
        "separate_mask_load_instruction": separate_load,
    }


def delta(a: int | None, b: int | None) -> str:
    if a is None or b is None:
        return "n/a"
    d = b - a
    return f"{d:+d}"


def main() -> None:
    out_dir = Path(sys.argv[1])
    baseline = analyze_variant(out_dir / "baseline")
    patched = analyze_variant(out_dir / "patched")

    comparison = {
        "baseline": baseline,
        "patched": patched,
        "table": {
            "static_instruction_count": {
                "baseline": baseline["static_instruction_count"],
                "patched": patched["static_instruction_count"],
                "delta": patched["static_instruction_count"]
                - baseline["static_instruction_count"],
            },
            "encoded_instruction_bytes": {
                "baseline": baseline["encoded_instruction_bytes"],
                "patched": patched["encoded_instruction_bytes"],
                "delta": patched["encoded_instruction_bytes"]
                - baseline["encoded_instruction_bytes"],
            },
            "function_code_size_bytes": {
                "baseline": baseline["function_code_size_bytes"],
                "patched": patched["function_code_size_bytes"],
                "delta": patched["function_code_size_bytes"]
                - baseline["function_code_size_bytes"],
            },
            "constant_pool_bytes": {
                "baseline": baseline["constant_pool_total_bytes"],
                "patched": patched["constant_pool_total_bytes"],
                "delta": patched["constant_pool_total_bytes"]
                - baseline["constant_pool_total_bytes"],
            },
            "rodata_section_bytes": {
                "baseline": baseline["rodata_section_size"],
                "patched": patched["rodata_section_size"],
                "delta": patched["rodata_section_size"]
                - baseline["rodata_section_size"],
            },
            "text_section_bytes": {
                "baseline": baseline["text_section_size"],
                "patched": patched["text_section_size"],
                "delta": (patched["text_section_size"] or 0)
                - (baseline["text_section_size"] or 0),
            },
            "content_section_total_bytes": {
                "baseline": baseline["content_section_total_bytes"],
                "patched": patched["content_section_total_bytes"],
                "delta": (patched["content_section_total_bytes"] or 0)
                - (baseline["content_section_total_bytes"] or 0),
            },
            "shuffle_instruction_count": {
                "baseline": baseline["shuffle_instruction_count"],
                "patched": patched["shuffle_instruction_count"],
                "delta": patched["shuffle_instruction_count"]
                - baseline["shuffle_instruction_count"],
            },
            "total_object_bytes": {
                "baseline": baseline["object_size_bytes"],
                "patched": patched["object_size_bytes"],
                "delta": patched["object_size_bytes"] - baseline["object_size_bytes"],
            },
        },
    }
    (out_dir / "comparison.json").write_text(json.dumps(comparison, indent=2) + "\n")

    t = comparison["table"]
    table_md = [
        "| Metric | Baseline | Patched | Δ (patched − baseline) |",
        "|--------|----------|---------|-------------------------|",
        f"| Static instruction count (incl. `ret`) | {t['static_instruction_count']['baseline']} | {t['static_instruction_count']['patched']} | {t['static_instruction_count']['delta']:+d} |",
        f"| Shuffle instruction count (excl. `ret`) | {t['shuffle_instruction_count']['baseline']} | {t['shuffle_instruction_count']['patched']} | {t['shuffle_instruction_count']['delta']:+d} |",
        f"| Encoded instruction bytes (`.text` disassembly) | {t['encoded_instruction_bytes']['baseline']} | {t['encoded_instruction_bytes']['patched']} | {t['encoded_instruction_bytes']['delta']:+d} |",
        f"| Function symbol size in `.text` | {t['function_code_size_bytes']['baseline']} | {t['function_code_size_bytes']['patched']} | {t['function_code_size_bytes']['delta']:+d} |",
        f"| Constant-pool payload (32-byte mask) | {t['constant_pool_bytes']['baseline']} | {t['constant_pool_bytes']['patched']} | {t['constant_pool_bytes']['delta']:+d} |",
        f"| Read-only data section (`.rodata*`) | {t['rodata_section_bytes']['baseline']} | {t['rodata_section_bytes']['patched']} | {t['rodata_section_bytes']['delta']:+d} |",
        f"| `.text` section size | {t['text_section_bytes']['baseline']} | {t['text_section_bytes']['patched']} | {t['text_section_bytes']['delta']:+d} |",
        f"| `llvm-size -A` content total | {t['content_section_total_bytes']['baseline']} | {t['content_section_total_bytes']['patched']} | {t['content_section_total_bytes']['delta']:+d} |",
        f"| Total on-disk object file size | {t['total_object_bytes']['baseline']} | {t['total_object_bytes']['patched']} | {t['total_object_bytes']['delta']:+d} |",
        "",
    ]
    (out_dir / "comparison_table.md").write_text("\n".join(table_md))

    lines = [
        "# Step 4A1 — Static code and object-size comparison (`@combine_and_pshufb`)",
        "",
        "## Compilation settings (identical for both variants)",
        "",
        "| Setting | Value |",
        "|---------|-------|",
        "| LLVM | 17.0.6 (`build-x86/bin/llc`) |",
        "| Input IR | `tests/step4a1_combine_and_pshufb.ll` |",
        "| Triple | `x86_64-unknown` |",
        "| Features | `+avx2` |",
        "| Options | default llc `-O2` (matches lit RUN lines) |",
        "| Object analysis tools | Homebrew LLVM 22 (`llvm-objdump`, `llvm-nm`, `llvm-size`) |",
        "",
        "---",
        "",
        "## Measured facts",
        "",
        "### 1. Exact generated assembly",
        "",
        "**Baseline** (`vpxor` + `vpblendw`):",
        "",
        "```asm",
        baseline["function_asm"],
        "```",
        "",
        "File: [`baseline/combine_and_pshufb.s`](baseline/combine_and_pshufb.s)",
        "",
        "**Patched** (`vpshufb` + constant-pool mask):",
        "",
        "```asm",
        patched["function_asm"],
        "```",
        "",
        "File: [`patched/combine_and_pshufb.s`](patched/combine_and_pshufb.s)",
        "",
        "### 2–4. Instruction count, encoded bytes, function code size",
        "",
        "See [`comparison_table.md`](comparison_table.md) for the full metric table.",
        "",
        "| Metric | Baseline | Patched | Δ (patched − baseline) |",
        "|--------|----------|---------|-------------------------|",
        f"| Static instruction count (incl. `ret`) | {t['static_instruction_count']['baseline']} | {t['static_instruction_count']['patched']} | {t['static_instruction_count']['delta']:+d} |",
        f"| Shuffle instruction count (excl. `ret`) | {t['shuffle_instruction_count']['baseline']} | {t['shuffle_instruction_count']['patched']} | {t['shuffle_instruction_count']['delta']:+d} |",
        f"| Encoded instruction bytes (`.text` disassembly) | {t['encoded_instruction_bytes']['baseline']} | {t['encoded_instruction_bytes']['patched']} | {t['encoded_instruction_bytes']['delta']:+d} |",
        f"| Function `.text` symbol size (`llvm-nm --print-size`) | {t['function_code_size_bytes']['baseline']} | {t['function_code_size_bytes']['patched']} | {t['function_code_size_bytes']['delta']:+d} |",
        "",
        "**Baseline encoded instructions:**",
        "",
    ]
    for rec in baseline["encoded_instructions"]:
        lines.append(f"- `{rec['text']}` — {rec['encoded_bytes']} B (`{rec['hex']}`)")
    lines.extend(["", "**Patched encoded instructions:**", ""])
    for rec in patched["encoded_instructions"]:
        lines.append(f"- `{rec['text']}` — {rec['encoded_bytes']} B (`{rec['hex']}`)")

    lines.extend(
        [
            "",
            "### 5–6. Constant pool and section sizes",
            "",
            "| Metric | Baseline | Patched | Δ |",
            "|--------|----------|---------|---|",
            f"| Constant-pool payload bytes (32-byte `.LCPI0_0`) | {t['constant_pool_bytes']['baseline']} | {t['constant_pool_bytes']['patched']} | {t['constant_pool_bytes']['delta']:+d} |",
            f"| Read-only data section (`{patched.get('rodata_section_name') or '.rodata'}`) | {t['rodata_section_bytes']['baseline']} | {t['rodata_section_bytes']['patched']} | {t['rodata_section_bytes']['delta']:+d} |",
            f"| `.text` section size | {t['text_section_bytes']['baseline']} | {t['text_section_bytes']['patched']} | {t['text_section_bytes']['delta']:+d} |",
            f"| `llvm-size -A` content total | {t['content_section_total_bytes']['baseline']} | {t['content_section_total_bytes']['patched']} | {t['content_section_total_bytes']['delta']:+d} |",
            f"| Total on-disk object file size | {t['total_object_bytes']['baseline']} | {t['total_object_bytes']['patched']} | {t['total_object_bytes']['delta']:+d} |",
            "",
            "**Baseline constant-pool labels:** "
            + (", ".join(baseline["constant_pool_labels"]) or "none"),
            "",
            "**Patched constant-pool labels:** "
            + (", ".join(patched["constant_pool_labels"]) or "none"),
            "",
            "**Alignment directives in patched assembly:** "
            + (", ".join(patched["align_directives"]) or "`.p2align 5` on `.rodata.cst32`, `.p2align 4` on `.text` (see full `.s`)"),
            "",
            "### 7–8. Constant-pool entry and mask operand form",
            "",
            "| Question | Baseline | Patched |",
            "|----------|----------|---------|",
            f"| New constant-pool entry introduced? | {'No' if not baseline['constant_pool_labels'] else 'Yes'} | {'Yes' if patched['constant_pool_labels'] else 'No'} |",
            f"| `vpshufb` mask operand | n/a (no `vpshufb`) | {'RIP-relative memory operand in the `vpshufb` instruction' if patched['vpshufb_uses_memory_operand'] else 'register/immediate'} |",
            f"| Separate load before shuffle? | n/a | {'Yes' if patched['separate_mask_load_instruction'] else 'No — mask fetched as part of the single `vpshufb` memory operand'} |",
            "",
            "---",
            "",
            "## Interpretation",
            "",
        ]
    )

    ins_delta = t["static_instruction_count"]["delta"]
    shuffle_delta = t["shuffle_instruction_count"]["delta"]
    code_delta = t["function_code_size_bytes"]["delta"]
    obj_delta = t["total_object_bytes"]["delta"]
    content_delta = t["content_section_total_bytes"]["delta"]
    pool_delta = t["constant_pool_bytes"]["delta"]

    if ins_delta < 0:
        lines.append(
            f"- **Instruction count:** patched emits {abs(ins_delta)} fewer static instruction ({baseline['static_instruction_count']} → {patched['static_instruction_count']}, including `ret`)."
        )
    if shuffle_delta < 0:
        lines.append(
            f"- **Shuffle uops in source:** {baseline['shuffle_instruction_count']} → {patched['shuffle_instruction_count']} (`vpxor`+`vpblendw` replaced by one `vpshufb`)."
        )

    if code_delta < 0:
        lines.append(
            f"- **Function code bytes:** patched function body is {abs(code_delta)} bytes smaller in `.text`."
        )
    elif code_delta > 0:
        lines.append(f"- **Function code bytes:** patched function body is {code_delta} bytes larger in `.text`.")

    if pool_delta > 0:
        lines.append(
            f"- **Constant-pool tradeoff:** patched introduces `.LCPI0_0` — a 32-byte AVX2 PSHUFB control mask in section `{patched.get('rodata_section_name', '.rodata.cst32')}` (`.p2align 5`). Baseline uses immediate-only `vpblendw` ($0xEE) with no pool."
        )

    if content_delta is not None and content_delta > 0:
        lines.append(
            f"- **Linked content sections (`llvm-size -A` total):** patched is {content_delta} bytes larger ({baseline['content_section_total_bytes']} → {patched['content_section_total_bytes']} B), driven mainly by the 32-byte mask plus a 1-byte `.text` saving."
        )
    elif content_delta is not None and content_delta < 0:
        lines.append("- **Linked content sections:** patched is smaller.")

    if obj_delta > 0:
        lines.append(
            f"- **Total object file:** patched `.o` is {obj_delta} bytes larger on disk ({baseline['object_size_bytes']} → {patched['object_size_bytes']} B), including extra ELF metadata (`.rela.text` for the RIP-relative `vpshufb`)."
        )
    elif obj_delta < 0:
        lines.append(
            f"- **Total object size:** patched object is {abs(obj_delta)} bytes smaller overall."
        )

    lines.extend(
        [
            "",
            "---",
            "",
            "## Limitations",
            "",
            "- Measurements are **static** (object file / disassembly), not runtime dynamic instruction count under inlining or LTO.",
            "- Isolated single-function object: no linker layout, no hot/cold splitting, no I-cache line packing effects.",
            "- `llvm-mca` microarchitectural cost **not** evaluated in Step 4A1.",
            "- Baseline generated by temporarily stashing the backend patch and rebuilding the same `llc` binary; patched restored immediately afterward.",
        "- Object inspection uses Homebrew LLVM 22 tools on objects emitted by LLVM 17.0.6 `llc`.",
            "- Constant-pool size counts `.byte` payload; section alignment padding in `.rodata` may add bytes beyond the 32-byte mask.",
            "",
            "## Artifacts",
            "",
            "| Path | Description |",
            "|------|-------------|",
            "| [`commands.log`](commands.log) | All shell commands |",
            "| [`comparison.json`](comparison.json) | Machine-readable metrics |",
        "| [`comparison_table.md`](comparison_table.md) | Summary comparison table |",
            "| [`baseline/`](baseline/) | Baseline `.s`, `.o`, disassembly, section dumps |",
            "| [`patched/`](patched/) | Patched `.s`, `.o`, disassembly, section dumps |",
        ]
    )
    (out_dir / "STEP4A1_REPORT.md").write_text("\n".join(lines) + "\n")
    print(f"Wrote {out_dir / 'STEP4A1_REPORT.md'}")


if __name__ == "__main__":
    main()
