"""
Database API - SQLAlchemy Models
"""

from sqlalchemy import (
    Column, Integer, BigInteger, String, Text, Boolean,
    DateTime, Numeric, ForeignKey, JSON, UniqueConstraint,
    LargeBinary, ARRAY, Enum as SQLEnum
)
from sqlalchemy.dialects.postgresql import UUID, JSONB, ENUM as PG_ENUM
import enum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid

Base = declarative_base()


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True)
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False)
    name = Column(String(255), nullable=False)
    nip = Column(String(20))
    address = Column(Text)
    contact_email = Column(String(255))
    contact_phone = Column(String(50))
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    projects = relationship("Project", back_populates="company", cascade="all, delete-orphan")
    api_keys = relationship("ApiKey", back_populates="company", cascade="all, delete-orphan")
    webhooks = relationship("Webhook", back_populates="company", cascade="all, delete-orphan")
    audit_entries = relationship("AuditLog", back_populates="company")


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True)
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"))
    name = Column(String(255), nullable=False)
    description = Column(Text)
    location_name = Column(String(255))
    latitude = Column(Numeric(10, 7))
    longitude = Column(Numeric(10, 7))
    analysis_mode = Column(String(50), default="pv_bess")
    status = Column(String(50), default="draft")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    company = relationship("Company", back_populates="projects")
    profiles = relationship("EnergyProfile", back_populates="project", cascade="all, delete-orphan")
    analyses = relationship("AnalysisResult", back_populates="project", cascade="all, delete-orphan")
    settings_versions = relationship("ProjectSettings", back_populates="project", cascade="all, delete-orphan")
    calculations = relationship("Calculation", back_populates="project", cascade="all, delete-orphan")
    exports = relationship("Export", back_populates="project", cascade="all, delete-orphan")


class EnergyProfile(Base):
    __tablename__ = "energy_profiles"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"))
    profile_type = Column(String(50), nullable=False)  # consumption, pv_generation, net_load
    time_resolution = Column(String(20), nullable=False, default="hourly")
    year = Column(Integer, nullable=False)
    source = Column(String(100))
    filename = Column(String(255))
    total_kwh = Column(Numeric(15, 3))
    peak_kw = Column(Numeric(12, 3))
    data_points = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    project = relationship("Project", back_populates="profiles")
    data = relationship("ProfileData", back_populates="profile", cascade="all, delete-orphan")


class ProfileData(Base):
    __tablename__ = "profile_data"

    id = Column(BigInteger, primary_key=True)
    profile_id = Column(Integer, ForeignKey("energy_profiles.id", ondelete="CASCADE"))
    timestamp = Column(DateTime(timezone=True), nullable=False)
    value_kw = Column(Numeric(12, 4), nullable=False)

    __table_args__ = (
        UniqueConstraint('profile_id', 'timestamp', name='uq_profile_timestamp'),
    )

    # Relationships
    profile = relationship("EnergyProfile", back_populates="data")


class PriceScenario(Base):
    __tablename__ = "price_scenarios"

    id = Column(Integer, primary_key=True)
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    scenario_type = Column(String(50), nullable=False)  # historical, forecast, custom
    source = Column(String(100))
    year = Column(Integer)
    currency = Column(String(10), default="PLN")
    unit = Column(String(20), default="PLN/MWh")
    avg_price = Column(Numeric(10, 2))
    min_price = Column(Numeric(10, 2))
    max_price = Column(Numeric(10, 2))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    data = relationship("PriceData", back_populates="scenario", cascade="all, delete-orphan")
    analyses = relationship("AnalysisResult", back_populates="price_scenario")


class PriceData(Base):
    __tablename__ = "price_data"

    id = Column(BigInteger, primary_key=True)
    scenario_id = Column(Integer, ForeignKey("price_scenarios.id", ondelete="CASCADE"))
    timestamp = Column(DateTime(timezone=True), nullable=False)
    price_pln_mwh = Column(Numeric(10, 4), nullable=False)

    __table_args__ = (
        UniqueConstraint('scenario_id', 'timestamp', name='uq_scenario_timestamp'),
    )

    # Relationships
    scenario = relationship("PriceScenario", back_populates="data")


