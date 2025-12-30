/**
 * Unit tests for v1.2.0 frontend SSE progress functions.
 *
 * Tests verify:
 * - SSE connection management (start/stop)
 * - Event handlers for progress, done, error, cancelled, timeout
 * - Download export function
 * - Fallback to polling when SSE unavailable
 */

// Mock EventSource
class MockEventSource {
  constructor(url) {
    this.url = url;
    this.listeners = {};
    this.onopen = null;
    this.onerror = null;
    this.readyState = 0; // CONNECTING
    MockEventSource.instances.push(this);
  }

  addEventListener(event, handler) {
    if (!this.listeners[event]) {
      this.listeners[event] = [];
    }
    this.listeners[event].push(handler);
  }

  removeEventListener(event, handler) {
    if (this.listeners[event]) {
      this.listeners[event] = this.listeners[event].filter(h => h !== handler);
    }
  }

  dispatchEvent(event) {
    const handlers = this.listeners[event.type] || [];
    handlers.forEach(h => h(event));
  }

  close() {
    this.readyState = 2; // CLOSED
  }

  // Test helper: simulate event
  simulateEvent(eventType, data) {
    const event = {
      type: eventType,
      data: typeof data === 'string' ? data : JSON.stringify(data)
    };
    this.dispatchEvent(event);
  }
}
MockEventSource.instances = [];

// Mock global objects
global.EventSource = MockEventSource;
global.activeEventSource = null;
global.activeJobId = null;
global.jobPollingInterval = null;

// Mock document
const mockContainers = {};
global.document = {
  getElementById: (id) => mockContainers[id] || null,
  createElement: (tag) => ({
    tag,
    href: '',
    download: '',
    click: function() { this.clicked = true; }
  }),
  body: {
    appendChild: () => {},
    removeChild: () => {}
  }
};

// Mock URL
global.URL = {
  createObjectURL: (blob) => 'blob:test',
  revokeObjectURL: () => {}
};

// Mock fetch
let lastFetchUrl = null;
let lastFetchOptions = null;
let fetchResponse = { ok: true, blob: () => Promise.resolve(new Blob()) };
global.fetch = async (url, options) => {
  lastFetchUrl = url;
  lastFetchOptions = options;
  return {
    ok: fetchResponse.ok,
    status: fetchResponse.ok ? 200 : 404,
    text: () => Promise.resolve(fetchResponse.text || ''),
    json: () => Promise.resolve(fetchResponse.json || {}),
    blob: () => Promise.resolve(fetchResponse.blob || new Blob()),
    headers: {
      get: (name) => fetchResponse.headers?.[name] || null
    }
  };
};

// Mock console for testing - but keep reference to real console for output
const realConsole = console;
const consoleLog = [];
const consoleWarn = [];
const consoleError = [];
global.console = {
  log: (...args) => consoleLog.push(args.join(' ')),
  warn: (...args) => consoleWarn.push(args.join(' ')),
  error: (...args) => consoleError.push(args.join(' '))
};

// Mock alert
global.alert = () => {};

// Mock setInterval/clearInterval
let intervals = [];
let intervalId = 0;
global.setInterval = (fn, ms) => {
  const id = ++intervalId;
  intervals.push({ id, fn, ms });
  return id;
};
global.clearInterval = (id) => {
  intervals = intervals.filter(i => i.id !== id);
};

// Helper to reset mocks
function resetMocks() {
  MockEventSource.instances = [];
  global.activeEventSource = null;
  global.activeJobId = null;
  global.jobPollingInterval = null;
  consoleLog.length = 0;
  consoleWarn.length = 0;
  consoleError.length = 0;
  intervals = [];
  lastFetchUrl = null;
  lastFetchOptions = null;
  fetchResponse = { ok: true };
  mockContainers.batchResultsContainer = { innerHTML: '', style: { display: 'none' } };
}

// Test functions (simulating what's in bess.js)
function stopJobSSE() {
  if (global.activeEventSource) {
    global.activeEventSource.close();
    global.activeEventSource = null;
    console.log('[SSE] Stopped SSE stream');
  }
}

function stopJobPolling() {
  if (global.jobPollingInterval) {
    clearInterval(global.jobPollingInterval);
    global.jobPollingInterval = null;
  }
}

