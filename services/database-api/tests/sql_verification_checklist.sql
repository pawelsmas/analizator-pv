-- =============================================================================
-- ECONOMICS SNAPSHOT V2 - SQL VERIFICATION CHECKLIST
-- =============================================================================
-- Run these queries after saving a project to verify data contract compliance.
-- Replace :snapshot_id with actual snapshot ID.
-- =============================================================================

-- =============================================================================
-- 1) VERIFY model_type IS ENUM (not VARCHAR)
-- =============================================================================
-- Expected: data_type = 'USER-DEFINED', udt_name = 'economics_model_type'

SELECT
  table_name,
  column_name,
  data_type,
  udt_name
FROM information_schema.columns
WHERE table_name = 'project_economics_cashflow_yearly'
  AND column_name = 'model_type';

-- Verify enum values
SELECT unnest(enum_range(NULL::economics_model_type)) AS enum_values;
-- Expected: CAPEX_CLIENT, EAAS_CLIENT, EAAS_INVESTOR

-- =============================================================================
-- 2) SANITY CHECK: Count/Min/Max per model type
-- =============================================================================
-- Expected:
--   CAPEX_CLIENT:  31 rows, min=0, max=30
--   EAAS_CLIENT:   30 rows, min=1, max=30
--   EAAS_INVESTOR: duration+1 rows, min=0, max=duration

SELECT
  model_type,
  COUNT(*) AS row_count,
  MIN(year) AS min_year,
  MAX(year) AS max_year
FROM project_economics_cashflow_yearly
WHERE snapshot_id = :snapshot_id
GROUP BY model_type
ORDER BY model_type;

-- =============================================================================
-- 3) COMPLETENESS CHECK: No missing years per model
-- =============================================================================

-- 3a) CAPEX_CLIENT (expected years: 0..30)
-- Expected result: 0 rows (no missing years)
WITH expected AS (
  SELECT generate_series(0, 30) AS year
)
SELECT e.year AS missing_year
FROM expected e
LEFT JOIN project_economics_cashflow_yearly y
  ON y.snapshot_id = :snapshot_id
 AND y.model_type = 'CAPEX_CLIENT'
 AND y.year = e.year
WHERE y.year IS NULL
ORDER BY e.year;

-- 3b) EAAS_CLIENT (expected years: 1..30)
-- Expected result: 0 rows (no missing years)
WITH expected AS (
  SELECT generate_series(1, 30) AS year
)
SELECT e.year AS missing_year
FROM expected e
LEFT JOIN project_economics_cashflow_yearly y
  ON y.snapshot_id = :snapshot_id
 AND y.model_type = 'EAAS_CLIENT'
 AND y.year = e.year
WHERE y.year IS NULL
ORDER BY e.year;

-- 3c) EAAS_INVESTOR (expected years: 0..duration)
-- Expected result: 0 rows (no missing years)
WITH snapshot_duration AS (
  SELECT eaas_client_duration_years AS duration
  FROM project_economics_snapshot
  WHERE id = :snapshot_id
),
expected AS (
  SELECT generate_series(0, (SELECT duration FROM snapshot_duration)) AS year
)
SELECT e.year AS missing_year
FROM expected e
LEFT JOIN project_economics_cashflow_yearly y
  ON y.snapshot_id = :snapshot_id
 AND y.model_type = 'EAAS_INVESTOR'
 AND y.year = e.year
WHERE y.year IS NULL
ORDER BY e.year;

-- =============================================================================
-- 4) YEAR 0 SIGN CHECK: CAPEX must be negative
-- =============================================================================
-- Expected:
--   CAPEX_CLIENT year=0: net_cashflow_pln < 0
--   EAAS_INVESTOR year=0: net_cashflow_pln < 0
--   EAAS_CLIENT: no year=0 row

SELECT
  model_type,
  year,
  capex_pln,
  net_cashflow_pln,
  CASE
    WHEN net_cashflow_pln < 0 THEN 'OK (negative)'
    WHEN net_cashflow_pln > 0 THEN 'ERROR: should be negative!'
    ELSE 'ZERO'
  END AS sign_check
FROM project_economics_cashflow_yearly
WHERE snapshot_id = :snapshot_id
  AND year = 0
ORDER BY model_type;

-- Verify EAAS_CLIENT has no year 0
SELECT COUNT(*) AS eaas_client_year0_count
FROM project_economics_cashflow_yearly
WHERE snapshot_id = :snapshot_id
  AND model_type = 'EAAS_CLIENT'
  AND year = 0;
-- Expected: 0

-- =============================================================================
-- 5) SNAPSHOT COMPLETENESS CHECK
-- =============================================================================
-- Verify all key fields are populated

