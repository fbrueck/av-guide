#!/usr/bin/env sh
# Bare-dict ratchet. Counts untyped-collection annotations (mypy
# --disallow-any-generics, rule [type-arg]) and fails if the count rises above
# the committed baseline. This is the mechanical half of "domain records are
# dataclasses, not dicts" (see data-pipeline/CLAUDE.md): a new `entry: dict` or
# `dict[str, dict]` pushes the count up and breaks the build. Ratchet the
# baseline DOWN as records become dataclasses; never up.
#
# Run from a package dir: cd data-pipeline/<pkg> && ../dict-ratchet.sh
set -eu

baseline_file=".dict-baseline"
[ -f "$baseline_file" ] || { echo "dict-ratchet: no $baseline_file in $(pwd)" >&2; exit 1; }
baseline=$(cat "$baseline_file")

count=$(uv run mypy --config-file ../../mypy.ini --disallow-any-generics pipeline 2>&1 \
  | grep -c 'type-arg' || true)

echo "dict-ratchet: $count untyped dict/collection annotations (baseline $baseline)"

if [ "$count" -gt "$baseline" ]; then
  echo "FAIL: $((count - baseline)) above baseline. New domain records must be" \
       "dataclasses, not dicts — convert at the I/O boundary, or type the" \
       "collection. See data-pipeline/CLAUDE.md." >&2
  exit 1
fi
if [ "$count" -lt "$baseline" ]; then
  echo "Ratchet down: set $baseline_file to $count to lock in the win." >&2
fi
