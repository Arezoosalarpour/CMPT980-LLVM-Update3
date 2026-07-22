#include <stdio.h>
#include <stdint.h>
#include <immintrin.h>

static void apply_sv(const uint8_t *in, const int *sv, uint8_t *out) {
  for (int i = 0; i < 32; i++)
    out[i] = (sv[i] >= 32) ? 0 : in[sv[i]];
}

static int cmp_pshufb(const char *name, const uint8_t *ref, __m256i (*fn)(__m256i)) {
  uint8_t in[32], got[32];
  for (int i = 0; i < 32; i++)
    in[i] = (uint8_t)(i + 1);
  _mm256_storeu_si256((__m256i *)got, fn(_mm256_loadu_si256((__m256i *)in)));
  int diff = 0;
  for (int i = 0; i < 32; i++)
    if (ref[i] != got[i]) {
      if (!diff)
        printf("%s MISMATCH\n", name);
      printf("  byte %d ref=%u got=%u\n", i, ref[i], got[i]);
      diff++;
    }
  if (!diff)
    printf("%s: MATCH (vpshufb equivalent)\n", name);
  return diff;
}

static __m256i pshuf_a(__m256i a) {
  const __m256i m = _mm256_setr_epi8(
      0, 1, -1, -1, -1, -1, -1, -1, 8, 9, -1, -1, -1, -1, -1, -1,
      0, 1, -1, -1, -1, -1, -1, -1, 8, 9, -1, -1, -1, -1, -1, -1);
  return _mm256_shuffle_epi8(a, m);
}

static __m256i pshuf_b(__m256i a) {
  const __m256i m = _mm256_setr_epi8(
      2, 3, -1, -1, -1, -1, -1, -1, 10, 11, -1, -1, -1, -1, -1, -1,
      2, 3, -1, -1, -1, -1, -1, -1, 10, 11, -1, -1, -1, -1, -1, -1);
  return _mm256_shuffle_epi8(a, m);
}

static __m256i pshuf_c(__m256i a) {
  const __m256i m = _mm256_setr_epi8(
      0, 1, -1, -1, 4, 5, -1, -1, 8, 9, -1, -1, 12, 13, -1, -1,
      0, 1, -1, -1, 4, 5, -1, -1, 8, 9, -1, -1, 12, 13, -1, -1);
  return _mm256_shuffle_epi8(a, m);
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

  uint8_t in[32], ref_a[32], ref_b[32], ref_c[32];
  for (int i = 0; i < 32; i++)
    in[i] = (uint8_t)(i + 1);
  apply_sv(in, sv_a, ref_a);
  apply_sv(in, sv_b, ref_b);
  apply_sv(in, sv_c, ref_c);

  int err = 0;
  err += cmp_pshufb("variant_a", ref_a, pshuf_a);
  err += cmp_pshufb("variant_b", ref_b, pshuf_b);
  err += cmp_pshufb("variant_c", ref_c, pshuf_c);
  return err ? 1 : 0;
}
