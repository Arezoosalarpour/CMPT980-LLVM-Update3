#!/usr/bin/env python3
"""Write Step 5A2 report from search results."""

from __future__ import annotations

import json
import sys
from pathlib import Path

CPUS = ["haswell", "skylake", "znver1"]


def main() -> None:
    out = Path(sys.argv[1])
    results = json.loads((out / "results.json").read_text())
    summary = json.loads((out / "summary.json").read_text())

    missed = [r for r in results if r.get("missed")]
    ranked = []
    for r in missed:
        mca = r.get("mca") or {}
        deltas = mca.get("deltas") or {}
        if not deltas:
            continue
        ds = [deltas[c] for c in CPUS]
        ranked.append((sum(ds), r, ds))
    ranked.sort(key=lambda x: x[0])

    lines = [
        "# Step 5A2 — Missed lowering opportunity search",
        "",
        "## Scope",
        "",
        "Search three Step 5A1 overlap families with **unmodified LLVM 17.0.6**",
        "(project patch temporarily removed for this measurement).",
        "",
        "For each generated mask: baseline `llc`, **semantically verified** alternative",
        "sequences, llvm-mca on Haswell / Skylake / Zen1. **No LLVM source or test edits.**",
        "",
        "Success criteria for a missed opportunity:",
        "",
        "1. LLVM selects one legal sequence;",
        "2. a different **semantically equivalent** sequence exists;",
        "3. the alternative has lower llvm-mca cycles on ≥2 CPUs;",
        "4. the alternative does not lose on any CPU (or Zen loss is negligible);",
        "5. the mask is a structural family, not a one-off constant.",
        "",
        "---",
        "",
        "## Summary counts",
        "",
        "| Family | Masks tested | Overlapping legal lowerings | LLVM choice measurably worse |",
        "|--------|--------------|----------------------------|------------------------------|",
    ]

    for fam in ("zext", "unpck", "pack", "control_pos_shift", "control_neg_blend"):
        s = summary["by_family"].get(fam, {})
        lines.append(
            f"| **{fam}** | {s.get('tested', 0)} | {s.get('overlap', 0)} | {s.get('missed', 0)} |"
        )

    total_tested = sum(summary["by_family"][f]["tested"] for f in summary["by_family"])
    total_overlap = sum(summary["by_family"][f]["overlap"] for f in summary["by_family"])
    total_missed = sum(summary["by_family"][f]["missed"] for f in summary["by_family"])
    lines.extend(
        [
            f"| **TOTAL** | {total_tested} | {total_overlap} | {total_missed} |",
            "",
            "### Per-family LLVM path distribution",
            "",
        ]
    )
    for fam in ("zext", "unpck", "pack", "control_pos_shift", "control_neg_blend"):
        paths = summary["by_family"].get(fam, {}).get("llvm_paths", {})
        if paths:
            lines.append(f"- **{fam}:** " + ", ".join(f"`{k}`×{v}" for k, v in sorted(paths.items())))

    ctrl = summary.get("controls", {})
    lines.extend(
        [
            "",
            "### Controls",
            "",
            f"- **Positive (byte shift):** LLVM chose `vpslldq` in "
            f"**{ctrl.get('positive_shift_optimal', 0)} / {ctrl.get('positive_shift_tested', 0)}** cases.",
            f"- **Negative (A/C blend vs PSHUFB):** blend ≤ PSHUFB on MCA for "
            f"**{ctrl.get('negative_blend_beats_or_ties_pshufb', 0)} / {ctrl.get('negative_tested', 0)}** "
            f"variants (fewer instructions ≠ cheaper).",
            "",
            "---",
            "",
            "## Findings by family",
            "",
            "### 1. Zero/AnyExtend versus PSHUFB",
            "",
            "Prefix / suffix / sparse identity-or-zero masks. Unpatched LLVM typically selects",
            "`vblendps`/`vpblendw` (when dword/word aligned) or `vandps` (bitmask keep), not PSHUFB.",
            "Where PSHUFB is also legal, MCA usually favors the specialized path LLVM already chose,",
            "or shows Intel/Zen disagreement (pool `vandps` can win on Zen while blend wins on Intel).",
            "",
            "### 2. VPUNPCK interleave-zero versus PSHUFB",
            "",
            "Full `vpunpcklwd` / `vpunpcklbw` / `vpunpckhbw` patterns: LLVM already emits UNPCK when",
            "the mask matches exactly. Partial prefixes fall to blend/bitmask/PSHUFB; full UNPCK is",
            "**not** semantically equivalent to those partial masks, so it is not a legal alternative.",
            "",
            "### 3. VPACK compaction versus dual-PSHUFB",
            "",
            "Even-byte compaction often lowers to a **single** `vpshufb`. A legal AND+`vpackuswb`",
            "sequence exists for some of these, but is **more** instructions and not cheaper on MCA.",
            "True dual-PSHUFB vs PACK overlap needs multi-op DAG combine patterns, not a single",
            "`shufflevector` IR (see Step 5A1 lit tests `@shuffle_combine_packsswb_pshufb`).",
            "",
            "---",
            "",
        ]
    )

    if not missed:
        lines.extend(
            [
                "## Missed lowering opportunities",
                "",
                "**None found** under the success criteria.",
                "",
                "LLVM’s choices in these families were either:",
                "",
                "- already the specialized cheap path (shift, unpck, blend), or",
                "- a pool `vandps`/`vpshufb` that is not dominated by a verified alternative on ≥2 CPUs",
                "  without a large loss on another CPU.",
                "",
                "**Do not recommend implementation** of cases LLVM already lowers optimally.",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "## Missed lowering opportunities",
                "",
                f"**{len(missed)}** case(s) met success criteria.",
                "",
            ]
        )
        for i, (total_delta, r, deltas) in enumerate(ranked[:3], 1):
            lines.extend(
                [
                    f"### Candidate {i}: `{r['family']}/{r['case_id']}`",
                    "",
                    f"- **LLVM:** `{r['llvm_path']}` — `{'; '.join(r['llvm_insns'])}`",
                    f"- **Alt:** `{r.get('alt_path')}` — {r.get('alt_reason', '')}",
                    f"- **Cycle Δ (alt−llvm):** Haswell {deltas[0]:+d}, Skylake {deltas[1]:+d}, znver1 {deltas[2]:+d}",
                    f"- **Notes:** {r.get('notes', '')}",
                    "",
                ]
            )
        best = ranked[0][1]
        lines.extend(
            [
                "### Single best implementation candidate",
                "",
                f"**`{best['family']}/{best['case_id']}`** — prefer `{best.get('alt_path')}` over "
                f"`{best['llvm_path']}` for this structural family.",
                "",
            ]
        )

    near = summary.get("near_misses", [])
    if near:
        lines.extend(
            [
                "---",
                "",
                "## Near misses (alt wins ≥1 CPU; not implementation candidates)",
                "",
                "| Case | LLVM | Alt | HSW Δ | SKL Δ | Zen Δ | Note |",
                "|------|------|-----|-------|-------|-------|------|",
            ]
        )
        for n in near[:20]:
            d = n["deltas"]
            lines.append(
                f"| `{n['family']}/{n['case_id']}` | `{n['llvm_path']}` | `{n['alt_path']}` | "
                f"{d['haswell']:+d} | {d['skylake']:+d} | {d['znver1']:+d} | {n.get('notes','')} |"
            )

    lines.extend(
        [
            "",
            "---",
            "",
            "## Method",
            "",
            "- IR: `shufflevector <32 x i8>` with `zeroinitializer` (or two-source for pack).",
            "- Alternatives accepted only if byte-level simulation matches the shuffle mask.",
            "- MCA: 1000 iterations, isolated body, `ret` excluded.",
            "- Positive control: `pslldq_*`. Negative control: Variant A/C blend vs PSHUFB.",
            "",
            "## Artifacts",
            "",
            "| Path | Description |",
            "|------|-------------|",
            "| [`results.json`](results.json) | Per-mask results |",
            "| [`summary.json`](summary.json) | Aggregates |",
            "| [`work/`](work/) | Per-case `.ll` / `.s` |",
            "| [`commands.log`](commands.log) | Reproduce log |",
            "| [`llvm_lowering.patch.save`](llvm_lowering.patch.save) | Stashed project patch |",
        ]
    )

    (out / "STEP5A2_REPORT.md").write_text("\n".join(lines) + "\n")
    print(f"Wrote {out / 'STEP5A2_REPORT.md'}")


if __name__ == "__main__":
    main()
