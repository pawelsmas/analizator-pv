# PV Optimizer - Micro-Frontend Architecture

## Architektura

System został podzielony na **7 niezależnych kontenerów frontend** + **5 kontenerów backend**:

### Frontend Modules (Micro-Frontends)

| Module | Port | Responsibility | Container Name |
|--------|------|----------------|----------------|
| **Shell** | 80 | Main application shell, routing, navigation | `pv-frontend-shell` |
| **Admin** | 9001 | System administration, user management | `pv-frontend-admin` |
| **Configuration** | 9002 | Data upload, PV configuration, analysis parameters | `pv-frontend-config` |
| **Consumption** | 9003 | Consumption analysis, charts, heatmaps | `pv-frontend-consumption` |
| **Production** | 9004 | PV production analysis, generation profiles | `pv-frontend-production` |
| **Comparison** | 9005 | Scenario comparison, variant analysis | `pv-frontend-comparison` |
| **Economics** | 9006 | Economic analysis, NPV, IRR, sensitivity | `pv-frontend-economics` |

### Backend Services

| Service | Port | Responsibility |
|---------|------|----------------|
| data-analysis | 8001 | Data processing, statistics |
| pv-calculation | 8002 | PV generation calculations (improved algorithms) |
| economics | 8003 | Economic analysis, sensitivity |
| advanced-analytics | 8004 | Advanced KPI, load duration curves |
| typical-days | 8005 | Typical day patterns, seasonal analysis |

## Communication Pattern

```
┌─────────────────────────────────────────────────┐
│          Frontend Shell (Port 80)               │
│  - Navigation                                    │
│  - Module Routing                                │
│  - Inter-module Communication (postMessage)      │
└────────┬────────────────────────────────────────┘
         │
         ├───► Admin Module (9001)
         ├───► Config Module (9002) ──┐
         ├───► Consumption Module (9003)│
         ├───► Production Module (9004) ├──► Backend APIs (8001-8005)
         ├───► Comparison Module (9005) │
         └───► Economics Module (9006) ─┘
```

## Directory Structure

```
services/
├── frontend-shell/          # Main shell (routing, navigation)
│   ├── index.html
│   ├── shell.js
│   ├── styles.css
│   ├── nginx.conf
│   └── Dockerfile
│
├── frontend-admin/          # Admin module
│   ├── index.html
│   ├── admin.js
│   ├── styles.css
│   └── Dockerfile
│
├── frontend-config/         # Configuration module
│   ├── index.html
│   ├── config.js
│   ├── styles.css
│   └── Dockerfile
│
├── frontend-consumption/    # Consumption analysis module
│   ├── index.html
│   ├── consumption.js
│   ├── styles.css
│   └── Dockerfile
│
├── frontend-production/     # PV production module
│   ├── index.html
│   ├── production.js
│   ├── styles.css
│   └── Dockerfile
│
├── frontend-comparison/     # Comparison module
│   ├── index.html
│   ├── comparison.js
│   ├── styles.css
│   └── Dockerfile
│
└── frontend-economics/      # Economics module
    ├── index.html
    ├── economics.js
    ├── styles.css
    └── Dockerfile
```

## Inter-Module Communication

Modules communicate via **postMessage API**:

### Message Types

```javascript
// Data uploaded
{
  type: 'DATA_UPLOADED',
  data: { filename, rows, year }
}

// Analysis complete
{
  type: 'ANALYSIS_COMPLETE',
  data: { scenarios, variants }
}

// Navigate to another module
{
  type: 'NAVIGATE',
  module: 'consumption' // target module name
}

// Data available (broadcast to all)
{
  type: 'DATA_AVAILABLE',
  data: { consumption, statistics }
}
```

### Example: Config Module sends message to Shell

```javascript
// In config.js
window.parent.postMessage({
  type: 'DATA_UPLOADED',
  data: {
    filename: 'data.xlsx',
    rows: 8760,
    year: 2024
  }
}, '*');
```

