/**
 * Unit tests for Report URL Builder (v2.4.0)
 *
 * Run with: node tests/unit/test_report_url_builder.js
 */

// Load the module
const ReportUrlBuilder = require('../../services/frontend-bess/report_url_builder.js');

// Test utilities
let passed = 0;
let failed = 0;

function test(name, fn) {
  try {
    fn();
    console.log(`  ✓ ${name}`);
    passed++;
  } catch (error) {
    console.log(`  ✗ ${name}`);
    console.log(`    Error: ${error.message}`);
    failed++;
  }
}

function assertEqual(actual, expected, message) {
  if (actual !== expected) {
    throw new Error(`${message}: expected "${expected}", got "${actual}"`);
  }
}

function assertTrue(value, message) {
  if (!value) {
    throw new Error(`${message}: expected truthy value`);
  }
}

function assertFalse(value, message) {
  if (value) {
    throw new Error(`${message}: expected falsy value`);
  }
}

function assertThrows(fn, message) {
  try {
    fn();
    throw new Error(`${message}: expected function to throw`);
  } catch (e) {
    if (e.message.startsWith(message)) throw e;
    // Expected to throw, success
  }
}

// ============================================
// buildReportUrl tests
// ============================================

console.log('\n--- buildReportUrl tests ---');

test('basic PDF URL without options', () => {
  const url = ReportUrlBuilder.buildReportUrl('abc12345-1234-4abc-8abc-123456789abc', 'pdf');
  assertEqual(url, '/api/bess-dispatch/runs/abc12345-1234-4abc-8abc-123456789abc/report.pdf', 'URL mismatch');
});

test('basic XLSX URL without options', () => {
  const url = ReportUrlBuilder.buildReportUrl('abc12345-1234-4abc-8abc-123456789abc', 'xlsx');
  assertEqual(url, '/api/bess-dispatch/runs/abc12345-1234-4abc-8abc-123456789abc/report.xlsx', 'URL mismatch');
});

test('basic ZIP URL without options', () => {
  const url = ReportUrlBuilder.buildReportUrl('abc12345-1234-4abc-8abc-123456789abc', 'zip');
  assertEqual(url, '/api/bess-dispatch/runs/abc12345-1234-4abc-8abc-123456789abc/report.zip', 'URL mismatch');
});

test('URL with client profile (default) - no query param', () => {
  const url = ReportUrlBuilder.buildReportUrl('abc12345-1234-4abc-8abc-123456789abc', 'pdf', { profile: 'client' });
  assertEqual(url, '/api/bess-dispatch/runs/abc12345-1234-4abc-8abc-123456789abc/report.pdf', 'URL should not have profile param for default');
});

test('URL with engineering profile', () => {
  const url = ReportUrlBuilder.buildReportUrl('abc12345-1234-4abc-8abc-123456789abc', 'pdf', { profile: 'engineering' });
  assertTrue(url.includes('profile=engineering'), 'Should include engineering profile');
});

test('URL with client_name', () => {
  const url = ReportUrlBuilder.buildReportUrl('abc12345-1234-4abc-8abc-123456789abc', 'pdf', { client_name: 'Test Client' });
  assertTrue(url.includes('client_name=Test+Client') || url.includes('client_name=Test%20Client'), 'Should include client_name');
});

test('URL with site_name', () => {
  const url = ReportUrlBuilder.buildReportUrl('abc12345-1234-4abc-8abc-123456789abc', 'xlsx', { site_name: 'Site A' });
  assertTrue(url.includes('site_name=Site+A') || url.includes('site_name=Site%20A'), 'Should include site_name');
});

test('URL with multiple options', () => {
  const url = ReportUrlBuilder.buildReportUrl('abc12345-1234-4abc-8abc-123456789abc', 'pdf', {
    profile: 'engineering',
    client_name: 'ABC Corp',
    site_name: 'Factory 1'
  });
  assertTrue(url.includes('profile=engineering'), 'Should include profile');
  assertTrue(url.includes('client_name='), 'Should include client_name');
  assertTrue(url.includes('site_name='), 'Should include site_name');
});

test('URL with empty client_name is skipped', () => {
  const url = ReportUrlBuilder.buildReportUrl('abc12345-1234-4abc-8abc-123456789abc', 'pdf', { client_name: '' });
  assertFalse(url.includes('client_name'), 'Should not include empty client_name');
});

test('URL with whitespace-only client_name is skipped', () => {
  const url = ReportUrlBuilder.buildReportUrl('abc12345-1234-4abc-8abc-123456789abc', 'pdf', { client_name: '   ' });
  assertFalse(url.includes('client_name'), 'Should not include whitespace-only client_name');
});

