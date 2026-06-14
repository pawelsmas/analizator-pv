// ============================================================================
// BANKABILITY MODULE - Pure calculation functions (no DOM)
// Version: 20260113-DSCR-v2 - Grace period fix + division by zero guards
// ============================================================================
//
// METHODOLOGY:
// - DSCR (Debt Service Coverage Ratio) = CFADS / DebtService
// - CCR (Contract Coverage Ratio) = ContractRevenue / (OPEX + Reserves)
// - CFADS = Revenue - OPEX - TaxesCash - MaintCapex ± DeltaWC
// - DebtService = Interest + Principal + Fees
//
// IMPORTANT:
// - DSCR is always a NUMBER or null (never string "n/a")
// - "n/a" display is handled by UI layer only
// - Weighted Avg DSCR = sum(CFADS) / sum(DebtService) for years with DS > 0
//
// GRACE PERIOD METHODS:
// - 'interest_only': Pay interest during grace, recalculate annuity for remaining years
// - 'capitalize': No payments during grace, interest accrues to principal
// ============================================================================

console.log('🏦 bankability.js LOADED v=20260113-DSCR-v2');

// ============================================================================
// DEBT SCHEDULE GENERATION
// ============================================================================

/**
 * Generate annual debt service schedule
 *
 * P0-2 FIX: Proper grace period handling with two methods:
 * - 'interest_only': Pay interest during grace, then recalculate annuity for remaining years on current balance
 * - 'capitalize': No payments during grace, interest accrues to principal
 *
 * @param {Object} params - Financing parameters
 * @param {number} params.debtAmount - Principal amount
 * @param {number} params.tenorYears - Total loan duration in years
 * @param {number} params.interestRate - Annual interest rate (decimal, e.g., 0.065 for 6.5%)
 * @param {string} params.repaymentType - 'annuity' | 'bullet' | 'linear'
 * @param {number} params.graceYears - Grace period in years (0 = no grace)
 * @param {string} params.graceMethod - 'interest_only' (default) | 'capitalize'
 * @param {number} params.feesRate - Annual fees rate on outstanding (decimal)
 * @returns {Object} - { [year]: { interest, principal, fees, total, outstandingEnd } }
 */
