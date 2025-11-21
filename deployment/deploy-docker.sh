#!/bin/bash

# PV Optimizer - Docker Compose Deployment Script

set -e

echo "=========================================="
echo "PV Optimizer - Docker Compose Deployment"
echo "=========================================="

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

# Check if docker-compose is installed
if ! command -v docker-compose &> /dev/null; then
    echo "docker-compose not found. Please install docker-compose first."
    exit 1
fi

# Build images
echo -e "\n${BLUE}Building images...${NC}"
docker-compose build
echo -e "${GREEN}✓ Images built${NC}"

# Start services
echo -e "\n${BLUE}Starting services...${NC}"
docker-compose up -d
echo -e "${GREEN}✓ Services started${NC}"

# Wait for services to be healthy
echo -e "\n${BLUE}Waiting for services to be healthy...${NC}"
sleep 10

# Check service health
echo -e "\n${BLUE}Checking service health...${NC}"

services=("data-analysis:8001" "pv-calculation:8002" "economics:8003" "frontend:80")

for service in "${services[@]}"; do
    name="${service%%:*}"
    port="${service##*:}"

    if [ "$name" = "frontend" ]; then
        endpoint="http://localhost:$port/"
    else
        endpoint="http://localhost:$port/health"
    fi

    max_attempts=30
    attempt=0

    while [ $attempt -lt $max_attempts ]; do
        if curl -s "$endpoint" > /dev/null 2>&1; then
            echo -e "${GREEN}✓ $name is healthy${NC}"
            break
        fi

        attempt=$((attempt + 1))
        sleep 2

        if [ $attempt -eq $max_attempts ]; then
            echo -e "${YELLOW}⚠ $name is not responding${NC}"
        fi
    done
done

echo -e "\n${GREEN}=========================================="
echo "Deployment completed!"
echo "==========================================${NC}"

# Show running containers
echo -e "\n${BLUE}Running containers:${NC}"
docker-compose ps

echo -e "\n${BLUE}Access the application at: http://localhost${NC}"
echo -e "${BLUE}API endpoints:${NC}"
echo "  - Data Analysis: http://localhost:8001"
echo "  - PV Calculation: http://localhost:8002"
echo "  - Economics: http://localhost:8003"
