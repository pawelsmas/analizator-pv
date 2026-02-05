.PHONY: help build up down logs restart clean deploy-k8s delete-k8s status test test-contract smoke smoke-no-arb smoke-with-arb validate validate-list validate-pack capture-scenario test-frontend helm-lint helm-template helm-template-dev helm-package

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

# ===== CONTRACT TESTS & SMOKE TESTS =====

test-contract: ## Run pytest contract tests
	@echo "${BLUE}Running contract tests...${RESET}"
	@python -m pytest tests/contract/ -v --tb=short
	@echo "${GREEN}✓ Contract tests passed${RESET}"

test-quick: ## Run contract tests (quiet mode)
	@python -m pytest tests/contract/ -q

smoke: smoke-no-arb smoke-with-arb ## Run all smoke tests
	@echo "${GREEN}✓ All smoke tests passed${RESET}"

smoke-no-arb: ## Smoke test: sizing without arbitrage
	@echo "${BLUE}Smoke test: no arbitrage...${RESET}"
	@curl -sS http://localhost:8031/sizing \
		-H "Content-Type: application/json" \
		--data-binary @scripts/smoke/sizing_stacked_no_arbitrage.json \
		-o scripts/smoke/sizing_no_arb.json
	@python -c "import json; d=json.load(open('scripts/smoke/sizing_no_arb.json')); \
		v=d['variants'][0]; \
		assert abs(v['annual_savings_pln'] - v['savings_breakdown']['net_savings_pln']) < 1, 'SSoT mismatch'; \
		assert 'period_info' in d, 'Missing period_info'; \
		print('  SSoT OK: annual={:.0f}, net={:.0f}'.format(v['annual_savings_pln'], v['savings_breakdown']['net_savings_pln']))"

smoke-with-arb: ## Smoke test: sizing with arbitrage config
	@echo "${BLUE}Smoke test: with arbitrage...${RESET}"
	@curl -sS http://localhost:8031/sizing \
		-H "Content-Type: application/json" \
		--data-binary @scripts/smoke/sizing_stacked_with_arbitrage.json \
		-o scripts/smoke/sizing_with_arb.json
	@python -c "import json; d=json.load(open('scripts/smoke/sizing_with_arb.json')); \
		assert len(d['variants']) > 0, 'No variants'; \
		print('  Arbitrage test: {} variants returned'.format(len(d['variants'])))"

wait-ready: ## Wait for bess-dispatch to be ready
	@echo "${BLUE}Waiting for services...${RESET}"
	@timeout 60 bash -c 'until curl -sf http://localhost:8031/health 2>/dev/null; do sleep 2; done' 2>/dev/null || \
		python -c "import time,urllib.request as u; [time.sleep(2) for _ in range(30) if not (lambda: (u.urlopen('http://localhost:8031/health'),True)[1])()]" 2>/dev/null || true
	@echo "${GREEN}✓ Services ready${RESET}"

# ===== CORRECTNESS VALIDATION =====

validate: ## Run scenario validation tests (correctness)
	@echo "${BLUE}Running scenario validation...${RESET}"
	@python scripts/validate_scenarios.py
	@echo "${GREEN}✓ Validation passed${RESET}"

validate-list: ## List available validation scenarios
	@python scripts/validate_scenarios.py --list

validate-pack: ## Run scenario pack validation (usage: PACK=baseline make validate-pack)
	@echo "${BLUE}Running pack validation: $(PACK)...${RESET}"
	@python scripts/validate_scenarios.py --pack docs/scenarios/packs/$(PACK).yml
	@echo "${GREEN}✓ Pack validation passed${RESET}"

capture-scenario: ## Capture scenario from run_id (usage: make capture-scenario RUN_ID=xxx NAME=yyy)
	@echo "${BLUE}Capturing scenario from run $(RUN_ID)...${RESET}"
	@python scripts/capture_scenario.py --run-id $(RUN_ID) --name $(NAME)
	@echo "${GREEN}✓ Scenario captured to docs/scenarios/$(NAME)/${RESET}"

test-frontend: ## Run frontend JavaScript syntax checks
	@echo "${BLUE}Checking frontend JavaScript syntax...${RESET}"
	@node --check services/frontend-bess/bess.js
	@echo "${GREEN}✓ Frontend syntax OK${RESET}"

# ===== LOCAL DEVELOPMENT (v2.6.0) =====