function generateDebtSchedule(params) {
  const {
    debtAmount = 0,
    tenorYears = 15,
    interestRate = 0.065,  // 6.5%
    repaymentType = 'annuity',  // 'annuity' | 'bullet' | 'linear'
    graceYears = 0,
    graceMethod = 'interest_only',  // 'interest_only' | 'capitalize'
    feesRate = 0.005  // 0.5% p.a. on outstanding
  } = params;

  // Guard: invalid inputs
  if (debtAmount <= 0 || tenorYears <= 0) {
    return {};
  }

  // Guard: grace years cannot exceed tenor
  const effectiveGraceYears = Math.min(graceYears, tenorYears - 1);
  const repaymentYears = tenorYears - effectiveGraceYears;

  // Guard: must have at least 1 year for repayment
  if (repaymentYears <= 0) {
    console.warn('⚠️ generateDebtSchedule: graceYears >= tenorYears, no repayment possible');
    return {};
  }

  const schedule = {};
  let outstandingPrincipal = debtAmount;
  const r = interestRate;

  // ========== ANNUITY ==========
  if (repaymentType === 'annuity') {
    // For capitalize method, we need to track accrued interest during grace
    let principalForAnnuity = debtAmount;

    // Phase 1: Grace period
    for (let year = 1; year <= effectiveGraceYears; year++) {
      const interest = outstandingPrincipal * r;
      const fees = outstandingPrincipal * feesRate;

      if (graceMethod === 'capitalize') {
        // Capitalize: no payment, interest accrues to principal
        outstandingPrincipal += interest;
        schedule[year] = {
          interest: 0,  // No interest payment
          principal: 0,
          fees: 0,      // Typically no fees during full grace
          total: 0,
          outstandingEnd: Math.round(outstandingPrincipal),
          graceType: 'capitalize',
          accruedInterest: Math.round(interest)
        };
      } else {
        // Interest-only: pay interest, no principal
        schedule[year] = {
          interest: Math.round(interest),
          principal: 0,
          fees: Math.round(fees),
          total: Math.round(interest + fees),
          outstandingEnd: Math.round(outstandingPrincipal),
          graceType: 'interest_only'
        };
      }
    }

    // Recalculate annuity payment for repayment phase
    // CRITICAL: Use current outstanding principal (may have grown if capitalize)
    principalForAnnuity = outstandingPrincipal;
    const n = repaymentYears;

    // Guard against division by zero
    let annuityPayment = 0;
    if (r > 0 && n > 0) {
      annuityPayment = principalForAnnuity * (r * Math.pow(1 + r, n)) / (Math.pow(1 + r, n) - 1);
    } else if (r === 0 && n > 0) {
      annuityPayment = principalForAnnuity / n;  // Zero interest case
    }

    // Phase 2: Repayment period
    for (let year = effectiveGraceYears + 1; year <= tenorYears; year++) {
      const interest = outstandingPrincipal * r;
      const fees = outstandingPrincipal * feesRate;

      // Principal = annuity payment - interest (but capped at outstanding)
      let principal = Math.min(annuityPayment - interest, outstandingPrincipal);
      principal = Math.max(0, principal);  // Never negative
      outstandingPrincipal -= principal;

      // Handle rounding residual in last year
      if (year === tenorYears && outstandingPrincipal > 0 && outstandingPrincipal < 1) {
        principal += outstandingPrincipal;
        outstandingPrincipal = 0;
      }

      schedule[year] = {
        interest: Math.round(interest),
        principal: Math.round(principal),
        fees: Math.round(fees),
        total: Math.round(interest + principal + fees),
        outstandingEnd: Math.round(Math.max(0, outstandingPrincipal))
      };
    }
  }

  // ========== BULLET ==========
  else if (repaymentType === 'bullet') {
    for (let year = 1; year <= tenorYears; year++) {
      const interest = outstandingPrincipal * r;
      const fees = outstandingPrincipal * feesRate;

      // Grace period handling
      if (year <= effectiveGraceYears) {
        if (graceMethod === 'capitalize') {
          outstandingPrincipal += interest;
          schedule[year] = {
            interest: 0,
            principal: 0,
            fees: 0,
            total: 0,
            outstandingEnd: Math.round(outstandingPrincipal),
            graceType: 'capitalize',
            accruedInterest: Math.round(interest)
          };
        } else {
          schedule[year] = {
            interest: Math.round(interest),
            principal: 0,
            fees: Math.round(fees),
            total: Math.round(interest + fees),
            outstandingEnd: Math.round(outstandingPrincipal),
            graceType: 'interest_only'
          };
        }
      } else {
        // Non-grace: pay interest, principal only in last year
        const principal = year === tenorYears ? outstandingPrincipal : 0;
        if (year === tenorYears) outstandingPrincipal = 0;

        schedule[year] = {
          interest: Math.round(interest),
          principal: Math.round(principal),
          fees: Math.round(fees),
          total: Math.round(interest + principal + fees),
          outstandingEnd: Math.round(outstandingPrincipal)
        };
      }
    }
  }

  // ========== LINEAR ==========
  else if (repaymentType === 'linear') {
    // For capitalize, we need principal after grace to calculate equal payments
    let principalAtRepaymentStart = debtAmount;

    // Phase 1: Calculate accrued principal during grace (if capitalize)
    if (graceMethod === 'capitalize' && effectiveGraceYears > 0) {
      for (let y = 1; y <= effectiveGraceYears; y++) {
        principalAtRepaymentStart += principalAtRepaymentStart * r;
      }
    }

    // Equal principal payment during repayment phase
    const annualPrincipal = repaymentYears > 0 ? principalAtRepaymentStart / repaymentYears : 0;

    // Phase 1: Grace period
    for (let year = 1; year <= effectiveGraceYears; year++) {
      const interest = outstandingPrincipal * r;
      const fees = outstandingPrincipal * feesRate;

      if (graceMethod === 'capitalize') {
        outstandingPrincipal += interest;
        schedule[year] = {
          interest: 0,
          principal: 0,
          fees: 0,
          total: 0,
          outstandingEnd: Math.round(outstandingPrincipal),
          graceType: 'capitalize',
          accruedInterest: Math.round(interest)
        };
      } else {
        schedule[year] = {
          interest: Math.round(interest),
          principal: 0,
          fees: Math.round(fees),
          total: Math.round(interest + fees),
          outstandingEnd: Math.round(outstandingPrincipal),
          graceType: 'interest_only'
        };
      }
    }

    // Phase 2: Repayment period
    for (let year = effectiveGraceYears + 1; year <= tenorYears; year++) {
      const interest = outstandingPrincipal * r;
      const fees = outstandingPrincipal * feesRate;

      let principal = Math.min(annualPrincipal, outstandingPrincipal);
      outstandingPrincipal -= principal;

      // Handle rounding residual in last year
      if (year === tenorYears && outstandingPrincipal > 0 && outstandingPrincipal < 1) {
        principal += outstandingPrincipal;
        outstandingPrincipal = 0;
      }

      schedule[year] = {
        interest: Math.round(interest),
        principal: Math.round(principal),
        fees: Math.round(fees),
        total: Math.round(interest + principal + fees),
        outstandingEnd: Math.round(Math.max(0, outstandingPrincipal))
      };
    }
  }

  return schedule;
}

