#!/usr/bin/env bash
# Browser tests for the chat page (Stage 0). Runs after run_all.sh so the
# fast suite stays fast: run_all runs first, before Playwright is
# installed, and test_chat_dom.py SKIPs there. This script installs
# nothing; CI installs requirements-test.txt + Chromium first, and
# BROWSER_STRICT turns a missing Playwright into a failure here.
# Usage: tests/run_browser.sh [python]   (default python3).
cd "$(dirname "$0")" || exit 1
PY="${1:-python3}"
BROWSER_STRICT=1 timeout 600 "$PY" test_chat_dom.py memory
