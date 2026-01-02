/**
 * k6 Load Test: BESS Validation Endpoint
 * Version: v3.9.0
 *
 * Tests the /validate/sizing endpoint under load.
 *
 * Usage:
 *   k6 run tests/load/validation_load.js
 *   k6 run tests/load/validation_load.js --env SCENARIO=stress
 *
 * Environment Variables:
 *   TARGET_URL: Base URL of the BESS service (default: http://localhost:8031)
 *   SCENARIO: Load scenario (smoke, baseline, stress, soak)
 */

import http from 'k6/http';
import { check, sleep, group } from 'k6';
import { Rate, Trend, Counter } from 'k6/metrics';

// Custom metrics
const validationSuccessRate = new Rate('validation_success_rate');
const validationDuration = new Trend('validation_duration_ms');
const validationErrors = new Counter('validation_errors');
const validationPassed = new Counter('validation_passed');
const validationFailed = new Counter('validation_failed');

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
    vus: 3,
    duration: '2m',
  },
  stress: {
    executor: 'ramping-vus',
    startVUs: 1,
    stages: [
      { duration: '1m', target: 3 },
      { duration: '2m', target: 10 },
      { duration: '1m', target: 10 },
      { duration: '1m', target: 0 },
    ],
  },
  soak: {
    executor: 'constant-vus',
    vus: 5,
    duration: '30m',
  },
};

export const options = {
  scenarios: {
    default: scenarios[SCENARIO] || scenarios.smoke,
  },
  thresholds: {
    'validation_success_rate': ['rate>0.995'],
    'validation_duration_ms': ['p(95)<3000'], // Validation can be slower
    'http_req_failed': ['rate<0.01'],
  },
};

// Generate validation request with expected values
function generateValidationRequest() {
  const load_kw = Array.from({ length: 24 }, () => 100);
  const pv_generation_kw = Array.from({ length: 24 }, (_, i) => {
    if (i < 6 || i > 18) return 0;
    return Math.round(200 * Math.sin((i - 6) * Math.PI / 12));
  });

  return {
    request: {
      load_kw: load_kw,
      pv_generation_kw: pv_generation_kw,
      mode: 'pv_surplus',
      durations_h: [2.0],
      interval_minutes: 60,
      discount_rate: 0.08,
      analysis_years: 15,
      capex_pln_per_kwh: 1800.0,
      import_price_pln_mwh: 800.0,
    },
    expected_kpis: {
      recommended_energy_kwh: { min: 50, max: 500 },
      recommended_power_kw: { min: 25, max: 250 },
      npv_pln: { min: -50000, max: 200000 },
    },
    tolerance_pct: 10.0,
  };
}

export default function () {
  group('Validation Endpoint', function () {
    const payload = JSON.stringify(generateValidationRequest());

    const params = {
      headers: {
        'Content-Type': 'application/json',
      },
      timeout: '60s',
    };

    const startTime = Date.now();
    const response = http.post(`${TARGET_URL}/validate/sizing`, payload, params);
    const duration = Date.now() - startTime;

    validationDuration.add(duration);

    const success = check(response, {
      'status is 200': (r) => r.status === 200,
      'response has passed field': (r) => {
        try {
          const body = JSON.parse(r.body);
          return body.passed !== undefined;
        } catch {
          return false;
        }
      },
      'response has field_results': (r) => {
        try {
          const body = JSON.parse(r.body);
          return body.field_results !== undefined;
        } catch {
          return false;
        }
      },
    });

    validationSuccessRate.add(success);

    if (success) {
      try {
        const body = JSON.parse(response.body);
        if (body.passed) {
          validationPassed.add(1);
        } else {
          validationFailed.add(1);
        }
      } catch {}
    } else {
      validationErrors.add(1);
      console.log(`Error: status=${response.status}`);
    }

    sleep(Math.random() * 2 + 1);
  });
}

export function setup() {
  console.log(`Starting validation load test against ${TARGET_URL}`);
  console.log(`Scenario: ${SCENARIO}`);

  const healthResponse = http.get(`${TARGET_URL}/health`);
  if (healthResponse.status !== 200) {
    throw new Error(`Target not healthy: ${healthResponse.status}`);
  }

  return { startTime: Date.now() };
}

export function teardown(data) {
  const duration = (Date.now() - data.startTime) / 1000;
  console.log(`Validation load test completed in ${duration.toFixed(1)}s`);
}