// ============================================================================
// CFADS CALCULATION
// ============================================================================

/**
 * Calculate CFADS (Cash Flow Available for Debt Service)
 * @param {Object} yearData - Annual data for a single year
 * @returns {number} - CFADS value
 */
function calculateCFADS(yearData) {
  const {
    revenue = 0,
    opex = 0,
    taxesCash = 0,
    maintCapex = 0,
    deltaWC = 0,
    // P0-1: BESS replacement is a capital expenditure that reduces CFADS
    bessReplacementCost = 0
  } = yearData;

  // CFADS = Revenue - OPEX - Taxes - MaintCapex - BESS Replacement ± DeltaWC
  return revenue - opex - taxesCash - maintCapex - bessReplacementCost - deltaWC;
}

// ============================================================================
// DSCR CALCULATION
// ============================================================================

/**
 * Calculate DSCR for a single year
 * IMPORTANT: Returns NUMBER or null (never string!)
 * @param {number} cfads - Cash Flow Available for Debt Service
 * @param {number} debtService - Total debt service (interest + principal + fees)
 * @returns {number|null} - DSCR value or null if debtService <= 0
 */
function calculateDSCR(cfads, debtService) {
  if (debtService <= 0) {
    return null;  // NOT "n/a" string - null for calculations
  }
  return cfads / debtService;
}

// ============================================================================
// CCR CALCULATION (for EaaS without assigned debt)
// ============================================================================

/**
 * Calculate CCR (Contract Coverage Ratio) for EaaS
 * CCR = ContractRevenue / (OPEX + Reserves)
 * @param {Object} yearData - Annual data
 * @returns {number|null} - CCR value or null
 */
function calculateCCR(yearData) {
  const {
    contractRevenue = 0,
    opex = 0,
    serviceReserve = 0,
    replacementReserve = 0
  } = yearData;

  const denominator = opex + serviceReserve + replacementReserve;

  if (denominator <= 0) {
    return null;
  }

  return contractRevenue / denominator;
}

/**
 * Calculate Implied Max Debt Service (for EaaS debt capacity analysis)
 * @param {number} cfads - CFADS
 * @param {number} targetDSCR - Target DSCR (e.g., 1.25)
 * @returns {number} - Maximum annual debt service supportable
 */
function calculateImpliedDebtService(cfads, targetDSCR = 1.25) {
  if (targetDSCR <= 0) return 0;
  return cfads / targetDSCR;
}

// ============================================================================
// BANKABILITY METRICS CALCULATION
// ============================================================================