dev-up: ## Start local development environment (docker compose + wait)
	@echo "${BLUE}Starting local development environment...${RESET}"
	@docker compose up -d --build bess-dispatch
	@echo "${YELLOW}Waiting for backend to be ready...${RESET}"
	@python scripts/dev/wait_http.py http://localhost:8031/version --timeout 120 || true
	@echo ""
	@echo "${GREEN}Development environment ready!${RESET}"
	@echo ""
	@echo "  Backend:  http://localhost:8031"
	@echo "  API Docs: http://localhost:8031/docs"
	@echo "  Metrics:  http://localhost:8031/metrics"
	@echo ""

dev-down: ## Stop local development environment
	@echo "${BLUE}Stopping local development environment...${RESET}"
	@docker compose down
	@echo "${GREEN}✓ Environment stopped${RESET}"

demo: ## Run a sample sizing request and show results
	@echo "${BLUE}Running demo sizing request...${RESET}"
	@python -c "\
import json, urllib.request as u; \
req = {'load_kw': [100]*24, 'pv_generation_kw': [0,0,0,0,0,0,50,200,500,800,1000,1100,1100,1000,800,500,200,50,0,0,0,0,0,0], \
'mode': 'pv_surplus', 'durations_h': [1.0, 2.0], 'interval_minutes': 60, 'discount_rate': 0.08, 'analysis_years': 15, \
'capex_pln_per_kwh': 1800.0, 'import_price_pln_mwh': 800.0}; \
r = u.urlopen(u.Request('http://localhost:8031/sizing', json.dumps(req).encode(), {'Content-Type': 'application/json'})); \
d = json.loads(r.read()); run_id = d.get('meta', {}).get('run_id', 'N/A'); \
rec = d.get('recommended', {}); \
print(f'Run ID: {run_id}'); \
print(f'Recommended: {rec.get(\"energy_kwh\", \"N/A\")} kWh / {rec.get(\"power_kw\", \"N/A\")} kW'); \
print(f'NPV: {rec.get(\"npv_pln\", \"N/A\")} PLN'); \
print(f''); \
print(f'Run Explorer: http://localhost:8031/api/bess-dispatch/runs/{run_id}'); \
print(f'PDF Report:   http://localhost:8031/api/bess-dispatch/runs/{run_id}/report.pdf')"

# ===== RELEASE CANDIDATE (v2.6.0) =====

rc: ## Run full RC check (tests + smoke + validation + contracts)
	@echo "${BLUE}Running Release Candidate checks...${RESET}"
	@python scripts/rc/rc_check.py
	@echo ""

rc-skip-backend: ## Run RC check without backend tests
	@echo "${BLUE}Running Release Candidate checks (no backend)...${RESET}"
	@python scripts/rc/rc_check.py --skip-backend
	@echo ""

# ===== GUARDS (v2.8.0) =====

guard-no-legacy: ## Check for legacy references in codebase
	@echo "${BLUE}Checking for legacy references...${RESET}"
	@python scripts/guards/check_no_legacy.py
	@echo "${GREEN}✓ No legacy references found${RESET}"

# ===== HELM (v3.5.0) =====

helm-lint: ## Lint Helm chart (uses Docker, no local Helm required)
	@echo "${BLUE}Linting Helm chart...${RESET}"
	@docker run --rm -v "$(CURDIR)":/src -w /src alpine/helm:3.14.0 lint deploy/helm/pv-portal
	@echo "${GREEN}✓ Helm lint passed${RESET}"

helm-template: ## Render Helm chart templates (uses Docker)
	@echo "${BLUE}Rendering Helm templates...${RESET}"
	@docker run --rm -v "$(CURDIR)":/src -w /src alpine/helm:3.14.0 template pv-portal deploy/helm/pv-portal
	@echo "${GREEN}✓ Helm template rendered${RESET}"

helm-template-dev: ## Render Helm templates with dev values
	@echo "${BLUE}Rendering Helm templates (dev mode)...${RESET}"
	@docker run --rm -v "$(CURDIR)":/src -w /src alpine/helm:3.14.0 template pv-portal deploy/helm/pv-portal \
		--set redis.enabled=true \
		--set redis.embedded.enabled=true \
		--set database.embedded.enabled=true
	@echo "${GREEN}✓ Helm template (dev) rendered${RESET}"

helm-package: ## Package Helm chart
	@echo "${BLUE}Packaging Helm chart...${RESET}"
	@docker run --rm -v "$(CURDIR)":/src -w /src alpine/helm:3.14.0 package deploy/helm/pv-portal -d dist/
	@echo "${GREEN}✓ Helm chart packaged to dist/${RESET}"
