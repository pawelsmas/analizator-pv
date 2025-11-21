#!/bin/bash

# PV Optimizer - Build Script
# Builds all Docker images for the microservices

set -e

echo "=========================================="
echo "PV Optimizer - Building Docker Images"
echo "=========================================="

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Build Data Analysis Service
echo -e "\n${BLUE}Building Data Analysis Service...${NC}"
docker build -t pv-optimizer/data-analysis:latest ./services/data-analysis/
echo -e "${GREEN}✓ Data Analysis Service built${NC}"

# Build PV Calculation Service
echo -e "\n${BLUE}Building PV Calculation Service...${NC}"
docker build -t pv-optimizer/pv-calculation:latest ./services/pv-calculation/
echo -e "${GREEN}✓ PV Calculation Service built${NC}"

# Build Economics Service
echo -e "\n${BLUE}Building Economics Service...${NC}"
docker build -t pv-optimizer/economics:latest ./services/economics/
echo -e "${GREEN}✓ Economics Service built${NC}"

# Build Frontend Service
echo -e "\n${BLUE}Building Frontend Service...${NC}"
docker build -t pv-optimizer/frontend:latest ./services/frontend/
echo -e "${GREEN}✓ Frontend Service built${NC}"

echo -e "\n${GREEN}=========================================="
echo "All images built successfully!"
echo "==========================================${NC}"

# List images
echo -e "\n${BLUE}Docker images:${NC}"
docker images | grep pv-optimizer