/**
 * Calculate full bankability metrics for a scenario
 * @param {Array} yearlyData - Array of yearly cashflow data
 * @param {Object} debtSchedule - Debt schedule { [year]: { total, ... } }
 * @param {Object} options - { covenant, targetDSCR, optionType, hasAssignedDebt }
 * @returns {Object} - Full bankability analysis
 */
function calculateBankabilityMetrics(yearlyData, debtSchedule, options = {}) {
  const {
    covenant = 1.20,
    targetDSCR = 1.25,
    optionType = 'CAPEX',  // 'CAPEX' or 'EaaS'
    hasAssignedDebt = true
  } = options;

  const usesDSCR = optionType === 'CAPEX' || hasAssignedDebt;

  const cashflow = {};
  const dscrValues = [];  // Only years with DebtService > 0
  const yearsBelowCovenant = [];
  let totalCFADS = 0;
  let totalDebtService = 0;

  yearlyData.forEach((yearData, index) => {
    const year = yearData.year || (index + 1);
    const debtYear = debtSchedule[year] || { interest: 0, principal: 0, fees: 0, total: 0 };

    // Calculate CFADS
    // P0-1: Include BESS replacement cost in CFADS calculation
    const cfads = calculateCFADS({
      revenue: yearData.revenue || yearData.savings || 0,
      opex: yearData.opex || yearData.oAndM || 0,
      taxesCash: yearData.taxesCash || 0,
      maintCapex: yearData.maintCapex || 0,
      deltaWC: yearData.deltaWC || 0,
      bessReplacementCost: yearData.bessReplacementCost || 0
    });

    const debtService = debtYear.total || 0;

    // Calculate DSCR (number or null, NEVER string)
    const dscr = usesDSCR ? calculateDSCR(cfads, debtService) : null;

    // Calculate CCR for EaaS
    const ccr = !usesDSCR ? calculateCCR({
      contractRevenue: yearData.contractRevenue || yearData.revenue || yearData.savings || 0,
      opex: yearData.opex || yearData.oAndM || 0,
      serviceReserve: yearData.serviceReserve || 0,
      replacementReserve: yearData.replacementReserve || 0
    }) : null;

    // Flags
    const belowCovenant = dscr !== null && dscr < covenant;
    if (belowCovenant) {
      yearsBelowCovenant.push(year);
    }

    // Accumulate for weighted average (only years with DS > 0)
    if (debtService > 0) {
      dscrValues.push({ year, dscr, cfads, debtService });
      totalCFADS += cfads;
      totalDebtService += debtService;
    }

    // Store in cashflow object
    cashflow[year] = {
      year,
      revenue: yearData.revenue || yearData.savings || 0,
      opex: yearData.opex || yearData.oAndM || 0,
      taxesCash: yearData.taxesCash || 0,
      maintCapex: yearData.maintCapex || 0,
      deltaWC: yearData.deltaWC || 0,
      cfads,
      debtInterest: debtYear.interest || 0,
      debtPrincipal: debtYear.principal || 0,
      feesCash: debtYear.fees || 0,
      debtService,
      dscr,  // number or null
      ccr,   // number or null
      impliedDebtService: !usesDSCR ? calculateImpliedDebtService(cfads, targetDSCR) : null,
      flags: {
        belowCovenant,
        hasDebtService: debtService > 0
      }
    };
  });

  // Calculate KPI metrics
  // P1-1 FIX: Guard against division by zero and ensure null (never NaN)
  let minDSCR = null;
  let avgDSCR = null;
  let avgDSCRWeighted = null;
  let worstYear = null;

  if (usesDSCR && dscrValues.length > 0) {
    // Min DSCR (only from years with DebtService > 0)
    const validDSCRs = dscrValues.filter(d => d.dscr !== null && !isNaN(d.dscr) && isFinite(d.dscr));

    if (validDSCRs.length > 0) {
      const minEntry = validDSCRs.reduce((min, curr) =>
        curr.dscr < min.dscr ? curr : min, validDSCRs[0]);
      minDSCR = minEntry.dscr;
      worstYear = minEntry.year;

      // Simple average (guarded)
      const sum = validDSCRs.reduce((s, d) => s + d.dscr, 0);
      avgDSCR = validDSCRs.length > 0 ? sum / validDSCRs.length : null;

      // Final NaN guard
      if (avgDSCR !== null && (isNaN(avgDSCR) || !isFinite(avgDSCR))) {
        avgDSCR = null;
      }
    }

    // Weighted average DSCR = sum(CFADS) / sum(DebtService)
    // P1-1 FIX: Guard against totalDebtService === 0
    if (totalDebtService > 0) {
      avgDSCRWeighted = totalCFADS / totalDebtService;
      // NaN guard
      if (isNaN(avgDSCRWeighted) || !isFinite(avgDSCRWeighted)) {
        avgDSCRWeighted = null;
      }
    } else {
      avgDSCRWeighted = null;  // Explicitly null when no debt service
    }
  }

  // Calculate headroom
  const headroom = minDSCR !== null ? (minDSCR / covenant) - 1 : null;

  // CCR metrics for EaaS
  let minCCR = null;
  let avgCCR = null;
  let totalImpliedDebtCapacity = 0;

  if (!usesDSCR) {
    const ccrValues = Object.values(cashflow).filter(c => c.ccr !== null);
    if (ccrValues.length > 0) {
      minCCR = Math.min(...ccrValues.map(c => c.ccr));
      avgCCR = ccrValues.reduce((sum, c) => sum + c.ccr, 0) / ccrValues.length;
    }

    // Sum implied debt capacity
    totalImpliedDebtCapacity = Object.values(cashflow)
      .filter(c => c.impliedDebtService !== null)
      .reduce((sum, c) => sum + c.impliedDebtService, 0);
  }

  return {
    mode: usesDSCR ? 'DSCR' : 'CCR',
    optionType,
    hasAssignedDebt,

    cashflow,

    kpi: {
      // DSCR metrics (for CAPEX + DEBT)
      minDSCR,           // number or null
      avgDSCR,           // simple average, number or null
      avgDSCRWeighted,   // weighted by DebtService, number or null
      worstYear,         // year number or null
      yearsBelowCovenant,
      headroom,          // number or null

      // CCR metrics (for EaaS without debt)
      minCCR,
      avgCCR,
      totalImpliedDebtCapacity
    },

    assumptions: {
      covenant,
      targetDSCR
    }
  };
}

