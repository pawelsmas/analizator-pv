.PHONY: help build up down logs restart clean deploy-k8s delete-k8s status test

# Colors
GREEN  := $(shell tput -Txterm setaf 2)
YELLOW := $(shell tput -Txterm setaf 3)
BLUE   := $(shell tput -Txterm setaf 4)
RESET  := $(shell tput -Txterm sgr0)

help: ## Show this help
	@echo '${BLUE}PV Optimizer - Makefile Commands${RESET}'
	@echo ''
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "${GREEN}%-20s${RESET} %s\n", $$1, $$2}'

build: ## Build all Docker images
	@echo "${BLUE}Building Docker images...${RESET}"
	@docker-compose build
	@echo "${GREEN}✓ Build complete${RESET}"

up: ## Start all services with Docker Compose
	@echo "${BLUE}Starting services...${RESET}"
	@docker-compose up -d
	@echo "${GREEN}✓ Services started${RESET}"
	@echo "${YELLOW}Access at: http://localhost${RESET}"

down: ## Stop all services
	@echo "${BLUE}Stopping services...${RESET}"
	@docker-compose down
	@echo "${GREEN}✓ Services stopped${RESET}"

logs: ## Show logs from all services
	@docker-compose logs -f

logs-data: ## Show logs from data-analysis service
	@docker-compose logs -f data-analysis

logs-pv: ## Show logs from pv-calculation service
	@docker-compose logs -f pv-calculation

logs-economics: ## Show logs from economics service
	@docker-compose logs -f economics

logs-frontend: ## Show logs from frontend service
	@docker-compose logs -f frontend

restart: ## Restart all services
	@echo "${BLUE}Restarting services...${RESET}"
	@docker-compose restart
	@echo "${GREEN}✓ Services restarted${RESET}"

clean: ## Remove all containers, volumes, and images
	@echo "${BLUE}Cleaning up...${RESET}"
	@docker-compose down -v --rmi all
	@echo "${GREEN}✓ Cleanup complete${RESET}"

status: ## Show status of all services
	@echo "${BLUE}Service Status:${RESET}"
	@docker-compose ps

deploy-k8s: ## Deploy to Kubernetes
	@echo "${BLUE}Deploying to Kubernetes...${RESET}"
	@kubectl apply -f k8s/namespace.yaml
	@kubectl apply -f k8s/data-analysis-deployment.yaml
	@kubectl apply -f k8s/pv-calculation-deployment.yaml
	@kubectl apply -f k8s/economics-deployment.yaml
	@kubectl apply -f k8s/frontend-deployment.yaml
	@kubectl apply -f k8s/ingress.yaml
	@echo "${GREEN}✓ Deployed to Kubernetes${RESET}"
	@echo "${YELLOW}Waiting for deployments...${RESET}"
	@kubectl wait --for=condition=available --timeout=300s \
		deployment/data-analysis \
		deployment/pv-calculation \
		deployment/economics \
		deployment/frontend \
		-n pv-optimizer
	@echo "${GREEN}✓ All deployments ready${RESET}"

delete-k8s: ## Delete Kubernetes deployment
	@echo "${BLUE}Deleting Kubernetes deployment...${RESET}"
	@kubectl delete -f k8s/ --ignore-not-found=true
	@echo "${GREEN}✓ Deployment deleted${RESET}"

status-k8s: ## Show Kubernetes deployment status
	@echo "${BLUE}Kubernetes Status:${RESET}"
	@kubectl get all -n pv-optimizer

test: ## Run basic health checks
	@echo "${BLUE}Testing services...${RESET}"
	@echo "Data Analysis Service:"
	@curl -s http://localhost:8001/health | jq . || echo "Not responding"
	@echo "\nPV Calculation Service:"
	@curl -s http://localhost:8002/health | jq . || echo "Not responding"
	@echo "\nEconomics Service:"
	@curl -s http://localhost:8003/health | jq . || echo "Not responding"
	@echo "\nFrontend:"
	@curl -s -o /dev/null -w "Status: %{http_code}\n" http://localhost/

dev: ## Start in development mode with hot reload
	@echo "${BLUE}Starting in development mode...${RESET}"
	@docker-compose -f docker-compose.yml -f docker-compose.dev.yml up

prod: build up ## Build and start in production mode

rebuild: ## Rebuild and restart a specific service (usage: make rebuild SERVICE=data-analysis)
	@echo "${BLUE}Rebuilding $(SERVICE)...${RESET}"
	@docker-compose build $(SERVICE)
	@docker-compose up -d $(SERVICE)
	@echo "${GREEN}✓ $(SERVICE) rebuilt and restarted${RESET}"

scale: ## Scale a service (usage: make scale SERVICE=data-analysis REPLICAS=3)
	@echo "${BLUE}Scaling $(SERVICE) to $(REPLICAS) replicas...${RESET}"
	@kubectl scale deployment/$(SERVICE) --replicas=$(REPLICAS) -n pv-optimizer
	@echo "${GREEN}✓ $(SERVICE) scaled to $(REPLICAS) replicas${RESET}"
