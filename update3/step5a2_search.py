#!/usr/bin/env python3
"""Step 5A2 — search three helper-overlap families for missed lowerings.

Uses unmodified LLVM 17.0.6 llc. Alternatives must be semantically equivalent
to the generated shuffle mask (simulated byte-wise).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

CPUS = ["haswell", "skylake", "znver1"]
ZERO = 32
UNDEF = -1
LLC_FLAGS = ["-mtriple=x86_64-unknown", "-mattr=+avx2", "-O2"]
MCA_ITERS = 1000


@dataclass
class CaseResult:
    family: str
    case_id: str
    mask: list[int]
    llvm_path: str
    llvm_insns: list[str]
    llvm_insn_count: int
    llvm_has_pool: bool
    alt_path: str | None
    alt_legal: bool
    alt_reason: str
    overlap: bool
    missed: bool
    mca_wins: int
    mca_losses: int
    mca: dict | None = None
    notes: str = ""


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


def classify_asm(asm: str) -> tuple[str, list[str], bool]:
    insns: list[str] = []
    has_pool = ".LCPI" in asm or ".rodata" in asm
    for line in asm.splitlines():
        s = line.strip()
        if not s or s.startswith(".") or s.startswith("#") or s.startswith("ret"):
            continue
        if re.match(r"^v[a-z0-9]+", s):
            insns.append(s.split("#")[0].strip())
    blob = " ".join(insns).lower()
    if "vpunpck" in blob:
        path = "unpck"
    elif "vpack" in blob:
        path = "pack"
    elif "vpslldq" in blob or "vpsrldq" in blob:
        path = "shift"
    elif "vpmovzx" in blob or "vpmovsx" in blob:
        path = "zext"
    elif "vpblendw" in blob or "vblendps" in blob or "vpblendd" in blob:
        path = "blend"
    elif "vpshufb" in blob:
        path = "pshufb"
    elif "vpand" in blob or "vandps" in blob or "vandpd" in blob:
        path = "bitmask"
    elif "vmovq" in blob:
        path = "movq"
    else:
        path = "other"
    return path, insns, has_pool


def apply_shuffle(src: list[int], mask: list[int]) -> list[int]:
    """Apply shuffle mask to a 32-byte source; zeroinitializer as second input."""
    out = []
    for m in mask:
        if m < 0:
            out.append(None)  # undef
        elif m >= 32:
            out.append(0)
        else:
            out.append(src[m])
    return out


def results_equiv(a: list, b: list) -> bool:
    for x, y in zip(a, b):
        if x is None or y is None:
            continue
        if x != y:
            return False
    return True


def mask_to_ir(mask: list[int], two_source: bool = False) -> str:
    elems = ", ".join("i32 undef" if m < 0 else f"i32 {m}" for m in mask)
    if two_source:
        return f"""target datalayout = "e-m:o-i64:64"
target triple = "x86_64-unknown"

define <32 x i8> @f(<32 x i8> %a, <32 x i8> %b) {{
  %s = shufflevector <32 x i8> %a, <32 x i8> %b,
    <32 x i32> <{elems}>
  ret <32 x i8> %s
}}
"""
    return f"""target datalayout = "e-m:o-i64:64"
target triple = "x86_64-unknown"

