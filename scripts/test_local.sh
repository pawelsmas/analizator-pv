#!/bin/bash
# Local test runner for contract tests
# Usage: ./scripts/test_local.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

echo "=========================================="
echo "  PV Optimizer Pro - Contract Tests"
echo "=========================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if docker-compose is available
if ! command -v docker-compose &> /dev/null; then
    echo -e "${RED}Error: docker-compose not found${NC}"
    exit 1
fi

# Step 1: Start services
echo -e "${YELLOW}[1/4] Starting Docker services...${NC}"
docker-compose up -d bess-dispatch pv-calculation

# Step 2: Wait for services to be healthy
echo -e "${YELLOW}[2/4] Waiting for services to be ready...${NC}"

MAX_WAIT=120
WAITED=0

while [ $WAITED -lt $MAX_WAIT ]; do
    BESS_HEALTH=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8031/health 2>/dev/null || echo "000")
    PV_HEALTH=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8002/health 2>/dev/null || echo "000")

    if [ "$BESS_HEALTH" == "200" ] && [ "$PV_HEALTH" == "200" ]; then
        echo -e "${GREEN}Services are ready!${NC}"
        break
    fi

    echo "  Waiting... (BESS: $BESS_HEALTH, PV: $PV_HEALTH)"
    sleep 5
    WAITED=$((WAITED + 5))
done

if [ $WAITED -ge $MAX_WAIT ]; then
    echo -e "${RED}Error: Services did not become healthy in ${MAX_WAIT}s${NC}"
    docker-compose logs bess-dispatch pv-calculation
    exit 1
fi

# Step 3: Run pytest
echo -e "${YELLOW}[3/4] Running contract tests...${NC}"
echo ""

# Check if pytest is available, if not use docker
if command -v pytest &> /dev/null; then
    pytest tests/contract/ -v --tb=short
    TEST_RESULT=$?
else
    # Run pytest in a Python container
    echo "pytest not found locally, running in Docker..."
    docker run --rm \
        --network host \
        -v "$PROJECT_ROOT/tests:/tests" \
        python:3.11-slim \
        bash -c "pip install pytest requests && pytest /tests/contract/ -v --tb=short"
    TEST_RESULT=$?
fi

# Step 4: Report results
echo ""
echo "=========================================="
if [ $TEST_RESULT -eq 0 ]; then
    echo -e "${GREEN}  All contract tests PASSED${NC}"
else
    echo -e "${RED}  Some tests FAILED${NC}"
fi
echo "=========================================="

exit $TEST_RESULT
