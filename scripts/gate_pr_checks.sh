#!/bin/bash
#
# Gate PR Checks - Fail if any GitHub check is not SUCCESS
#
# Usage:
#   ./scripts/gate_pr_checks.sh <PR_NUMBER>
#   ./scripts/gate_pr_checks.sh <PR_NUMBER> --repo owner/repo
#
# Exit codes:
#   0 - All checks passed (SUCCESS)
#   1 - Some checks failed or are pending
#   2 - Invalid arguments or gh CLI error
#
# Example n8n integration:
#   Execute this script before merge/tag/release steps
#   If exit code != 0, stop the workflow
#

set -euo pipefail

PR_NUMBER="${1:-}"
REPO_FLAG=""

if [[ -z "$PR_NUMBER" ]]; then
    echo "ERROR: PR number required"
    echo "Usage: $0 <PR_NUMBER> [--repo owner/repo]"
    exit 2
fi

# Parse optional --repo flag
shift
while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo)
            REPO_FLAG="--repo $2"
            shift 2
            ;;
        *)
            echo "ERROR: Unknown argument: $1"
            exit 2
            ;;
    esac
done

echo "Checking PR #${PR_NUMBER} status..."

# Get status check rollup
STATUS_JSON=$(gh pr view "$PR_NUMBER" $REPO_FLAG --json statusCheckRollup 2>&1) || {
    echo "ERROR: Failed to get PR status"
    echo "$STATUS_JSON"
    exit 2
}

# Count non-SUCCESS checks
FAILED_COUNT=$(echo "$STATUS_JSON" | jq '[.statusCheckRollup[] | select(.conclusion != "SUCCESS" and .conclusion != null)] | length')
PENDING_COUNT=$(echo "$STATUS_JSON" | jq '[.statusCheckRollup[] | select(.conclusion == null)] | length')
TOTAL_COUNT=$(echo "$STATUS_JSON" | jq '.statusCheckRollup | length')

echo "Total checks: $TOTAL_COUNT"
echo "Passed: $((TOTAL_COUNT - FAILED_COUNT - PENDING_COUNT))"
echo "Pending: $PENDING_COUNT"
echo "Failed: $FAILED_COUNT"

if [[ "$PENDING_COUNT" -gt 0 ]]; then
    echo ""
    echo "GATE BLOCKED: $PENDING_COUNT checks still pending"
    echo "Pending checks:"
    echo "$STATUS_JSON" | jq -r '.statusCheckRollup[] | select(.conclusion == null) | "  - \(.name // .context)"'
    exit 1
fi

if [[ "$FAILED_COUNT" -gt 0 ]]; then
    echo ""
    echo "GATE BLOCKED: $FAILED_COUNT checks failed"
    echo "Failed checks:"
    echo "$STATUS_JSON" | jq -r '.statusCheckRollup[] | select(.conclusion != "SUCCESS" and .conclusion != null) | "  - \(.name // .context): \(.conclusion)"'
    exit 1
fi

echo ""
echo "GATE PASSED: All $TOTAL_COUNT checks succeeded"
exit 0