function startJobPolling(jobId) {
  stopJobPolling();
  console.log('[BATCH] Starting polling for job:', jobId);
  global.jobPollingInterval = setInterval(() => {}, 2000);
}

function startJobSSE(jobId) {
  stopJobSSE();
  stopJobPolling();

  if (typeof EventSource === 'undefined') {
    console.warn('[BATCH] EventSource not supported, falling back to polling');
    startJobPolling(jobId);
    return;
  }

  const bessDispatchUrl = '/api/bess-dispatch';
  global.activeEventSource = new EventSource(`${bessDispatchUrl}/jobs/${jobId}/events?poll_interval=0.5`);

  global.activeEventSource.addEventListener('progress', (event) => {
    try {
      const data = JSON.parse(event.data);
      console.log('[SSE] Progress event:', JSON.stringify(data));
    } catch (e) {
      console.error('[SSE] Failed to parse progress event:', e);
    }
  });

  global.activeEventSource.addEventListener('done', (event) => {
    try {
      const data = JSON.parse(event.data);
      console.log('[SSE] Done event:', JSON.stringify(data));
      stopJobSSE();
      global.activeJobId = null;
    } catch (e) {
      console.error('[SSE] Failed to parse done event:', e);
    }
  });

  global.activeEventSource.addEventListener('error', (event) => {
    try {
      const data = JSON.parse(event.data);
      console.log('[SSE] Error event:', JSON.stringify(data));
      stopJobSSE();
      global.activeJobId = null;
    } catch (e) {
      console.error('[SSE] Failed to parse error event:', e);
    }
  });

  global.activeEventSource.addEventListener('cancelled', (event) => {
    try {
      const data = JSON.parse(event.data);
      console.log('[SSE] Cancelled event:', JSON.stringify(data));
      stopJobSSE();
      global.activeJobId = null;
    } catch (e) {
      console.error('[SSE] Failed to parse cancelled event:', e);
    }
  });

  global.activeEventSource.addEventListener('timeout', (event) => {
    console.warn('[SSE] Stream timed out, falling back to polling');
    stopJobSSE();
    startJobPolling(jobId);
  });

  global.activeEventSource.onerror = (error) => {
    console.error('[SSE] Connection error:', error);
    stopJobSSE();
    startJobPolling(jobId);
  };

  console.log('[SSE] Started SSE stream for job:', jobId);
}

async function downloadJobExport(jobId, format = 'json') {
  const validFormats = ['json', 'csv', 'zip'];
  if (!validFormats.includes(format)) {
    console.error('[EXPORT] Invalid format:', format);
    return;
  }

  try {
    const bessDispatchUrl = '/api/bess-dispatch';
    const response = await fetch(`${bessDispatchUrl}/jobs/${jobId}/export/${format}`);

    if (!response.ok) {
      throw new Error(`Export failed: ${response.status}`);
    }

    console.log('[EXPORT] Downloaded: job_' + jobId.substring(0, 8) + '.' + format);
  } catch (e) {
    console.error('[EXPORT] Download failed:', e.message);
  }
}

// =============================================================================
// Tests
// =============================================================================

let passed = 0;
let failed = 0;
const asyncTests = [];

function test(name, fn) {
  resetMocks();
  try {
    const result = fn();
    if (result && typeof result.then === 'function') {
      // Async test - store for later
      asyncTests.push({ name, promise: result });
    } else {
      realConsole.log(`✓ ${name}`);
      passed++;
    }
  } catch (e) {
    realConsole.error(`✗ ${name}: ${e.message}`);
    failed++;
  }
}

async function runAsyncTests() {
  for (const { name, promise } of asyncTests) {
    resetMocks();
    try {
      await promise;
      console.log(`✓ ${name}`);
      passed++;
    } catch (e) {
      console.error(`✗ ${name}: ${e.message}`);
      failed++;
    }
  }
}

function assertEqual(actual, expected, message = '') {
  if (actual !== expected) {
    throw new Error(`${message} Expected ${expected}, got ${actual}`);
  }
}

function assertTrue(value, message = '') {
  if (!value) {
    throw new Error(`${message} Expected truthy value, got ${value}`);
  }
}

function assertFalse(value, message = '') {
  if (value) {
    throw new Error(`${message} Expected falsy value, got ${value}`);
  }
}

