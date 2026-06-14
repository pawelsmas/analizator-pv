-- =============================================================================
-- MIGRATION 002: Add Full Investor Model fields
-- =============================================================================
-- Date: 2026-01-10
-- Description: Adds all fields required for full EaaS investor model
--              as displayed in the frontend:
--              - Subscription: annual, monthly, price per MWh
--              - IRR: target, project, equity, driver
--              - Capital structure: CAPEX, debt, equity, leverage
--              - Contract financials: revenue, opex, tax, interest
--              - Model parameters: CIT rate, depreciation, indexation, project life
--              - Residual value
-- =============================================================================

-- EaaS Client - new fields
ALTER TABLE project_economics_snapshot
ADD COLUMN IF NOT EXISTS eaas_client_subscription_monthly DECIMAL(15, 2);

ALTER TABLE project_economics_snapshot
ADD COLUMN IF NOT EXISTS eaas_client_price_per_mwh DECIMAL(10, 2);

COMMENT ON COLUMN project_economics_snapshot.eaas_client_subscription_monthly IS 'Miesięczna rata PLN/mies';
COMMENT ON COLUMN project_economics_snapshot.eaas_client_price_per_mwh IS 'Cena EaaS PLN/MWh';

-- EaaS Investor - IRR metrics
ALTER TABLE project_economics_snapshot
ADD COLUMN IF NOT EXISTS eaas_investor_target_irr DECIMAL(8, 4);

ALTER TABLE project_economics_snapshot
ADD COLUMN IF NOT EXISTS eaas_investor_project_irr DECIMAL(8, 4);

ALTER TABLE project_economics_snapshot
ADD COLUMN IF NOT EXISTS eaas_investor_equity_irr DECIMAL(8, 4);

ALTER TABLE project_economics_snapshot
ADD COLUMN IF NOT EXISTS eaas_investor_irr_driver VARCHAR(10);

COMMENT ON COLUMN project_economics_snapshot.eaas_investor_target_irr IS 'Target IRR (decimal, np. 0.104 = 10.4%)';
COMMENT ON COLUMN project_economics_snapshot.eaas_investor_project_irr IS 'Project IRR';
COMMENT ON COLUMN project_economics_snapshot.eaas_investor_equity_irr IS 'Equity IRR';
COMMENT ON COLUMN project_economics_snapshot.eaas_investor_irr_driver IS 'IRR Driver: PLN lub EUR';

-- EaaS Investor - Capital structure
ALTER TABLE project_economics_snapshot
ADD COLUMN IF NOT EXISTS eaas_investor_capex_pln DECIMAL(15, 2);

ALTER TABLE project_economics_snapshot
ADD COLUMN IF NOT EXISTS eaas_investor_debt_pln DECIMAL(15, 2);

ALTER TABLE project_economics_snapshot
ADD COLUMN IF NOT EXISTS eaas_investor_equity_pln DECIMAL(15, 2);

ALTER TABLE project_economics_snapshot
ADD COLUMN IF NOT EXISTS eaas_investor_leverage_pct DECIMAL(6, 2);

COMMENT ON COLUMN project_economics_snapshot.eaas_investor_capex_pln IS 'CAPEX inwestora PLN';
COMMENT ON COLUMN project_economics_snapshot.eaas_investor_debt_pln IS 'Dług PLN';
COMMENT ON COLUMN project_economics_snapshot.eaas_investor_equity_pln IS 'Kapitał własny PLN';
COMMENT ON COLUMN project_economics_snapshot.eaas_investor_leverage_pct IS 'Leverage %';

-- EaaS Investor - Contract financials
ALTER TABLE project_economics_snapshot
ADD COLUMN IF NOT EXISTS eaas_investor_contract_revenue_pln DECIMAL(15, 2);

ALTER TABLE project_economics_snapshot
ADD COLUMN IF NOT EXISTS eaas_investor_contract_opex_pln DECIMAL(15, 2);

ALTER TABLE project_economics_snapshot
ADD COLUMN IF NOT EXISTS eaas_investor_contract_tax_pln DECIMAL(15, 2);

ALTER TABLE project_economics_snapshot
ADD COLUMN IF NOT EXISTS eaas_investor_contract_interest_pln DECIMAL(15, 2);

COMMENT ON COLUMN project_economics_snapshot.eaas_investor_contract_revenue_pln IS 'Przychody kontraktu PLN';
COMMENT ON COLUMN project_economics_snapshot.eaas_investor_contract_opex_pln IS 'OPEX kontraktu PLN';
COMMENT ON COLUMN project_economics_snapshot.eaas_investor_contract_tax_pln IS 'Podatek CIT PLN';
COMMENT ON COLUMN project_economics_snapshot.eaas_investor_contract_interest_pln IS 'Odsetki PLN';

-- EaaS Investor - Model parameters
ALTER TABLE project_economics_snapshot
ADD COLUMN IF NOT EXISTS eaas_investor_cit_rate_pct DECIMAL(6, 2);

ALTER TABLE project_economics_snapshot
ADD COLUMN IF NOT EXISTS eaas_investor_depreciation_years INT;

ALTER TABLE project_economics_snapshot
ADD COLUMN IF NOT EXISTS eaas_investor_indexation_type VARCHAR(20);

ALTER TABLE project_economics_snapshot
ADD COLUMN IF NOT EXISTS eaas_investor_project_life_years INT;

COMMENT ON COLUMN project_economics_snapshot.eaas_investor_cit_rate_pct IS 'Stawka CIT %';
COMMENT ON COLUMN project_economics_snapshot.eaas_investor_depreciation_years IS 'Amortyzacja (lata)';
COMMENT ON COLUMN project_economics_snapshot.eaas_investor_indexation_type IS 'Indeksacja: Stała lub Inflacja';
COMMENT ON COLUMN project_economics_snapshot.eaas_investor_project_life_years IS 'Życie projektu (lata)';

-- EaaS Investor - Residual value
ALTER TABLE project_economics_snapshot
ADD COLUMN IF NOT EXISTS eaas_investor_residual_value_pln DECIMAL(15, 2);

ALTER TABLE project_economics_snapshot
ADD COLUMN IF NOT EXISTS eaas_investor_residual_per_kwp DECIMAL(10, 2);

COMMENT ON COLUMN project_economics_snapshot.eaas_investor_residual_value_pln IS 'Wartość rezydualna PLN';
COMMENT ON COLUMN project_economics_snapshot.eaas_investor_residual_per_kwp IS 'Wykup przez klienta PLN/kWp';

-- Verification query
SELECT
    column_name,
    data_type,
    is_nullable
FROM information_schema.columns
WHERE table_name = 'project_economics_snapshot'
AND column_name LIKE 'eaas_investor_%'
ORDER BY column_name;