### Example: Shell broadcasts to all modules

```javascript
// In shell.js
function broadcastToModules(message) {
  const iframe = document.getElementById('module-frame');
  iframe.contentWindow.postMessage(message, '*');
}
```

## Benefits of Micro-Frontend Architecture

1. **Independent Development** - Each module can be developed/deployed separately
2. **Technology Flexibility** - Each module can use different frameworks
3. **Scalability** - Modules can scale independently
4. **Team Autonomy** - Different teams can own different modules
5. **Isolated Failures** - If one module fails, others continue working
6. **Faster Builds** - Only changed modules need to be rebuilt

## Docker Compose Configuration

```yaml
services:
  # Frontend Shell
  frontend-shell:
    build: ./services/frontend-shell
    container_name: pv-frontend-shell
    ports:
      - "80:80"
    depends_on:
      - frontend-admin
      - frontend-config
      - frontend-consumption
      - frontend-production
      - frontend-comparison
      - frontend-economics

  # Admin Module
  frontend-admin:
    build: ./services/frontend-admin
    container_name: pv-frontend-admin
    ports:
      - "9001:80"

  # Configuration Module
  frontend-config:
    build: ./services/frontend-config
    container_name: pv-frontend-config
    ports:
      - "9002:80"

  # ... other modules ...
```

## Kubernetes Deployment

Each micro-frontend gets its own:
- **Deployment** (2 replicas for HA)
- **Service** (ClusterIP)
- **Ingress** rule (path-based routing)

```yaml
# Example for Config Module
apiVersion: apps/v1
kind: Deployment
metadata:
  name: frontend-config
  namespace: pv-optimizer
spec:
  replicas: 2
  selector:
    matchLabels:
      app: frontend-config
  template:
    spec:
      containers:
      - name: frontend-config
        image: pv-optimizer/frontend-config:latest
        ports:
        - containerPort: 80
---
apiVersion: v1
kind: Service
metadata:
  name: frontend-config
spec:
  type: ClusterIP
  ports:
  - port: 9002
    targetPort: 80
```

## Development Workflow

### Work on Single Module

```bash
# Develop only Configuration module
cd services/frontend-config

# Make changes to config.js, index.html, etc.

# Rebuild only this module
docker-compose build frontend-config
docker-compose up -d frontend-config

# Test at http://localhost:9002 (direct)
# Or http://localhost → Configuration tab (via shell)
```

### Shared State Management

Modules share data via:
1. **LocalStorage** - For client-side persistence
2. **Backend APIs** - For server-side state
3. **postMessage** - For real-time communication

```javascript
// Save to localStorage (available to all modules)
localStorage.setItem('pv_data', JSON.stringify(data));

// Read from localStorage
const data = JSON.parse(localStorage.getItem('pv_data'));
```

## Next Steps

1. ✅ Create Shell (routing, navigation)
2. 🔄 Create Configuration Module (data upload, parameters)
3. ⏳ Create remaining modules:
   - Admin
   - Consumption
   - Production
   - Comparison
   - Economics
4. ⏳ Update docker-compose.yml
5. ⏳ Create Kubernetes manifests
6. ⏳ Test inter-module communication
7. ⏳ Deploy to production

## Testing

```bash
# Test Shell
curl http://localhost:80

# Test Config Module (direct)
curl http://localhost:9002

# Test Config Module (via shell)
# Open http://localhost → click Configuration tab
```

## Troubleshooting

### Module not loading in iframe
- Check CORS headers in nginx.conf
- Verify module is running: `docker ps`
- Check browser console for errors

### postMessage not working
- Verify origin in message handler
- Check iframe src matches MODULES config
- Use browser DevTools → Console to debug

### Data not persisting
- Check localStorage in DevTools
- Verify backend API calls succeed
- Check network tab for failed requests
