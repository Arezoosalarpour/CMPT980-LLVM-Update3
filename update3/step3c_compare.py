#!/usr/bin/env python3
"""Step 3C validation: 71-function lit compare + summary report."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

INTENDED = {"combine_and_pshufb"}
NEW_TESTS = {
    "sparse_identity_or_zero_variant_a",
    "sparse_identity_or_zero_variant_b",
    "sparse_identity_or_zero_variant_c",
    "sparse_one_zero_word_pair_per_lane",
    "sparse_two_source_cross_lane",
}

BEGIN_RE = re.compile(r"# -- Begin function (\S+)")
OP_RE = re.compile(
    r"\b(vpshufb|vpblend\w*|vpxor|vpand|vpslldq|vpsrldq|vpsrlw|vpslld|vpsrlq|"
    r"vpshuflw|vpshufhw|vpmovzx|vshufps|vpermd|vpermps|vpermq|vpshufd|"
    r"vextracti128|vpaddq|vandps|vpbroadcast\w*|vmovq|vpsrad|vpack\w*)\b"
)


def extract_functions(asm_text: str) -> dict[str, str]:
    funcs: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []
    for line in asm_text.splitlines():
        m = BEGIN_RE.search(line)
        if m:
            if current is not None:
                funcs[current] = "\n".join(buf)
            current = m.group(1)
            buf = [line]
            continue
        if current is not None:
            buf.append(line)
            if "# -- End function" in line:
                funcs[current] = "\n".join(buf)
                current = None
                buf = []
    return funcs


def normalize(body: str) -> str:
    lines = []
    for line in body.splitlines():
        if line.lstrip().startswith("#"):
            continue
        line = re.sub(r"\s+#.*$", "", line).rstrip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def ops(body: str) -> list[str]:
    found: list[str] = []
    for line in body.splitlines():
        for m in OP_RE.finditer(line):
            found.append(m.group(1))
    return found


def count_ops(body: str, op: str) -> int:
    return len(re.findall(rf"\b{re.escape(op)}\w*\b", body))


def main() -> None:
    out_dir = Path(sys.argv[1])
    asm_dir = out_dir / "asm"
    baseline = extract_functions((asm_dir / "unpatched.s").read_text())
    patched = extract_functions((asm_dir / "patched.s").read_text())
    all_names = sorted(baseline.keys())

    changed = []
    per_fn = {}
    for name in all_names:
        diff = normalize(patched.get(name, "")) != normalize(baseline[name])
        per_fn[name] = {
            "changed": diff,
            "unpatched_ops": ops(baseline[name]),
            "patched_ops": ops(patched.get(name, "")),
        }
        if diff:
            changed.append(name)

    new_in_patched = sorted(set(patched.keys()) - set(baseline.keys()))
    intended_ok = changed == sorted(INTENDED)
    step3_complete = intended_ok and len(changed) == 1

    results = {
        "total_functions_baseline": len(all_names),
        "changed_count": len(changed),
        "unchanged_count": len(all_names) - len(changed),
        "intended_changed": sorted(INTENDED),
        "actual_changed": sorted(changed),
        "new_tests_in_patched_only": new_in_patched,
        "intended_only_changed": intended_ok,
        "step3_complete": step3_complete,
        "per_function": per_fn,
    }
    (out_dir / "step3c_compare.json").write_text(
        json.dumps(results, indent=2) + "\n"
    )

    combine_body = patched.get("combine_and_pshufb", "")
    lines = [
        "# Step 3C — Finalize LLVM regression tests (Step 3B3 patch)",
        "",
        "## Summary",
        "",
        f"- **71-function compare:** {len(changed)} changed, {len(all_names) - len(changed)} unchanged",
        f"- **Intended-only change (`combine_and_pshufb`):** {'PASS' if intended_ok else 'FAIL'}",
        f"- **Step 3 complete / ready for Step 4:** {'YES' if step3_complete else 'NO'}",
        "",
        "## Changed functions",
        "",
        ", ".join(changed) if changed else "none",
        "",
        "## New lit tests added (Step 3C)",
        "",
        ", ".join(sorted(NEW_TESTS)),
        "",
        "## `@combine_and_pshufb` opcode counts (patched x86_64 AVX2)",
        "",
        f"- vpshufb: {count_ops(combine_body, 'vpshufb')}",
        f"- vpxor: {count_ops(combine_body, 'vpxor')}",
        f"- vpand: {count_ops(combine_body, 'vpand')}",
        f"- vpblendw: {count_ops(combine_body, 'vpblendw')}",
        "",
        "## Artifacts",
        "",
        "- [`X86ISelLowering.patch`](X86ISelLowering.patch)",
        "- [`commands.log`](commands.log)",
        "- [`filecheck_runs.log`](filecheck_runs.log)",
        "- [`broader_runs.log`](broader_runs.log)",
        "- [`semantic/verify.log`](semantic/verify.log)",
        "- [`step3c_compare.json`](step3c_compare.json)",
        "- [`asm/combine_and_pshufb.s`](asm/combine_and_pshufb.s)",
    ]
    (out_dir / "STEP3C_REPORT.md").write_text("\n".join(lines) + "\n")
    print(f"Wrote {out_dir / 'STEP3C_REPORT.md'}")


if __name__ == "__main__":
    main()
