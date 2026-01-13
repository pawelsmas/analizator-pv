/**
 * Unit tests for bankability.js
 *
 * Tests cover:
 * - generateDebtSchedule: various repayment types and grace period methods
 * - calculateBankabilityMetrics: DSCR calculation and null handling
 * - Year indexing helpers
 *
 * Run with: npm test
 */

import { describe, it, expect, beforeAll } from 'vitest';

// Mock window object for browser code
globalThis.window = {};

// Import bankability functions
const {
  generateDebtSchedule,
  calculateBankabilityMetrics,
  validateDebtSchedule,
  getArrayIndexForYear,
  getYearForArrayIndex,
  validateYearMapping
} = require('../services/frontend-economics/bankability.js');


describe('generateDebtSchedule', () => {

  describe('annuity repayment', () => {

    it('should generate valid schedule without grace period', () => {
      const schedule = generateDebtSchedule({
        debtAmount: 1000000,
        tenorYears: 15,
        interestRate: 0.065,
        repaymentType: 'annuity',
        graceYears: 0
      });

      const validation = validateDebtSchedule(schedule, 1000000);

      expect(validation.valid).toBe(true);
      expect(validation.finalBalance).toBeLessThanOrEqual(1);
      expect(Object.keys(schedule).length).toBe(15);
    });

    it('should handle interest_only grace period correctly', () => {
      const schedule = generateDebtSchedule({
        debtAmount: 1000000,
        tenorYears: 15,
        interestRate: 0.065,
        repaymentType: 'annuity',
        graceYears: 2,
        graceMethod: 'interest_only'
      });

      const validation = validateDebtSchedule(schedule, 1000000);

      expect(validation.valid).toBe(true);

      // Grace years should have 0 principal and graceType flag
      expect(schedule[1].principal).toBe(0);
      expect(schedule[1].graceType).toBe('interest_only');
      expect(schedule[2].principal).toBe(0);

      // Interest should be paid during grace
      expect(schedule[1].interest).toBeGreaterThan(0);

      // Outstanding should remain constant during grace (interest_only)
      expect(schedule[1].outstandingEnd).toBe(schedule[2].outstandingEnd);
    });

    it('should handle capitalize grace period correctly', () => {
      const schedule = generateDebtSchedule({
        debtAmount: 1000000,
        tenorYears: 15,
        interestRate: 0.065,
        repaymentType: 'annuity',
        graceYears: 2,
        graceMethod: 'capitalize'
      });

      const validation = validateDebtSchedule(schedule, 1000000);

      expect(validation.valid).toBe(true);

      // Grace years should have 0 payments and graceType flag
      expect(schedule[1].total).toBe(0);
      expect(schedule[1].graceType).toBe('capitalize');
      expect(schedule[1].accruedInterest).toBeGreaterThan(0);

      // Outstanding should GROW during grace (capitalize)
      expect(schedule[2].outstandingEnd).toBeGreaterThan(schedule[1].outstandingEnd);

      // Sum of principal should be >= original debt (due to capitalized interest)
      expect(validation.sumPrincipal).toBeGreaterThanOrEqual(1000000);
    });

  });

  describe('linear repayment', () => {

    it('should generate valid schedule with grace period', () => {
      const schedule = generateDebtSchedule({
        debtAmount: 1000000,
        tenorYears: 10,
        interestRate: 0.07,
        repaymentType: 'linear',
        graceYears: 2,
        graceMethod: 'interest_only'
      });

      const validation = validateDebtSchedule(schedule, 1000000);

      expect(validation.valid).toBe(true);
      expect(validation.finalBalance).toBeLessThanOrEqual(1);
    });

  });

  describe('bullet repayment', () => {

    it('should pay all principal in last year', () => {
      const schedule = generateDebtSchedule({
        debtAmount: 1000000,
        tenorYears: 10,
        interestRate: 0.06,
        repaymentType: 'bullet',
        graceYears: 0
      });

      const validation = validateDebtSchedule(schedule, 1000000);

      expect(validation.valid).toBe(true);

      // All years except last should have 0 principal
      for (let year = 1; year < 10; year++) {
        expect(schedule[year].principal).toBe(0);
      }

      // Last year should pay full principal
      expect(schedule[10].principal).toBe(1000000);
    });

  });

  describe('edge cases', () => {

    it('should return empty schedule for zero debt', () => {
      const schedule = generateDebtSchedule({
        debtAmount: 0,
        tenorYears: 10
      });

      expect(Object.keys(schedule).length).toBe(0);
    });

    it('should return empty schedule for negative debt', () => {
      const schedule = generateDebtSchedule({
        debtAmount: -100000,
        tenorYears: 10
      });

      expect(Object.keys(schedule).length).toBe(0);
    });

    it('should handle grace years >= tenor', () => {
      const schedule = generateDebtSchedule({
        debtAmount: 1000000,
        tenorYears: 5,
        graceYears: 10  // More grace years than tenor
      });

      // Should return empty or handle gracefully
      expect(Object.keys(schedule).length).toBeLessThanOrEqual(5);
    });

    it('should handle zero interest rate', () => {
      const schedule = generateDebtSchedule({
        debtAmount: 1000000,
        tenorYears: 10,
        interestRate: 0,
        repaymentType: 'annuity'
      });

      const validation = validateDebtSchedule(schedule, 1000000);

      expect(validation.valid).toBe(true);

      // All interest payments should be 0
      for (const year of Object.keys(schedule)) {
        expect(schedule[year].interest).toBe(0);
      }
    });

  });

});


