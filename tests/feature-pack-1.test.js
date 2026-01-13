/**
 * Unit tests for Feature Pack 1 (P0-1, P0-2, P0-3)
 *
 * Tests cover:
 * - P0-1: BESS Replacement Schedule (calculateBessReplacementSchedule)
 * - P0-2: Residual Value Modes (calculateResidualValue)
 * - P0-3: Nominal/Real Rate Consistency (getEffectiveDiscountRate, nominalToRealRate, realToNominalRate)
 *
 * Run with: npm test
 */

import { describe, it, expect, beforeAll } from 'vitest';

// Mock browser globals for Node.js environment
globalThis.window = {
  economicsSettings: {},
  addEventListener: () => {},
  removeEventListener: () => {}
};
globalThis.document = {
  getElementById: () => null,
  querySelector: () => null,
  querySelectorAll: () => [],
  createElement: () => ({
    style: {},
    classList: { add: () => {}, remove: () => {} },
    appendChild: () => {},
    innerHTML: ''
  }),
  addEventListener: () => {}
};
globalThis.Chart = class MockChart {
  constructor() {}
  destroy() {}
  update() {}
};
globalThis.XLSX = {
  utils: {
    book_new: () => ({}),
    aoa_to_sheet: () => ({}),
    book_append_sheet: () => {}
  },
  writeFile: () => {}
};
globalThis.ExcelJS = {
  Workbook: class MockWorkbook {
    constructor() {
      this.worksheets = [];
    }
    addWorksheet() {
      return { columns: [], addRow: () => {}, getRow: () => ({ font: {} }) };
    }
  }
};
globalThis.fetch = () => Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
globalThis.console.log = () => {}; // Suppress logs during tests

// Import economics functions
const {
  calculateBessReplacementSchedule,
  calculateInverterReplacementSchedule,
  calculateReinvestmentSchedule,
  calculateResidualValue,
  getEffectiveDiscountRate,
  nominalToRealRate,
  realToNominalRate
} = require('../services/frontend-economics/economics.js');


// ============================================================================
// P0-1: BESS REPLACEMENT SCHEDULE TESTS
// Returns: Array of {year, cost, description}
// ============================================================================

