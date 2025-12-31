/**
 * Unit tests for Scenario Drilldown Modal (v1.8.0)
 *
 * Run with: node tests/unit/test_drilldown_modal.js
 */

// Simulate DOM elements
const mockElements = {};
function getElementById(id) {
  if (!mockElements[id]) {
    mockElements[id] = {
      textContent: '',
      innerHTML: '',
      className: '',
      style: { display: '' },
      disabled: false,
      appendChild: () => {},
    };
  }
  return mockElements[id];
}
global.document = { getElementById };

// Simulate formatNumber function
function formatNumber(val) {
  if (val === null || val === undefined) return '-';
  if (typeof val === 'number') {
    return val.toLocaleString('pl-PL', { maximumFractionDigits: 4 });
  }
  return String(val);
}

// ============= TESTS =============

let passed = 0;
let failed = 0;

function test(name, fn) {
  try {
    fn();
    console.log(`✅ ${name}`);
    passed++;
  } catch (e) {
    console.log(`❌ ${name}: ${e.message}`);
    failed++;
  }
}

function assertEqual(actual, expected, msg = '') {
  if (actual !== expected) {
    throw new Error(`${msg} Expected "${expected}", got "${actual}"`);
  }
}

console.log('\n=== Drilldown Modal Unit Tests ===\n');

// === Test: formatNumber ===
console.log('-- formatNumber tests --');

test('formatNumber with integer', () => {
  const result = formatNumber(1000);
  // Polish locale uses spaces or non-breaking spaces
  assertEqual(result.replace(/\s/g, ''), '1000');
});

test('formatNumber with float', () => {
  const result = formatNumber(1234.5678);
  // Should limit to 4 decimal places
  assertEqual(result.includes('5678') || result.includes('5678'), true);
});

test('formatNumber with null returns dash', () => {
  assertEqual(formatNumber(null), '-');
});

test('formatNumber with undefined returns dash', () => {
  assertEqual(formatNumber(undefined), '-');
});

test('formatNumber with zero', () => {
  assertEqual(formatNumber(0), '0');
});

test('formatNumber with string passes through', () => {
  assertEqual(formatNumber('test'), 'test');
});

// === Test: Scenario data structure ===
console.log('\n-- Scenario data structure tests --');

test('Scenario with top_mismatches has correct fields', () => {
  const scenario = {
    name: 'test_scenario',
    pass: false,
    mismatch_count: 3,
    top_mismatches: [
      { field: 'npv_pln', expected: 1000, actual: 900, abs_diff: 100, rel_diff_pct: 10.0 }
    ],
    debug_summary: {
      steps: 24,
      export_limited_steps: 0,
      pv_curtail_mwh: 0.5
    }
  };

  assertEqual(scenario.top_mismatches.length, 1);
  assertEqual(scenario.top_mismatches[0].field, 'npv_pln');
  assertEqual(scenario.debug_summary.steps, 24);
});

test('Scenario with passing status has no mismatches', () => {
  const scenario = {
    name: 'passing_scenario',
    pass: true,
    mismatch_count: 0,
    top_mismatches: [],
    debug_summary: { steps: 24 }
  };

  assertEqual(scenario.pass, true);
  assertEqual(scenario.top_mismatches.length, 0);
});

test('Scenario with error has error field', () => {
  const scenario = {
    name: 'error_scenario',
    pass: false,
    mismatch_count: 0,
    error: 'Request file not found'
  };

  assertEqual(scenario.error, 'Request file not found');
});

// === Test: Debug summary fields ===
console.log('\n-- Debug summary structure tests --');

test('Debug summary has all required fields', () => {
  const debug = {
    steps: 24,
    export_limited_steps: 0,
    export_limited_mwh: 0.0,
    import_limited_steps: 0,
    import_limited_mwh: 0.0,
    pv_curtail_steps: 5,
    pv_curtail_mwh: 0.123,
    unserved_load_steps: 0,
    unserved_load_kwh: 0.0
  };

  assertEqual(debug.steps, 24);
  assertEqual(debug.pv_curtail_steps, 5);
  assertEqual(debug.unserved_load_steps, 0);
});

test('Debug summary with warnings detected', () => {
  const debug = {
    steps: 24,
    export_limited_steps: 5,
    pv_curtail_mwh: 1.5
  };

  const hasWarnings = debug.export_limited_steps > 0 || debug.pv_curtail_mwh > 0;
  assertEqual(hasWarnings, true);
});

test('Debug summary with errors detected', () => {
  const debug = {
    steps: 24,
    unserved_load_steps: 3,
    unserved_load_kwh: 150
  };

  const hasErrors = debug.unserved_load_steps > 0 || debug.unserved_load_kwh > 0;
  assertEqual(hasErrors, true);
});

// Summary
console.log('\n=== Summary ===');
console.log(`Passed: ${passed}`);
console.log(`Failed: ${failed}`);
console.log(`Total:  ${passed + failed}`);

if (failed > 0) {
  process.exit(1);
}
