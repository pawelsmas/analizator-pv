/**
 * Unit tests for BESS Request Builder
 *
 * Run with: node tests/unit/test_bess_request_builder.js
 */

// Mock sharedData
const mockSharedData = {
  analyticalPeriod: {
    start_datetime: '2025-01-01T00:00:00',
    end_datetime: '2025-01-08T00:00:00',
    interval_minutes: 60,
    n_points: 168,
    timezone: 'Europe/Warsaw',
    clock_mode: 'CET_FIXED',
    is_full_year: false,
    annualization_factor: 52.14,
  },
  settings: {
    bessMode: 'pro',
    bessTopology: 'pv_bess',
    bessDuration: 'auto',
    bessRoundtripEfficiency: 0.90,
    bessSocMin: 0.10,
    bessSocMax: 0.90,
    bessSocInitial: 0.50,
    bessCapexPerKwh: 1500,
    bessCapexPerKw: 300,
    bessOpexPctPerYear: 1.5,
    bessLifetimeYears: 15,
    bessDegradationPctPerYear: 2.0,
    bessPeakShavingEnabled: true,
    bessPeakShavingTargetKw: 500,
    bessPowerChargePlnPerKwMonth: 50,
    discountRate: 8,
    totalEnergyPrice: 800,
    // Arbitrage settings
    bessOsdArbitrageEnabled: false,
    bessPriceArbitrageEnabled: false,
  }
};

// Minimal mock window
global.window = {
  sharedData: mockSharedData,
  parent: { sharedData: mockSharedData },
};

// Load the builder
const fs = require('fs');
const path = require('path');
const builderCode = fs.readFileSync(
  path.join(__dirname, '../../services/frontend-shell/bess_request_builder.js'),
  'utf-8'
);
eval(builderCode);

// Test suite
let passed = 0;
let failed = 0;

function test(name, fn) {
  try {
    fn();
    console.log(`✅ ${name}`);
    passed++;
  } catch (e) {
    console.log(`❌ ${name}`);
    console.log(`   Error: ${e.message}`);
    failed++;
  }
}

function assertEqual(actual, expected, msg = '') {
  if (actual !== expected) {
    throw new Error(`${msg}: expected ${expected}, got ${actual}`);
  }
}

function assertExists(obj, key, msg = '') {
  if (!(key in obj)) {
    throw new Error(`${msg}: missing key "${key}"`);
  }
}

// Tests
console.log('\n=== BESS Request Builder Tests ===\n');

test('buildBessRequest returns object', () => {
  const load_kw = Array(168).fill(100);
  const result = window.buildBessRequest({ load_kw });
  assertEqual(typeof result, 'object', 'Result type');
});

test('buildBessRequest includes analytical_period', () => {
  const load_kw = Array(168).fill(100);
  const result = window.buildBessRequest({ load_kw });
  assertExists(result, 'analytical_period', 'Has analytical_period');
  assertEqual(result.analytical_period.start_datetime, '2025-01-01T00:00:00', 'Start datetime');
});

test('buildBessRequest includes load_kw', () => {
  const load_kw = Array(168).fill(100);
  const result = window.buildBessRequest({ load_kw });
  assertExists(result, 'load_kw', 'Has load_kw');
  assertEqual(result.load_kw.length, 168, 'Load length');
});

test('buildBessRequest uses settings for capex', () => {
  const load_kw = Array(168).fill(100);
  const result = window.buildBessRequest({ load_kw });
  assertEqual(result.capex_per_kwh, 1500, 'CAPEX per kWh');
});

test('buildBessRequest includes peak_limit_kw when enabled', () => {
  const load_kw = Array(168).fill(100);
  const result = window.buildBessRequest({ load_kw });
  assertExists(result, 'peak_limit_kw', 'Has peak_limit_kw');
  assertEqual(result.peak_limit_kw, 500, 'Peak limit');
});

test('buildBessRequest topology defaults to pv_load', () => {
  const load_kw = Array(168).fill(100);
  const result = window.buildBessRequest({ load_kw });
  assertExists(result, 'topology', 'Has topology');
  assertEqual(result.topology, 'pv_load', 'Topology');
});

test('buildBessRequest no arbitrage_config when disabled', () => {
  const load_kw = Array(168).fill(100);
  const result = window.buildBessRequest({ load_kw });
  assertEqual(result.arbitrage_config, undefined, 'No arbitrage_config');
});

test('buildBessRequest with OSD arbitrage enabled', () => {
  // Enable arbitrage
  window.sharedData.settings.bessOsdArbitrageEnabled = true;
  window.sharedData.settings.bessOsdTariffGroup = 'C12a';
  window.sharedData.settings.bessOsdOperator = 'pge';

  const load_kw = Array(168).fill(100);
  const result = window.buildBessRequest({ load_kw });

  assertExists(result, 'arbitrage_config', 'Has arbitrage_config');
  assertEqual(result.arbitrage_config.enabled, true, 'Arbitrage enabled');
  assertEqual(result.arbitrage_config.tariff_id, 'C12a', 'Tariff ID');
  assertEqual(result.arbitrage_config.strategy, 'zone_based', 'Strategy');

  // Reset
  window.sharedData.settings.bessOsdArbitrageEnabled = false;
});

test('validateBessRequest returns valid for good request', () => {
  const load_kw = Array(168).fill(100);
  const request = window.buildBessRequest({ load_kw });
  const validation = window.validateBessRequest(request);
  assertEqual(validation.valid, true, 'Is valid');
  assertEqual(validation.errors.length, 0, 'No errors');
});

test('validateBessRequest returns error for empty load', () => {
  const request = { load_kw: [] };
  const validation = window.validateBessRequest(request);
  assertEqual(validation.valid, false, 'Is invalid');
  assertEqual(validation.errors.length > 0, true, 'Has errors');
});

// Summary
console.log(`\n=== Results: ${passed} passed, ${failed} failed ===\n`);
process.exit(failed > 0 ? 1 : 0);