SELECT
  id,
  snapshot_version,
  variant_key,
  analysis_period_years,
  -- CAPEX Client
  capex_client_npv25,
  capex_client_irr,
  capex_client_capex0_pln,
  -- CAPEX Deal (margin)
  capex_deal_sell_price_pln,
  capex_deal_direct_cost_pln,
  capex_deal_gross_margin_pln,
  capex_deal_gross_margin_pct,
  -- EaaS Client
  eaas_client_npv25,
  eaas_client_duration_years,
  -- EaaS Investor
  eaas_investor_npv25,
  eaas_investor_irr,
  eaas_investor_capex0_pln,
  -- Metadata
  created_at
FROM project_economics_snapshot
WHERE id = :snapshot_id;

-- =============================================================================
-- 6) MARGIN FORMULA VERIFICATION
-- =============================================================================
-- Verify margin% = margin_pln / sell_price_pln (not margin_pln / cost_pln)
-- Expected: calculated_margin_pct should equal capex_deal_gross_margin_pct

SELECT
  capex_deal_sell_price_pln,
  capex_deal_direct_cost_pln,
  capex_deal_gross_margin_pln,
  capex_deal_gross_margin_pct AS stored_margin_pct,
  ROUND((capex_deal_gross_margin_pln / capex_deal_sell_price_pln * 100)::numeric, 2) AS calculated_margin_pct,
  CASE
    WHEN ABS(capex_deal_gross_margin_pct - (capex_deal_gross_margin_pln / capex_deal_sell_price_pln * 100)) < 0.1
    THEN 'OK'
    ELSE 'MISMATCH - check formula!'
  END AS verification
FROM project_economics_snapshot
WHERE id = :snapshot_id;

-- =============================================================================
-- 7) NPV CONSISTENCY CHECK
-- =============================================================================
-- Compare NPV from snapshot with NPV calculated from cashflows
-- They should match (within rounding tolerance)

-- CAPEX_CLIENT NPV from cashflows
WITH cf_npv AS (
  SELECT
    MAX(cumulative_discounted_pln) AS npv_from_cashflows
  FROM project_economics_cashflow_yearly
  WHERE snapshot_id = :snapshot_id
    AND model_type = 'CAPEX_CLIENT'
    AND year = 30
)
SELECT
  s.capex_client_npv25 AS npv_in_snapshot,
  cf.npv_from_cashflows,
  ABS(COALESCE(s.capex_client_npv25, 0) - COALESCE(cf.npv_from_cashflows, 0)) AS difference,
  CASE
    WHEN ABS(COALESCE(s.capex_client_npv25, 0) - COALESCE(cf.npv_from_cashflows, 0)) < 1000
    THEN 'OK (within 1k PLN)'
    ELSE 'CHECK - significant difference'
  END AS consistency
FROM project_economics_snapshot s
CROSS JOIN cf_npv cf
WHERE s.id = :snapshot_id;

-- EAAS_INVESTOR NPV from cashflows
WITH investor_cf_npv AS (
  SELECT
    MAX(cumulative_discounted_pln) AS npv_from_cashflows
  FROM project_economics_cashflow_yearly
  WHERE snapshot_id = :snapshot_id
    AND model_type = 'EAAS_INVESTOR'
)
SELECT
  s.eaas_investor_npv25 AS npv_in_snapshot,
  cf.npv_from_cashflows,
  ABS(COALESCE(s.eaas_investor_npv25, 0) - COALESCE(cf.npv_from_cashflows, 0)) AS difference,
  CASE
    WHEN ABS(COALESCE(s.eaas_investor_npv25, 0) - COALESCE(cf.npv_from_cashflows, 0)) < 1000
    THEN 'OK (within 1k PLN)'
    ELSE 'CHECK - significant difference'
  END AS consistency
FROM project_economics_snapshot s
CROSS JOIN investor_cf_npv cf
WHERE s.id = :snapshot_id;

-- =============================================================================
-- 8) DISCOUNT RATE UNITS CHECK
-- =============================================================================
-- Verify discount_rate_pct is stored as percentage (e.g., 7.0 for 7%)
-- NOT as decimal (0.07)

SELECT
  discount_rate_pct,
  CASE
    WHEN discount_rate_pct > 1 THEN 'OK (stored as percentage)'
    WHEN discount_rate_pct < 1 AND discount_rate_pct > 0 THEN 'WARNING: looks like decimal, expected percentage!'
    ELSE 'CHECK VALUE'
  END AS unit_check
FROM project_economics_snapshot
WHERE id = :snapshot_id;