describe('calculateBessReplacementSchedule (P0-1)', () => {

  // Helper to convert array to year->cost dict
  function scheduleToDict(schedule) {
    const dict = {};
    schedule.forEach(item => { dict[item.year] = item.cost; });
    return dict;
  }

  describe('basic replacement scenarios', () => {

    it('should return empty schedule when no BESS (initial cost = 0)', () => {
      const schedule = calculateBessReplacementSchedule(0, 100, 25, {
        bessLifetimeYears: 12
      });

      expect(schedule.length).toBe(0);
    });

    it('should return empty schedule when analysis period <= BESS lifetime', () => {
      const schedule = calculateBessReplacementSchedule(500000, 100, 10, {
        bessLifetimeYears: 12
      });

      expect(schedule.length).toBe(0);
    });

    it('should schedule replacement at year 12 for 25-year horizon (percent_of_initial mode)', () => {
      const schedule = calculateBessReplacementSchedule(1000000, 100, 25, {
        bessLifetimeYears: 12,
        bessReplacementMode: 'percent_of_initial',
        bessReplacementCostValue: 0.7,
        bessReplacementFraction: 1.0
      });

      const dict = scheduleToDict(schedule);
      expect(dict[12]).toBeDefined();
      expect(dict[12]).toBeCloseTo(700000, 0); // 70% of 1M
      expect(dict[24]).toBeDefined();
      expect(dict[24]).toBeCloseTo(700000, 0);
    });

    it('should schedule replacement at year 15 for 25-year horizon with 15-year lifetime', () => {
      const schedule = calculateBessReplacementSchedule(1000000, 100, 25, {
        bessLifetimeYears: 15,
        bessReplacementMode: 'percent_of_initial',
        bessReplacementCostValue: 0.6,
        bessReplacementFraction: 1.0
      });

      const dict = scheduleToDict(schedule);
      expect(dict[15]).toBeDefined();
      expect(dict[15]).toBeCloseTo(600000, 0);
      // No second replacement since 30 > 25
      expect(dict[30]).toBeUndefined();
    });

    it('should use per_kwh mode correctly', () => {
      const schedule = calculateBessReplacementSchedule(1000000, 500, 25, {
        bessLifetimeYears: 12,
        bessReplacementMode: 'per_kwh',
        bessReplacementCostValue: 800, // PLN per kWh
        bessReplacementFraction: 1.0
      });

      const dict = scheduleToDict(schedule);
      expect(dict[12]).toBeDefined();
      expect(dict[12]).toBeCloseTo(400000, 0); // 500 kWh * 800 PLN/kWh = 400,000 PLN
    });

    it('should apply replacement fraction correctly', () => {
      const schedule = calculateBessReplacementSchedule(1000000, 100, 25, {
        bessLifetimeYears: 12,
        bessReplacementMode: 'percent_of_initial',
        bessReplacementCostValue: 0.7,
        bessReplacementFraction: 0.8 // Only 80% capacity replacement
      });

      const dict = scheduleToDict(schedule);
      expect(dict[12]).toBeCloseTo(560000, 0); // 70% * 80% * 1M = 560,000
    });

  });

  describe('edge cases', () => {

    it('should handle negative initial CAPEX gracefully', () => {
      const schedule = calculateBessReplacementSchedule(-100000, 100, 25, {});
      expect(schedule.length).toBe(0);
    });

    it('should handle zero kWh gracefully in per_kwh mode', () => {
      const schedule = calculateBessReplacementSchedule(1000000, 0, 25, {
        bessLifetimeYears: 12,
        bessReplacementMode: 'per_kwh',
        bessReplacementCostValue: 800
      });

      // With 0 kWh, cost is 0 so nothing should be scheduled (based on implementation)
      // Note: if cost=0, the item is NOT added to schedule
      expect(schedule.length).toBe(0);
    });

    it('should use default values when settings are missing', () => {
      const schedule = calculateBessReplacementSchedule(1000000, 100, 25, {});

      const dict = scheduleToDict(schedule);
      // Default lifetime is 15 years
      expect(dict[15]).toBeDefined();
      // Default mode is percent_of_initial at 70%
      expect(dict[15]).toBeCloseTo(700000, 0);
    });

  });

});


// ============================================================================
// P0-2: RESIDUAL VALUE TESTS
// Returns: {year, value, mode, description}
// ============================================================================

describe('calculateResidualValue (P0-2)', () => {

  describe('mode: zero', () => {

    it('should return 0 for zero mode', () => {
      const result = calculateResidualValue(1000000, 500, 25, {
        residualValueMode: 'zero'
      });

      expect(result.value).toBe(0);
      expect(result.mode).toBe('zero');
      expect(result.year).toBe(25);
    });

  });

  describe('mode: fmv (fair market value)', () => {

    it('should calculate FMV as percentage of initial CAPEX', () => {
      const result = calculateResidualValue(1000000, 500, 25, {
        residualValueMode: 'fmv',
        residualValueFmvPercent: 0.20
      });

      expect(result.value).toBeCloseTo(200000, 0); // 20% of 1M
      expect(result.mode).toBe('fmv');
    });

    it('should use default FMV percent (20%) when not specified', () => {
      const result = calculateResidualValue(1000000, 500, 25, {
        residualValueMode: 'fmv'
      });

      expect(result.value).toBeCloseTo(200000, 0);
    });

  });

  describe('mode: contractual', () => {

    it('should calculate contractual value based on PLN/kWp', () => {
      const result = calculateResidualValue(1000000, 500, 25, {
        residualValueMode: 'contractual',
        residualValueContractualPerKwp: 100 // 100 PLN/kWp
      });

      expect(result.value).toBeCloseTo(50000, 0); // 500 kWp * 100 PLN/kWp
      expect(result.mode).toBe('contractual');
    });

    it('should use default contractual rate (1 PLN/kWp) when not specified', () => {
      const result = calculateResidualValue(1000000, 500, 25, {
        residualValueMode: 'contractual'
      });

      expect(result.value).toBeCloseTo(500, 0); // 500 kWp * 1 PLN/kWp
    });

  });

  describe('edge cases', () => {

    it('should handle zero CAPEX gracefully', () => {
      const result = calculateResidualValue(0, 500, 25, {
        residualValueMode: 'fmv',
        residualValueFmvPercent: 0.20
      });

      expect(result.value).toBe(0);
    });

    it('should handle zero capacity gracefully in contractual mode', () => {
      const result = calculateResidualValue(1000000, 0, 25, {
        residualValueMode: 'contractual',
        residualValueContractualPerKwp: 100
      });

      expect(result.value).toBe(0);
    });

    it('should default to zero mode when mode is invalid', () => {
      const result = calculateResidualValue(1000000, 500, 25, {
        residualValueMode: 'invalid_mode'
      });

      expect(result.value).toBe(0);
    });

  });

});


