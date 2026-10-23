#!/usr/bin/env bash
# Runs every test with in-memory storage and with a fake Upstash Redis.
# Usage: tests/run_all.sh [python]   (default python3). Exits 1 if any fail.
cd "$(dirname "$0")" || exit 1
PY="${1:-python3}"
failed=0
for mode in memory redis; do
  for t in test_*.py; do
    out=$(timeout 300 "$PY" "$t" "$mode" 2>&1)
    if echo "$out" | grep -q "^FAIL\|^Traceback"; then
      failed=1
      echo "✗ $t ($mode)"
      echo "$out" | grep -A8 "^FAIL\|^Traceback" | head -12 | sed 's/^/    /'
    else
      echo "✓ $t ($mode): $(echo "$out" | grep -c '^PASS') checks"
    fi
  done
done
[ "$failed" = 0 ] && echo "All tests passed." || { echo "Some tests failed."; exit 1; }