// ============================================================================
// MULTI-SCENARIO ANALYSIS
// ============================================================================

/**
 * Calculate bankability for multiple scenarios (P50, P90, P97)
 * @param {Object} scenarioData - { P50: [...], P90: [...], P97: [...] }
 * @param {Object} debtSchedule - Debt schedule (same for all scenarios)
 * @param {Object} financingParams - Financing parameters
 * @param {Object} options - Analysis options
 * @returns {Object} - Full multi-scenario bankability analysis
 */
function calculateMultiScenarioBankability(scenarioData, debtSchedule, financingParams, options = {}) {
  const scenarios = ['P50', 'P90', 'P97'];
  const results = {
    financing: financingParams,
    debtSchedule,
    scenarios: {}
  };

  scenarios.forEach(scenario => {
    const yearlyData = scenarioData[scenario];
    if (yearlyData && yearlyData.length > 0) {
      results.scenarios[scenario] = calculateBankabilityMetrics(
        yearlyData,
        debtSchedule,
        options
      );
    }
  });

  // Primary metrics from P90 (banker's view)
  if (results.scenarios.P90) {
    results.primaryMetrics = results.scenarios.P90.kpi;
  } else if (results.scenarios.P50) {
    results.primaryMetrics = results.scenarios.P50.kpi;
  }

  return results;
}

// ============================================================================
// EXCEL FORMULAS HELPER
// ============================================================================

