; Update 2 sparse byte-select family — Variant A
; Keep bytes 0,1,8,9 per 128-bit lane; zero the rest (= @combine_and_pshufb semantics)
target datalayout = "e-m:o-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-apple-macos"

define <32 x i8> @sparse_variant_a(<32 x i8> %a0) {
  %out = shufflevector <32 x i8> %a0, <32 x i8> zeroinitializer,
    <32 x i32> <i32 0, i32 1, i32 32, i32 32, i32 32, i32 32, i32 32, i32 32,
                i32 8, i32 9, i32 32, i32 32, i32 32, i32 32, i32 32, i32 32,
                i32 16, i32 17, i32 48, i32 48, i32 48, i32 48, i32 48, i32 48,
                i32 24, i32 25, i32 48, i32 48, i32 48, i32 48, i32 48, i32 48>
  ret <32 x i8> %out
}