class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id = Column(Integer, primary_key=True)
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"))
    price_scenario_id = Column(Integer, ForeignKey("price_scenarios.id", ondelete="SET NULL"), nullable=True)
    analysis_type = Column(String(50), nullable=False)
    input_params = Column(JSONB, nullable=False)
    results = Column(JSONB, nullable=False)
    status = Column(String(50), default="completed")
    compute_time_ms = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    project = relationship("Project", back_populates="analyses")
    price_scenario = relationship("PriceScenario", back_populates="analyses")


class AnalysisMode(Base):
    __tablename__ = "analysis_modes"

    id = Column(Integer, primary_key=True)
    code = Column(String(50), unique=True, nullable=False)
    name_pl = Column(String(100), nullable=False)
    name_en = Column(String(100), nullable=False)
    description_pl = Column(Text)
    icon = Column(String(50))
    requires_pv = Column(Boolean, default=False)
    requires_bess = Column(Boolean, default=False)
    requires_load = Column(Boolean, default=True)
    requires_prices = Column(Boolean, default=False)
    display_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)


# ===========================================
# PROJECT SETTINGS (wersjonowane ustawienia)
# ===========================================

class ProjectSettings(Base):
    __tablename__ = "project_settings"

    id = Column(Integer, primary_key=True)
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"))
    version = Column(Integer, default=1)
    settings = Column(JSONB, nullable=False)  # Pełne ustawienia
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    created_by = Column(String(255))
    description = Column(String(500))

    # Relationships
    project = relationship("Project", back_populates="settings_versions")


# ===========================================
# CALCULATIONS (wszystkie obliczenia)
# ===========================================

class Calculation(Base):
    __tablename__ = "calculations"

    id = Column(Integer, primary_key=True)
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"))
    parent_calc_id = Column(Integer, ForeignKey("calculations.id", ondelete="SET NULL"), nullable=True)

    # Typ obliczenia
    calc_type = Column(String(50), nullable=False)
    # Dozwolone: consumption_analysis, pv_sizing, pv_production, bess_dispatch,
    #            bess_sizing, peak_shaving, economics, economics_eaas,
    #            monte_carlo, sensitivity, capacity_fee, profile_analysis, scoring

    # Status
    status = Column(String(20), default="pending")  # pending, running, completed, failed

    # Dane
    request_payload = Column(JSONB, nullable=False)
    result_payload = Column(JSONB)
    error_message = Column(Text)

    # Metadane serwisu
    service_name = Column(String(100))
    service_version = Column(String(50))
    service_endpoint = Column(String(255))

    # Timing
    duration_ms = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))

    # Użytkownik
    created_by = Column(String(255))

    # Metadane
    calc_metadata = Column("metadata", JSONB, default={})

    # Relationships
    project = relationship("Project", back_populates="calculations")
    parent = relationship("Calculation", remote_side=[id], backref="children")
    metrics = relationship("CalculationMetric", back_populates="calculation", cascade="all, delete-orphan")
    exports = relationship("Export", back_populates="calculation", cascade="all, delete-orphan")


class CalculationMetric(Base):
    __tablename__ = "calculation_metrics"

    id = Column(Integer, primary_key=True)
    calculation_id = Column(Integer, ForeignKey("calculations.id", ondelete="CASCADE"))
    metric_name = Column(String(100), nullable=False)
    metric_value = Column(Numeric(20, 6))
    metric_unit = Column(String(50))

    __table_args__ = (
        UniqueConstraint('calculation_id', 'metric_name', name='uq_calc_metric'),
    )

    # Relationships
    calculation = relationship("Calculation", back_populates="metrics")


# ===========================================
# EXPORTS (pliki Excel/PDF)
# ===========================================

