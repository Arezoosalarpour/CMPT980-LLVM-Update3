// Semantic verifier for llc-generated sparse shuffle variants.
// Links against object files produced from update2_sparse_variant_*.ll.
#include <immintrin.h>
#include <stdint.h>
#include <stdio.h>

typedef __m256i (*shuffle_fn)(__m256i);

extern __m256i sparse_variant_a(__m256i);
extern __m256i sparse_variant_b(__m256i);
extern __m256i sparse_variant_c(__m256i);

static void apply_sv(const uint8_t *in, const int *sv, uint8_t *out) {
  for (int i = 0; i < 32; i++)
    out[i] = (sv[i] >= 32) ? 0 : in[sv[i]];
}

static int cmp_fn(const char *name, const uint8_t *ref, shuffle_fn fn) {
  uint8_t in[32], got[32];
  for (int i = 0; i < 32; i++)
    in[i] = (uint8_t)(i + 1);
  _mm256_storeu_si256((__m256i *)got,
                      fn(_mm256_loadu_si256((__m256i *)in)));
  int diff = 0;
  for (int i = 0; i < 32; i++) {
    if (ref[i] != got[i]) {
      if (!diff)
        printf("%s MISMATCH\n", name);
      printf("  byte %d ref=%u got=%u\n", i, ref[i], got[i]);
      diff++;
    }
  }
  if (!diff)
    printf("%s: MATCH (shufflevector semantics)\n", name);
  return diff;
}

int main(void) {
  static const int sv_a[32] = {
      0, 1, 32, 32, 32, 32, 32, 32, 8, 9, 32, 32, 32, 32, 32, 32,
      16, 17, 48, 48, 48, 48, 48, 48, 24, 25, 48, 48, 48, 48, 48, 48};
  static const int sv_b[32] = {
      2, 3, 32, 32, 32, 32, 32, 32, 10, 11, 32, 32, 32, 32, 32, 32,
      18, 19, 48, 48, 48, 48, 48, 48, 26, 27, 48, 48, 48, 48, 48, 48};
  static const int sv_c[32] = {
      0, 1, 32, 32, 4, 5, 32, 32, 8, 9, 32, 32, 12, 13, 32, 32,
      16, 17, 48, 48, 20, 21, 48, 48, 24, 25, 48, 48, 28, 29, 48, 48};

  uint8_t ref_a[32], ref_b[32], ref_c[32];
  uint8_t in[32];
  for (int i = 0; i < 32; i++)
    in[i] = (uint8_t)(i + 1);
  apply_sv(in, sv_a, ref_a);
  apply_sv(in, sv_b, ref_b);
  apply_sv(in, sv_c, ref_c);

  int err = 0;
  err += cmp_fn("patched_variant_a", ref_a, sparse_variant_a);
  err += cmp_fn("patched_variant_b", ref_b, sparse_variant_b);
  err += cmp_fn("patched_variant_c", ref_c, sparse_variant_c);
  return err ? 1 : 0;
}
