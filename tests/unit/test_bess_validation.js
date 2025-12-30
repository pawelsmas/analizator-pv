/**
 * Unit tests for BESS Scenario Validation (v1.4.0)
 *
 * Run with: node tests/unit/test_bess_validation.js
 */

// Mock DOM environment
global.document = {
  getElementById: (id) => {
    if (id === 'validationScenarioSelect') {
      return {
        innerHTML: '',
        value: '',
        options: []
      };
    }
    if (id === 'scenarioDetailsPanel') {
      return { style: { display: 'none' } };
    }
    if (id === 'scenarioDescription') {
      return { textContent: '' };
    }
    if (id === 'scenarioExpectedKpis') {
      return { innerHTML: '' };
    }
    if (id === 'validationResultsPanel') {
      return { style: { display: 'none' } };
    }
    if (id === 'validationStatus') {
      return { className: '', innerHTML: '' };
    }
    if (id === 'validationDiffsTable') {
      return { innerHTML: '' };
    }
    if (id === 'runValidationBtn') {
      return { disabled: false };
    }
    return null;
  },
  querySelector: () => null,
  addEventListener: () => {}
};
global.window = {};
global.localStorage = {
  data: {},
  getItem(key) { return this.data[key] || null; },
  setItem(key, value) { this.data[key] = value; }
};
global.console = console;

// Simulate validationState from bess.js
let validationState = {
  scenarios: [],
  selectedScenario: null,
  isLoading: false
};

// Simulate loadAvailableScenarios function (hardcoded scenarios)
function loadAvailableScenarios() {
  const scenarios = [
    {
      id: 'baseline_stacked_no_arb',
      description: 'STACKED mode without arbitrage - baseline savings validation',
      request_file: 'docs/scenarios/baseline_stacked_no_arb.json',
      expected_kpis: {
        "recommended_variant": "medium",
        "variants[0].npv_pln": 50000,
        "variants[0].savings_breakdown.net_savings_pln": 8000,
        "period_info.period_hours": 8760
      },
      tolerance: { rel: 0.05, abs: 100 }
    },
    {
      id: 'baseline_stacked_with_arb',
      description: 'STACKED mode with ToU arbitrage - arbitrage savings validation',
      request_file: 'docs/scenarios/baseline_stacked_with_arb.json',
      expected_kpis: {
        "recommended_variant": "medium",
        "variants[0].npv_pln": 55000,
        "variants[0].savings_breakdown.arbitrage_savings_pln": 1000,
        "period_info.period_hours": 8760
      },
      tolerance: { rel: 0.05, abs: 100 }
    }
  ];

  validationState.scenarios = scenarios;
  return scenarios;
}

// Simulate loadScenarioDetails
function loadScenarioDetails(scenarioId) {
  if (!scenarioId) {
    validationState.selectedScenario = null;
    return null;
  }

  const scenario = validationState.scenarios.find(s => s.id === scenarioId);
  if (!scenario) {
    validationState.selectedScenario = null;
    return null;
  }

  validationState.selectedScenario = scenario;
  return scenario;
}

// Simulate displayValidationResults
function displayValidationResults(result) {
  const passed = result.passed;
  const diffs = result.diffs || [];

  return {
    passed: passed,
    diffCount: diffs.length,
    passingDiffs: diffs.filter(d => d.passed).length,
    failingDiffs: diffs.filter(d => !d.passed).length
  };
}

