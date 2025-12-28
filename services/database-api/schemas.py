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


# Forward reference update
CompanyWithProjects.model_rebuild()