// ============================================================================
// P0-3: NOMINAL/REAL RATE TESTS
// ============================================================================

describe('nominalToRealRate (P0-3)', () => {

  it('should convert nominal rate to real rate correctly', () => {
    // Formula: r_real = (1 + r_nominal) / (1 + inflation) - 1
    const nominalRate = 0.10; // 10%
    const inflationRate = 0.025; // 2.5%

    const realRate = nominalToRealRate(nominalRate, inflationRate);

    // Expected: (1.10 / 1.025) - 1 = 0.07317...
    expect(realRate).toBeCloseTo(0.07317, 4);
  });

  it('should return nominal rate when inflation is 0', () => {
    const realRate = nominalToRealRate(0.07, 0);
    expect(realRate).toBeCloseTo(0.07, 5);
  });

  it('should handle high inflation correctly', () => {
    const realRate = nominalToRealRate(0.15, 0.10);
    // (1.15 / 1.10) - 1 = 0.04545...
    expect(realRate).toBeCloseTo(0.04545, 4);
  });

});


describe('realToNominalRate (P0-3)', () => {

  it('should convert real rate to nominal rate correctly', () => {
    // Formula: r_nominal = (1 + r_real) * (1 + inflation) - 1
    const realRate = 0.07; // 7%
    const inflationRate = 0.025; // 2.5%

    const nominalRate = realToNominalRate(realRate, inflationRate);

    // Expected: (1.07 * 1.025) - 1 = 0.09675
    expect(nominalRate).toBeCloseTo(0.09675, 4);
  });

  it('should return real rate when inflation is 0', () => {
    const nominalRate = realToNominalRate(0.07, 0);
    expect(nominalRate).toBeCloseTo(0.07, 5);
  });

  it('should be inverse of nominalToRealRate', () => {
    const originalNominal = 0.10;
    const inflation = 0.03;

    const realRate = nominalToRealRate(originalNominal, inflation);
    const backToNominal = realToNominalRate(realRate, inflation);

    expect(backToNominal).toBeCloseTo(originalNominal, 5);
  });

});


