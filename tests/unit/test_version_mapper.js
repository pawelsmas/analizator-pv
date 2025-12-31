/**
 * Unit tests for Version Mapper (v1.8.0)
 *
 * Run with: node tests/unit/test_version_mapper.js
 */

// Simulate mapVersionResponse function from bess.js
function mapVersionResponse(versionResponse) {
  return {
    service: versionResponse.service || 'unknown',
    gitSha: versionResponse.git_sha || 'unknown',
    gitShaShort: (versionResponse.git_sha || 'unknown').substring(0, 7),
    buildTime: versionResponse.build_time_utc || 'unknown',
    schemaVersion: versionResponse.schema_version || 'unknown',
    assumptionsVersion: versionResponse.assumptions_version || 'unknown',
    displayText: `v${versionResponse.schema_version || '?'} (${(versionResponse.git_sha || 'unknown').substring(0, 7)})`,
  };
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

function assertTrue(condition, msg = '') {
  if (!condition) {
    throw new Error(msg || 'Expected true');
  }
}

console.log('\n=== Version Mapper Unit Tests ===\n');

// === Test: mapVersionResponse with full data ===
console.log('-- mapVersionResponse with full data --');

test('mapVersionResponse returns correct service', () => {
  const response = {
    service: 'bess-dispatch',
    git_sha: 'abc1234567890',
    build_time_utc: '2025-01-01T12:00:00Z',
    schema_version: '1.0.0',
    assumptions_version: 'v1.0-xyz12345'
  };
  const result = mapVersionResponse(response);
  assertEqual(result.service, 'bess-dispatch');
});

test('mapVersionResponse returns full git_sha', () => {
  const response = {
    service: 'bess-dispatch',
    git_sha: 'abc1234567890',
    build_time_utc: '2025-01-01T12:00:00Z',
    schema_version: '1.0.0',
    assumptions_version: 'v1.0-xyz12345'
  };
  const result = mapVersionResponse(response);
  assertEqual(result.gitSha, 'abc1234567890');
});

test('mapVersionResponse returns short git_sha (7 chars)', () => {
  const response = {
    service: 'bess-dispatch',
    git_sha: 'abc1234567890',
    build_time_utc: '2025-01-01T12:00:00Z',
    schema_version: '1.0.0',
    assumptions_version: 'v1.0-xyz12345'
  };
  const result = mapVersionResponse(response);
  assertEqual(result.gitShaShort, 'abc1234');
  assertEqual(result.gitShaShort.length, 7);
});

test('mapVersionResponse returns correct build time', () => {
  const response = {
    service: 'bess-dispatch',
    git_sha: 'abc1234567890',
    build_time_utc: '2025-01-01T12:00:00Z',
    schema_version: '1.0.0',
    assumptions_version: 'v1.0-xyz12345'
  };
  const result = mapVersionResponse(response);
  assertEqual(result.buildTime, '2025-01-01T12:00:00Z');
});

test('mapVersionResponse returns correct schema version', () => {
  const response = {
    service: 'bess-dispatch',
    git_sha: 'abc1234567890',
    build_time_utc: '2025-01-01T12:00:00Z',
    schema_version: '1.0.0',
    assumptions_version: 'v1.0-xyz12345'
  };
  const result = mapVersionResponse(response);
  assertEqual(result.schemaVersion, '1.0.0');
});

test('mapVersionResponse returns correct assumptions version', () => {
  const response = {
    service: 'bess-dispatch',
    git_sha: 'abc1234567890',
    build_time_utc: '2025-01-01T12:00:00Z',
    schema_version: '1.0.0',
    assumptions_version: 'v1.0-xyz12345'
  };
  const result = mapVersionResponse(response);
  assertEqual(result.assumptionsVersion, 'v1.0-xyz12345');
});

test('mapVersionResponse returns formatted displayText', () => {
  const response = {
    service: 'bess-dispatch',
    git_sha: 'abc1234567890',
    build_time_utc: '2025-01-01T12:00:00Z',
    schema_version: '1.0.0',
    assumptions_version: 'v1.0-xyz12345'
  };
  const result = mapVersionResponse(response);
  assertEqual(result.displayText, 'v1.0.0 (abc1234)');
});

// === Test: mapVersionResponse with missing fields ===
console.log('\n-- mapVersionResponse with missing fields --');

test('mapVersionResponse handles missing service', () => {
  const response = {
    git_sha: 'abc1234567890',
    schema_version: '1.0.0'
  };
  const result = mapVersionResponse(response);
  assertEqual(result.service, 'unknown');
});

test('mapVersionResponse handles missing git_sha', () => {
  const response = {
    service: 'bess-dispatch',
    schema_version: '1.0.0'
  };
  const result = mapVersionResponse(response);
  assertEqual(result.gitSha, 'unknown');
  assertEqual(result.gitShaShort, 'unknown');
});

test('mapVersionResponse handles missing build_time_utc', () => {
  const response = {
    service: 'bess-dispatch',
    git_sha: 'abc1234567890',
    schema_version: '1.0.0'
  };
  const result = mapVersionResponse(response);
  assertEqual(result.buildTime, 'unknown');
});

test('mapVersionResponse handles missing schema_version', () => {
  const response = {
    service: 'bess-dispatch',
    git_sha: 'abc1234567890'
  };
  const result = mapVersionResponse(response);
  assertEqual(result.schemaVersion, 'unknown');
});

test('mapVersionResponse handles missing assumptions_version', () => {
  const response = {
    service: 'bess-dispatch',
    git_sha: 'abc1234567890',
    schema_version: '1.0.0'
  };
  const result = mapVersionResponse(response);
  assertEqual(result.assumptionsVersion, 'unknown');
});

test('mapVersionResponse displayText with missing schema uses ?', () => {
  const response = {
    service: 'bess-dispatch',
    git_sha: 'abc1234567890'
  };
  const result = mapVersionResponse(response);
  assertEqual(result.displayText, 'v? (abc1234)');
});

// === Test: mapVersionResponse with empty object ===
console.log('\n-- mapVersionResponse with empty object --');

test('mapVersionResponse handles empty object', () => {
  const response = {};
  const result = mapVersionResponse(response);
  assertEqual(result.service, 'unknown');
  assertEqual(result.gitSha, 'unknown');
  assertEqual(result.gitShaShort, 'unknown');
  assertEqual(result.buildTime, 'unknown');
  assertEqual(result.schemaVersion, 'unknown');
  assertEqual(result.assumptionsVersion, 'unknown');
  assertEqual(result.displayText, 'v? (unknown)');
});

// === Test: Short SHA edge cases ===
console.log('\n-- Short SHA edge cases --');

test('mapVersionResponse handles SHA shorter than 7 chars', () => {
  const response = {
    service: 'bess-dispatch',
    git_sha: 'abc',
    schema_version: '1.0.0'
  };
  const result = mapVersionResponse(response);
  assertEqual(result.gitShaShort, 'abc');
});

test('mapVersionResponse handles SHA exactly 7 chars', () => {
  const response = {
    service: 'bess-dispatch',
    git_sha: 'abc1234',
    schema_version: '1.0.0'
  };
  const result = mapVersionResponse(response);
  assertEqual(result.gitShaShort, 'abc1234');
});

// Summary
console.log('\n=== Summary ===');
console.log(`Passed: ${passed}`);
console.log(`Failed: ${failed}`);
console.log(`Total:  ${passed + failed}`);

if (failed > 0) {
  process.exit(1);
}