/**
 * Generate Excel formula for DSCR calculation
 * IMPORTANT: Returns empty string "" if DebtService is 0 (not "n/a" text)
 * @param {string} cfadsCell - Cell reference for CFADS (e.g., "D5")
 * @param {string} dsCell - Cell reference for DebtService (e.g., "E5")
 * @returns {string} - Excel formula
 */
function excelDSCRFormula(cfadsCell, dsCell) {
  // Returns number or empty (for MIN/AVERAGE compatibility)
  return `IF(${dsCell}>0,${cfadsCell}/${dsCell},"")`;
}

/**
 * Generate Excel formula for flag below covenant
 * @param {string} dscrCell - Cell reference for DSCR
 * @param {string} covenantCell - Cell reference for covenant value
 * @returns {string} - Excel formula
 */
function excelBelowCovenantFormula(dscrCell, covenantCell) {
  return `IF(AND(${dscrCell}<>"",${dscrCell}<${covenantCell}),TRUE,FALSE)`;
}

// ============================================================================
// FORMATTING HELPERS
// ============================================================================

/**
 * Format DSCR for display (handles null → "n/a")
 * @param {number|null} dscr - DSCR value
 * @param {number} decimals - Decimal places
 * @returns {string} - Formatted string
 */
function formatDSCR(dscr, decimals = 2) {
  if (dscr === null || dscr === undefined || isNaN(dscr)) {
    return 'n/a';
  }
  return dscr.toFixed(decimals) + 'x';
}

/**
 * Format percentage with sign
 * @param {number|null} value - Value as decimal (e.g., 0.125 for 12.5%)
 * @param {number} decimals - Decimal places
 * @returns {string} - Formatted string
 */
function formatHeadroom(value, decimals = 1) {
  if (value === null || value === undefined || isNaN(value)) {
    return 'n/a';
  }
  const sign = value >= 0 ? '+' : '';
  return sign + (value * 100).toFixed(decimals) + '%';
}

/**
 * Get status color based on DSCR vs covenant
 * @param {number|null} dscr - DSCR value
 * @param {number} covenant - Covenant threshold
 * @returns {string} - CSS color class
 */
function getDSCRStatusColor(dscr, covenant = 1.20) {
  if (dscr === null) return 'neutral';
  if (dscr >= covenant * 1.25) return 'excellent';  // 25% above covenant
  if (dscr >= covenant * 1.10) return 'good';       // 10% above covenant
  if (dscr >= covenant) return 'acceptable';         // At or above covenant
  if (dscr >= covenant * 0.90) return 'warning';    // Within 10% below
  return 'critical';                                 // More than 10% below
}

// ============================================================================
// YEAR INDEXING HELPERS (P1-2)
// ============================================================================

/**
 * Standard: Financial years are 1-indexed (year 1, 2, 3, ...)
 * Arrays are 0-indexed. Use these helpers for conversion.
 */

/**
 * Convert financial year (1-indexed) to array index (0-indexed)
 * @param {number} year - Financial year (1, 2, 3, ...)
 * @returns {number} - Array index (0, 1, 2, ...)
 */
function getArrayIndexForYear(year) {
  return Math.max(0, year - 1);
}

/**
 * Convert array index (0-indexed) to financial year (1-indexed)
 * @param {number} index - Array index (0, 1, 2, ...)
 * @returns {number} - Financial year (1, 2, 3, ...)
 */
function getYearForArrayIndex(index) {
  return index + 1;
}

/**
 * Validate year mapping consistency between yearly data and debt schedule
 * @param {Array} yearlyData - Array of yearly cashflow data
 * @param {Object} debtSchedule - Debt schedule { [year]: { total, ... } }
 * @returns {Object} - { valid: boolean, errors: string[] }
 */