describe('getEffectiveDiscountRate (P0-3)', () => {
  // Returns: {effectiveRate, mode, isConverted, inflationRate, warning}

  it('should return nominal rate when rateMode is nominal', () => {
    const result = getEffectiveDiscountRate({
      rateMode: 'nominal',
      discountRate: 0.07,
      inflationRate: 0.025
    });

    expect(result.effectiveRate).toBeCloseTo(0.07, 5);
    expect(result.mode).toBe('nominal');
    expect(result.isConverted).toBe(false);
  });

  it('should convert real to nominal when rateMode is real', () => {
    const result = getEffectiveDiscountRate({
      rateMode: 'real',
      discountRate: 0.07,
      inflationRate: 0.025
    });

    // Real 7% + Inflation 2.5% -> Nominal ~9.675%
    expect(result.effectiveRate).toBeCloseTo(0.09675, 4);
    expect(result.isConverted).toBe(true);
  });

  it('should use default values when settings are missing', () => {
    const result = getEffectiveDiscountRate({});

    // Default: nominal mode, 7% rate
    expect(result.effectiveRate).toBeCloseTo(0.07, 5);
    expect(result.mode).toBe('nominal');
  });

  it('should handle 0% discount rate correctly', () => {
    const result = getEffectiveDiscountRate({
      rateMode: 'nominal',
      discountRate: 0,
      inflationRate: 0.025
    });

    expect(result.effectiveRate).toBe(0);
  });

});


// ============================================================================
// INTEGRATION TESTS
// ============================================================================

describe('Feature Pack 1 Integration', () => {

  it('ACCEPTANCE: horizon=25, bess_lifetime=12 should have replacements in year 12 and 24', () => {
    const schedule = calculateBessReplacementSchedule(1000000, 500, 25, {
      bessLifetimeYears: 12,
      bessReplacementMode: 'percent_of_initial',
      bessReplacementCostValue: 0.7,
      bessReplacementFraction: 1.0
    });

    // schedule is array of {year, cost, description}
    const replacementYears = schedule.map(item => item.year);
    expect(replacementYears).toContain(12);
    expect(replacementYears).toContain(24);
    expect(replacementYears.length).toBe(2);
  });

  it('ACCEPTANCE: residual_value_mode=fmv with 20% should return 20% of CAPEX', () => {
    const result = calculateResidualValue(5000000, 1000, 25, {
      residualValueMode: 'fmv',
      residualValueFmvPercent: 0.20
    });

    expect(result.value).toBe(1000000); // 5M * 20%
    expect(result.mode).toBe('fmv');
  });

  it('ACCEPTANCE: rate_mode=real, r=7%, inflation=2.5% should use ~9.675% effective rate', () => {
    const result = getEffectiveDiscountRate({
      rateMode: 'real',
      discountRate: 0.07,
      inflationRate: 0.025
    });

    expect(result.effectiveRate).toBeCloseTo(0.09675, 3);
    expect(result.isConverted).toBe(true);
  });

});


// ============================================================================
// P0-1 EXTENDED: INVERTER REPLACEMENT TESTS
// ============================================================================

describe('calculateInverterReplacementSchedule (P0-1)', () => {

  it('should return empty schedule when disabled', () => {
    const schedule = calculateInverterReplacementSchedule(1000000, 25, {
      inverterReplacementEnabled: false,
      inverterLifetimeYears: 12
    });

    expect(schedule.length).toBe(0);
  });

  it('should schedule replacement at year 12 for 25-year horizon when enabled', () => {
    const schedule = calculateInverterReplacementSchedule(1000000, 25, {
      inverterReplacementEnabled: true,
      inverterLifetimeYears: 12,
      inverterReplacementCostPercent: 0.15
    });

    expect(schedule.length).toBe(2); // year 12 and 24
    expect(schedule[0].year).toBe(12);
    expect(schedule[0].cost).toBeCloseTo(150000, 0); // 15% of 1M
    expect(schedule[1].year).toBe(24);
  });

});