describe('calculateBankabilityMetrics', () => {

  describe('DSCR calculation', () => {

    it('should return null DSCR when no debt', () => {
      const yearlyData = [
        { year: 1, revenue: 100000, opex: 20000 },
        { year: 2, revenue: 100000, opex: 20000 }
      ];

      const result = calculateBankabilityMetrics(yearlyData, {}, { covenant: 1.20 });

      expect(result.kpi.avgDSCR).toBeNull();
      expect(result.kpi.avgDSCRWeighted).toBeNull();
      expect(result.kpi.minDSCR).toBeNull();
    });

    it('should calculate positive DSCR with valid debt', () => {
      const debtSchedule = generateDebtSchedule({
        debtAmount: 500000,
        tenorYears: 10,
        interestRate: 0.06,
        repaymentType: 'annuity'
      });

      const yearlyData = [];
      for (let year = 1; year <= 10; year++) {
        yearlyData.push({
          year: year,
          revenue: 150000,  // Sufficient revenue
          opex: 20000
        });
      }

      const result = calculateBankabilityMetrics(yearlyData, debtSchedule, { covenant: 1.20 });

      expect(result.kpi.avgDSCR).toBeGreaterThan(0);
      expect(result.kpi.avgDSCRWeighted).toBeGreaterThan(0);
      expect(result.kpi.minDSCR).toBeGreaterThan(0);
    });

    it('should never return NaN or Infinity', () => {
      const yearlyData = [
        { year: 1, revenue: 0, opex: 0 },  // Edge case: all zeros
        { year: 2, revenue: 0, opex: 0 }
      ];

      const debtSchedule = {
        1: { total: 0, interest: 0, principal: 0 },  // Zero debt service
        2: { total: 0, interest: 0, principal: 0 }
      };

      const result = calculateBankabilityMetrics(yearlyData, debtSchedule, { covenant: 1.20 });

      // Should be null, not NaN or Infinity
      if (result.kpi.avgDSCR !== null) {
        expect(Number.isFinite(result.kpi.avgDSCR)).toBe(true);
      }
      if (result.kpi.avgDSCRWeighted !== null) {
        expect(Number.isFinite(result.kpi.avgDSCRWeighted)).toBe(true);
      }
    });

  });

});


describe('year indexing helpers', () => {

  it('getArrayIndexForYear should convert correctly', () => {
    expect(getArrayIndexForYear(1)).toBe(0);
    expect(getArrayIndexForYear(5)).toBe(4);
    expect(getArrayIndexForYear(25)).toBe(24);
  });

  it('getYearForArrayIndex should convert correctly', () => {
    expect(getYearForArrayIndex(0)).toBe(1);
    expect(getYearForArrayIndex(4)).toBe(5);
    expect(getYearForArrayIndex(24)).toBe(25);
  });

  it('should be inverse functions', () => {
    for (let year = 1; year <= 30; year++) {
      expect(getYearForArrayIndex(getArrayIndexForYear(year))).toBe(year);
    }
    for (let index = 0; index < 30; index++) {
      expect(getArrayIndexForYear(getYearForArrayIndex(index))).toBe(index);
    }
  });

  it('validateYearMapping should detect misaligned data', () => {
    const yearlyData = [
      { year: 1, revenue: 100 },
      { year: 3, revenue: 100 },  // Skipped year 2!
      { year: 3, revenue: 100 }
    ];

    const result = validateYearMapping(yearlyData, {});

    expect(result.valid).toBe(false);
    expect(result.errors.length).toBeGreaterThan(0);
  });

  it('validateYearMapping should pass for aligned data', () => {
    const yearlyData = [
      { year: 1, revenue: 100 },
      { year: 2, revenue: 100 },
      { year: 3, revenue: 100 }
    ];

    const result = validateYearMapping(yearlyData, {});

    expect(result.valid).toBe(true);
    expect(result.errors.length).toBe(0);
  });

});
