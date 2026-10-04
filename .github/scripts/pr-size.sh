#!/usr/bin/env bash
# Report how big the current branch is against the PR size rule in CLAUDE.md.
# Lock files, test data and generated files are not counted.
# Usage: pr-size.sh [base-ref]   (default: origin/main)
# Exits 1 when the branch is over either limit.
set -euo pipefail

base="${1:-origin/main}"
max_lines=400
max_files=10

lines=0
files=0
while IFS=$'\t' read -r added deleted path; do
  [ -z "$path" ] && continue
  # Binary files show "-" for both counts.
  [ "$added" = "-" ] && added=0
  [ "$deleted" = "-" ] && deleted=0
  lines=$((lines + added + deleted))
  files=$((files + 1))
done < <(git diff --numstat "$base"...HEAD -- . \
  ':(exclude,glob)**/*.lock' \
  ':(exclude,glob)**/fixtures/**' \
  ':(exclude,glob)**/*.csv' \
  ':(exclude,glob)**/*.csv.gz' \
  ':(exclude,glob)**/*.parquet' \
  ':(exclude,glob)**/generated/**')

echo "Changed lines: $lines (limit $max_lines)"
echo "Changed files: $files (limit $max_files)"

if [ "$lines" -gt "$max_lines" ] || [ "$files" -gt "$max_files" ]; then
  echo "Over the size limit: split the task."
  exit 1
fi
echo "Within the size limit."
