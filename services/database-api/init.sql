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
-- GRANTS (uprawnienia)
-- ===========================================
-- W produkcji dostosuj uprawnienia do potrzeb
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO pv_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO pv_user;