function assertContains(str, substring, message = '') {
  if (!str.includes(substring)) {
    throw new Error(`${message} Expected "${str}" to contain "${substring}"`);
  }
}

// -----------------------------------------------------------------------------
// SSE Connection Tests
// -----------------------------------------------------------------------------

test('startJobSSE creates EventSource with correct URL', () => {
  startJobSSE('test-job-123');

  assertEqual(MockEventSource.instances.length, 1, 'Should create one EventSource');
  assertContains(MockEventSource.instances[0].url, '/api/bess-dispatch/jobs/test-job-123/events');
  assertContains(MockEventSource.instances[0].url, 'poll_interval=0.5');
});

test('startJobSSE sets activeEventSource', () => {
  startJobSSE('test-job-123');

  assertTrue(global.activeEventSource !== null, 'activeEventSource should be set');
});

test('startJobSSE logs connection start', () => {
  startJobSSE('test-job-123');

  assertTrue(consoleLog.some(msg => msg.includes('[SSE] Started SSE stream')), 'Should log start');
});

test('stopJobSSE closes connection', () => {
  startJobSSE('test-job-123');
  const es = global.activeEventSource;

  stopJobSSE();

  assertEqual(es.readyState, 2, 'EventSource should be closed');
  assertEqual(global.activeEventSource, null, 'activeEventSource should be null');
});

test('stopJobSSE logs stop', () => {
  startJobSSE('test-job-123');
  stopJobSSE();

  assertTrue(consoleLog.some(msg => msg.includes('[SSE] Stopped SSE stream')), 'Should log stop');
});

test('startJobSSE stops existing SSE before creating new one', () => {
  startJobSSE('job-1');
  const first = global.activeEventSource;

  startJobSSE('job-2');

  assertEqual(first.readyState, 2, 'First EventSource should be closed');
  assertTrue(global.activeEventSource !== first, 'Should have new EventSource');
});

test('startJobSSE stops existing polling', () => {
  startJobPolling('job-1');
  assertEqual(intervals.length, 1, 'Should have polling interval');

  startJobSSE('job-2');

  assertEqual(intervals.length, 0, 'Should clear polling interval');
});

// -----------------------------------------------------------------------------
// SSE Event Handler Tests
// -----------------------------------------------------------------------------

test('progress event is handled', () => {
  startJobSSE('test-job-123');

  global.activeEventSource.simulateEvent('progress', {
    items_done: 5,
    items_total: 10,
    error_count: 0
  });

  assertTrue(consoleLog.some(msg => msg.includes('[SSE] Progress event')), 'Should log progress');
});

test('done event closes connection', () => {
  startJobSSE('test-job-123');
  const es = global.activeEventSource;

  es.simulateEvent('done', {
    items_done: 10,
    items_total: 10,
    error_count: 0
  });

  assertEqual(es.readyState, 2, 'EventSource should be closed');
  assertEqual(global.activeEventSource, null, 'activeEventSource should be null');
});

test('done event logs completion', () => {
  startJobSSE('test-job-123');

  global.activeEventSource.simulateEvent('done', {
    items_done: 10,
    items_total: 10
  });

  assertTrue(consoleLog.some(msg => msg.includes('[SSE] Done event')), 'Should log done');
});

test('error event closes connection', () => {
  startJobSSE('test-job-123');
  const es = global.activeEventSource;

  es.simulateEvent('error', {
    items_done: 5,
    items_total: 10,
    message: 'Test error'
  });

  assertEqual(es.readyState, 2, 'EventSource should be closed');
});

test('cancelled event closes connection', () => {
  startJobSSE('test-job-123');
  const es = global.activeEventSource;

  es.simulateEvent('cancelled', {
    items_done: 3,
    items_total: 10
  });

  assertEqual(es.readyState, 2, 'EventSource should be closed');
  assertTrue(consoleLog.some(msg => msg.includes('[SSE] Cancelled event')), 'Should log cancelled');
});

test('timeout event falls back to polling', () => {
  startJobSSE('test-job-123');

  global.activeEventSource.simulateEvent('timeout', {});

  assertEqual(global.activeEventSource, null, 'SSE should be stopped');
  assertEqual(intervals.length, 1, 'Should start polling');
  assertTrue(consoleWarn.some(msg => msg.includes('timed out')), 'Should warn about timeout');
});