describe('calculateReinvestmentSchedule (P0-1 Combined)', () => {

  it('should combine BESS and Inverter replacement costs in same year', () => {
    const result = calculateReinvestmentSchedule(
      500000, // BESS CAPEX
      200,    // BESS kWh
      1000000, // PV CAPEX
      25,     // analysis period
      {
        bessReplacementEnabled: true,
        bessLifetimeYears: 12,
        bessReplacementMode: 'percent_of_initial',
        bessReplacementCostValue: 0.7,
        bessReplacementFraction: 1.0,
        inverterReplacementEnabled: true,
        inverterLifetimeYears: 12,
        inverterReplacementCostPercent: 0.15
      }
    );

    // Year 12: BESS (70% of 500k = 350k) + Inverter (15% of 1M = 150k) = 500k
    expect(result.schedule[12]).toBeCloseTo(500000, 0);
    // Year 24: same
    expect(result.schedule[24]).toBeCloseTo(500000, 0);
    expect(result.totalCost).toBeCloseTo(1000000, 0);
  });

  it('should work with only BESS replacement', () => {
    const result = calculateReinvestmentSchedule(
      500000, 200, 1000000, 25,
      {
        bessReplacementEnabled: true,
        bessLifetimeYears: 12,
        bessReplacementMode: 'percent_of_initial',
        bessReplacementCostValue: 0.7,
        inverterReplacementEnabled: false
      }
    );

    expect(result.bessSchedule.length).toBe(2);
    expect(result.inverterSchedule.length).toBe(0);
    expect(result.schedule[12]).toBeCloseTo(350000, 0);
  });

});


// ============================================================================
// P0-2 EXTENDED: residualValueYearMode TESTS
// ============================================================================

describe('calculateResidualValue yearMode (P0-2)', () => {

  it('should apply residual value in end_of_analysis year by default', () => {
    const result = calculateResidualValue(1000000, 500, 25, {
      residualValueMode: 'fmv',
      residualValueFmvPercent: 0.20,
      residualValueYearMode: 'end_of_analysis'
    });

    expect(result.year).toBe(25);
    expect(result.yearMode).toBe('end_of_analysis');
  });

  it('should apply residual value at end_of_contract when specified', () => {
    const result = calculateResidualValue(1000000, 500, 25, {
      residualValueMode: 'contractual',
      residualValueContractualPerKwp: 50,
      residualValueYearMode: 'end_of_contract'
    }, 15); // EaaS duration = 15 years

    expect(result.year).toBe(15);
    expect(result.yearMode).toBe('end_of_contract');
    expect(result.value).toBeCloseTo(25000, 0); // 500 kWp * 50 PLN
  });

  it('should cap residual year at analysis period', () => {
    const result = calculateResidualValue(1000000, 500, 20, {
      residualValueMode: 'fmv',
      residualValueFmvPercent: 0.20,
      residualValueYearMode: 'end_of_contract'
    }, 25); // EaaS duration > analysis period

    expect(result.year).toBe(20); // capped at analysis period
  });

});


// ============================================================================
// P0-3 EXTENDED: GUARDRAILS TESTS
// ============================================================================

describe('getEffectiveDiscountRate guardrails (P0-3)', () => {

  it('should fallback to nominal when inflation is NaN in real mode', () => {
    const result = getEffectiveDiscountRate({
      rateMode: 'real',
      discountRate: 0.07,
      inflationRate: NaN
    });

    // Should fallback to 7% nominal with warning
    expect(result.effectiveRate).toBeCloseTo(0.07, 5);
    expect(result.warning).not.toBeNull();
    expect(result.warning).toContain('missing/NaN');
  });

  it('should handle string discount rate (parseFloat)', () => {
    const result = getEffectiveDiscountRate({
      rateMode: 'nominal',
      discountRate: '0.08', // string instead of number
      inflationRate: 0.025
    });

    expect(result.effectiveRate).toBeCloseTo(0.08, 5);
  });

  it('should return same NPV when inflation=0 (real vs nominal)', () => {
    const nominalResult = getEffectiveDiscountRate({
      rateMode: 'nominal',
      discountRate: 0.07,
      inflationRate: 0
    });

    const realResult = getEffectiveDiscountRate({
      rateMode: 'real',
      discountRate: 0.07,
      inflationRate: 0
    });

    // With 0% inflation, nominal and real rates should be identical
    expect(nominalResult.effectiveRate).toBeCloseTo(realResult.effectiveRate, 5);
  });

});