class Export(Base):
    __tablename__ = "exports"

    id = Column(Integer, primary_key=True)
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False)
    calculation_id = Column(Integer, ForeignKey("calculations.id", ondelete="CASCADE"), nullable=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"))

    # Plik
    file_type = Column(String(20), nullable=False)  # xlsx, pdf, csv, json
    file_name = Column(String(255), nullable=False)
    file_size = Column(Integer)
    file_data = Column(LargeBinary)  # BYTEA

    # Metadane
    export_type = Column(String(100))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    created_by = Column(String(255))
    expires_at = Column(DateTime(timezone=True))

    # Relationships
    calculation = relationship("Calculation", back_populates="exports")
    project = relationship("Project", back_populates="exports")


# ===========================================
# API KEYS (dla zewnętrznego portalu)
# ===========================================

class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True)
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"))

    # Klucz
    key_prefix = Column(String(10), nullable=False)
    key_hash = Column(String(128), nullable=False)
    name = Column(String(100), nullable=False)

    # Uprawnienia
    permissions = Column(JSONB, default=["read"])

    # Ograniczenia
    allowed_ips = Column(ARRAY(Text))
    rate_limit_per_hour = Column(Integer, default=1000)

    # Status
    is_active = Column(Boolean, default=True)
    expires_at = Column(DateTime(timezone=True))

    # Statystyki
    last_used_at = Column(DateTime(timezone=True))
    total_requests = Column(Integer, default=0)

    # Audit
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    created_by = Column(String(255))

    # Relationships
    company = relationship("Company", back_populates="api_keys")
    audit_entries = relationship("AuditLog", back_populates="api_key")


# ===========================================
# WEBHOOKS
# ===========================================

class Webhook(Base):
    __tablename__ = "webhooks"

    id = Column(Integer, primary_key=True)
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"))

    # Konfiguracja
    name = Column(String(100), nullable=False)
    url = Column(String(500), nullable=False)
    secret = Column(String(255))

    # Wydarzenia
    events = Column(ARRAY(Text), nullable=False)

    # Status
    is_active = Column(Boolean, default=True)

    # Retry
    max_retries = Column(Integer, default=3)
    retry_delay_seconds = Column(Integer, default=60)

    # Statystyki
    last_triggered_at = Column(DateTime(timezone=True))
    last_status_code = Column(Integer)
    failure_count = Column(Integer, default=0)
    total_triggers = Column(Integer, default=0)

    # Audit
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    company = relationship("Company", back_populates="webhooks")
    deliveries = relationship("WebhookDelivery", back_populates="webhook", cascade="all, delete-orphan")


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    id = Column(BigInteger, primary_key=True)
    webhook_id = Column(Integer, ForeignKey("webhooks.id", ondelete="CASCADE"))

    # Wywołanie
    event_type = Column(String(100), nullable=False)
    payload = Column(JSONB, nullable=False)

    # Odpowiedź
    status_code = Column(Integer)
    response_body = Column(Text)
    response_time_ms = Column(Integer)

    # Status
    status = Column(String(20), default="pending")
    attempt_number = Column(Integer, default=1)
    next_retry_at = Column(DateTime(timezone=True))

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    webhook = relationship("Webhook", back_populates="deliveries")


# ===========================================
# AUDIT LOG
# ===========================================

class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(BigInteger, primary_key=True)

    # Kto
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="SET NULL"))
    api_key_id = Column(Integer, ForeignKey("api_keys.id", ondelete="SET NULL"))
    user_info = Column(String(255))

    # Co
    action = Column(String(100), nullable=False)
    resource_type = Column(String(100), nullable=False)
    resource_id = Column(String(100))

    # Szczegóły
    request_method = Column(String(10))
    request_path = Column(String(500))
    request_body = Column(JSONB)

    # Odpowiedź
    response_status = Column(Integer)

    # Kontekst
    ip_address = Column(String(45))  # IPv6 compatible
    user_agent = Column(Text)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    company = relationship("Company", back_populates="audit_entries")
    api_key = relationship("ApiKey", back_populates="audit_entries")


# ===========================================
# PROJECT ECONOMICS SNAPSHOT (investor-ready v2)
# ===========================================

