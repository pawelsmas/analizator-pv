/**
 * k6 Load Test: BESS Jobs Endpoint
 * Version: v3.9.0
 *
 * Tests job creation and polling flow under load.
 *
 * Usage:
 *   k6 run tests/load/jobs_load.js
 *   k6 run tests/load/jobs_load.js --env SCENARIO=stress
 *
 * Environment Variables:
 *   TARGET_URL: Base URL of the BESS service (default: http://localhost:8031)
 *   SCENARIO: Load scenario (smoke, baseline, stress, soak)
 */

import http from 'k6/http';
import { check, sleep, group } from 'k6';
import { Rate, Trend, Counter } from 'k6/metrics';

// Custom metrics
const jobCreateSuccessRate = new Rate('job_create_success_rate');
const jobCreateDuration = new Trend('job_create_duration_ms');
const jobPollDuration = new Trend('job_poll_duration_ms');
const jobsCreated = new Counter('jobs_created');
const jobsCompleted = new Counter('jobs_completed');
const jobErrors = new Counter('job_errors');

// Configuration
const TARGET_URL = __ENV.TARGET_URL || 'http://localhost:8031';
const SCENARIO = __ENV.SCENARIO || 'smoke';

// Load scenarios (lower VUs for jobs since they're heavier)
const scenarios = {
  smoke: {
    executor: 'constant-vus',
    vus: 1,
    duration: '30s',
  },
  baseline: {
    executor: 'constant-vus',
    vus: 2,
    duration: '2m',
  },
  stress: {
    executor: 'ramping-vus',
    startVUs: 1,
    stages: [
      { duration: '1m', target: 2 },
      { duration: '2m', target: 5 },
      { duration: '1m', target: 5 },
      { duration: '1m', target: 0 },
    ],
  },
  soak: {
    executor: 'constant-vus',
    vus: 3,
    duration: '30m',
  },
};

export const options = {
  scenarios: {
    default: scenarios[SCENARIO] || scenarios.smoke,
  },
  thresholds: {
    'job_create_success_rate': ['rate>0.99'],
    'job_create_duration_ms': ['p(95)<5000'],
    'http_req_failed': ['rate<0.02'],
  },
};

// Generate batch job request
function generateBatchJobRequest() {
  const items = [];
  const numItems = Math.floor(Math.random() * 3) + 1; // 1-3 items

  for (let i = 0; i < numItems; i++) {
    const load_kw = Array.from({ length: 24 }, () => 80 + Math.floor(Math.random() * 40));
    const pv_generation_kw = Array.from({ length: 24 }, (_, h) => {
      if (h < 6 || h > 18) return 0;
      return Math.round(300 * Math.sin((h - 6) * Math.PI / 12));
    });

    items.push({
      load_kw: load_kw,
      pv_generation_kw: pv_generation_kw,
      mode: 'pv_surplus',
      durations_h: [2.0],
      interval_minutes: 60,
      discount_rate: 0.08,
      analysis_years: 15,
      capex_pln_per_kwh: 1800.0,
      import_price_pln_mwh: 800.0,
    });
  }

  return { items: items };
}

// Poll job status until complete or timeout
function pollJobStatus(jobId, maxAttempts = 30, intervalMs = 1000) {
  for (let i = 0; i < maxAttempts; i++) {
    const response = http.get(`${TARGET_URL}/api/bess-dispatch/jobs/${jobId}`);

    if (response.status === 200) {
      try {
        const body = JSON.parse(response.body);
        if (body.status === 'completed' || body.status === 'failed') {
          return body;
        }
      } catch {}
    }

    sleep(intervalMs / 1000);
  }

  return null; // Timeout
}

export default function () {
  group('Job Creation and Polling', function () {
    const payload = JSON.stringify(generateBatchJobRequest());

    const params = {
      headers: {
        'Content-Type': 'application/json',
      },
      timeout: '30s',
    };

    // Create job
    const createStartTime = Date.now();
    const createResponse = http.post(
      `${TARGET_URL}/api/bess-dispatch/jobs/sizing-batch`,
      payload,
      params
    );
    const createDuration = Date.now() - createStartTime;

    jobCreateDuration.add(createDuration);

    const createSuccess = check(createResponse, {
      'job create status is 201 or 202': (r) => r.status === 201 || r.status === 202,
      'response has job_id': (r) => {
        try {
          const body = JSON.parse(r.body);
          return body.job_id !== undefined;
        } catch {
          return false;
        }
      },
    });

    jobCreateSuccessRate.add(createSuccess);

    if (!createSuccess) {
      jobErrors.add(1);
      console.log(`Create error: status=${createResponse.status}`);
      sleep(2);
      return;
    }

    jobsCreated.add(1);

    // Get job ID and poll
    let jobId;
    try {
      const body = JSON.parse(createResponse.body);
      jobId = body.job_id;
    } catch {
      sleep(2);
      return;
    }

    // Poll for completion
    const pollStartTime = Date.now();
    const jobResult = pollJobStatus(jobId);
    const pollDuration = Date.now() - pollStartTime;

    jobPollDuration.add(pollDuration);

    if (jobResult && jobResult.status === 'completed') {
      jobsCompleted.add(1);
    } else {
      console.log(`Job ${jobId} did not complete in time`);
    }

    // Think time between job submissions
    sleep(Math.random() * 3 + 2);
  });
}

export function setup() {
  console.log(`Starting jobs load test against ${TARGET_URL}`);
  console.log(`Scenario: ${SCENARIO}`);

  const healthResponse = http.get(`${TARGET_URL}/health`);
  if (healthResponse.status !== 200) {
    throw new Error(`Target not healthy: ${healthResponse.status}`);
  }

  return { startTime: Date.now() };
}

export function teardown(data) {
  const duration = (Date.now() - data.startTime) / 1000;
  console.log(`Jobs load test completed in ${duration.toFixed(1)}s`);
}
