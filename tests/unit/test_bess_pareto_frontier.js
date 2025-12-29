/**
 * Unit tests for BESS Pareto Frontier Table (v0.8.0)
 *
 * Run with: node tests/unit/test_bess_pareto_frontier.js
 */

// Mock DOM environment
global.document = {
  _elements: {},
  getElementById(id) {
    if (!this._elements[id]) {
      this._elements[id] = {
        style: { display: '' },
        innerHTML: ''
      };
    }
    return this._elements[id];
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

// Mock formatNumberEU function
function formatNumberEU(num, decimals) {
  return num.toFixed(decimals).replace('.', ',');
}

// Simulate updateParetoFrontierTable function from bess.js
function updateParetoFrontierTable(result) {
  const paretoPanel = document.getElementById('paretoFrontierCompare');
  const tableBody = document.getElementById('paretoFrontierTableBody');

  if (!paretoPanel || !tableBody) return null;

  const pareto = result.pareto_frontier;

  if (!pareto || pareto.length === 0) {
    paretoPanel.style.display = 'none';
    return { visible: false, rows: 0 };
  }

  paretoPanel.style.display = 'block';

  const variantLabels = {
    'small': 'Small (1h)',
    'medium': 'Medium (2h)',
    'large': 'Large (4h)'
  };

  const rows = pareto.map(point => {
    const isOnFrontier = !point.is_dominated;
    const rowClass = isOnFrontier ? 'pareto-row' : 'dominated-row';
    const statusBadge = isOnFrontier
      ? '<span class="pareto-badge">Pareto</span>'
      : '<span class="dominated-badge">Dominated</span>';

    const label = variantLabels[point.variant] || point.variant;
    const npvFormatted = `${formatNumberEU(point.npv_pln / 1000, 0)} tys.`;
    const npvClass = point.npv_pln >= 0 ? 'positive' : 'negative';
    const paybackFormatted = point.payback_years < 100 ? `${formatNumberEU(point.payback_years, 1)} lat` : '> 25 lat';

    return `
      <tr class="${rowClass}">
        <td>${label}</td>
        <td class="${npvClass}">${npvFormatted}</td>
        <td>${paybackFormatted}</td>
        <td>${statusBadge}</td>
      </tr>
    `;
  }).join('');

  tableBody.innerHTML = rows;

  const frontierCount = pareto.filter(p => !p.is_dominated).length;
  return { visible: true, rows: pareto.length, frontierCount, html: rows };
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

function assertIncludes(str, substring, message) {
  if (!str.includes(substring)) {
    throw new Error(`${message || 'Assertion failed'}: expected string to include "${substring}"`);
  }
}

// Reset DOM before each test
function reset() {
  document._elements = {};
}

// ============================================
// TESTS
// ============================================

console.log('\nTesting BESS Pareto Frontier Table (v0.8.0)\n');

console.log('1. Visibility tests:');

test('hides panel when pareto_frontier is empty', () => {
  reset();
  const result = updateParetoFrontierTable({ pareto_frontier: [] });
  assertEqual(result.visible, false);
});

test('hides panel when pareto_frontier is null', () => {
  reset();
  const result = updateParetoFrontierTable({ pareto_frontier: null });
  assertEqual(result.visible, false);
});

test('hides panel when pareto_frontier is undefined', () => {
  reset();
  const result = updateParetoFrontierTable({});
  assertEqual(result.visible, false);
});

test('shows panel when pareto_frontier has data', () => {
  reset();
  const result = updateParetoFrontierTable({
    pareto_frontier: [
      { variant: 'small', npv_pln: 10000, payback_years: 5, is_dominated: false }
    ]
  });
  assertEqual(result.visible, true);
});

console.log('\n2. Row generation tests:');

test('generates correct number of rows', () => {
  reset();
  const result = updateParetoFrontierTable({
    pareto_frontier: [
      { variant: 'small', npv_pln: 10000, payback_years: 5, is_dominated: false },
      { variant: 'medium', npv_pln: 20000, payback_years: 6, is_dominated: false },
      { variant: 'large', npv_pln: 15000, payback_years: 8, is_dominated: true }
    ]
  });
  assertEqual(result.rows, 3);
});

test('counts frontier points correctly', () => {
  reset();
  const result = updateParetoFrontierTable({
    pareto_frontier: [
      { variant: 'small', npv_pln: 10000, payback_years: 5, is_dominated: false },
      { variant: 'medium', npv_pln: 20000, payback_years: 6, is_dominated: false },
      { variant: 'large', npv_pln: 15000, payback_years: 8, is_dominated: true }
    ]
  });
  assertEqual(result.frontierCount, 2);
});

console.log('\n3. HTML content tests:');

test('includes Pareto badge for non-dominated points', () => {
  reset();
  const result = updateParetoFrontierTable({
    pareto_frontier: [
      { variant: 'small', npv_pln: 10000, payback_years: 5, is_dominated: false }
    ]
  });
  assertIncludes(result.html, 'pareto-badge', 'Should include pareto-badge class');
  assertIncludes(result.html, 'Pareto', 'Should include Pareto text');
});

test('includes Dominated badge for dominated points', () => {
  reset();
  const result = updateParetoFrontierTable({
    pareto_frontier: [
      { variant: 'small', npv_pln: 10000, payback_years: 5, is_dominated: true }
    ]
  });
  assertIncludes(result.html, 'dominated-badge', 'Should include dominated-badge class');
  assertIncludes(result.html, 'Dominated', 'Should include Dominated text');
});

test('uses pareto-row class for non-dominated points', () => {
  reset();
  const result = updateParetoFrontierTable({
    pareto_frontier: [
      { variant: 'medium', npv_pln: 50000, payback_years: 4, is_dominated: false }
    ]
  });
  assertIncludes(result.html, 'pareto-row', 'Should include pareto-row class');
});

test('uses dominated-row class for dominated points', () => {
  reset();
  const result = updateParetoFrontierTable({
    pareto_frontier: [
      { variant: 'large', npv_pln: 30000, payback_years: 10, is_dominated: true }
    ]
  });
  assertIncludes(result.html, 'dominated-row', 'Should include dominated-row class');
});

test('uses positive class for positive NPV', () => {
  reset();
  const result = updateParetoFrontierTable({
    pareto_frontier: [
      { variant: 'small', npv_pln: 10000, payback_years: 5, is_dominated: false }
    ]
  });
  assertIncludes(result.html, 'positive', 'Should include positive class');
});

test('uses negative class for negative NPV', () => {
  reset();
  const result = updateParetoFrontierTable({
    pareto_frontier: [
      { variant: 'small', npv_pln: -5000, payback_years: 50, is_dominated: true }
    ]
  });
  assertIncludes(result.html, 'negative', 'Should include negative class');
});

test('formats very long payback as > 25 lat', () => {
  reset();
  const result = updateParetoFrontierTable({
    pareto_frontier: [
      { variant: 'small', npv_pln: -1000, payback_years: 150, is_dominated: true }
    ]
  });
  assertIncludes(result.html, '> 25 lat', 'Should show > 25 lat for long payback');
});

console.log('\n4. Variant label tests:');

test('maps small variant to Small (1h)', () => {
  reset();
  const result = updateParetoFrontierTable({
    pareto_frontier: [
      { variant: 'small', npv_pln: 10000, payback_years: 5, is_dominated: false }
    ]
  });
  assertIncludes(result.html, 'Small (1h)', 'Should include Small (1h) label');
});

test('maps medium variant to Medium (2h)', () => {
  reset();
  const result = updateParetoFrontierTable({
    pareto_frontier: [
      { variant: 'medium', npv_pln: 20000, payback_years: 6, is_dominated: false }
    ]
  });
  assertIncludes(result.html, 'Medium (2h)', 'Should include Medium (2h) label');
});

test('maps large variant to Large (4h)', () => {
  reset();
  const result = updateParetoFrontierTable({
    pareto_frontier: [
      { variant: 'large', npv_pln: 30000, payback_years: 8, is_dominated: false }
    ]
  });
  assertIncludes(result.html, 'Large (4h)', 'Should include Large (4h) label');
});

// Summary
console.log('\n========================================');
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('========================================\n');

process.exit(failed > 0 ? 1 : 0);