define <32 x i8> @f(<32 x i8> %a) {{
  %s = shufflevector <32 x i8> %a, <32 x i8> zeroinitializer,
    <32 x i32> <{elems}>
  ret <32 x i8> %s
}}
"""


def can_pshufb_in_lane(mask: list[int]) -> bool:
    """Single-source in-lane PSHUFB: each lane only reads that lane (or zero)."""
    for lane in (0, 16):
        uses_v1 = False
        for i in range(16):
            m = mask[lane + i]
            if m < 0:
                continue
            if m >= 32:
                continue
            if (m // 16) != (lane // 16):
                return False
            # PSHUFB cannot cross 128-bit... wait, within lane also cannot
            # cross the 16-byte lane; indices are relative within 16-byte.
            # Absolute source index must be in same 16-byte half.
            if m < lane or m >= lane + 16:
                return False
            uses_v1 = True
        # ok
    return True


def sim_pshufb(src: list[int], mask: list[int]) -> list[int]:
    """PSHUFB implements the IR shuffle for in-lane single-source masks."""
    return apply_shuffle(src, mask)


def pshufb_ctrl(mask: list[int]) -> list[int]:
    ctrl = []
    for lane in (0, 16):
        for i in range(16):
            m = mask[lane + i]
            if m < 0 or m >= 32:
                ctrl.append(128)
            else:
                ctrl.append(m - lane)  # lane-relative control byte
    return ctrl


def sim_vandps_keep(src: list[int], keep: list[bool]) -> list[int]:
    return [src[i] if keep[i] else 0 for i in range(32)]


def sim_vpunpcklwd_zero(src: list[int]) -> list[int]:
    out = [0] * 32
    for lane in (0, 16):
        # unpack low 4 words of lane with zeros
        for w in range(4):
            out[lane + 4 * w] = src[lane + 2 * w]
            out[lane + 4 * w + 1] = src[lane + 2 * w + 1]
            out[lane + 4 * w + 2] = 0
            out[lane + 4 * w + 3] = 0
    return out


def sim_vpunpcklbw_zero(src: list[int]) -> list[int]:
    out = [0] * 32
    for lane in (0, 16):
        for b in range(8):
            out[lane + 2 * b] = src[lane + b]
            out[lane + 2 * b + 1] = 0
    return out


def sim_vpunpckhbw_zero(src: list[int]) -> list[int]:
    out = [0] * 32
    for lane in (0, 16):
        for b in range(8):
            out[lane + 2 * b] = 0
            out[lane + 2 * b + 1] = src[lane + 8 + b]
    return out


def sim_vpblendw(src: list[int], imm: int) -> list[int]:
    """Blend src with zero using VPBLENDW immediate (bit=1 keeps src word)."""
    out = []
    for lane in (0, 16):
        for w in range(8):
            keep = bool(imm & (1 << w))
            b0, b1 = lane + 2 * w, lane + 2 * w + 1
            if keep:
                out.extend([src[b0], src[b1]])
            else:
                out.extend([0, 0])
    return out


def sim_vblendps(src: list[int], imm: int) -> list[int]:
    """VBLENDPS imm: bit=1 selects src dword, else zero. Imm applies per 128-bit?"""
    # AVX VBLENDPS uses 8-bit mask for 8 dwords of YMM.
    out = []
    for d in range(8):
        keep = bool(imm & (1 << d))
        base = 4 * d
        if keep:
            out.extend(src[base : base + 4])
        else:
            out.extend([0, 0, 0, 0])
    return out


def sim_vpslldq(src: list[int], amt: int) -> list[int]:
    out = [0] * 32
    for lane in (0, 16):
        for i in range(16):
            if i >= amt:
                out[lane + i] = src[lane + i - amt]
    return out


def sim_packuswb_and_zero(src: list[int]) -> list[int]:
    """vpand 0x00FF per word, then vpackuswb with zero (low half = even bytes)."""
    out = [0] * 32
    for lane in (0, 16):
        # after and: words keep low byte
        low_bytes = [src[lane + 2 * w] for w in range(8)]  # even bytes
        for i, b in enumerate(low_bytes):
            out[lane + i] = b
        # high 8 of lane from zero pack = 0 (already)
    return out


def blend_imm_for_mask(mask: list[int]) -> int | None:
    """If mask is identity-or-zero at i16 granularity (lane-repeated), return imm."""
    imm = 0
    for w in range(8):
        # check both lanes agree
        for lane in (0, 16):
            b0, b1 = lane + 2 * w, lane + 2 * w + 1
            m0, m1 = mask[b0], mask[b1]
            if m0 < 0 and m1 < 0:
                continue
            # both zero
            if m0 >= 32 and m1 >= 32:
                keep = False
            elif m0 == b0 and m1 == b1:
                keep = True
            else:
                return None
            bit = 1 << w
            if lane == 0:
                if keep:
                    imm |= bit
            else:
                # must match low-lane choice
                low_keep = bool(imm & bit)
                if keep != low_keep and not (m0 < 0 or m1 < 0):
                    # if high lane defined differently
                    if m0 >= 0 and m1 >= 0:
                        return None
        # also require high lane same pattern when defined
        for lane in (16,):
            b0, b1 = lane + 2 * w, lane + 2 * w + 1
            m0, m1 = mask[b0], mask[b1]
            if m0 < 0 and m1 < 0:
                continue
            keep = not (m0 >= 32 and m1 >= 32)
            if keep and not (m0 == b0 and m1 == b1):
                return None
            if (m0 >= 0 and m1 >= 0) and keep != bool(imm & (1 << w)):
                return None
    return imm


def identity_keep_bits(mask: list[int]) -> list[bool] | None:
    """If every defined lane is either identity or zero, return keep bitmap."""
    keep = []
    for i, m in enumerate(mask):
        if m < 0:
            keep.append(True)  # undef: don't care
            continue
        if m >= 32:
            keep.append(False)
        elif m == i:
            keep.append(True)
        else:
            return None
    return keep


# ---------- mask generators ----------


def gen_masks() -> dict[str, list[tuple[str, list[int], dict]]]:
    """family -> list of (id, mask, meta)."""
    cases: dict[str, list[tuple[str, list[int], dict]]] = {
        "zext": [],
        "unpck": [],
        "pack": [],
        "control_pos_shift": [],
        "control_neg_blend": [],
    }

    # Zext / prefix-zero families
    for prefix in range(1, 16):
        for tag, lanes in (("both", (0, 16)), ("low", (0,)), ("high", (16,))):
            mask = [ZERO] * 32
            for lane in lanes:
                for i in range(prefix):
                    mask[lane + i] = lane + i
            cases["zext"].append((f"prefix{prefix}_{tag}", mask, {}))

        # suffix identity
        mask = [ZERO] * 32
        for lane in (0, 16):
            for i in range(prefix):
                mask[lane + 16 - prefix + i] = lane + 16 - prefix + i
        cases["zext"].append((f"suffix{prefix}_both", mask, {}))

    # sparse word-pair identity (A/C-like)
    for positions in ([0], [0, 4], [0, 1], [0, 2, 4], [0, 1, 2, 3], [1], [2], [3, 7]):
        m = [ZERO] * 32
        for lane in (0, 16):
            for p in positions:
                m[lane + 2 * p] = lane + 2 * p
                m[lane + 2 * p + 1] = lane + 2 * p + 1
        cases["zext"].append((f"sparse_w_{'_'.join(map(str, positions))}", m, {}))

    # undef high half of prefix
    for prefix in (2, 4, 6, 8, 12):
        mask = [UNDEF] * 32
        for lane in (0, 16):
            for i in range(16):
                g = lane + i
                mask[g] = g if i < prefix else UNDEF
        cases["zext"].append((f"prefix{prefix}_undef_rest", mask, {}))

    # UNPCK families — semantically exact patterns
    # full vpunpcklwd with zero
    m = [ZERO] * 32
    for lane in (0, 16):
        for w in range(4):
            m[lane + 4 * w] = lane + 2 * w
            m[lane + 4 * w + 1] = lane + 2 * w + 1
    cases["unpck"].append(("unpcklwd_full", m, {"kind": "unpcklwd"}))

    # partial prefixes of unpack (still legal as PSHUFB / blend / bitmask)
    for n in (1, 2, 3):
        m = [ZERO] * 32
        for lane in (0, 16):
            for w in range(n):
                m[lane + 4 * w] = lane + 2 * w
                m[lane + 4 * w + 1] = lane + 2 * w + 1
        cases["unpck"].append((f"unpcklwd_prefix{n}", m, {"kind": "partial_lwd"}))

    # full vpunpcklbw with zero
    m = [ZERO] * 32
    for lane in (0, 16):
        for b in range(8):
            m[lane + 2 * b] = lane + b
            m[lane + 2 * b + 1] = ZERO
    cases["unpck"].append(("unpcklbw_full", m, {"kind": "unpcklbw"}))

    # partial unpcklbw
    for n in (2, 4, 6):
        m = [ZERO] * 32
        for lane in (0, 16):
            for b in range(n):
                m[lane + 2 * b] = lane + b
                m[lane + 2 * b + 1] = ZERO
        cases["unpck"].append((f"unpcklbw_prefix{n}", m, {"kind": "partial_lbw"}))

    # full vpunpckhbw with zero
    m = [ZERO] * 32
    for lane in (0, 16):
        for b in range(8):
            m[lane + 2 * b] = ZERO
            m[lane + 2 * b + 1] = lane + 8 + b
    cases["unpck"].append(("unpckhbw_full", m, {"kind": "unpckhbw"}))

    # only high lane unpack
    m = [ZERO] * 32
    for b in range(8):
        m[16 + 2 * b] = 16 + b
        m[16 + 2 * b + 1] = ZERO
    cases["unpck"].append(("unpcklbw_high_only", m, {"kind": "partial_lbw"}))

    # PACK families — even-byte compaction (PSHUFB vs AND+PACKUS)
    m = [ZERO] * 32
    for lane in (0, 16):
        for i in range(8):
            m[lane + i] = lane + 2 * i
    cases["pack"].append(("even_compact_low8", m, {"kind": "packus_and"}))

    # odd-byte compaction
    m = [ZERO] * 32
    for lane in (0, 16):
        for i in range(8):
            m[lane + i] = lane + 2 * i + 1
    cases["pack"].append(("odd_compact_low8", m, {"kind": "pshufb_only"}))

    # even compact into high half of lane
    m = [ZERO] * 32
    for lane in (0, 16):
        for i in range(8):
            m[lane + 8 + i] = lane + 2 * i
    cases["pack"].append(("even_compact_high8", m, {"kind": "pshufb_only"}))

    # two-source interleave pack-like (select low bytes from a and b alternating)
    # mask: a0,b0,a2,b2,... not classic pack — skip for now
    # Classic packuswb of two inputs: needs v16i16 domain. Represent as byte
    # shuffle selecting low bytes of consecutive words from V1 then V2.
    m = []
    for lane in (0, 16):
        for i in range(8):
            m.append(lane + 2 * i)  # from V1
        for i in range(8):
            m.append(32 + lane + 2 * i)  # from V2
    cases["pack"].append(("packus_two_source", m, {"kind": "two_src", "two_source": True}))

    # low-lane only even compact
    m = [ZERO] * 32
    for i in range(8):
        m[i] = 2 * i
    cases["pack"].append(("even_compact_low_lane", m, {"kind": "packus_and"}))

    # Positive control: pslldq
    for amt in range(1, 16):
        mask = [ZERO] * 32
        for lane in (0, 16):
            for i in range(16):
                mask[lane + i] = (lane + i - amt) if i >= amt else ZERO
        cases["control_pos_shift"].append((f"pslldq_{amt}", mask, {"amt": amt}))

    # Negative control: variant A / C
    m = [ZERO] * 32
    for lane in (0, 16):
        for p in (0, 4):
            m[lane + 2 * p] = lane + 2 * p
            m[lane + 2 * p + 1] = lane + 2 * p + 1
    cases["control_neg_blend"].append(("variant_a", m, {}))

    m = [ZERO] * 32
    for lane in (0, 16):
        for p in range(4):
            m[lane + 4 * p] = lane + 4 * p
            m[lane + 4 * p + 1] = lane + 4 * p + 1
    cases["control_neg_blend"].append(("variant_c", m, {}))

    return cases


def pool_bytes(vals: list[int]) -> list[str]:
    return [
        '	.section .rodata.cst32,"aM",@progbits,32',
        "	.p2align 5",
        ".LCPI0_0:",
        *[f"	.byte {b}" for b in vals],
        "	.text",
    ]


def and_mask_pool(keep: list[bool]) -> list[str]:
    return pool_bytes([255 if k else 0 for k in keep])


def pshufb_pool(mask: list[int]) -> list[str]:
    return pool_bytes(pshufb_ctrl(mask))


def asm_body(insns: list[str]) -> str:
    return "\n".join(["	# %bb.0:"] + ["	" + i for i in insns]) + "\n"


def find_alternatives(mask: list[int], llvm_path: str) -> list[tuple[str, str, list[str], str]]:
    """Return semantically verified alternatives different from llvm_path."""
    # Use a distinctive source pattern
    src = list(range(32))
    expected = apply_shuffle(src, mask)
    alts: list[tuple[str, str, list[str], str]] = []

    # PSHUFB
    if can_pshufb_in_lane(mask):
        got = sim_pshufb(src, mask)
        # For zero-from-V2, sim_pshufb uses relative indices — verify vs expected
        # Rebuild expected with relative semantics for comparison
        if results_equiv(got, expected):
            alts.append(
                (
                    "pshufb",
                    "in-lane vpshufb + pool",
                    pshufb_pool(mask),
                    asm_body(["vpshufb	.LCPI0_0(%rip), %ymm0, %ymm0"]),
                )
            )

    # Bitmask (identity-or-zero)
    keep = identity_keep_bits(mask)
    if keep is not None:
        got = sim_vandps_keep(src, keep)
        if results_equiv(got, expected):
            alts.append(
                (
                    "bitmask",
                    "vandps/vpand keep mask",
                    and_mask_pool(keep),
                    asm_body(["vandps	.LCPI0_0(%rip), %ymm0, %ymm0"]),
                )
            )

    # VPBLENDW
    imm = blend_imm_for_mask(mask)
    if imm is not None:
        got = sim_vpblendw(src, imm)
        if results_equiv(got, expected):
            alts.append(
                (
                    "blend",
                    f"vpxor + vpblendw ${imm}",
                    [],
                    asm_body(
                        [
                            "vpxor	%xmm1, %xmm1, %xmm1",
                            f"vpblendw	${imm}, %ymm0, %ymm1, %ymm0",
                        ]
                    ),
                )
            )

    # VBLENDPS for dword-aligned identity-or-zero
    for imm in range(256):
        # only try a few likely immediates derived from mask
        pass
    # derive blendps imm
    d_imm = 0
    ok_ps = True
    for d in range(8):
        base = 4 * d
        chunk = mask[base : base + 4]
        if all(m >= 32 or m < 0 for m in chunk):
            keep_d = False
        elif all(chunk[i] == base + i for i in range(4) if chunk[i] >= 0):
            keep_d = True
        else:
            ok_ps = False
            break
        if keep_d:
            d_imm |= 1 << d
    if ok_ps:
        got = sim_vblendps(src, d_imm)
        if results_equiv(got, expected):
            alts.append(
                (
                    "blendps",
                    f"vxorps + vblendps ${d_imm}",
                    [],
                    asm_body(
                        [
                            "vxorps	%xmm1, %xmm1, %xmm1",
                            f"vblendps	${d_imm}, %ymm0, %ymm1, %ymm0",
                        ]
                    ),
                )
            )

    # UNPCK full patterns
    if results_equiv(sim_vpunpcklwd_zero(src), expected):
        alts.append(
            (
                "unpck",
                "vpxor + vpunpcklwd",
                [],
                asm_body(
                    ["vpxor	%xmm1, %xmm1, %xmm1", "vpunpcklwd	%ymm1, %ymm0, %ymm0"]
                ),
            )
        )
    if results_equiv(sim_vpunpcklbw_zero(src), expected):
        alts.append(
            (
                "unpck",
                "vpxor + vpunpcklbw",
                [],
                asm_body(
                    ["vpxor	%xmm1, %xmm1, %xmm1", "vpunpcklbw	%ymm1, %ymm0, %ymm0"]
                ),
            )
        )
    if results_equiv(sim_vpunpckhbw_zero(src), expected):
        alts.append(
            (
                "unpck",
                "vpxor + vpunpckhbw",
                [],
                asm_body(
                    ["vpxor	%xmm1, %xmm1, %xmm1", "vpunpckhbw	%ymm0, %ymm1, %ymm0"]
                ),
            )
        )

    # PACK: and + packuswb
    if results_equiv(sim_packuswb_and_zero(src), expected):
        # and mask 0x00FF per word
        and_bytes = []
        for i in range(32):
            and_bytes.append(255 if (i % 2) == 0 else 0)
        alts.append(
            (
                "pack",
                "vpand 0x00FF + vpackuswb zero",
                pool_bytes(and_bytes),
                asm_body(
                    [
                        "vpand	.LCPI0_0(%rip), %ymm0, %ymm0",
                        "vpxor	%xmm1, %xmm1, %xmm1",
                        "vpackuswb	%ymm1, %ymm0, %ymm0",
                    ]
                ),
            )
        )

    # Shift
    for amt in range(1, 16):
        if results_equiv(sim_vpslldq(src, amt), expected):
            alts.append(
                (
                    "shift",
                    f"vpslldq ${amt}",
                    [],
                    asm_body([f"vpslldq	${amt}, %ymm0, %ymm0"]),
                )
            )
            break

    # Deduplicate; drop same path as LLVM
    seen = set()
    uniq = []
    for path, reason, pools, body in alts:
        key = (path, body)
        if key in seen:
            continue
        seen.add(key)
        if path == llvm_path:
            continue
        # Also skip if body path class matches llvm (e.g. blend vs blendps both blend-like)
        uniq.append((path, reason, pools, body))
    return uniq


def extract_pools(asm: str) -> list[str]:
    pools: list[str] = []
    lines = asm.splitlines()
    i = 0
    while i < len(lines):
        if ".section" in lines[i] and "rodata" in lines[i]:
            start = i
            i += 1
            while i < len(lines) and not (
                lines[i].startswith("\t.text") or lines[i].strip() == ".text"
            ):
                i += 1
            pools.append("\n".join(lines[start:i]))
            if i < len(lines) and lines[i].strip() == ".text":
                i += 1
        else:
            i += 1
    return pools


def mca_run(mca: Path, pools: list[str], body: str, cpu: str) -> dict | None:
    asm = "\n".join(pools + ["	.text", "	.globl	mca_region", "mca_region:"]) + "\n" + body
    proc = subprocess.run(
        [str(mca), "-mtriple=x86_64-unknown", f"-mcpu={cpu}", f"-iterations={MCA_ITERS}"],
        input=asm,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        return {"error": proc.stderr[-500:]}
    return parse_mca(proc.stdout)


def run_llc(llc: Path, ir: str, asm_path: Path) -> str:
    ir_path = asm_path.with_suffix(".ll")
    ir_path.write_text(ir)
    subprocess.run(
        [str(llc), *LLC_FLAGS, str(ir_path), "-o", str(asm_path)],
        check=True,
        capture_output=True,
    )
    return asm_path.read_text()


def main() -> None:
    root = Path(sys.argv[1])
    llc = Path(sys.argv[2])
    mca = Path(sys.argv[3])
    out = root / "results/update3/step5a2"
    work = out / "work"
    work.mkdir(parents=True, exist_ok=True)

    results: list[CaseResult] = []
    all_cases = gen_masks()

    for family, case_list in all_cases.items():
        for case_id, mask, meta in case_list:
            w = work / family / case_id
            w.mkdir(parents=True, exist_ok=True)
            asm_path = w / "out.s"
            two_src = bool(meta.get("two_source"))
            try:
                asm = run_llc(llc, mask_to_ir(mask, two_source=two_src), asm_path)
            except subprocess.CalledProcessError as e:
                (w / "error.txt").write_text((e.stderr or b"").decode())
                continue

            llvm_path, insns, has_pool = classify_asm(asm)
            alts = find_alternatives(mask, llvm_path)
            # For two-source, skip our one-source alts
            if two_src:
                alts = []

            overlap = len(alts) > 0
            mca_data = None
            missed = False
            mca_wins = 0
            mca_losses = 0
            notes = ""

            if overlap:
                mca_data = {"llvm": {}, "alternatives": []}
                llvm_pools = extract_pools(asm)
                llvm_body = asm_body(insns)
                best = None
                best_score = None  # (wins, -losses, -sum_delta)

                for alt_path, reason, pools, body in alts:
                    alt_mca: dict = {}
                    wins = losses = 0
                    deltas = []
                    ok = True
                    for cpu in CPUS:
                        lm = mca_run(mca, llvm_pools, llvm_body, cpu)
                        am = mca_run(mca, pools, body, cpu)
                        if not lm or not am or "total_cycles" not in lm or "total_cycles" not in am:
                            ok = False
                            break
                        mca_data["llvm"][cpu] = lm
                        alt_mca[cpu] = am
                        d = am["total_cycles"] - lm["total_cycles"]
                        deltas.append(d)
                        if d < 0:
                            wins += 1
                        elif d > 0:
                            losses += 1
                    if not ok:
                        continue
                    entry = {
                        "path": alt_path,
                        "reason": reason,
                        "mca": alt_mca,
                        "deltas": dict(zip(CPUS, deltas)),
                        "wins": wins,
                        "losses": losses,
                    }
                    mca_data["alternatives"].append(entry)
                    score = (wins, -losses, -sum(deltas))
                    if best_score is None or score > best_score:
                        best_score = score
                        best = entry

                if best:
                    mca_data["alt_best"] = best["mca"]
                    mca_data["alt_path"] = best["path"]
                    mca_data["alt_reason"] = best["reason"]
                    mca_data["deltas"] = best["deltas"]
                    mca_wins = best["wins"]
                    mca_losses = best["losses"]
                    # Missed: alt wins on ≥2 CPUs, and does not lose on any CPU
                    # (or loses only on Zen while winning both Intel by ≥5 cycles)
                    if mca_wins >= 2 and mca_losses == 0:
                        missed = True
                        notes = "alt wins ≥2 CPUs with no losses"
                    elif mca_wins >= 2 and mca_losses == 1:
                        # require Intel wins of at least 5 cycles each
                        intel = [best["deltas"][c] for c in ("haswell", "skylake")]
                        if all(d <= -5 for d in intel) and best["deltas"]["znver1"] > 0:
                            # Zen prefers LLVM — mixed; only mark if Intel win is clear
                            # and Zen loss is not catastrophic relative to Intel win scale
                            # Require Zen loss ≤ 2x Intel win magnitude... actually for
                            # vandps vs blend, Zen loss is huge → NOT a miss.
                            if best["deltas"]["znver1"] < 50:
                                missed = True
                                notes = "Intel-only win; Zen nearly tied"
                            else:
                                notes = "Intel win but Zen strongly prefers LLVM — not a miss"
                        else:
                            notes = "mixed MCA; not counted as miss"

            results.append(
                CaseResult(
                    family=family,
                    case_id=case_id,
                    mask=mask,
                    llvm_path=llvm_path,
                    llvm_insns=insns,
                    llvm_insn_count=len(insns),
                    llvm_has_pool=has_pool,
                    alt_path=(mca_data or {}).get("alt_path"),
                    alt_legal=overlap,
                    alt_reason=(mca_data or {}).get("alt_reason", ""),
                    overlap=overlap,
                    missed=missed,
                    mca_wins=mca_wins,
                    mca_losses=mca_losses,
                    mca=mca_data,
                    notes=notes,
                )
            )

    summary: dict = {"by_family": {}, "missed_cases": [], "controls": {}, "near_misses": []}
    for fam in all_cases:
        sub = [r for r in results if r.family == fam]
        summary["by_family"][fam] = {
            "tested": len(sub),
            "overlap": sum(1 for r in sub if r.overlap),
            "missed": sum(1 for r in sub if r.missed),
            "llvm_paths": {},
        }
        for r in sub:
            summary["by_family"][fam]["llvm_paths"][r.llvm_path] = (
                summary["by_family"][fam]["llvm_paths"].get(r.llvm_path, 0) + 1
            )

    summary["missed_cases"] = [asdict(r) for r in results if r.missed]

    # Near misses: alt wins ≥1 CPU
    for r in results:
        if r.missed or not r.mca or not r.mca.get("deltas"):
            continue
        if r.mca_wins >= 1:
            summary["near_misses"].append(
                {
                    "family": r.family,
                    "case_id": r.case_id,
                    "llvm_path": r.llvm_path,
                    "alt_path": r.alt_path,
                    "deltas": r.mca["deltas"],
                    "notes": r.notes,
                }
            )

    pos = [r for r in results if r.family == "control_pos_shift"]
    neg = [r for r in results if r.family == "control_neg_blend"]
    neg_ok = 0
    for r in neg:
        if not r.mca or not r.mca.get("alternatives"):
            continue
        # find pshufb alt
        for alt in r.mca["alternatives"]:
            if alt["path"] == "pshufb":
                if all(alt["deltas"][c] >= 0 for c in CPUS):
                    neg_ok += 1
                break
        else:
            # LLVM is blend; pshufb should be in alts when overlap
            if r.llvm_path == "blend" and any(
                a["path"] == "pshufb" and all(a["deltas"][c] >= 0 for c in CPUS)
                for a in r.mca.get("alternatives", [])
            ):
                neg_ok += 1

    summary["controls"] = {
        "positive_shift_optimal": sum(1 for r in pos if r.llvm_path == "shift"),
        "positive_shift_tested": len(pos),
        "negative_blend_beats_or_ties_pshufb": neg_ok,
        "negative_tested": len(neg),
    }

    (out / "results.json").write_text(json.dumps([asdict(r) for r in results], indent=2))
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