test('URL trims client_name', () => {
  const url = ReportUrlBuilder.buildReportUrl('abc12345-1234-4abc-8abc-123456789abc', 'pdf', { client_name: '  Test  ' });
  assertTrue(url.includes('client_name=Test'), 'Should trim client_name');
});

test('URL with report_title', () => {
  const url = ReportUrlBuilder.buildReportUrl('abc12345-1234-4abc-8abc-123456789abc', 'pdf', { report_title: 'Custom Report' });
  assertTrue(url.includes('report_title='), 'Should include report_title');
});

test('URL with notes', () => {
  const url = ReportUrlBuilder.buildReportUrl('abc12345-1234-4abc-8abc-123456789abc', 'pdf', { notes: 'Some notes' });
  assertTrue(url.includes('notes='), 'Should include notes');
});

test('throws on missing runId', () => {
  assertThrows(() => ReportUrlBuilder.buildReportUrl(null, 'pdf'), 'Should throw');
});

test('throws on empty runId', () => {
  assertThrows(() => ReportUrlBuilder.buildReportUrl('', 'pdf'), 'Should throw');
});

test('throws on invalid format', () => {
  assertThrows(() => ReportUrlBuilder.buildReportUrl('abc12345-1234-4abc-8abc-123456789abc', 'doc'), 'Should throw');
});

test('throws on missing format', () => {
  assertThrows(() => ReportUrlBuilder.buildReportUrl('abc12345-1234-4abc-8abc-123456789abc', null), 'Should throw');
});

// ============================================
// buildPortfolioReportUrl tests
// ============================================

console.log('\n--- buildPortfolioReportUrl tests ---');

test('returns correct portfolio URL', () => {
  const url = ReportUrlBuilder.buildPortfolioReportUrl(['run1', 'run2']);
  assertEqual(url, '/api/bess-dispatch/portfolio/report.zip', 'URL mismatch');
});

test('throws on empty array', () => {
  assertThrows(() => ReportUrlBuilder.buildPortfolioReportUrl([]), 'Should throw');
});

test('throws on non-array', () => {
  assertThrows(() => ReportUrlBuilder.buildPortfolioReportUrl('run1'), 'Should throw');
});

test('throws on null', () => {
  assertThrows(() => ReportUrlBuilder.buildPortfolioReportUrl(null), 'Should throw');
});

// ============================================
// isValidRunId tests
// ============================================

console.log('\n--- isValidRunId tests ---');

test('valid UUID v4 returns true', () => {
  assertTrue(ReportUrlBuilder.isValidRunId('abc12345-1234-4abc-8abc-123456789abc'), 'Should be valid');
});

test('valid UUID v4 uppercase returns true', () => {
  assertTrue(ReportUrlBuilder.isValidRunId('ABC12345-1234-4ABC-8ABC-123456789ABC'), 'Should be valid');
});

test('valid UUID v4 mixed case returns true', () => {
  assertTrue(ReportUrlBuilder.isValidRunId('AbC12345-1234-4aBc-8AbC-123456789aBc'), 'Should be valid');
});

test('invalid UUID without hyphens returns false', () => {
  assertFalse(ReportUrlBuilder.isValidRunId('abc123451234abcdabcd123456789abc'), 'Should be invalid');
});

test('invalid UUID with wrong version returns false', () => {
  assertFalse(ReportUrlBuilder.isValidRunId('abc12345-1234-1abc-8abc-123456789abc'), 'Should be invalid (v1)');
});

test('empty string returns false', () => {
  assertFalse(ReportUrlBuilder.isValidRunId(''), 'Should be invalid');
});

test('null returns false', () => {
  assertFalse(ReportUrlBuilder.isValidRunId(null), 'Should be invalid');
});

test('undefined returns false', () => {
  assertFalse(ReportUrlBuilder.isValidRunId(undefined), 'Should be invalid');
});

test('number returns false', () => {
  assertFalse(ReportUrlBuilder.isValidRunId(12345), 'Should be invalid');
});

test('short UUID returns false', () => {
  assertFalse(ReportUrlBuilder.isValidRunId('abc12345-1234-4abc'), 'Should be invalid');
});

// ============================================
// Summary
// ============================================

console.log('\n--- Summary ---');
console.log(`Passed: ${passed}`);
console.log(`Failed: ${failed}`);
console.log(`Total:  ${passed + failed}`);

if (failed > 0) {
  process.exit(1);
}
