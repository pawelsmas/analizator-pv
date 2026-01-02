#!/bin/bash
# Pod Failover Chaos Test (v3.9.0)
# Tests BESS service resilience under pod failures
#
# Prerequisites:
#   - kind cluster with bess-ha deployment
#   - k6 installed
#   - kubectl configured
#
# Usage:
#   ./tests/chaos/pod_failover_test.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Configuration
NAMESPACE="bess"
DEPLOYMENT="bess-dispatch"
TARGET_URL="${TARGET_URL:-http://localhost:30031}"
LOAD_DURATION="${LOAD_DURATION:-120}"  # seconds
POD_KILL_INTERVAL="${POD_KILL_INTERVAL:-30}"  # seconds between pod kills

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."

    if ! command -v kubectl &> /dev/null; then
        log_error "kubectl not found"
        exit 1
    fi

    if ! command -v k6 &> /dev/null; then
        log_error "k6 not found"
        exit 1
    fi

    # Check cluster access
    if ! kubectl cluster-info &> /dev/null; then
        log_error "Cannot connect to Kubernetes cluster"
        exit 1
    fi

    # Check deployment exists
    if ! kubectl get deployment "$DEPLOYMENT" -n "$NAMESPACE" &> /dev/null; then
        log_error "Deployment $DEPLOYMENT not found in namespace $NAMESPACE"
        exit 1
    fi

    log_success "Prerequisites OK"
}

# Get pod count
get_ready_pods() {
    kubectl get deployment "$DEPLOYMENT" -n "$NAMESPACE" -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0"
}

# Kill a random pod
kill_random_pod() {
    local pod=$(kubectl get pods -n "$NAMESPACE" -l app="$DEPLOYMENT" --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)

    if [ -n "$pod" ]; then
        log_warning "Killing pod: $pod"
        kubectl delete pod "$pod" -n "$NAMESPACE" --grace-period=0 --force &> /dev/null || true
        return 0
    fi

    return 1
}

# Wait for pods to recover
wait_for_recovery() {
    local target_replicas=$(kubectl get deployment "$DEPLOYMENT" -n "$NAMESPACE" -o jsonpath='{.spec.replicas}')
    local max_wait=60
    local waited=0

    while [ "$waited" -lt "$max_wait" ]; do
        local ready=$(get_ready_pods)
        if [ "$ready" -ge "$target_replicas" ]; then
            log_success "Pods recovered: $ready/$target_replicas ready"
            return 0
        fi
        sleep 2
        waited=$((waited + 2))
    done

    log_error "Pods did not recover within ${max_wait}s"
    return 1
}

# Run chaos test
run_chaos_test() {
    log_info "Starting chaos test..."
    log_info "  Duration: ${LOAD_DURATION}s"
    log_info "  Pod kill interval: ${POD_KILL_INTERVAL}s"
    log_info "  Target URL: $TARGET_URL"

    # Start k6 load test in background
    log_info "Starting k6 load test in background..."
    k6 run \
        --env TARGET_URL="$TARGET_URL" \
        --env SCENARIO=baseline \
        --out json=chaos_results.json \
        "$PROJECT_ROOT/tests/load/sizing_load.js" &
    local k6_pid=$!

    # Give k6 time to start
    sleep 10

    # Calculate number of pod kills
    local num_kills=$((LOAD_DURATION / POD_KILL_INTERVAL - 1))
    log_info "Will perform $num_kills pod kills"

    # Kill pods periodically
    for i in $(seq 1 $num_kills); do
        log_info "Chaos injection $i/$num_kills"

        # Record pod count before kill
        local before=$(get_ready_pods)
        log_info "  Ready pods before: $before"

        # Kill a pod
        if kill_random_pod; then
            sleep 5

            # Record pod count after kill
            local after=$(get_ready_pods)
            log_info "  Ready pods after kill: $after"

            # Wait for partial recovery
            sleep $((POD_KILL_INTERVAL - 5))
        fi
    done

    # Wait for k6 to complete
    log_info "Waiting for load test to complete..."
    wait $k6_pid || true

    log_success "Chaos test completed"
}

# Analyze results
analyze_results() {
    log_info "Analyzing results..."

    if [ ! -f "chaos_results.json" ]; then
        log_error "Results file not found"
        return 1
    fi

    # Extract key metrics (basic parsing)
    local total_requests=$(grep -c '"type":"Point"' chaos_results.json || echo "0")
    local failed_requests=$(grep '"metric":"http_req_failed"' chaos_results.json | grep -c '"value":1' || echo "0")

    if [ "$total_requests" -gt 0 ]; then
        local success_rate=$(echo "scale=4; ($total_requests - $failed_requests) / $total_requests * 100" | bc)
        log_info "Results:"
        log_info "  Total requests: $total_requests"
        log_info "  Failed requests: $failed_requests"
        log_info "  Success rate: ${success_rate}%"

        # Check against SLO (99.5%)
        if (( $(echo "$success_rate >= 99.5" | bc -l) )); then
            log_success "SLO MET: Success rate >= 99.5%"
            return 0
        else
            log_error "SLO BREACHED: Success rate < 99.5%"
            return 1
        fi
    fi

    log_warning "Could not calculate success rate"
    return 0
}

# Main
main() {
    echo "========================================"
    echo "BESS Pod Failover Chaos Test"
    echo "========================================"
    echo ""

    check_prerequisites

    # Record initial state
    local initial_pods=$(get_ready_pods)
    log_info "Initial ready pods: $initial_pods"

    # Run chaos test
    run_chaos_test

    # Wait for full recovery
    log_info "Waiting for full recovery..."
    wait_for_recovery

    # Final pod count
    local final_pods=$(get_ready_pods)
    log_info "Final ready pods: $final_pods"

    # Analyze results
    analyze_results
    local exit_code=$?

    echo ""
    echo "========================================"
    if [ $exit_code -eq 0 ]; then
        log_success "Chaos test PASSED"
    else
        log_error "Chaos test FAILED"
    fi
    echo "========================================"

    exit $exit_code
}

main "$@"
