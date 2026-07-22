# Step 5A2 — Missed lowering opportunity search

## Scope

Search three Step 5A1 overlap families with **unmodified LLVM 17.0.6**
(project patch temporarily removed for this measurement, then restored).

For each generated mask: baseline `llc`, **semantically verified** alternative
sequences, llvm-mca on Haswell / Skylake / Zen1. **No LLVM source or test edits.**

Success criteria for a missed opportunity:

1. LLVM selects one legal sequence;
2. a different **semantically equivalent** sequence exists;
3. the alternative has lower llvm-mca cycles on ≥2 CPUs;
4. the alternative does not lose on any CPU (or Zen loss is negligible);
5. the mask is a structural family, not a one-off constant.

Controls:

- **Positive:** byte-shift (`pslldq`) — LLVM should already choose well.
- **Negative:** Variant A/C blend vs PSHUFB — fewer instructions must not be treated as cheaper.

---

## Summary counts

| Family | Masks tested | Overlapping legal lowerings | LLVM choice measurably worse |
|--------|--------------|----------------------------|------------------------------|
| **zext** (Zero/AnyExtend vs PSHUFB) | 73 | 73 | **0** |
| **unpck** (VPUNPCK vs PSHUFB) | 10 | 4 | **0** |
| **pack** (VPACK vs dual/single PSHUFB) | 5 | 1 | **0** |
| **control_pos_shift** | 15 | 15 | **0** |
| **control_neg_blend** | 2 | 2 | **0** |
| **TOTAL** | **105** | **95** | **0** |

### Per-family LLVM path distribution

- **zext:** `bitmask`×40, `blend`×27, `movq`×1, `other`×5
- **unpck:** `unpck`×3 (full patterns), `pshufb`×6 (partial prefixes), `blend`×1
- **pack:** `pshufb`×4, dual-`vpshufb`+`vpblendd`×1
- **control_pos_shift:** `shift`×15
- **control_neg_blend:** `blend`×2

### Controls

- **Positive (byte shift):** LLVM chose `vpslldq` in **15 / 15** cases.
- **Negative (A/C blend vs PSHUFB):** blend ≤ PSHUFB on MCA for **2 / 2** variants.

---

## Findings by family

### 1. Zero/AnyExtend versus PSHUFB

Prefix / suffix / sparse identity-or-zero masks. Unpatched LLVM typically selects
`vblendps`/`vpblendw` (dword/word aligned) or `vandps` (byte keep-mask), **not** PSHUFB.

Where PSHUFB or the other specialized path is also legal:

- Blend vs bitmask shows **CPU disagreement**: blend wins Haswell/Skylake (~−7 cycles);
  pool `vandps` wins Zen by a large margin (~−494). Neither dominates ≥2 CPUs without a loss.
- Bitmask vs PSHUFB is essentially a wash (±1–2 cycles).

**No missed lowering** meeting success criteria.

### 2. VPUNPCK interleave-zero versus PSHUFB

| Pattern | LLVM choice | Notes |
|---------|-------------|-------|
| Full `vpunpcklwd` / `lbw` / `hbw` + zero | **`vpunpck*`** | Already optimal |
| Partial unpack prefixes | `vpshufb` or `vpblendw` | Full UNPCK is **not** equivalent (would keep extra lanes) |

**No missed lowering** — when UNPCK is legal, LLVM already selects it.

### 3. VPACK compaction versus dual-PSHUFB

| Case | LLVM | Legal alt | MCA |
|------|------|-----------|-----|
| `even_compact_low8` | 1× `vpshufb` | `vpand` + `vpackuswb` | **PSHUFB much cheaper** (~1010 vs ~8004) |
| `packus_two_source` | 2× `vpshufb` + `vpblendd` | 2× `vpand` + `vpackuswb` | **Near-tie** (~8005 vs ~8004); not a clear win |
| Odd / high-half compact | 1× `vpshufb` | (no cheaper verified alt) | LLVM fine |

True “PACK vs dual-PSHUFB” from Step 5A1 lit (`@shuffle_combine_packsswb_pshufb`) is a
**combine** rewrite of multi-op DAGs; as a single `shufflevector`, LLVM’s PSHUFB (or near-tie
PACK) is not a defensible miss.

---

## Missed lowering opportunities

**None found.**

| Question | Answer |
|----------|--------|
| Masks tested per family | zext 73, unpck 10, pack 5 (+17 controls) |
| Overlapping legal lowerings | 95 / 105 |
| Any current LLVM choice measurably worse? | **No** (0 under success criteria) |
| Three strongest missed-lowering candidates | **None** — do not recommend optimal cases |
| Single best candidate for implementation | **None** |

### Why the Step 5A1 “promising” families did not yield a miss

1. **Zext:** LLVM already prefers blend/`vandps`/`vmovq` over PSHUFB for these shapes.
2. **UNPCK:** LLVM already emits `vpunpck*` on exact full patterns.
3. **PACK:** Single-input compaction prefers 1× PSHUFB; two-source AND+PACK only ties dual-PSHUFB.

Near misses (alt wins on 1 CPU, or wins Intel but loses badly on Zen) are documented in
[`summary.json`](summary.json) under `near_misses` — **not** implementation candidates.

---

## Three strongest *observed* overlaps (not implementation candidates)

These are the closest structural overlaps; **none** clear the success bar:

1. **Identity-or-zero blend vs pool bitmask** — CPU-dependent; Zen favors `vandps`, Intel favors `vpblendw`/`vblendps`.
2. **Two-source even-byte pack** (`packus_two_source`) — dual-`vpshufb`+blend ≈ AND+`vpackuswb` (tie).
3. **Partial unpack prefixes** — LLVM uses `vpshufb`; full UNPCK is illegal for those masks.

**Do not implement** these; they do not show a consistently better missed path.

---

## Method

- IR: `shufflevector <32 x i8>` with `zeroinitializer` (two-source for pack).
- Alternatives accepted only if byte-level simulation matches the shuffle mask.
- MCA: 1000 iterations, isolated body, `ret` excluded.
- Unmodified LLVM: patch saved to `llvm_lowering.patch.save`, tree checked out to HEAD, `llc` rebuilt, then patch restored.

## Artifacts

| Path | Description |
|------|-------------|
| [`results.json`](results.json) | Per-mask results |
| [`summary.json`](summary.json) | Aggregates + near_misses |
| [`work/`](work/) | Per-case `.ll` / `.s` |
| [`commands.log`](commands.log) | Reproduce log |
| [`llvm_lowering.patch.save`](llvm_lowering.patch.save) | Project patch snapshot from this run |
