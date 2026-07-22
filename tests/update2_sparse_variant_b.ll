; Update 2 sparse byte-select family — Variant B
; Keep bytes 2,3,10,11 per 128-bit lane; zero the rest
target datalayout = "e-m:o-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-apple-macos"

define <32 x i8> @sparse_variant_b(<32 x i8> %a0) {
  %out = shufflevector <32 x i8> %a0, <32 x i8> zeroinitializer,
    <32 x i32> <i32 2, i32 3, i32 32, i32 32, i32 32, i32 32, i32 32, i32 32,
                i32 10, i32 11, i32 32, i32 32, i32 32, i32 32, i32 32, i32 32,
                i32 18, i32 19, i32 48, i32 48, i32 48, i32 48, i32 48, i32 48,
                i32 26, i32 27, i32 48, i32 48, i32 48, i32 48, i32 48, i32 48>
  ret <32 x i8> %out
}