function validateYearMapping(yearlyData, debtSchedule) {
  const errors = [];

  if (!yearlyData || yearlyData.length === 0) {
    errors.push('yearlyData is empty');
    return { valid: false, errors };
  }

  yearlyData.forEach((data, index) => {
    const expectedYear = getYearForArrayIndex(index);
    const actualYear = data.year || data.rok || expectedYear;

    if (actualYear !== expectedYear) {
      errors.push(`Index ${index}: expected year ${expectedYear}, got ${actualYear}`);
    }

    // Check if debt schedule has matching entry
    if (debtSchedule && Object.keys(debtSchedule).length > 0) {
      const scheduleEntry = debtSchedule[actualYear];
      if (!scheduleEntry && actualYear <= Object.keys(debtSchedule).length) {
        errors.push(`Year ${actualYear}: no matching debt schedule entry`);
      }
    }
  });

  return { valid: errors.length === 0, errors };
}

// ============================================================================
// VALIDATION / SELF-TEST FUNCTIONS
// ============================================================================

/**
 * Validate debt schedule: final balance should be ~0, sum of principals = original debt
 * @param {Object} schedule - Generated debt schedule
 * @param {number} originalDebt - Original debt amount
 * @param {number} tolerance - Acceptable tolerance (default: 1 PLN per 1M debt)
 * @returns {Object} - { valid: boolean, finalBalance: number, sumPrincipal: number, errors: string[] }
 */
function validateDebtSchedule(schedule, originalDebt, tolerance = null) {
  const errors = [];
  const years = Object.keys(schedule).map(Number).sort((a, b) => a - b);

  if (years.length === 0) {
    return { valid: true, finalBalance: 0, sumPrincipal: 0, errors: ['Empty schedule (valid for no debt)'] };
  }

  // Calculate tolerance as 1e-6 * originalDebt (minimum 1)
  const effectiveTolerance = tolerance ?? Math.max(1, originalDebt * 1e-6);

  const lastYear = years[years.length - 1];
  const finalBalance = schedule[lastYear]?.outstandingEnd || 0;
  const sumPrincipal = years.reduce((sum, year) => sum + (schedule[year]?.principal || 0), 0);

  // Check final balance is ~0
  if (Math.abs(finalBalance) > effectiveTolerance) {
    errors.push(`Final balance ${finalBalance} exceeds tolerance ${effectiveTolerance}`);
  }

  // Check sum of principal payments = original debt (for interest_only grace method)
  // For capitalize, sum may be higher due to accrued interest
  // So we check if sumPrincipal >= originalDebt (within tolerance)
  if (sumPrincipal < originalDebt - effectiveTolerance) {
    errors.push(`Sum of principal ${sumPrincipal} is less than original debt ${originalDebt}`);
  }

  return {
    valid: errors.length === 0,
    finalBalance,
    sumPrincipal,
    originalDebt,
    tolerance: effectiveTolerance,
    errors
  };
}

/**
 * Run self-tests for debt schedule generation
 * Call this during development to verify correctness
 * @returns {Object} - Test results
 */