// Helper to format KPI value for display
function formatKpiValue(value) {
  if (value === null || value === undefined) {
    return 'null';
  }
  if (typeof value === 'number') {
    if (Number.isInteger(value)) {
      return value.toLocaleString('pl-PL');
    }
    return value.toLocaleString('pl-PL', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  if (typeof value === 'string') {
    return `"${value}"`;
  }
  return String(value);
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
    throw new Error(`${msg} Expected ${expected}, got ${actual}`);
  }
}

function assertTrue(condition, msg = '') {
  if (!condition) {
    throw new Error(msg || 'Expected true');
  }
}

function assertFalse(condition, msg = '') {
  if (condition) {
    throw new Error(msg || 'Expected false');
  }
}

// Reset state before each test group
function resetState() {
  validationState = {
    scenarios: [],
    selectedScenario: null,
    isLoading: false
  };
}

console.log('\n=== BESS Validation Unit Tests ===\n');

// === Test: loadAvailableScenarios ===
console.log('-- loadAvailableScenarios --');

test('loadAvailableScenarios returns scenarios array', () => {
  resetState();
  const scenarios = loadAvailableScenarios();
  assertTrue(Array.isArray(scenarios), 'Should return array');
  assertTrue(scenarios.length >= 2, 'Should have at least 2 scenarios');
});

test('loadAvailableScenarios populates validationState.scenarios', () => {
  resetState();
  loadAvailableScenarios();
  assertTrue(validationState.scenarios.length >= 2, 'State should have scenarios');
});

test('scenario has required fields', () => {
  resetState();
  const scenarios = loadAvailableScenarios();
  const scenario = scenarios[0];
  assertTrue('id' in scenario, 'Scenario should have id');
  assertTrue('description' in scenario, 'Scenario should have description');
  assertTrue('request_file' in scenario, 'Scenario should have request_file');
  assertTrue('expected_kpis' in scenario, 'Scenario should have expected_kpis');
  assertTrue('tolerance' in scenario, 'Scenario should have tolerance');
});

test('scenario tolerance has rel and abs', () => {
  resetState();
  const scenarios = loadAvailableScenarios();
  const scenario = scenarios[0];
  assertTrue('rel' in scenario.tolerance, 'Tolerance should have rel');
  assertTrue('abs' in scenario.tolerance, 'Tolerance should have abs');
  assertEqual(typeof scenario.tolerance.rel, 'number', 'rel should be number');
  assertEqual(typeof scenario.tolerance.abs, 'number', 'abs should be number');
});

// === Test: loadScenarioDetails ===
console.log('\n-- loadScenarioDetails --');

test('loadScenarioDetails returns null for empty id', () => {
  resetState();
  loadAvailableScenarios();
  const result = loadScenarioDetails('');
  assertEqual(result, null, 'Should return null for empty id');
  assertEqual(validationState.selectedScenario, null, 'State should be null');
});

test('loadScenarioDetails returns null for unknown id', () => {
  resetState();
  loadAvailableScenarios();
  const result = loadScenarioDetails('unknown_scenario');
  assertEqual(result, null, 'Should return null for unknown id');
});

test('loadScenarioDetails returns scenario for valid id', () => {
  resetState();
  loadAvailableScenarios();
  const result = loadScenarioDetails('baseline_stacked_no_arb');
  assertTrue(result !== null, 'Should return scenario');
  assertEqual(result.id, 'baseline_stacked_no_arb', 'Should return correct scenario');
});

test('loadScenarioDetails sets selectedScenario in state', () => {
  resetState();
  loadAvailableScenarios();
  loadScenarioDetails('baseline_stacked_with_arb');
  assertTrue(validationState.selectedScenario !== null, 'State should have selected scenario');
  assertEqual(validationState.selectedScenario.id, 'baseline_stacked_with_arb', 'Should select correct scenario');
});

// === Test: displayValidationResults ===
console.log('\n-- displayValidationResults --');

test('displayValidationResults handles passed result', () => {
  const result = {
    passed: true,
    diffs: [
      { field: 'npv_pln', expected: 50000, actual: 50100, passed: true },
      { field: 'payback', expected: 5.0, actual: 5.1, passed: true }
    ]
  };
  const display = displayValidationResults(result);
  assertTrue(display.passed, 'Should show passed');
  assertEqual(display.diffCount, 2, 'Should have 2 diffs');
  assertEqual(display.passingDiffs, 2, 'All diffs should pass');
  assertEqual(display.failingDiffs, 0, 'No diffs should fail');
});

test('displayValidationResults handles failed result', () => {
  const result = {
    passed: false,
    diffs: [
      { field: 'npv_pln', expected: 50000, actual: 40000, passed: false },
      { field: 'payback', expected: 5.0, actual: 5.1, passed: true }
    ]
  };
  const display = displayValidationResults(result);
  assertFalse(display.passed, 'Should show failed');
  assertEqual(display.diffCount, 2, 'Should have 2 diffs');
  assertEqual(display.passingDiffs, 1, 'One diff should pass');
  assertEqual(display.failingDiffs, 1, 'One diff should fail');
});

test('displayValidationResults handles empty diffs', () => {
  const result = {
    passed: true,
    diffs: []
  };
  const display = displayValidationResults(result);
  assertTrue(display.passed, 'Should show passed');
  assertEqual(display.diffCount, 0, 'Should have 0 diffs');
});

test('displayValidationResults handles missing diffs', () => {
  const result = {
    passed: true
  };
  const display = displayValidationResults(result);
  assertTrue(display.passed, 'Should show passed');
  assertEqual(display.diffCount, 0, 'Should default to 0 diffs');
});

// === Test: formatKpiValue ===
console.log('\n-- formatKpiValue --');

test('formatKpiValue handles null', () => {
  assertEqual(formatKpiValue(null), 'null', 'Should return "null"');
});

test('formatKpiValue handles undefined', () => {
  assertEqual(formatKpiValue(undefined), 'null', 'Should return "null"');
});

test('formatKpiValue handles integer', () => {
  const result = formatKpiValue(50000);
  assertTrue(result.includes('50'), 'Should contain 50');
});

test('formatKpiValue handles float', () => {
  const result = formatKpiValue(5.25);
  assertTrue(result.includes('5'), 'Should contain 5');
  assertTrue(result.includes('25'), 'Should contain 25');
});

test('formatKpiValue handles string', () => {
  const result = formatKpiValue('medium');
  assertEqual(result, '"medium"', 'Should wrap in quotes');
});

// === Test: Scenario structure ===
console.log('\n-- Scenario Structure --');

test('baseline_stacked_no_arb has correct expected_kpis', () => {
  resetState();
  loadAvailableScenarios();
  const scenario = validationState.scenarios.find(s => s.id === 'baseline_stacked_no_arb');
  assertTrue('recommended_variant' in scenario.expected_kpis, 'Should have recommended_variant');
  assertTrue('variants[0].npv_pln' in scenario.expected_kpis, 'Should have npv_pln');
});

test('baseline_stacked_with_arb has arbitrage kpi', () => {
  resetState();
  loadAvailableScenarios();
  const scenario = validationState.scenarios.find(s => s.id === 'baseline_stacked_with_arb');
  assertTrue('variants[0].savings_breakdown.arbitrage_savings_pln' in scenario.expected_kpis, 'Should have arbitrage_savings_pln');
});

// Summary
console.log('\n=== Summary ===');
console.log(`Passed: ${passed}`);
console.log(`Failed: ${failed}`);
console.log(`Total:  ${passed + failed}`);

if (failed > 0) {
  process.exit(1);
}
