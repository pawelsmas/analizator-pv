#!/bin/bash
# promtool_check.sh - Validate Prometheus recording rules
# Version: v3.9.0
#
# Usage: ./scripts/monitoring/promtool_check.sh
# Or:    make promtool-check

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if promtool is available
check_promtool() {
    if ! command -v promtool &> /dev/null; then
        echo -e "${YELLOW}promtool not found, attempting to use Docker...${NC}"
        if command -v docker &> /dev/null; then
            PROMTOOL_CMD="docker run --rm -v ${PROJECT_ROOT}:/workspace -w /workspace prom/prometheus promtool"
        else
            echo -e "${RED}Error: promtool not found and Docker not available${NC}"
            echo "Install promtool: go install github.com/prometheus/prometheus/cmd/promtool@latest"
            echo "Or install Docker to use the containerized version"
            exit 1
        fi
    else
        PROMTOOL_CMD="promtool"
    fi
}

# Validate recording rules
validate_recording_rules() {
    local rules_file="$1"
    local relative_path="${rules_file#$PROJECT_ROOT/}"

    echo -e "${YELLOW}Checking: ${relative_path}${NC}"

    if $PROMTOOL_CMD check rules "$rules_file" 2>&1; then
        echo -e "${GREEN}✓ ${relative_path} - VALID${NC}"
        return 0
    else
        echo -e "${RED}✗ ${relative_path} - INVALID${NC}"
        return 1
    fi
}

# Validate alerting rules (if present)
validate_alerting_rules() {
    local rules_file="$1"
    local relative_path="${rules_file#$PROJECT_ROOT/}"

    echo -e "${YELLOW}Checking alerts: ${relative_path}${NC}"

    if $PROMTOOL_CMD check rules "$rules_file" 2>&1; then
        echo -e "${GREEN}✓ ${relative_path} - VALID${NC}"
        return 0
    else
        echo -e "${RED}✗ ${relative_path} - INVALID${NC}"
        return 1
    fi
}

# Run unit tests on rules (expression syntax)
test_rule_expressions() {
    local rules_file="$1"
    local relative_path="${rules_file#$PROJECT_ROOT/}"

    echo -e "${YELLOW}Testing expressions: ${relative_path}${NC}"

    # promtool test rules requires a test file, so we just do syntax check
    if $PROMTOOL_CMD check rules "$rules_file" 2>&1; then
        echo -e "${GREEN}✓ Expressions valid${NC}"
        return 0
    else
        echo -e "${RED}✗ Expression errors found${NC}"
        return 1
    fi
}

main() {
    echo "========================================"
    echo "BESS Prometheus Rules Validation"
    echo "========================================"
    echo ""

    check_promtool

    local exit_code=0
    local files_checked=0
    local files_failed=0

    # Find all YAML files in monitoring directory
    RULES_DIR="${PROJECT_ROOT}/monitoring/prometheus"

    if [[ ! -d "$RULES_DIR" ]]; then
        echo -e "${RED}Error: Rules directory not found: ${RULES_DIR}${NC}"
        exit 1
    fi

    # Check recording rules
    echo ""
    echo "--- Recording Rules ---"
    for rules_file in "${RULES_DIR}"/*_rules.yml "${RULES_DIR}"/*_rules.yaml 2>/dev/null; do
        if [[ -f "$rules_file" ]]; then
            files_checked=$((files_checked + 1))
            if ! validate_recording_rules "$rules_file"; then
                files_failed=$((files_failed + 1))
                exit_code=1
            fi
        fi
    done

    # Check alerting rules
    echo ""
    echo "--- Alerting Rules ---"
    for alert_file in "${RULES_DIR}"/*_alerts.yml "${RULES_DIR}"/*_alerts.yaml 2>/dev/null; do
        if [[ -f "$alert_file" ]]; then
            files_checked=$((files_checked + 1))
            if ! validate_alerting_rules "$alert_file"; then
                files_failed=$((files_failed + 1))
                exit_code=1
            fi
        fi
    done

    # Summary
    echo ""
    echo "========================================"
    echo "Summary"
    echo "========================================"
    echo "Files checked: ${files_checked}"
    echo "Files passed:  $((files_checked - files_failed))"
    echo "Files failed:  ${files_failed}"
    echo ""

    if [[ $exit_code -eq 0 ]]; then
        echo -e "${GREEN}All Prometheus rules are valid!${NC}"
    else
        echo -e "${RED}Some rules failed validation. See errors above.${NC}"
    fi

    exit $exit_code
}

main "$@"