class ProjectEconomicsSnapshot(Base):
    __tablename__ = "project_economics_snapshot"

    id = Column(Integer, primary_key=True)
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)

    # Snapshot metadata
    snapshot_version = Column(Integer, default=1)
    production_scenario = Column(String(10), nullable=False, default="P50")  # P50, P75, P90
    variant_key = Column(String(50), nullable=False)

    # Installation configuration
    pv_capacity_kwp = Column(Numeric(12, 3), nullable=False)
    pv_type = Column(String(50), nullable=False, default="ground_s")
    bess_power_kw = Column(Numeric(12, 3), default=0)
    bess_energy_kwh = Column(Numeric(12, 3), default=0)

    # Analysis parameters
    analysis_period_years = Column(Integer, nullable=False, default=25)
    discount_rate_pct = Column(Numeric(6, 4), nullable=False)
    inflation_rate_pct = Column(Numeric(6, 4), default=2.50)

    # CAPEX Client
    capex_client_npv25 = Column(Numeric(15, 2))
    capex_client_irr = Column(Numeric(8, 4))
    capex_client_irr_mode = Column(String(10), default="real")
    capex_client_simple_payback = Column(Numeric(6, 2))
    capex_client_discounted_payback = Column(Numeric(6, 2))
    capex_client_capex0_pln = Column(Numeric(15, 2), nullable=False)

    # CAPEX Deal (margin)
    capex_deal_sell_price_pln = Column(Numeric(15, 2))
    capex_deal_direct_cost_pln = Column(Numeric(15, 2))
    capex_deal_gross_margin_pct = Column(Numeric(6, 2))
    capex_deal_gross_margin_pln = Column(Numeric(15, 2))

    # EaaS Client
    eaas_client_npv25 = Column(Numeric(15, 2))
    eaas_client_duration_years = Column(Integer, default=10)
    eaas_client_subscription_annual = Column(Numeric(15, 2))

    # EaaS Investor
    eaas_investor_npv25 = Column(Numeric(15, 2))
    eaas_investor_irr = Column(Numeric(8, 4))
    eaas_investor_capex0_pln = Column(Numeric(15, 2))
    eaas_investor_revenue_annual = Column(Numeric(15, 2))
    eaas_investor_opex_annual = Column(Numeric(15, 2))

    # Full payload backup
    full_payload = Column(JSONB)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    created_by = Column(String(255))

    # Relationships
    project = relationship("Project", backref="economics_snapshots")
    cashflows = relationship("ProjectEconomicsCashflowYearly", back_populates="snapshot", cascade="all, delete-orphan")


# Enum for economics model types
class EconomicsModelTypeEnum(enum.Enum):
    CAPEX_CLIENT = "CAPEX_CLIENT"
    EAAS_CLIENT = "EAAS_CLIENT"
    EAAS_INVESTOR = "EAAS_INVESTOR"


# PostgreSQL ENUM type definition (must match init.sql)
economics_model_type_enum = PG_ENUM(
    'CAPEX_CLIENT', 'EAAS_CLIENT', 'EAAS_INVESTOR',
    name='economics_model_type',
    create_type=False  # Type already created in init.sql
)


class ProjectEconomicsCashflowYearly(Base):
    __tablename__ = "project_economics_cashflow_yearly"

    id = Column(BigInteger, primary_key=True)
    snapshot_id = Column(Integer, ForeignKey("project_economics_snapshot.id", ondelete="CASCADE"), nullable=False)
    model_type = Column(economics_model_type_enum, nullable=False)  # Uses ENUM: CAPEX_CLIENT, EAAS_CLIENT, EAAS_INVESTOR

    year = Column(Integer, nullable=False)  # 0 = initial investment

    # Cash flow components
    capex_pln = Column(Numeric(15, 2), default=0)
    revenue_pln = Column(Numeric(15, 2), default=0)
    opex_pln = Column(Numeric(15, 2), default=0)
    net_cashflow_pln = Column(Numeric(15, 2), nullable=False)
    cumulative_cashflow_pln = Column(Numeric(15, 2))
    discounted_cashflow_pln = Column(Numeric(15, 2))
    cumulative_discounted_pln = Column(Numeric(15, 2))

    # Production data
    production_kwh = Column(Numeric(15, 2))
    self_consumed_kwh = Column(Numeric(15, 2))
    pv_degradation_pct = Column(Numeric(6, 2))
    bess_degradation_pct = Column(Numeric(6, 2))

    __table_args__ = (
        UniqueConstraint('snapshot_id', 'model_type', 'year', name='uq_snapshot_model_year'),
    )

    # Relationships
    snapshot = relationship("ProjectEconomicsSnapshot", back_populates="cashflows")