function runDebtScheduleTests() {
  console.log('🧪 Running debt schedule self-tests...');
  const results = { passed: 0, failed: 0, tests: [] };

  // Test 1: Annuity without grace
  const test1 = generateDebtSchedule({
    debtAmount: 1000000,
    tenorYears: 15,
    interestRate: 0.065,
    repaymentType: 'annuity',
    graceYears: 0
  });
  const val1 = validateDebtSchedule(test1, 1000000);
  results.tests.push({ name: 'Annuity no grace', ...val1 });
  val1.valid ? results.passed++ : results.failed++;

  // Test 2: Annuity with 2y grace (interest_only)
  const test2 = generateDebtSchedule({
    debtAmount: 1000000,
    tenorYears: 15,
    interestRate: 0.065,
    repaymentType: 'annuity',
    graceYears: 2,
    graceMethod: 'interest_only'
  });
  const val2 = validateDebtSchedule(test2, 1000000);
  results.tests.push({ name: 'Annuity 2y grace interest_only', ...val2 });
  val2.valid ? results.passed++ : results.failed++;

  // Test 3: Annuity with 2y grace (capitalize)
  const test3 = generateDebtSchedule({
    debtAmount: 1000000,
    tenorYears: 15,
    interestRate: 0.065,
    repaymentType: 'annuity',
    graceYears: 2,
    graceMethod: 'capitalize'
  });
  const val3 = validateDebtSchedule(test3, 1000000);
  results.tests.push({ name: 'Annuity 2y grace capitalize', ...val3 });
  val3.valid ? results.passed++ : results.failed++;

  // Test 4: Linear with grace
  const test4 = generateDebtSchedule({
    debtAmount: 1000000,
    tenorYears: 10,
    interestRate: 0.07,
    repaymentType: 'linear',
    graceYears: 2,
    graceMethod: 'interest_only'
  });
  const val4 = validateDebtSchedule(test4, 1000000);
  results.tests.push({ name: 'Linear 2y grace', ...val4 });
  val4.valid ? results.passed++ : results.failed++;

  // Test 5: Bullet
  const test5 = generateDebtSchedule({
    debtAmount: 1000000,
    tenorYears: 10,
    interestRate: 0.06,
    repaymentType: 'bullet',
    graceYears: 0
  });
  const val5 = validateDebtSchedule(test5, 1000000);
  results.tests.push({ name: 'Bullet no grace', ...val5 });
  val5.valid ? results.passed++ : results.failed++;

  // Test 6: Zero debt (should return empty schedule)
  const test6 = generateDebtSchedule({ debtAmount: 0, tenorYears: 10 });
  const val6 = { valid: Object.keys(test6).length === 0, errors: [] };
  results.tests.push({ name: 'Zero debt', ...val6 });
  val6.valid ? results.passed++ : results.failed++;

  // Test 7: Bankability with no debt -> avgDSCR = null
  const yearlyData = [
    { year: 1, revenue: 100000, opex: 20000 },
    { year: 2, revenue: 100000, opex: 20000 }
  ];
  const bankResult = calculateBankabilityMetrics(yearlyData, {}, { covenant: 1.20 });
  const test7Valid = bankResult.kpi.avgDSCR === null && bankResult.kpi.avgDSCRWeighted === null;
  results.tests.push({
    name: 'Bankability no debt -> null metrics',
    valid: test7Valid,
    avgDSCR: bankResult.kpi.avgDSCR,
    avgDSCRWeighted: bankResult.kpi.avgDSCRWeighted,
    errors: test7Valid ? [] : ['Expected null metrics for no debt']
  });
  test7Valid ? results.passed++ : results.failed++;

  console.log(`🧪 Test results: ${results.passed} passed, ${results.failed} failed`);
  results.tests.forEach(t => {
    console.log(`  ${t.valid ? '✅' : '❌'} ${t.name}`, t.valid ? '' : t.errors);
  });

  return results;
}

// ============================================================================
// EXPORTS
// ============================================================================

// Export for use in economics.js
window.Bankability = {
  // Core calculations
  generateDebtSchedule,
  calculateCFADS,
  calculateDSCR,
  calculateCCR,
  calculateImpliedDebtService,
  calculateBankabilityMetrics,
  calculateMultiScenarioBankability,

  // Excel helpers
  excelDSCRFormula,
  excelBelowCovenantFormula,

  // Formatting
  formatDSCR,
  formatHeadroom,
  getDSCRStatusColor,

  // Year indexing helpers (P1-2)
  getArrayIndexForYear,
  getYearForArrayIndex,
  validateYearMapping,

  // Validation (for testing)
  validateDebtSchedule,
  runDebtScheduleTests
};

console.log('✅ Bankability module ready');

// Auto-run tests in development (check for dev flag)
if (typeof window !== 'undefined' && window.location?.search?.includes('bankability_test=1')) {
  setTimeout(() => {
    console.log('🧪 Auto-running bankability tests (dev mode)...');
    window.Bankability.runDebtScheduleTests();
  }, 100);
}

// ============================================================================
// NODE.JS / TEST EXPORTS (CommonJS compatibility)
// ============================================================================
// This allows importing functions in Node.js for unit testing without breaking browser usage
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    generateDebtSchedule,
    calculateBankabilityMetrics,
    validateDebtSchedule,
    runDebtScheduleTests,
    getArrayIndexForYear,
    getYearForArrayIndex,
    validateYearMapping
  };
}
