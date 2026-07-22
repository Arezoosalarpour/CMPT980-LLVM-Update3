#!/usr/bin/env bash
# Shared Update 3 environment helpers.
# Source from scripts:
#   source "$(cd "$(dirname "$0")" && pwd)/common.sh"
#
# REQUIRED (no silent same-binary defaults):
#   export LLVM_UNPATCHED_LLC=/path/to/unpatched/bin/llc
#   export LLVM_PATCHED_LLC=/path/to/patched/bin/llc
#
# Also set for Steps 3C / 4 / 5 as needed:
#   export LLVM_FILECHECK=/path/to/patched/bin/FileCheck
#   export LLVM_MCA=/path/to/patched/bin/llvm-mca
#
# Optional path hints (not used as llc defaults):
#   export LLVM_PROJECT=$HOME/llvm-project
#   export LLVM_BUILD=$LLVM_PROJECT/build-x86          # patched build tree
#   export LIT_TEST=$LLVM_PROJECT/llvm/test/CodeGen/X86/vector-shuffle-combining-avx2.ll

: "${LLVM_PROJECT:=$HOME/llvm-project}"
: "${LLVM_BUILD:=$LLVM_PROJECT/build-x86}"
: "${LLVM_SRC:=$LLVM_PROJECT/llvm/lib/Target/X86/X86ISelLowering.cpp}"
: "${LIT_TEST:=$LLVM_PROJECT/llvm/test/CodeGen/X86/vector-shuffle-combining-avx2.ll}"

# LLVM_UNPATCHED_LLC / LLVM_PATCHED_LLC / LLVM_FILECHECK / LLVM_MCA are NOT
# defaulted here. Scripts must call require_* so misconfiguration fails loudly.

require_exe() {
  local path=$1 label=$2
  if [[ -z "$path" ]]; then
    echo "error: $label is unset." >&2
    echo "Configure it to an absolute path before running this script." >&2
    exit 1
  fi
  if [[ ! -x "$path" ]]; then
    echo "error: $label not found or not executable: $path" >&2
    exit 1
  fi
}

_llc_realpath() {
  local p=$1
  if command -v realpath >/dev/null 2>&1; then
    realpath "$p"
  else
    python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$p"
  fi
}

require_unpatched_llc() {
  if [[ -z "${LLVM_UNPATCHED_LLC:-}" ]]; then
    cat >&2 <<'EOF'
error: LLVM_UNPATCHED_LLC is not set.

Step 1 and other unpatched roles require a separate llc built from stock
LLVM 17.0.6 (WITHOUT this project's X86ISelLowering patch).

Example:
  export LLVM_UNPATCHED_LLC=$HOME/llvm-project-unpatched/build-x86/bin/llc

Do not point LLVM_UNPATCHED_LLC at a patched build. Scripts will not stash,
modify, or rebuild the LLVM source tree for you.
EOF
    exit 1
  fi
  require_exe "$LLVM_UNPATCHED_LLC" "LLVM_UNPATCHED_LLC"
}

require_patched_llc() {
  if [[ -z "${LLVM_PATCHED_LLC:-}" ]]; then
    cat >&2 <<'EOF'
error: LLVM_PATCHED_LLC is not set.

Patched steps require an llc built AFTER applying:
  results/update3/step3c/X86ISelLowering.patch

Example:
  export LLVM_PATCHED_LLC=$HOME/llvm-project/build-x86/bin/llc
EOF
    exit 1
  fi
  require_exe "$LLVM_PATCHED_LLC" "LLVM_PATCHED_LLC"
}

require_filecheck() {
  if [[ -z "${LLVM_FILECHECK:-}" ]]; then
    cat >&2 <<'EOF'
error: LLVM_FILECHECK is not set.

Example (usually from the patched build):
  export LLVM_FILECHECK=$HOME/llvm-project/build-x86/bin/FileCheck
EOF
    exit 1
  fi
  require_exe "$LLVM_FILECHECK" "LLVM_FILECHECK"
}

require_mca() {
  if [[ -z "${LLVM_MCA:-}" ]]; then
    cat >&2 <<'EOF'
error: LLVM_MCA is not set.

Example (usually from the patched build):
  export LLVM_MCA=$HOME/llvm-project/build-x86/bin/llvm-mca
EOF
    exit 1
  fi
  require_exe "$LLVM_MCA" "LLVM_MCA"
}

# Ensure unpatched and patched llc paths are not the same executable unless the
# user explicitly opts in (discouraged; roles can be mixed accidentally).
require_distinct_llc_roles() {
  require_unpatched_llc
  require_patched_llc
  local u p
  u=$(_llc_realpath "$LLVM_UNPATCHED_LLC")
  p=$(_llc_realpath "$LLVM_PATCHED_LLC")
  if [[ "$u" == "$p" ]]; then
    if [[ "${ALLOW_SAME_LLC:-0}" == "1" ]]; then
      echo "WARNING: LLVM_UNPATCHED_LLC and LLVM_PATCHED_LLC resolve to the same file:" >&2
      echo "  $u" >&2
      echo "ALLOW_SAME_LLC=1 is set; proceeding, but roles may be wrong." >&2
      return 0
    fi
    cat >&2 <<EOF
error: LLVM_UNPATCHED_LLC and LLVM_PATCHED_LLC resolve to the same executable:

  $u

Configure two separate builds (stock vs patched LLVM 17.0.6).
If you intentionally reuse one binary across carefully sequenced rebuilds,
set ALLOW_SAME_LLC=1 (not recommended).
EOF
    exit 1
  fi
}
