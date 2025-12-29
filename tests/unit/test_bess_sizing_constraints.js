/**
 * Unit tests for BESS Sizing Constraints (v0.8.0)
 *
 * Run with: node tests/unit/test_bess_sizing_constraints.js
 */

// Mock DOM environment
global.document = {
  getElementById: () => null,
  querySelector: () => null,
  addEventListener: () => {}
};
global.window = {};
global.localStorage = {
  data: {},
  getItem(key) { return this.data[key] || null; },
  setItem(key, value) { this.data[key] = value; }
};

// Simulate advancedConfig from bess.js
let advancedConfig = {
  topology: 'pv_load',
  objective: 'npv',
  constraints: [],
  gridConstraints: {
    maxExportKw: null,
    maxImportKw: null,
    allowExport: true,
    unservedLoadPenaltyPlnKwh: 0
  },
  sizingConstraints: {
    maxCapexPln: null,
    maxPaybackYears: null,
    minNpvPln: null,
    minNetSavingsPln: null,
    requireNoUnservedLoad: false,
    maxUnservedLoadKwh: null
  }
};

// Simulate updateSizingConstraint function from bess.js
function updateSizingConstraint(field, value) {
  if (!advancedConfig.sizingConstraints) {
    advancedConfig.sizingConstraints = {
      maxCapexPln: null,
      maxPaybackYears: null,
      minNpvPln: null,
      minNetSavingsPln: null,
      requireNoUnservedLoad: false,
      maxUnservedLoadKwh: null
    };
  }

  if (field === 'requireNoUnservedLoad') {
    advancedConfig.sizingConstraints.requireNoUnservedLoad = Boolean(value);
  } else {
    const numValue = value === '' || value === null || value === undefined ? null : parseFloat(value);
    advancedConfig.sizingConstraints[field] = numValue;
  }

  localStorage.setItem('bessSizingConstraints', JSON.stringify(advancedConfig.sizingConstraints));
}

// Simulate buildSizingRequest constraints_config section
function buildConstraintsConfig() {
  const sc = advancedConfig.sizingConstraints;
  if (!sc) return null;

  const hasConstraints = (
    sc.maxCapexPln !== null ||
    sc.maxPaybackYears !== null ||
    sc.minNpvPln !== null ||
    sc.minNetSavingsPln !== null ||
    sc.requireNoUnservedLoad ||
    sc.maxUnservedLoadKwh !== null
  );

  if (!hasConstraints) return null;

  return {
    max_capex_pln: sc.maxCapexPln,
    max_payback_years: sc.maxPaybackYears,
    min_npv_pln: sc.minNpvPln,
    min_net_savings_pln: sc.minNetSavingsPln,
    require_no_unserved_load: sc.requireNoUnservedLoad,
    max_unserved_load_kwh: sc.maxUnservedLoadKwh
  };
}

// Test framework
let passed = 0;
let failed = 0;

function test(name, fn) {
  try {
    fn();
    console.log(`  PASS: ${name}`);
    passed++;
  } catch (e) {
    console.log(`  FAIL: ${name}`);
    console.log(`        ${e.message}`);
    failed++;
  }
}

function assert(condition, message) {
  if (!condition) throw new Error(message || 'Assertion failed');
}

function assertEqual(actual, expected, message) {
  if (actual !== expected) {
    throw new Error(`${message || 'Assertion failed'}: expected ${expected}, got ${actual}`);
  }
}

// Reset config before each test
function reset() {
  advancedConfig.sizingConstraints = {
    maxCapexPln: null,
    maxPaybackYears: null,
    minNpvPln: null,
    minNetSavingsPln: null,
    requireNoUnservedLoad: false,
    maxUnservedLoadKwh: null
  };
  localStorage.data = {};
}

// ============================================
// TESTS
// ============================================

console.log('\nTesting BESS Sizing Constraints (v0.8.0)\n');

console.log('1. updateSizingConstraint() tests:');

test('maxCapexPln accepts numeric value', () => {
  reset();
  updateSizingConstraint('maxCapexPln', '500000');
  assertEqual(advancedConfig.sizingConstraints.maxCapexPln, 500000);
});

test('maxCapexPln empty string becomes null', () => {
  reset();
  updateSizingConstraint('maxCapexPln', '500000');
  updateSizingConstraint('maxCapexPln', '');
  assertEqual(advancedConfig.sizingConstraints.maxCapexPln, null);
});

test('maxPaybackYears accepts float', () => {
  reset();
  updateSizingConstraint('maxPaybackYears', '7.5');
  assertEqual(advancedConfig.sizingConstraints.maxPaybackYears, 7.5);
});

test('minNpvPln accepts negative value', () => {
  reset();
  updateSizingConstraint('minNpvPln', '-10000');
  assertEqual(advancedConfig.sizingConstraints.minNpvPln, -10000);
});

test('requireNoUnservedLoad accepts boolean true', () => {
  reset();
  updateSizingConstraint('requireNoUnservedLoad', true);
  assertEqual(advancedConfig.sizingConstraints.requireNoUnservedLoad, true);
});

test('requireNoUnservedLoad accepts boolean false', () => {
  reset();
  updateSizingConstraint('requireNoUnservedLoad', true);
  updateSizingConstraint('requireNoUnservedLoad', false);
  assertEqual(advancedConfig.sizingConstraints.requireNoUnservedLoad, false);
});

test('localStorage updated on constraint change', () => {
  reset();
  updateSizingConstraint('maxCapexPln', '200000');
  const saved = JSON.parse(localStorage.getItem('bessSizingConstraints'));
  assertEqual(saved.maxCapexPln, 200000);
});

console.log('\n2. buildConstraintsConfig() tests:');

test('returns null when no constraints set', () => {
  reset();
  const config = buildConstraintsConfig();
  assertEqual(config, null);
});

test('returns config when maxCapexPln set', () => {
  reset();
  updateSizingConstraint('maxCapexPln', '300000');
  const config = buildConstraintsConfig();
  assert(config !== null, 'config should not be null');
  assertEqual(config.max_capex_pln, 300000);
});

test('returns config when requireNoUnservedLoad true', () => {
  reset();
  updateSizingConstraint('requireNoUnservedLoad', true);
  const config = buildConstraintsConfig();
  assert(config !== null, 'config should not be null');
  assertEqual(config.require_no_unserved_load, true);
});

test('maps all fields correctly to snake_case', () => {
  reset();
  updateSizingConstraint('maxCapexPln', '100000');
  updateSizingConstraint('maxPaybackYears', '10');
  updateSizingConstraint('minNpvPln', '50000');
  updateSizingConstraint('minNetSavingsPln', '5000');
  updateSizingConstraint('requireNoUnservedLoad', true);
  updateSizingConstraint('maxUnservedLoadKwh', '100');

  const config = buildConstraintsConfig();

  assertEqual(config.max_capex_pln, 100000);
  assertEqual(config.max_payback_years, 10);
  assertEqual(config.min_npv_pln, 50000);
  assertEqual(config.min_net_savings_pln, 5000);
  assertEqual(config.require_no_unserved_load, true);
  assertEqual(config.max_unserved_load_kwh, 100);
});

// Summary
console.log('\n========================================');
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('========================================\n');

process.exit(failed > 0 ? 1 : 0);
