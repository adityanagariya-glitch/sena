#!/usr/bin/env bash
# pre-tool-use.sh — PreToolUse hook
# Reads event JSON from stdin, exits 0 (no blocking rules active)

cat &>/dev/null || true
exit 0