test('connection error falls back to polling', () => {
  startJobSSE('test-job-123');
  const es = global.activeEventSource;

  es.onerror(new Error('Connection failed'));

  assertEqual(global.activeEventSource, null, 'SSE should be stopped');
  assertEqual(intervals.length, 1, 'Should start polling');
});

// -----------------------------------------------------------------------------
// Polling Fallback Tests
// -----------------------------------------------------------------------------

test('startJobPolling creates interval', () => {
  startJobPolling('test-job-123');

  assertEqual(intervals.length, 1, 'Should create one interval');
  assertEqual(intervals[0].ms, 2000, 'Should poll every 2 seconds');
});

test('stopJobPolling clears interval', () => {
  startJobPolling('test-job-123');
  stopJobPolling();

  assertEqual(intervals.length, 0, 'Should clear interval');
  assertEqual(global.jobPollingInterval, null, 'jobPollingInterval should be null');
});

test('startJobPolling stops existing interval first', () => {
  startJobPolling('job-1');
  startJobPolling('job-2');

  assertEqual(intervals.length, 1, 'Should only have one interval');
});

// -----------------------------------------------------------------------------
// Download Export Tests (run synchronously with immediate await)
// -----------------------------------------------------------------------------

// These tests need to be run in an async context
async function runDownloadTests() {
  // Test: downloadJobExport calls correct URL for JSON
  resetMocks();
  await downloadJobExport('test-job-123', 'json');
  if (lastFetchUrl === '/api/bess-dispatch/jobs/test-job-123/export/json') {
    realConsole.log('✓ downloadJobExport calls correct URL for JSON');
    passed++;
  } else {
    realConsole.error('✗ downloadJobExport calls correct URL for JSON');
    failed++;
  }

  // Test: downloadJobExport calls correct URL for CSV
  resetMocks();
  await downloadJobExport('test-job-123', 'csv');
  if (lastFetchUrl === '/api/bess-dispatch/jobs/test-job-123/export/csv') {
    realConsole.log('✓ downloadJobExport calls correct URL for CSV');
    passed++;
  } else {
    realConsole.error('✗ downloadJobExport calls correct URL for CSV');
    failed++;
  }

  // Test: downloadJobExport calls correct URL for ZIP
  resetMocks();
  await downloadJobExport('test-job-123', 'zip');
  if (lastFetchUrl === '/api/bess-dispatch/jobs/test-job-123/export/zip') {
    realConsole.log('✓ downloadJobExport calls correct URL for ZIP');
    passed++;
  } else {
    realConsole.error('✗ downloadJobExport calls correct URL for ZIP');
    failed++;
  }

  // Test: downloadJobExport rejects invalid format
  resetMocks();
  await downloadJobExport('test-job-123', 'invalid');
  if (lastFetchUrl === null && consoleError.some(msg => msg.includes('Invalid format'))) {
    realConsole.log('✓ downloadJobExport rejects invalid format');
    passed++;
  } else {
    realConsole.error('✗ downloadJobExport rejects invalid format');
    failed++;
  }

  // Test: downloadJobExport logs success
  resetMocks();
  fetchResponse = { ok: true };
  await downloadJobExport('test-job-123', 'json');
  if (consoleLog.some(msg => msg.includes('[EXPORT] Downloaded'))) {
    realConsole.log('✓ downloadJobExport logs success');
    passed++;
  } else {
    realConsole.error('✗ downloadJobExport logs success');
    failed++;
  }

  // Test: downloadJobExport handles fetch error
  resetMocks();
  fetchResponse = { ok: false, status: 404 };
  await downloadJobExport('test-job-123', 'json');
  if (consoleError.some(msg => msg.includes('[EXPORT] Download failed'))) {
    realConsole.log('✓ downloadJobExport handles fetch error');
    passed++;
  } else {
    realConsole.error('✗ downloadJobExport handles fetch error');
    failed++;
  }
}

// -----------------------------------------------------------------------------
// Run all tests
// -----------------------------------------------------------------------------

runDownloadTests().then(() => {
  realConsole.log(`\n========================================`);
  realConsole.log(`Tests: ${passed + failed}, Passed: ${passed}, Failed: ${failed}`);
  realConsole.log(`========================================`);

  if (failed > 0) {
    process.exit(1);
  }
});
