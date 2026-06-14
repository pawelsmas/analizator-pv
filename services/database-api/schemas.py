"""
Database API - Pydantic Schemas
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Any
from datetime import datetime
from uuid import UUID
from enum import Enum


# ===========================================
# Enums
# ===========================================

class AnalysisModeEnum(str, Enum):
    PV_SOLO = "pv_solo"
    PV_BESS = "pv_bess"
    BESS_SOLO = "bess_solo"
    PEAK_SHAVING = "peak_shaving"
    ARBITRAGE = "arbitrage"


class ProjectStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class ProfileType(str, Enum):
    CONSUMPTION = "consumption"
    PV_GENERATION = "pv_generation"
    NET_LOAD = "net_load"


class TimeResolution(str, Enum):
    HOURLY = "hourly"
    QUARTER_HOURLY = "15min"


class ScenarioType(str, Enum):
    HISTORICAL = "historical"
    FORECAST = "forecast"
    CUSTOM = "custom"


# ===========================================
# Company Schemas
# ===========================================

class CompanyBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    nip: Optional[str] = None
    address: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    notes: Optional[str] = None


class CompanyCreate(CompanyBase):
    pass


class CompanyUpdate(BaseModel):
    name: Optional[str] = None
    nip: Optional[str] = None
    address: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    notes: Optional[str] = None


class CompanyResponse(CompanyBase):
    id: int
    uuid: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CompanyWithProjects(CompanyResponse):
    projects: List["ProjectResponse"] = []


# ===========================================
# Project Schemas
# ===========================================

class ProjectBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    location_name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    analysis_mode: AnalysisModeEnum = AnalysisModeEnum.PV_BESS
    status: ProjectStatus = ProjectStatus.DRAFT


class ProjectCreate(ProjectBase):
    company_id: int


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    location_name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    analysis_mode: Optional[AnalysisModeEnum] = None
    status: Optional[ProjectStatus] = None


class ProjectResponse(ProjectBase):
    id: int
    uuid: UUID
    company_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ProjectWithCompany(ProjectResponse):
    company_name: Optional[str] = None


# ===========================================
# Energy Profile Schemas
# ===========================================

class EnergyProfileBase(BaseModel):
    profile_type: ProfileType
    time_resolution: TimeResolution = TimeResolution.HOURLY
    year: int = Field(..., ge=2000, le=2050)
    source: Optional[str] = None
    filename: Optional[str] = None


class EnergyProfileCreate(EnergyProfileBase):
    project_id: int
    data: List[float] = Field(..., description="Array of kW values (8760 for hourly, 35040 for 15-min)")


class EnergyProfileResponse(EnergyProfileBase):
    id: int
    project_id: int
    total_kwh: Optional[float] = None
    peak_kw: Optional[float] = None
    data_points: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ProfileDataResponse(BaseModel):
    timestamp: datetime
    value_kw: float

    class Config:
        from_attributes = True


# ===========================================
# Price Scenario Schemas
# ===========================================

class PriceScenarioBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    scenario_type: ScenarioType
    source: Optional[str] = None
    year: Optional[int] = None
    currency: str = "PLN"
    unit: str = "PLN/MWh"


class PriceScenarioCreate(PriceScenarioBase):
    data: List[float] = Field(..., description="Array of PLN/MWh prices (8760 hourly values)")


class PriceScenarioResponse(PriceScenarioBase):
    id: int
    uuid: UUID
    avg_price: Optional[float] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ===========================================
# Analysis Schemas
# ===========================================

class AnalysisResultBase(BaseModel):
    analysis_type: str
    input_params: dict
    results: dict
    status: str = "completed"
    compute_time_ms: Optional[int] = None


class AnalysisResultCreate(AnalysisResultBase):
    project_id: int
    price_scenario_id: Optional[int] = None


class AnalysisResultResponse(AnalysisResultBase):
    id: int
    uuid: UUID
    project_id: int
    price_scenario_id: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ===========================================
# Analysis Mode Schema
# ===========================================

class AnalysisModeResponse(BaseModel):
    id: int
    code: str
    name_pl: str
    name_en: str
    description_pl: Optional[str] = None
    icon: Optional[str] = None
    requires_pv: bool
    requires_bess: bool
    requires_load: bool
    requires_prices: bool
    display_order: int
    is_active: bool

    class Config:
        from_attributes = True


# ===========================================
# Bulk Import Schemas
# ===========================================

class BulkProfileImport(BaseModel):
    project_id: int
    profile_type: ProfileType
    time_resolution: TimeResolution
    year: int
    source: str = "upload"
    filename: Optional[str] = None
    timestamps: List[datetime]
    values: List[float]


class BulkPriceImport(BaseModel):
    name: str
    scenario_type: ScenarioType
    source: str = "csv_import"
    year: int
    timestamps: List[datetime]
    prices: List[float]


# ===========================================
# Stats / Summary Schemas
# ===========================================

class DatabaseStats(BaseModel):
    companies_count: int
    projects_count: int
    profiles_count: int
    price_scenarios_count: int
    analyses_count: int
    total_profile_data_points: int
    total_price_data_points: int


class ProjectSummary(BaseModel):
    project: ProjectResponse
    company_name: str
    profiles_count: int
    analyses_count: int
    has_consumption: bool
    has_pv: bool
    has_prices: bool


# ===========================================
# Project Settings Schemas
# ===========================================

class ProjectSettingsCreate(BaseModel):
    settings: dict
    created_by: Optional[str] = None
    description: Optional[str] = None


class ProjectSettingsResponse(BaseModel):
    id: int
    uuid: UUID
    project_id: int
    version: int
    settings: dict
    created_at: datetime
    created_by: Optional[str] = None
    description: Optional[str] = None

    class Config:
        from_attributes = True


# ===========================================
# Calculation Schemas
# ===========================================

class CalculationCreate(BaseModel):
    project_id: int
    calc_type: str
    request_payload: dict
    parent_calc_id: Optional[int] = None
    created_by: Optional[str] = None
    service_name: Optional[str] = None
    service_version: Optional[str] = None
    service_endpoint: Optional[str] = None
    calc_metadata: Optional[dict] = None


class CalculationUpdate(BaseModel):
    status: Optional[str] = None
    result_payload: Optional[dict] = None
    error_message: Optional[str] = None
    service_name: Optional[str] = None
    service_version: Optional[str] = None
    service_endpoint: Optional[str] = None
    duration_ms: Optional[int] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class CalculationMetricResponse(BaseModel):
    metric_name: str
    metric_value: Optional[float] = None
    metric_unit: Optional[str] = None

    class Config:
        from_attributes = True


class CalculationResponse(BaseModel):
    id: int
    uuid: UUID
    project_id: int
    parent_calc_id: Optional[int] = None
    calc_type: str
    status: str
    request_payload: dict
    result_payload: Optional[dict] = None
    error_message: Optional[str] = None
    service_name: Optional[str] = None
    service_version: Optional[str] = None
    service_endpoint: Optional[str] = None
    duration_ms: Optional[int] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_by: Optional[str] = None
    calc_metadata: Optional[dict] = None

    class Config:
        from_attributes = True


class CalculationWithMetrics(CalculationResponse):
    metrics: List[CalculationMetricResponse] = []


# ===========================================
# Export Schemas
# ===========================================

class ExportCreate(BaseModel):
    file_type: str
    file_name: str
    file_data: bytes
    export_type: Optional[str] = None
    calculation_id: Optional[int] = None
    created_by: Optional[str] = None
    expires_at: Optional[datetime] = None


class ExportResponse(BaseModel):
    id: int
    uuid: UUID
    project_id: int
    calculation_id: Optional[int] = None
    file_type: str
    file_name: str
    file_size: Optional[int] = None
    export_type: Optional[str] = None
    created_at: datetime
    created_by: Optional[str] = None
    expires_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ===========================================
# API Key Schemas
# ===========================================

class ApiKeyCreate(BaseModel):
    name: str
    permissions: Optional[List[str]] = ["read"]
    allowed_ips: Optional[List[str]] = None
    rate_limit_per_hour: Optional[int] = 1000
    expires_at: Optional[datetime] = None
    created_by: Optional[str] = None


class ApiKeyResponse(BaseModel):
    id: int
    uuid: UUID
    company_id: int
    key_prefix: str
    name: str
    permissions: List[str]
    allowed_ips: Optional[List[str]] = None
    rate_limit_per_hour: int
    is_active: bool
    expires_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    total_requests: int
    created_at: datetime
    created_by: Optional[str] = None

    class Config:
        from_attributes = True


class ApiKeyWithSecret(ApiKeyResponse):
    secret_key: str  # Only returned once during creation


# ===========================================
# Webhook Schemas
# ===========================================

class WebhookCreate(BaseModel):
    name: str
    url: str
    events: List[str]
    secret: Optional[str] = None
    max_retries: Optional[int] = 3
    retry_delay_seconds: Optional[int] = 60


class WebhookUpdate(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    events: Optional[List[str]] = None
    secret: Optional[str] = None
    is_active: Optional[bool] = None
    max_retries: Optional[int] = None
    retry_delay_seconds: Optional[int] = None


class WebhookResponse(BaseModel):
    id: int
    uuid: UUID
    company_id: int
    name: str
    url: str
    events: List[str]
    is_active: bool
    max_retries: int
    retry_delay_seconds: int
    last_triggered_at: Optional[datetime] = None
    last_status_code: Optional[int] = None
    failure_count: int
    total_triggers: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class WebhookDeliveryResponse(BaseModel):
    id: int
    webhook_id: int
    event_type: str
    payload: dict
    status_code: Optional[int] = None
    response_body: Optional[str] = None
    response_time_ms: Optional[int] = None
    status: str
    attempt_number: int
    next_retry_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ===========================================
# Audit Log Schemas
# ===========================================

class AuditLogResponse(BaseModel):
    id: int
    company_id: Optional[int] = None
    api_key_id: Optional[int] = None
    user_info: Optional[str] = None
    action: str
    resource_type: str
    resource_id: Optional[str] = None
    request_method: Optional[str] = None
    request_path: Optional[str] = None
    request_body: Optional[dict] = None
    response_status: Optional[int] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ===========================================
# External Portal Schemas
# ===========================================

class ExternalProjectResponse(BaseModel):
    """Simplified project response for external portal"""
    id: int
    uuid: UUID
    name: str
    city: Optional[str] = None
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class ExternalCalculationResponse(BaseModel):
    """Simplified calculation response for external portal"""
    id: int
    uuid: UUID
    calc_type: str
    status: str
    created_at: datetime
    completed_at: Optional[datetime] = None
    result_summary: Optional[dict] = None

    class Config:
        from_attributes = True


class ExternalCalculationListResponse(BaseModel):
    """List of calculations for external portal"""
    calculations: List[ExternalCalculationResponse]
    total: int
    page: int
    page_size: int


# ===========================================
# Economics Snapshot Schemas
# ===========================================

class EconomicsCashflowYearlyCreate(BaseModel):
    """Create schema for yearly cashflow data"""
    model_type: str  # CAPEX_CLIENT, EAAS_CLIENT, EAAS_INVESTOR
    year: int
    capex_pln: Optional[float] = 0
    revenue_pln: Optional[float] = 0
    opex_pln: Optional[float] = 0
    net_cashflow_pln: float
    cumulative_cashflow_pln: Optional[float] = None
    discounted_cashflow_pln: Optional[float] = None
    cumulative_discounted_pln: Optional[float] = None
    production_kwh: Optional[float] = None
    self_consumed_kwh: Optional[float] = None
    pv_degradation_pct: Optional[float] = None
    bess_degradation_pct: Optional[float] = None


class EconomicsCashflowYearlyResponse(BaseModel):
    """Response schema for yearly cashflow data"""
    id: int
    snapshot_id: int
    model_type: str
    year: int
    capex_pln: Optional[float] = None
    revenue_pln: Optional[float] = None
    opex_pln: Optional[float] = None
    net_cashflow_pln: float
    cumulative_cashflow_pln: Optional[float] = None
    discounted_cashflow_pln: Optional[float] = None
    cumulative_discounted_pln: Optional[float] = None
    production_kwh: Optional[float] = None
    self_consumed_kwh: Optional[float] = None
    pv_degradation_pct: Optional[float] = None
    bess_degradation_pct: Optional[float] = None

    class Config:
        from_attributes = True


class EconomicsSnapshotCreate(BaseModel):
    """Create schema for economics snapshot (investor-ready v2)"""
    production_scenario: str = "P50"  # P50, P75, P90
    variant_key: str

    # Installation configuration
    pv_capacity_kwp: float
    pv_type: str = "ground_s"
    bess_power_kw: Optional[float] = 0
    bess_energy_kwh: Optional[float] = 0

    # Analysis parameters
    analysis_period_years: int = 25
    discount_rate_pct: float
    inflation_rate_pct: Optional[float] = 2.50

    # CAPEX Client
    capex_client_npv25: Optional[float] = None
    capex_client_irr: Optional[float] = None
    capex_client_irr_mode: str = "real"
    capex_client_simple_payback: Optional[float] = None
    capex_client_discounted_payback: Optional[float] = None
    capex_client_capex0_pln: float

    # CAPEX Deal (margin)
    capex_deal_sell_price_pln: Optional[float] = None
    capex_deal_direct_cost_pln: Optional[float] = None
    capex_deal_gross_margin_pct: Optional[float] = None
    capex_deal_gross_margin_pln: Optional[float] = None

    # EaaS Client
    eaas_client_npv25: Optional[float] = None
    eaas_client_duration_years: int = 10
    eaas_client_subscription_annual: Optional[float] = None

    # EaaS Investor
    eaas_investor_npv25: Optional[float] = None
    eaas_investor_irr: Optional[float] = None
    eaas_investor_capex0_pln: Optional[float] = None
    eaas_investor_revenue_annual: Optional[float] = None
    eaas_investor_opex_annual: Optional[float] = None

    # Full payload backup
    full_payload: Optional[dict] = None

    # User info
    created_by: Optional[str] = None

    # Cashflows data
    cashflows: Optional[List[EconomicsCashflowYearlyCreate]] = None


class EconomicsSnapshotResponse(BaseModel):
    """Response schema for economics snapshot"""
    id: int
    uuid: UUID
    project_id: int
    snapshot_version: int
    production_scenario: str
    variant_key: str

    # Installation configuration
    pv_capacity_kwp: float
    pv_type: str
    bess_power_kw: Optional[float] = None
    bess_energy_kwh: Optional[float] = None

    # Analysis parameters
    analysis_period_years: int
    discount_rate_pct: float
    inflation_rate_pct: Optional[float] = None

    # CAPEX Client
    capex_client_npv25: Optional[float] = None
    capex_client_irr: Optional[float] = None
    capex_client_irr_mode: Optional[str] = None
    capex_client_simple_payback: Optional[float] = None
    capex_client_discounted_payback: Optional[float] = None
    capex_client_capex0_pln: float

    # CAPEX Deal
    capex_deal_sell_price_pln: Optional[float] = None
    capex_deal_direct_cost_pln: Optional[float] = None
    capex_deal_gross_margin_pct: Optional[float] = None
    capex_deal_gross_margin_pln: Optional[float] = None

    # EaaS Client
    eaas_client_npv25: Optional[float] = None
    eaas_client_duration_years: Optional[int] = None
    eaas_client_subscription_annual: Optional[float] = None

    # EaaS Investor
    eaas_investor_npv25: Optional[float] = None
    eaas_investor_irr: Optional[float] = None
    eaas_investor_capex0_pln: Optional[float] = None
    eaas_investor_revenue_annual: Optional[float] = None
    eaas_investor_opex_annual: Optional[float] = None

    # Full payload
    full_payload: Optional[dict] = None

    # Timestamps
    created_at: datetime
    created_by: Optional[str] = None

    class Config:
        from_attributes = True


class EconomicsSnapshotWithCashflows(EconomicsSnapshotResponse):
    """Snapshot with full cashflow data"""
    cashflows: List[EconomicsCashflowYearlyResponse] = []


class EconomicsSnapshotSummary(BaseModel):
    """Simplified snapshot summary for lists"""
    id: int
    uuid: UUID
    snapshot_version: int
    production_scenario: str
    variant_key: str
    pv_capacity_kwp: float
    capex_client_npv25: Optional[float] = None
    capex_client_irr: Optional[float] = None
    created_at: datetime

    class Config:
        from_attributes = True


# Forward reference update
CompanyWithProjects.model_rebuild()
