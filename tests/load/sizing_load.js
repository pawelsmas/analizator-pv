/**
 * k6 Load Test: BESS Sizing Endpoint
 * Version: v3.9.0
 *
 * Tests the /sizing endpoint under load with configurable scenarios.
 *
 * Usage:
 *   k6 run tests/load/sizing_load.js
 *   k6 run tests/load/sizing_load.js --vus 10 --duration 30s
 *   k6 run tests/load/sizing_load.js --env TARGET_URL=http://localhost:8031
 *
 * Environment Variables:
 *   TARGET_URL: Base URL of the BESS service (default: http://localhost:8031)
 *   SCENARIO: Load scenario to run (default: smoke)
 *     - smoke: 1 VU, 30s (sanity check)
 *     - baseline: 5 VU, 2m (steady state)
 *     - stress: ramp up to 20 VU, 5m (find limits)
 *     - soak: 10 VU, 30m (long-running stability)
 */

import http from 'k6/http';
import { check, sleep, group } from 'k6';
import { Rate, Trend, Counter } from 'k6/metrics';

// Custom metrics
const sizingSuccessRate = new Rate('sizing_success_rate');
const sizingDuration = new Trend('sizing_duration_ms');
const sizingErrors = new Counter('sizing_errors');

// Configuration
const TARGET_URL = __ENV.TARGET_URL || 'http://localhost:8031';
const SCENARIO = __ENV.SCENARIO || 'smoke';

// Load scenarios
const scenarios = {
  smoke: {
    executor: 'constant-vus',
    vus: 1,
    duration: '30s',
  },
  baseline: {
    executor: 'constant-vus',
    vus: 5,
    duration: '2m',
  },
  stress: {
    executor: 'ramping-vus',
    startVUs: 1,
    stages: [
      { duration: '1m', target: 5 },
      { duration: '2m', target: 20 },
      { duration: '1m', target: 20 },
      { duration: '1m', target: 0 },
    ],
  },
  soak: {
    executor: 'constant-vus',
    vus: 10,
    duration: '30m',
  },
};

// Export options based on scenario
export const options = {
  scenarios: {
    default: scenarios[SCENARIO] || scenarios.smoke,
  },
  thresholds: {
    // SLO: 99.5% availability
    'sizing_success_rate': ['rate>0.995'],
    // SLO: p95 < 2s
    'sizing_duration_ms': ['p(95)<2000'],
    // HTTP errors should be rare
    'http_req_failed': ['rate<0.01'],
  },
};

// Sample sizing request payload
function generateSizingRequest() {
  // Generate 24-hour load profile with some variation
  const load_kw = Array.from({ length: 24 }, (_, i) => {
    const baseLoad = 100;
    const peakHours = [9, 10, 11, 12, 13, 14, 15, 16, 17];
    const multiplier = peakHours.includes(i) ? 1.5 : 1.0;
    return Math.round(baseLoad * multiplier * (0.9 + Math.random() * 0.2));
  });

  // Generate PV generation profile (bell curve)
  const pv_generation_kw = Array.from({ length: 24 }, (_, i) => {
    if (i < 6 || i > 19) return 0;
    const peakHour = 13;
    const spread = 4;
    const maxPV = 500;
    const gaussian = Math.exp(-Math.pow(i - peakHour, 2) / (2 * spread * spread));
    return Math.round(maxPV * gaussian * (0.9 + Math.random() * 0.2));
  });

  return {
    load_kw: load_kw,
    pv_generation_kw: pv_generation_kw,
    mode: 'pv_surplus',
    durations_h: [1.0, 2.0, 4.0],
    interval_minutes: 60,
    discount_rate: 0.08,
    analysis_years: 15,
    capex_pln_per_kwh: 1800.0,
    import_price_pln_mwh: 800.0,
    export_price_pln_mwh: 400.0,
  };
}

// Main test function
export default function () {
  group('Sizing Endpoint', function () {
    const payload = JSON.stringify(generateSizingRequest());

    const params = {
      headers: {
        'Content-Type': 'application/json',
      },
      timeout: '30s',
    };

    const startTime = Date.now();
    const response = http.post(`${TARGET_URL}/sizing`, payload, params);
    const duration = Date.now() - startTime;

    // Record custom metrics
    sizingDuration.add(duration);

    // Check response
    const success = check(response, {
      'status is 200': (r) => r.status === 200,
      'response has variants': (r) => {
        try {
          const body = JSON.parse(r.body);
          return body.variants && body.variants.length > 0;
        } catch {
          return false;
        }
      },
      'response has recommended': (r) => {
        try {
          const body = JSON.parse(r.body);
          return body.recommended !== undefined;
        } catch {
          return false;
        }
      },
      'response has run_id': (r) => {
        try {
          const body = JSON.parse(r.body);
          return body.meta && body.meta.run_id;
        } catch {
          return false;
        }
      },
    });

    sizingSuccessRate.add(success);

    if (!success) {
      sizingErrors.add(1);
      console.log(`Error: status=${response.status}, body=${response.body.substring(0, 200)}`);
    }

    // Think time between requests (simulates user behavior)
    sleep(Math.random() * 2 + 1);
  });
}

// Setup function - runs once before the test
export function setup() {
  console.log(`Starting load test against ${TARGET_URL}`);
  console.log(`Scenario: ${SCENARIO}`);

  // Verify target is reachable
  const healthResponse = http.get(`${TARGET_URL}/health`);
  if (healthResponse.status !== 200) {
    throw new Error(`Target not healthy: ${healthResponse.status}`);
  }

  console.log('Target is healthy, starting load test...');
  return { startTime: Date.now() };
}

// Teardown function - runs once after the test
export function teardown(data) {
  const duration = (Date.now() - data.startTime) / 1000;
  console.log(`Load test completed in ${duration.toFixed(1)}s`);
}
