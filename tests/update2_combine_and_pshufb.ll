; Extracted from llvm/test/CodeGen/X86/vector-shuffle-combining-avx2.ll
; @combine_and_pshufb
target datalayout = "e-m:o-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-apple-macos"

declare <32 x i8> @llvm.x86.avx2.pshuf.b(<32 x i8>, <32 x i8>)

define <32 x i8> @combine_and_pshufb(<32 x i8> %a0) {
  %1 = shufflevector <32 x i8> %a0, <32 x i8> zeroinitializer,
    <32 x i32> <i32 0, i32 1, i32 32, i32 32, i32 4, i32 5, i32 6, i32 7,
                i32 8, i32 9, i32 10, i32 11, i32 12, i32 13, i32 14, i32 15,
                i32 16, i32 17, i32 18, i32 19, i32 20, i32 21, i32 22, i32 23,
                i32 24, i32 25, i32 26, i32 27, i32 28, i32 29, i32 30, i32 31>
  %2 = call <32 x i8> @llvm.x86.avx2.pshuf.b(<32 x i8> %1,
    <32 x i8> <i8 0, i8 1, i8 -1, i8 -1, i8 -1, i8 -1, i8 -1, i8 -1,
               i8 8, i8 9, i8 -1, i8 -1, i8 -1, i8 -1, i8 -1, i8 -1,
               i8 0, i8 1, i8 -1, i8 -1, i8 -1, i8 -1, i8 -1, i8 -1,
               i8 8, i8 9, i8 -1, i8 -1, i8 -1, i8 -1, i8 -1, i8 -1>)
  ret <32 x i8> %2
}
