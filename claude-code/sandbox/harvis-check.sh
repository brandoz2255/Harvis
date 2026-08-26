#!/usr/bin/env bash
# Syntax-check files in the Harvis Claude sandbox. Exit 0 if nothing is broken.
set -u
root="$(cd "$(dirname "$0")" && pwd)"
cd "$root" || exit 1
fail=0
skip='./SANDBOX.md ./README.md ./notes.md ./harvis-check.sh'

check() {
  local f="$1"
  case "$f" in
    ./SANDBOX.md|./README.md|./notes.md|./harvis-check.sh) return 0 ;;
  esac
  case "$f" in
    *.py)
      if command -v python3 >/dev/null 2>&1; then
        python3 -m py_compile "$f" || fail=1
      fi
      ;;
    *.js|*.mjs|*.cjs)
      if command -v node >/dev/null 2>&1; then
        node --check "$f" || fail=1
      fi
      ;;
    *.sh)
      bash -n "$f" || fail=1
      ;;
  esac
}

while IFS= read -r -d '' f; do
  check "$f"
done < <(find . -type f \( -name '*.py' -o -name '*.js' -o -name '*.mjs' -o -name '*.cjs' -o -name '*.sh' \) -print0 2>/dev/null)

if [ "$fail" -ne 0 ]; then
  echo "harvis-check: something failed syntax check" >&2
  exit 1
fi
echo "harvis-check: ok"
exit 0
