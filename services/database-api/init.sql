-- ===========================================
-- PV Analyzer - PostgreSQL Schema v1.0
-- Central Data Store for profiles and prices
-- ===========================================

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ===========================================
-- COMPANIES (Firmy klientów)
-- ===========================================
CREATE TABLE companies (
    id SERIAL PRIMARY KEY,
    uuid UUID DEFAULT uuid_generate_v4() UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    nip VARCHAR(20),
    address TEXT,
    contact_email VARCHAR(255),
    contact_phone VARCHAR(50),
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_companies_name ON companies(name);
CREATE INDEX idx_companies_uuid ON companies(uuid);

-- ===========================================
-- PROJECTS (Projekty w ramach firm)
-- ===========================================
CREATE TABLE projects (
    id SERIAL PRIMARY KEY,
    uuid UUID DEFAULT uuid_generate_v4() UNIQUE NOT NULL,
    company_id INT REFERENCES companies(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    location_name VARCHAR(255),
    latitude DECIMAL(10, 7),
    longitude DECIMAL(10, 7),
    -- Analysis mode
    analysis_mode VARCHAR(50) DEFAULT 'pv_bess',  -- pv_solo, pv_bess, bess_solo, peak_shaving, arbitrage
    -- Status
    status VARCHAR(50) DEFAULT 'draft',  -- draft, active, archived
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_projects_company ON projects(company_id);
CREATE INDEX idx_projects_uuid ON projects(uuid);
CREATE INDEX idx_projects_status ON projects(status);

-- ===========================================
-- ENERGY_PROFILES (Profile energetyczne 15-min/godzinowe)
-- ===========================================
CREATE TABLE energy_profiles (
    id SERIAL PRIMARY KEY,
    project_id INT REFERENCES projects(id) ON DELETE CASCADE,
    profile_type VARCHAR(50) NOT NULL,  -- consumption, pv_generation, net_load
    time_resolution VARCHAR(20) NOT NULL DEFAULT 'hourly',  -- hourly, 15min
    year INT NOT NULL,
    source VARCHAR(100),  -- 'upload', 'pvgis', 'manual'
    filename VARCHAR(255),
    total_kwh DECIMAL(15, 3),
    peak_kw DECIMAL(12, 3),
    data_points INT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_profiles_project ON energy_profiles(project_id);
CREATE INDEX idx_profiles_type_year ON energy_profiles(profile_type, year);

-- ===========================================
-- PROFILE_DATA (Dane czasowe profili - partycjonowane)
-- ===========================================
CREATE TABLE profile_data (
    id BIGSERIAL PRIMARY KEY,
    profile_id INT REFERENCES energy_profiles(id) ON DELETE CASCADE,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    value_kw DECIMAL(12, 4) NOT NULL,  -- Moc [kW] lub energia [kWh] w zależności od resolution
    UNIQUE(profile_id, timestamp)
);

CREATE INDEX idx_profile_data_profile_time ON profile_data(profile_id, timestamp);
CREATE INDEX idx_profile_data_timestamp ON profile_data(timestamp);

-- ===========================================
-- PRICE_SCENARIOS (Scenariusze cenowe)
-- ===========================================
CREATE TABLE price_scenarios (
    id SERIAL PRIMARY KEY,
    uuid UUID DEFAULT uuid_generate_v4() UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    scenario_type VARCHAR(50) NOT NULL,  -- historical, forecast, custom
    source VARCHAR(100),  -- tge_rdn, tge_rb, entsoe, custom
    year INT,
    currency VARCHAR(10) DEFAULT 'PLN',
    unit VARCHAR(20) DEFAULT 'PLN/MWh',
    -- Statistics
    avg_price DECIMAL(10, 2),
    min_price DECIMAL(10, 2),
    max_price DECIMAL(10, 2),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_price_scenarios_type ON price_scenarios(scenario_type);
CREATE INDEX idx_price_scenarios_year ON price_scenarios(year);

-- ===========================================
-- PRICE_DATA (Dane cenowe godzinowe)
-- ===========================================
CREATE TABLE price_data (
    id BIGSERIAL PRIMARY KEY,
    scenario_id INT REFERENCES price_scenarios(id) ON DELETE CASCADE,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    price_pln_mwh DECIMAL(10, 4) NOT NULL,
    UNIQUE(scenario_id, timestamp)
);

CREATE INDEX idx_price_data_scenario_time ON price_data(scenario_id, timestamp);

-- ===========================================
-- ANALYSIS_RESULTS (Wyniki analiz - cache)
-- ===========================================
CREATE TABLE analysis_results (
    id SERIAL PRIMARY KEY,
    uuid UUID DEFAULT uuid_generate_v4() UNIQUE NOT NULL,
    project_id INT REFERENCES projects(id) ON DELETE CASCADE,
    price_scenario_id INT REFERENCES price_scenarios(id) ON DELETE SET NULL,
    analysis_type VARCHAR(50) NOT NULL,  -- pv_sizing, bess_sizing, peak_shaving, arbitrage
    -- Input parameters (JSON)
    input_params JSONB NOT NULL,
    -- Results (JSON)
    results JSONB NOT NULL,
    -- Metadata
    status VARCHAR(50) DEFAULT 'completed',
    compute_time_ms INT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_analysis_project ON analysis_results(project_id);
CREATE INDEX idx_analysis_type ON analysis_results(analysis_type);

-- ===========================================
-- ANALYSIS MODES (Tryby analizy - słownik)
-- ===========================================
CREATE TABLE analysis_modes (
    id SERIAL PRIMARY KEY,
    code VARCHAR(50) UNIQUE NOT NULL,
    name_pl VARCHAR(100) NOT NULL,
    name_en VARCHAR(100) NOT NULL,
    description_pl TEXT,
    icon VARCHAR(50),
    requires_pv BOOLEAN DEFAULT FALSE,
    requires_bess BOOLEAN DEFAULT FALSE,
    requires_load BOOLEAN DEFAULT TRUE,
    requires_prices BOOLEAN DEFAULT FALSE,
    display_order INT DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE
);

-- Wstaw domyślne tryby analizy
INSERT INTO analysis_modes (code, name_pl, name_en, description_pl, icon, requires_pv, requires_bess, requires_load, requires_prices, display_order) VALUES
('pv_solo', 'Tylko PV', 'PV Only', 'Dobór optymalnej wielkości instalacji fotowoltaicznej do profilu zużycia', 'solar', TRUE, FALSE, TRUE, FALSE, 1),
('pv_bess', 'PV + BESS', 'PV + BESS', 'Kompleksowa analiza PV z magazynem energii - autokonsumpcja i zero-export', 'battery', TRUE, TRUE, TRUE, FALSE, 2),
('bess_solo', 'Tylko BESS', 'BESS Only', 'Magazyn energii bez PV - peak shaving lub arbitraż cenowy', 'storage', FALSE, TRUE, TRUE, FALSE, 3),
('peak_shaving', 'Peak Shaving', 'Peak Shaving', 'Redukcja szczytów mocy - oszczędności na opłacie mocowej', 'trending_down', FALSE, TRUE, TRUE, FALSE, 4),
('arbitrage', 'Arbitraż cenowy', 'Price Arbitrage', 'Handel energią - kupuj tanio, sprzedawaj drogo (wymaga cen TGE)', 'swap_vert', FALSE, TRUE, TRUE, TRUE, 5);

-- ===========================================
-- HELPER FUNCTIONS
-- ===========================================

-- Funkcja aktualizująca updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Triggery dla updated_at
CREATE TRIGGER update_companies_updated_at BEFORE UPDATE ON companies
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_projects_updated_at BEFORE UPDATE ON projects
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ===========================================
-- SAMPLE DATA (opcjonalne, do testów)
-- ===========================================

-- Przykładowa firma
INSERT INTO companies (name, nip, contact_email, notes) VALUES
('Demo Company Sp. z o.o.', '1234567890', 'demo@example.com', 'Firma demonstracyjna do testów');

-- Przykładowy projekt
INSERT INTO projects (company_id, name, description, location_name, latitude, longitude, analysis_mode, status) VALUES
(1, 'Fabryka Kraków', 'Instalacja PV+BESS dla zakładu produkcyjnego', 'Kraków', 50.0647, 19.9450, 'pv_bess', 'active');

-- Przykładowy scenariusz cenowy
INSERT INTO price_scenarios (name, description, scenario_type, source, year, avg_price, min_price, max_price) VALUES
('TGE RDN 2024', 'Historyczne ceny z Rynku Dnia Następnego 2024', 'historical', 'tge_rdn', 2024, 450.00, 50.00, 1200.00);

-- ===========================================
-- VIEWS (widoki pomocnicze)
-- ===========================================

-- Widok: projekty z nazwą firmy
CREATE VIEW v_projects_with_company AS
SELECT
    p.*,
    c.name as company_name,
    c.nip as company_nip
FROM projects p
LEFT JOIN companies c ON p.company_id = c.id;

-- Widok: statystyki profili
CREATE VIEW v_profile_stats AS
SELECT
    ep.id,
    ep.project_id,
    ep.profile_type,
    ep.year,
    ep.total_kwh,
    ep.peak_kw,
    ep.data_points,
    COUNT(pd.id) as actual_data_points,
    MIN(pd.timestamp) as first_timestamp,
    MAX(pd.timestamp) as last_timestamp,
    AVG(pd.value_kw) as avg_kw,
    MAX(pd.value_kw) as max_kw
FROM energy_profiles ep
LEFT JOIN profile_data pd ON ep.id = pd.profile_id
GROUP BY ep.id;

-- ===========================================
-- PROJECT_SETTINGS (wersjonowane ustawienia projektu)
-- ===========================================
CREATE TABLE project_settings (
    id SERIAL PRIMARY KEY,
    uuid UUID DEFAULT uuid_generate_v4() UNIQUE NOT NULL,
    project_id INT REFERENCES projects(id) ON DELETE CASCADE,
    version INT DEFAULT 1,
    settings JSONB NOT NULL,  -- Pełne ustawienia (taryfy, BESS params, ekonomia)
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_by VARCHAR(255),  -- Kto utworzył wersję
    description VARCHAR(500)  -- Opis wersji (np. "Zmiana taryfy na C22a")
);

CREATE INDEX idx_project_settings_project ON project_settings(project_id);
CREATE INDEX idx_project_settings_version ON project_settings(project_id, version DESC);

-- ===========================================
-- CALCULATIONS (wszystkie obliczenia z wszystkich serwisów)
-- ===========================================
CREATE TABLE calculations (
    id SERIAL PRIMARY KEY,
    uuid UUID DEFAULT uuid_generate_v4() UNIQUE NOT NULL,
    project_id INT REFERENCES projects(id) ON DELETE CASCADE,
    parent_calc_id INT REFERENCES calculations(id) ON DELETE SET NULL,  -- Łańcuch: PV → BESS → Economics

    -- Typ obliczenia
    calc_type VARCHAR(50) NOT NULL,
    -- Dozwolone typy:
    -- 'consumption_analysis'   - Analiza zużycia (data-analysis)
    -- 'pv_sizing'              - Dobór PV (pv-calculation)
    -- 'pv_production'          - Profil produkcji PV
    -- 'bess_dispatch'          - Symulacja BESS (bess-dispatch)
    -- 'bess_sizing'            - Optymalizacja BESS
    -- 'peak_shaving'           - Peak shaving analysis
    -- 'economics'              - Analiza ekonomiczna
    -- 'economics_eaas'         - EaaS monthly solver
    -- 'monte_carlo'            - Symulacja Monte Carlo
    -- 'sensitivity'            - Analiza wrażliwości
    -- 'capacity_fee'           - Opłata mocowa
    -- 'profile_analysis'       - Analiza profilu PV+BESS
    -- 'scoring'                - Wielokryterialna ocena

    -- Status
    status VARCHAR(20) DEFAULT 'pending',  -- pending, running, completed, failed

    -- Dane wejściowe i wyniki
    request_payload JSONB NOT NULL,      -- Pełne dane wejściowe (dla reprodukowalności)
    result_payload JSONB,                 -- Pełne wyniki
    error_message TEXT,                   -- Komunikat błędu (jeśli failed)

    -- Metadane serwisu
    service_name VARCHAR(100),            -- Nazwa mikroserwisu (np. 'bess-dispatch')
    service_version VARCHAR(50),          -- Wersja serwisu (np. 'v1.2.3')
    service_endpoint VARCHAR(255),        -- Endpoint API (np. '/api/bess-dispatch/sizing')

    -- Timing
    duration_ms INT,                      -- Czas obliczeń [ms]
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,

    -- Użytkownik
    created_by VARCHAR(255),              -- Kto zlecił obliczenie

    -- Metadane dodatkowe
    metadata JSONB DEFAULT '{}'::jsonb    -- Dodatkowe info (np. tags, notes)
);

CREATE INDEX idx_calculations_project ON calculations(project_id);
CREATE INDEX idx_calculations_type ON calculations(calc_type);
CREATE INDEX idx_calculations_status ON calculations(status);
CREATE INDEX idx_calculations_parent ON calculations(parent_calc_id);
CREATE INDEX idx_calculations_created ON calculations(created_at DESC);
-- Indeks GIN dla wyszukiwania w JSONB
CREATE INDEX idx_calculations_result ON calculations USING GIN (result_payload);

-- ===========================================
-- CALCULATION_METRICS (wyekstrahowane KPI dla szybkiego query)
-- ===========================================
CREATE TABLE calculation_metrics (
    id SERIAL PRIMARY KEY,
    calculation_id INT REFERENCES calculations(id) ON DELETE CASCADE,
    metric_name VARCHAR(100) NOT NULL,    -- np. 'npv', 'irr', 'payback_years', 'lcoe'
    metric_value DECIMAL(20, 6),          -- Wartość numeryczna
    metric_unit VARCHAR(50),              -- Jednostka (np. 'PLN', '%', 'years')
    UNIQUE(calculation_id, metric_name)
);

CREATE INDEX idx_calc_metrics_calc ON calculation_metrics(calculation_id);
CREATE INDEX idx_calc_metrics_name ON calculation_metrics(metric_name);
CREATE INDEX idx_calc_metrics_value ON calculation_metrics(metric_value);

-- ===========================================
-- EXPORTS (wygenerowane pliki Excel/PDF)
-- ===========================================
CREATE TABLE exports (
    id SERIAL PRIMARY KEY,
    uuid UUID DEFAULT uuid_generate_v4() UNIQUE NOT NULL,
    calculation_id INT REFERENCES calculations(id) ON DELETE CASCADE,
    project_id INT REFERENCES projects(id) ON DELETE CASCADE,

    -- Typ pliku
    file_type VARCHAR(20) NOT NULL,       -- 'xlsx', 'pdf', 'csv', 'json'
    file_name VARCHAR(255) NOT NULL,      -- Nazwa pliku z rozszerzeniem
    file_size INT,                        -- Rozmiar w bajtach

    -- Zawartość pliku
    file_data BYTEA,                      -- Plik binarny

    -- Metadane
    export_type VARCHAR(100),             -- Typ eksportu (np. 'eaas_economics', 'bess_sizing')
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_by VARCHAR(255),

    -- Opcjonalny czas wygaśnięcia (dla czyszczenia starych plików)
    expires_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_exports_calculation ON exports(calculation_id);
CREATE INDEX idx_exports_project ON exports(project_id);
CREATE INDEX idx_exports_type ON exports(file_type);
CREATE INDEX idx_exports_created ON exports(created_at DESC);

-- ===========================================
-- API_KEYS (klucze API dla zewnętrznego portalu)
-- ===========================================
CREATE TABLE api_keys (
    id SERIAL PRIMARY KEY,
    uuid UUID DEFAULT uuid_generate_v4() UNIQUE NOT NULL,
    company_id INT REFERENCES companies(id) ON DELETE CASCADE,

    -- Klucz
    key_prefix VARCHAR(10) NOT NULL,      -- Pierwsze 8 znaków klucza (do identyfikacji)
    key_hash VARCHAR(128) NOT NULL,       -- SHA-256 hash pełnego klucza
    name VARCHAR(100) NOT NULL,           -- Nazwa klucza (np. "Portal CRM")

    -- Uprawnienia
    permissions JSONB DEFAULT '["read"]'::jsonb,
    -- Dozwolone: 'read', 'write', 'delete', 'admin'

    -- Ograniczenia
    allowed_ips TEXT[],                   -- Whitelist IP (null = wszystkie)
    rate_limit_per_hour INT DEFAULT 1000, -- Limit requestów/godzinę

    -- Status
    is_active BOOLEAN DEFAULT TRUE,
    expires_at TIMESTAMP WITH TIME ZONE,  -- Opcjonalna data wygaśnięcia

    -- Statystyki użycia
    last_used_at TIMESTAMP WITH TIME ZONE,
    total_requests INT DEFAULT 0,

    -- Audit
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_by VARCHAR(255)
);

CREATE INDEX idx_api_keys_company ON api_keys(company_id);
CREATE INDEX idx_api_keys_prefix ON api_keys(key_prefix);
CREATE INDEX idx_api_keys_active ON api_keys(is_active);

-- ===========================================
-- WEBHOOKS (powiadomienia o wydarzeniach)
-- ===========================================
CREATE TABLE webhooks (
    id SERIAL PRIMARY KEY,
    uuid UUID DEFAULT uuid_generate_v4() UNIQUE NOT NULL,
    company_id INT REFERENCES companies(id) ON DELETE CASCADE,

    -- Konfiguracja
    name VARCHAR(100) NOT NULL,           -- Nazwa webhooka
    url VARCHAR(500) NOT NULL,            -- URL do wywołania
    secret VARCHAR(255),                  -- Sekret do podpisu (HMAC-SHA256)

    -- Wydarzenia
    events TEXT[] NOT NULL,               -- Lista wydarzeń do nasłuchiwania
    -- Dozwolone wydarzenia:
    -- 'calculation.completed'
    -- 'calculation.failed'
    -- 'export.created'
    -- 'project.created'
    -- 'project.updated'

    -- Status
    is_active BOOLEAN DEFAULT TRUE,

    -- Retry policy
    max_retries INT DEFAULT 3,
    retry_delay_seconds INT DEFAULT 60,

    -- Statystyki
    last_triggered_at TIMESTAMP WITH TIME ZONE,
    last_status_code INT,
    failure_count INT DEFAULT 0,
    total_triggers INT DEFAULT 0,

    -- Audit
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_webhooks_company ON webhooks(company_id);
CREATE INDEX idx_webhooks_active ON webhooks(is_active);

-- ===========================================
-- WEBHOOK_DELIVERIES (historia wywołań webhooków)
-- ===========================================
CREATE TABLE webhook_deliveries (
    id BIGSERIAL PRIMARY KEY,
    webhook_id INT REFERENCES webhooks(id) ON DELETE CASCADE,

    -- Wywołanie
    event_type VARCHAR(100) NOT NULL,
    payload JSONB NOT NULL,               -- Wysłane dane

    -- Odpowiedź
    status_code INT,
    response_body TEXT,
    response_time_ms INT,

    -- Status
    status VARCHAR(20) DEFAULT 'pending', -- pending, success, failed, retrying
    attempt_number INT DEFAULT 1,
    next_retry_at TIMESTAMP WITH TIME ZONE,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_webhook_deliveries_webhook ON webhook_deliveries(webhook_id);
CREATE INDEX idx_webhook_deliveries_status ON webhook_deliveries(status);
CREATE INDEX idx_webhook_deliveries_created ON webhook_deliveries(created_at DESC);

-- ===========================================
-- AUDIT_LOG (pełny log dostępu do API)
-- ===========================================
CREATE TABLE audit_log (
    id BIGSERIAL PRIMARY KEY,

    -- Kto
    company_id INT REFERENCES companies(id) ON DELETE SET NULL,
    api_key_id INT REFERENCES api_keys(id) ON DELETE SET NULL,
    user_info VARCHAR(255),

    -- Co
    action VARCHAR(100) NOT NULL,         -- np. 'read', 'create', 'update', 'delete'
    resource_type VARCHAR(100) NOT NULL,  -- np. 'calculation', 'project', 'export'
    resource_id VARCHAR(100),             -- UUID lub ID zasobu

    -- Szczegóły
    request_method VARCHAR(10),           -- GET, POST, PUT, DELETE
    request_path VARCHAR(500),
    request_body JSONB,

    -- Odpowiedź
    response_status INT,

    -- Kontekst
    ip_address INET,
    user_agent TEXT,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_audit_log_company ON audit_log(company_id);
CREATE INDEX idx_audit_log_action ON audit_log(action);
CREATE INDEX idx_audit_log_resource ON audit_log(resource_type, resource_id);
CREATE INDEX idx_audit_log_created ON audit_log(created_at DESC);

-- Partycjonowanie audit_log po miesiącach (opcjonalne, dla dużych wolumenów)
-- CREATE TABLE audit_log_2024_01 PARTITION OF audit_log
--     FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');

-- ===========================================
-- TRIGGER: aktualizacja updated_at dla webhooks
-- ===========================================
CREATE TRIGGER update_webhooks_updated_at BEFORE UPDATE ON webhooks
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ===========================================
-- TRIGGER: aktualizacja updated_at dla project_settings
-- ===========================================
-- Dodaj trigger dla project_settings (jeśli potrzebny)

-- ===========================================
-- FUNKCJA: Automatyczne ekstrakcja metryk z wyniku obliczenia
-- ===========================================
CREATE OR REPLACE FUNCTION extract_calculation_metrics()
RETURNS TRIGGER AS $$
DECLARE
    metric_keys TEXT[] := ARRAY[
        -- Basic economics
        'npv', 'irr', 'payback_years', 'lcoe', 'roi', 'annual_savings', 'capex', 'opex_annual',
        -- BESS
        'bess_power_kw', 'bess_energy_kwh', 'bess_cycles',
        -- PV
        'pv_capacity_kwp', 'pv_production_kwh', 'self_consumption_pct',
        -- Peak shaving
        'peak_reduction_kw', 'peak_reduction_pct',
        -- EaaS (Energy-as-a-Service) analysis
        'eaasDuration', 'analysisPeriod', 'eaasPhaseSavings', 'ownershipPhaseSavings',
        'totalSavings', 'cumulativeNPV', 'discountRate',
        -- CAPEX variant
        'capexInvestment', 'capexNPV', 'capexIRR', 'capexPayback',
        -- Common parameters
        'totalEnergyPrice', 'inflationRate'
    ];
    key TEXT;
    val DECIMAL;
BEGIN
    -- Tylko dla zakończonych obliczeń z wynikami
    IF NEW.status = 'completed' AND NEW.result_payload IS NOT NULL THEN
        -- Usuń stare metryki
        DELETE FROM calculation_metrics WHERE calculation_id = NEW.id;

        -- Ekstrakcja standardowych metryk
        FOREACH key IN ARRAY metric_keys LOOP
            -- Sprawdź czy klucz istnieje w result_payload
            IF NEW.result_payload ? key THEN
                val := (NEW.result_payload ->> key)::DECIMAL;
                IF val IS NOT NULL THEN
                    INSERT INTO calculation_metrics (calculation_id, metric_name, metric_value)
                    VALUES (NEW.id, key, val)
                    ON CONFLICT (calculation_id, metric_name)
                    DO UPDATE SET metric_value = EXCLUDED.metric_value;
                END IF;
            END IF;
        END LOOP;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_extract_metrics
    AFTER INSERT OR UPDATE OF status, result_payload ON calculations
    FOR EACH ROW
    EXECUTE FUNCTION extract_calculation_metrics();

-- ===========================================
-- WIDOKI POMOCNICZE
-- ===========================================

-- Widok: obliczenia z metrykami
CREATE VIEW v_calculations_with_metrics AS
SELECT
    c.*,
    comp.name as company_name,
    p.name as project_name,
    (SELECT jsonb_object_agg(metric_name, metric_value)
     FROM calculation_metrics cm
     WHERE cm.calculation_id = c.id) as metrics
FROM calculations c
LEFT JOIN projects p ON c.project_id = p.id
LEFT JOIN companies comp ON p.company_id = comp.id;

-- Widok: ostatnie obliczenia per projekt
CREATE VIEW v_latest_calculations AS
SELECT DISTINCT ON (project_id, calc_type)
    c.*
FROM calculations c
WHERE c.status = 'completed'
ORDER BY project_id, calc_type, created_at DESC;

-- Widok: statystyki API keys
CREATE VIEW v_api_key_stats AS
SELECT
    ak.*,
    c.name as company_name,
    (SELECT COUNT(*) FROM audit_log al WHERE al.api_key_id = ak.id) as total_audit_entries,
    (SELECT MAX(created_at) FROM audit_log al WHERE al.api_key_id = ak.id) as last_activity
FROM api_keys ak
LEFT JOIN companies c ON ak.company_id = c.id;

-- ===========================================
-- ECONOMICS MODEL TYPE ENUM
-- ===========================================
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'economics_model_type') THEN
        CREATE TYPE economics_model_type AS ENUM ('CAPEX_CLIENT', 'EAAS_CLIENT', 'EAAS_INVESTOR');
    END IF;
END$$;

-- ===========================================
-- PROJECT_ECONOMICS_SNAPSHOT (investor-ready economics v2)
-- ===========================================
CREATE TABLE IF NOT EXISTS project_economics_snapshot (
    id SERIAL PRIMARY KEY,
    uuid UUID DEFAULT uuid_generate_v4() UNIQUE NOT NULL,
    project_id INT REFERENCES projects(id) ON DELETE CASCADE NOT NULL,

    -- Snapshot metadata
    snapshot_version INT DEFAULT 1,
    production_scenario VARCHAR(10) NOT NULL DEFAULT 'P50',  -- P50, P75, P90
    variant_key VARCHAR(50) NOT NULL,  -- e.g., '500_balanced', '750_max_savings'

    -- Installation configuration
    pv_capacity_kwp DECIMAL(12, 3) NOT NULL,
    pv_type VARCHAR(50) NOT NULL DEFAULT 'ground_s',  -- ground_s, ground_ew, roof_ew, carport
    bess_power_kw DECIMAL(12, 3) DEFAULT 0,
    bess_energy_kwh DECIMAL(12, 3) DEFAULT 0,

    -- Analysis parameters
    analysis_period_years INT NOT NULL DEFAULT 25,
    discount_rate_pct DECIMAL(6, 4) NOT NULL,  -- e.g., 7.00 for 7%
    inflation_rate_pct DECIMAL(6, 4) DEFAULT 2.50,

    -- CAPEX Client (client buying the installation)
    capex_client_npv25 DECIMAL(15, 2),
    capex_client_irr DECIMAL(8, 4),  -- e.g., 0.1234 for 12.34%
    capex_client_irr_mode VARCHAR(10) DEFAULT 'real',  -- 'real' or 'nominal'
    capex_client_simple_payback DECIMAL(6, 2),  -- years
    capex_client_discounted_payback DECIMAL(6, 2),  -- years
    capex_client_capex0_pln DECIMAL(15, 2) NOT NULL,

    -- CAPEX Deal (installer margin)
    capex_deal_sell_price_pln DECIMAL(15, 2),
    capex_deal_direct_cost_pln DECIMAL(15, 2),
    capex_deal_gross_margin_pct DECIMAL(6, 2),
    capex_deal_gross_margin_pln DECIMAL(15, 2),

    -- EaaS Client (client using EaaS model)
    eaas_client_npv25 DECIMAL(15, 2),
    eaas_client_duration_years INT DEFAULT 10,
    eaas_client_subscription_annual DECIMAL(15, 2),

    -- EaaS Investor (investor perspective)
    eaas_investor_npv25 DECIMAL(15, 2),
    eaas_investor_irr DECIMAL(8, 4),
    eaas_investor_capex0_pln DECIMAL(15, 2),
    eaas_investor_revenue_annual DECIMAL(15, 2),
    eaas_investor_opex_annual DECIMAL(15, 2),

    -- Full payload (JSON backup)
    full_payload JSONB,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_by VARCHAR(255)
);

CREATE INDEX idx_econ_snapshot_project ON project_economics_snapshot(project_id);
CREATE INDEX idx_econ_snapshot_variant ON project_economics_snapshot(variant_key);
CREATE INDEX idx_econ_snapshot_scenario ON project_economics_snapshot(production_scenario);
CREATE INDEX idx_econ_snapshot_created ON project_economics_snapshot(created_at DESC);

-- ===========================================
-- PROJECT_ECONOMICS_CASHFLOW_YEARLY (yearly cashflows)
-- ===========================================
CREATE TABLE IF NOT EXISTS project_economics_cashflow_yearly (
    id BIGSERIAL PRIMARY KEY,
    snapshot_id INT REFERENCES project_economics_snapshot(id) ON DELETE CASCADE NOT NULL,
    model_type economics_model_type NOT NULL,  -- Uses ENUM: CAPEX_CLIENT, EAAS_CLIENT, EAAS_INVESTOR

    year INT NOT NULL,  -- 0 = initial investment, 1-25 = operating years

    -- Cash flow components
    capex_pln DECIMAL(15, 2) DEFAULT 0,
    revenue_pln DECIMAL(15, 2) DEFAULT 0,
    opex_pln DECIMAL(15, 2) DEFAULT 0,
    net_cashflow_pln DECIMAL(15, 2) NOT NULL,
    cumulative_cashflow_pln DECIMAL(15, 2),
    discounted_cashflow_pln DECIMAL(15, 2),
    cumulative_discounted_pln DECIMAL(15, 2),

    -- Production data (for reference)
    production_kwh DECIMAL(15, 2),
    self_consumed_kwh DECIMAL(15, 2),
    pv_degradation_pct DECIMAL(6, 2),
    bess_degradation_pct DECIMAL(6, 2),

    UNIQUE(snapshot_id, model_type, year)
);

CREATE INDEX idx_econ_cashflow_snapshot ON project_economics_cashflow_yearly(snapshot_id);
CREATE INDEX idx_econ_cashflow_model ON project_economics_cashflow_yearly(model_type);
CREATE INDEX idx_econ_cashflow_year ON project_economics_cashflow_yearly(year);

-- ===========================================
-- GRANTS (uprawnienia)
-- ===========================================
-- Uprawnienia dla pvanalyzer (użytkownik z docker-compose)
-- Nie potrzebne bo pvanalyzer jest właścicielem bazy, ale dla kompatybilności:
DO $$
BEGIN
    -- Grants are automatic for database owner (pvanalyzer)
    RAISE NOTICE 'Database initialized successfully for pvanalyzer user';
END$$;
