#!/bin/bash

# PV Optimizer - Kubernetes Deployment Script

set -e

echo "=========================================="
echo "PV Optimizer - Kubernetes Deployment"
echo "=========================================="

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Check if kubectl is installed
if ! command -v kubectl &> /dev/null; then
    echo -e "${YELLOW}kubectl not found. Please install kubectl first.${NC}"
    exit 1
fi

# Check if cluster is accessible
echo -e "\n${BLUE}Checking Kubernetes cluster...${NC}"
if ! kubectl cluster-info &> /dev/null; then
    echo -e "${YELLOW}Cannot connect to Kubernetes cluster.${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Cluster is accessible${NC}"

# Apply namespace
echo -e "\n${BLUE}Creating namespace...${NC}"
kubectl apply -f k8s/namespace.yaml
echo -e "${GREEN}✓ Namespace created${NC}"

# Apply deployments
echo -e "\n${BLUE}Deploying services...${NC}"
kubectl apply -f k8s/data-analysis-deployment.yaml
kubectl apply -f k8s/pv-calculation-deployment.yaml
kubectl apply -f k8s/economics-deployment.yaml
kubectl apply -f k8s/frontend-deployment.yaml
echo -e "${GREEN}✓ Services deployed${NC}"

# Apply ingress
echo -e "\n${BLUE}Setting up ingress...${NC}"
kubectl apply -f k8s/ingress.yaml
echo -e "${GREEN}✓ Ingress configured${NC}"

# Wait for deployments
echo -e "\n${BLUE}Waiting for deployments to be ready...${NC}"
kubectl wait --for=condition=available --timeout=300s \
    deployment/data-analysis \
    deployment/pv-calculation \
    deployment/economics \
    deployment/frontend \
    -n pv-optimizer

echo -e "\n${GREEN}=========================================="
echo "Deployment completed successfully!"
echo "==========================================${NC}"

# Show status
echo -e "\n${BLUE}Deployment status:${NC}"
kubectl get all -n pv-optimizer

# Show ingress
echo -e "\n${BLUE}Ingress information:${NC}"
kubectl get ingress -n pv-optimizer

echo -e "\n${YELLOW}Add the following to your /etc/hosts:${NC}"
echo "127.0.0.1 pv-optimizer.local"
echo -e "\n${BLUE}Access the application at: http://pv-optimizer.local${NC}"
