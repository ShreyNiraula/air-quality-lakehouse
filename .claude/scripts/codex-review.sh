#!/usr/bin/env bash
# Ask Codex to review a pull request and wait until it responds.
# Usage: codex-review.sh <pr-number> [timeout-minutes]   (default: 20)
# Prints what Codex did and exits 0, or exits 2 if it did not respond in time.
set -euo pipefail

pr="$1"
timeout_min="${2:-20}"
bot="chatgpt-codex-connector[bot]"
repo="$(gh repo view --json nameWithOwner --jq .nameWithOwner)"

comment_url="$(gh pr comment "$pr" --body "@codex review")"
comment_id="${comment_url##*issuecomment-}"
since="$(gh api "repos/$repo/issues/comments/$comment_id" --jq .created_at)"
echo "Asked Codex for a review at $since"

# Count what the bot created at or after the request. Timestamps are ISO 8601, so they sort as text.
# A failed request counts as zero, so one network error does not end the wait.
# Usage: bot_items <api path> <timestamp field> [extra jq condition]
bot_items() {
  { gh api "$1" --paginate \
      --jq ".[] | select(.user.login == \"$bot\" and $2 >= \"$since\"${3:+ and $3}) | .id" 2>/dev/null || true; } \
    | wc -l | tr -d ' '
}

deadline=$(( $(date +%s) + timeout_min * 60 ))
while [ "$(date +%s)" -lt "$deadline" ]; do
  reviews="$(bot_items "repos/$repo/pulls/$pr/reviews" .submitted_at)"
  comments="$(bot_items "repos/$repo/issues/$pr/comments" .created_at)"
  thumbs_request="$(bot_items "repos/$repo/issues/comments/$comment_id/reactions" .created_at '.content == "+1"')"
  thumbs_pr="$(bot_items "repos/$repo/issues/$pr/reactions" .created_at '.content == "+1"')"

  # With nothing to report, Codex reacts to the pull request with a thumbs-up and also posts a short comment.
  if [ "$thumbs_request" -gt 0 ] || [ "$thumbs_pr" -gt 0 ]; then
    echo "Codex reacted with a thumbs-up: nothing to report."
    exit 0
  fi
  if [ "$reviews" -gt 0 ] || [ "$comments" -gt 0 ]; then
    echo "Codex responded: $reviews review(s), $comments comment(s)."
    exit 0
  fi
  sleep 30
done

echo "Codex did not respond within $timeout_min minutes."
exit 2
