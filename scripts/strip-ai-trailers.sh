#!/usr/bin/env bash
f="$1"
grep -v -i -E '^(Co-Authored-By: Claude|.*Generated with \[Claude Code\])' "$f" > "$f.tmp" || true
mv "$f.tmp" "$f"
