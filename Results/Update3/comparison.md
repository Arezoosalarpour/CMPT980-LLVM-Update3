# Before/after instruction summary (baseline vs patched)

Step 1 baseline: `results/update3/baseline/sparse_variant_*.s`  
Step 2 patched: `results/update3/patched/sparse_variant_*.s`  
Full reports: [`PATCHED_SUMMARY.md`](PATCHED_SUMMARY.md), [`../baseline/BASELINE_SUMMARY.md`](../baseline/BASELINE_SUMMARY.md)

## Variant A
Baseline:
	vpxor	%xmm1, %xmm1, %xmm1
	vpblendw	$17, %ymm0, %ymm1, %ymm0        ## ymm0 = ymm0[0],ymm1[1,2,3],ymm0[4],ymm1[5,6,7],ymm0[8],ymm1[9,10,11],ymm0[12],ymm1[13,14,15]
Patched:
	vpshufb	LCPI0_0(%rip), %ymm0, %ymm0     ## ymm0 = ymm0[0,1],zero,zero,zero,zero,zero,zero,ymm0[8,9],zero,zero,zero,zero,zero,zero,ymm0[16,17],zero,zero,zero,zero,zero,zero,ymm0[24,25],zero,zero,zero,zero,zero,zero

## Variant B
Baseline:
	vpshufb	LCPI0_0(%rip), %ymm0, %ymm0     ## ymm0 = ymm0[2,3],zero,zero,zero,zero,zero,zero,ymm0[10,11],zero,zero,zero,zero,zero,zero,ymm0[18,19],zero,zero,zero,zero,zero,zero,ymm0[26,27],zero,zero,zero,zero,zero,zero
Patched:
	vpshufb	LCPI0_0(%rip), %ymm0, %ymm0     ## ymm0 = ymm0[2,3],zero,zero,zero,zero,zero,zero,ymm0[10,11],zero,zero,zero,zero,zero,zero,ymm0[18,19],zero,zero,zero,zero,zero,zero,ymm0[26,27],zero,zero,zero,zero,zero,zero

## Variant C
Baseline:
	vpxor	%xmm1, %xmm1, %xmm1
	vpblendw	$170, %ymm1, %ymm0, %ymm0       ## ymm0 = ymm0[0],ymm1[1],ymm0[2],ymm1[3],ymm0[4],ymm1[5],ymm0[6],ymm1[7],ymm0[8],ymm1[9],ymm0[10],ymm1[11],ymm0[12],ymm1[13],ymm0[14],ymm1[15]
Patched:
	vpshufb	LCPI0_0(%rip), %ymm0, %ymm0     ## ymm0 = ymm0[0,1],zero,zero,ymm0[4,5],zero,zero,ymm0[8,9],zero,zero,ymm0[12,13],zero,zero,ymm0[16,17],zero,zero,ymm0[20,21],zero,zero,ymm0[24,25],zero,zero,ymm0[28,29],zero,zero

