"""
Database API Service - FastAPI + SQLAlchemy
Central data store for PV Analyzer
"""

from fastapi import FastAPI, HTTPException, Depends, Query, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, text, func
from sqlalchemy.orm import Session, sessionmaker
from typing import List, Optional
from datetime import datetime, timedelta
from pydantic import BaseModel
import os
import pandas as pd
import numpy as np
from io import StringIO
import httpx

from models import (
    Base, Company, Project, EnergyProfile, ProfileData,
    PriceScenario, PriceData, AnalysisResult, AnalysisMode,
    ProjectSettings, Calculation, CalculationMetric, Export,
    ApiKey, Webhook, WebhookDelivery, AuditLog
)
from schemas import (
    CompanyCreate, CompanyUpdate, CompanyResponse, CompanyWithProjects,
    ProjectCreate, ProjectUpdate, ProjectResponse, ProjectWithCompany,
    EnergyProfileCreate, EnergyProfileResponse, ProfileDataResponse,
    PriceScenarioCreate, PriceScenarioResponse,
    AnalysisResultCreate, AnalysisResultResponse,
    AnalysisModeResponse, DatabaseStats, ProjectSummary,
    BulkProfileImport, BulkPriceImport,
    # New schemas
    ProjectSettingsCreate, ProjectSettingsResponse,
    CalculationCreate, CalculationUpdate, CalculationResponse, CalculationWithMetrics,
    ExportCreate, ExportResponse,
    ApiKeyCreate, ApiKeyResponse, ApiKeyWithSecret,
    WebhookCreate, WebhookUpdate, WebhookResponse, WebhookDeliveryResponse,
    AuditLogResponse,
    ExternalProjectResponse, ExternalCalculationResponse, ExternalCalculationListResponse
)

# ===========================================
# Database Setup
# ===========================================

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://pv_user:pv_secret_2024@localhost:5432/pv_analyzer")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ===========================================
# FastAPI App
# ===========================================

# Prometheus metrics
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI(
    title="PV Analyzer Database API",
    description="Central data store for companies, projects, profiles, and price scenarios",
    version="1.0.0"
)

# Initialize Prometheus metrics
Instrumentator().instrument(app).expose(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===========================================
# Health Check
# ===========================================

@app.get("/health")
async def health_check(db: Session = Depends(get_db)):
    """Health check with database connectivity test"""
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok", "service": "database-api", "database": "connected"}
    except Exception as e:
        return {"status": "degraded", "service": "database-api", "database": str(e)}


# ===========================================
# Analysis Modes
# ===========================================

@app.get("/modes", response_model=List[AnalysisModeResponse])
async def get_analysis_modes(db: Session = Depends(get_db)):
    """Get all available analysis modes"""
    modes = db.query(AnalysisMode).filter(AnalysisMode.is_active == True).order_by(AnalysisMode.display_order).all()
    return modes


# ===========================================
# Companies CRUD
# ===========================================

@app.get("/companies", response_model=List[CompanyResponse])
async def list_companies(
    skip: int = 0,
    limit: int = 100,
    search: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """List all companies with optional search by name or NIP"""
    query = db.query(Company)
    if search:
        # Search by name OR NIP
        search_term = search.strip()
        query = query.filter(
            (Company.name.ilike(f"%{search_term}%")) |
            (Company.nip.ilike(f"%{search_term}%"))
        )
    return query.order_by(Company.name).offset(skip).limit(limit).all()


@app.get("/companies/{company_id}", response_model=CompanyWithProjects)
async def get_company(company_id: int, db: Session = Depends(get_db)):
    """Get company by ID with its projects"""
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return company


@app.post("/companies", response_model=CompanyResponse)
async def create_company(company: CompanyCreate, db: Session = Depends(get_db)):
    """Create a new company"""
    db_company = Company(**company.model_dump())
    db.add(db_company)
    db.commit()
    db.refresh(db_company)
    return db_company


@app.put("/companies/{company_id}", response_model=CompanyResponse)
async def update_company(company_id: int, company: CompanyUpdate, db: Session = Depends(get_db)):
    """Update a company"""
    db_company = db.query(Company).filter(Company.id == company_id).first()
    if not db_company:
        raise HTTPException(status_code=404, detail="Company not found")

    update_data = company.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_company, key, value)

    db.commit()
    db.refresh(db_company)
    return db_company


@app.delete("/companies/{company_id}")
async def delete_company(company_id: int, db: Session = Depends(get_db)):
    """Delete a company and all its projects"""
    db_company = db.query(Company).filter(Company.id == company_id).first()
    if not db_company:
        raise HTTPException(status_code=404, detail="Company not found")

    db.delete(db_company)
    db.commit()
    return {"message": "Company deleted", "id": company_id}


# ===========================================
# Projects CRUD
# ===========================================

@app.get("/projects", response_model=List[ProjectWithCompany])
async def list_projects(
    company_id: Optional[int] = None,
    status: Optional[str] = None,
    analysis_mode: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """List all projects with optional filters"""
    query = db.query(
        Project,
        Company.name.label('company_name')
    ).outerjoin(Company)

    if company_id:
        query = query.filter(Project.company_id == company_id)
    if status:
        query = query.filter(Project.status == status)
    if analysis_mode:
        query = query.filter(Project.analysis_mode == analysis_mode)

    results = query.offset(skip).limit(limit).all()

    return [
        ProjectWithCompany(
            **project.__dict__,
            company_name=company_name
        )
        for project, company_name in results
    ]


@app.get("/projects/{project_id}", response_model=ProjectSummary)
async def get_project(project_id: int, db: Session = Depends(get_db)):
    """Get project with summary statistics"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    company_name = ""
    if project.company_id:
        company = db.query(Company).filter(Company.id == project.company_id).first()
        company_name = company.name if company else ""

    profiles_count = db.query(EnergyProfile).filter(EnergyProfile.project_id == project_id).count()
    analyses_count = db.query(AnalysisResult).filter(AnalysisResult.project_id == project_id).count()

    has_consumption = db.query(EnergyProfile).filter(
        EnergyProfile.project_id == project_id,
        EnergyProfile.profile_type == "consumption"
    ).first() is not None

    has_pv = db.query(EnergyProfile).filter(
        EnergyProfile.project_id == project_id,
        EnergyProfile.profile_type == "pv_generation"
    ).first() is not None

    has_prices = db.query(PriceScenario).count() > 0

    return ProjectSummary(
        project=project,
        company_name=company_name,
        profiles_count=profiles_count,
        analyses_count=analyses_count,
        has_consumption=has_consumption,
        has_pv=has_pv,
        has_prices=has_prices
    )


@app.post("/projects", response_model=ProjectResponse)
async def create_project(project: ProjectCreate, db: Session = Depends(get_db)):
    """Create a new project"""
    db_project = Project(**project.model_dump())
    db.add(db_project)
    db.commit()
    db.refresh(db_project)
    return db_project


@app.put("/projects/{project_id}", response_model=ProjectResponse)
async def update_project(project_id: int, project: ProjectUpdate, db: Session = Depends(get_db)):
    """Update a project"""
    db_project = db.query(Project).filter(Project.id == project_id).first()
    if not db_project:
        raise HTTPException(status_code=404, detail="Project not found")

    update_data = project.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_project, key, value)

    db.commit()
    db.refresh(db_project)
    return db_project


@app.delete("/projects/{project_id}")
async def delete_project(project_id: int, db: Session = Depends(get_db)):
    """Delete a project and all its data"""
    db_project = db.query(Project).filter(Project.id == project_id).first()
    if not db_project:
        raise HTTPException(status_code=404, detail="Project not found")

    db.delete(db_project)
    db.commit()
    return {"message": "Project deleted", "id": project_id}


# ===========================================
# Draft Project (Hybrid Workflow)
# ===========================================

@app.post("/projects/draft", response_model=ProjectResponse)
async def create_draft_project(
    session_id: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Create a draft project for the hybrid workflow.
    Draft projects are temporary - they become real projects when user saves them.
    """
    from datetime import datetime

    # Generate session-based name
    now = datetime.now()
    draft_name = f"Nowa analiza - {now.strftime('%Y-%m-%d %H:%M')}"

    # Create draft project (no company_id - will be assigned on save)
    db_project = Project(
        name=draft_name,
        description=f"Draft session: {session_id or 'anonymous'}",
        status="draft",
        analysis_mode="pv_bess"
    )
    db.add(db_project)
    db.commit()
    db.refresh(db_project)

    return db_project


@app.get("/projects/draft/active")
async def get_active_draft(
    session_id: str,
    db: Session = Depends(get_db)
):
    """
    Get active draft project for a session.
    Returns existing draft or creates new one.
    """
    # Look for existing draft with this session_id in description
    draft = db.query(Project).filter(
        Project.status == "draft",
        Project.description.contains(f"Draft session: {session_id}")
    ).order_by(Project.created_at.desc()).first()

    if draft:
        return {
            "found": True,
            "project": draft
        }

    return {"found": False, "project": None}


@app.put("/projects/{project_id}/finalize", response_model=ProjectResponse)
async def finalize_draft_project(
    project_id: int,
    name: str,
    company_id: Optional[int] = None,
    description: Optional[str] = None,
    location_name: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Finalize a draft project - convert it to an active project.
    This is called when user clicks "Save Project" and provides a name.
    """
    db_project = db.query(Project).filter(Project.id == project_id).first()
    if not db_project:
        raise HTTPException(status_code=404, detail="Project not found")

    if db_project.status != "draft":
        raise HTTPException(status_code=400, detail="Project is not a draft")

    # Update project with user-provided data
    db_project.name = name
    db_project.status = "active"
    if company_id:
        db_project.company_id = company_id
    if description:
        db_project.description = description
    if location_name:
        db_project.location_name = location_name

    db.commit()
    db.refresh(db_project)

    return db_project


@app.delete("/projects/drafts/cleanup")
async def cleanup_old_drafts(
    days_old: int = 7,
    db: Session = Depends(get_db)
):
    """
    Clean up old draft projects that were never finalized.
    Called periodically or on startup.
    """
    from datetime import datetime, timedelta

    cutoff_date = datetime.utcnow() - timedelta(days=days_old)

    old_drafts = db.query(Project).filter(
        Project.status == "draft",
        Project.created_at < cutoff_date
    ).all()

    deleted_count = len(old_drafts)
    for draft in old_drafts:
        db.delete(draft)

    db.commit()

    return {
        "message": f"Cleaned up {deleted_count} old draft projects",
        "deleted_count": deleted_count,
        "cutoff_date": cutoff_date.isoformat()
    }


# ===========================================
# Energy Profiles
# ===========================================

@app.get("/profiles", response_model=List[EnergyProfileResponse])
async def list_profiles(
    project_id: Optional[int] = None,
    profile_type: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """List energy profiles with optional filters"""
    query = db.query(EnergyProfile)
    if project_id:
        query = query.filter(EnergyProfile.project_id == project_id)
    if profile_type:
        query = query.filter(EnergyProfile.profile_type == profile_type)
    return query.all()


@app.get("/profiles/{profile_id}/data", response_model=List[ProfileDataResponse])
async def get_profile_data(
    profile_id: int,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    db: Session = Depends(get_db)
):
    """Get profile time series data"""
    query = db.query(ProfileData).filter(ProfileData.profile_id == profile_id)
    if start:
        query = query.filter(ProfileData.timestamp >= start)
    if end:
        query = query.filter(ProfileData.timestamp <= end)
    return query.order_by(ProfileData.timestamp).all()


@app.post("/profiles", response_model=EnergyProfileResponse)
async def create_profile(profile: EnergyProfileCreate, db: Session = Depends(get_db)):
    """Create a new energy profile with data"""
    # Create profile metadata
    db_profile = EnergyProfile(
        project_id=profile.project_id,
        profile_type=profile.profile_type.value,
        time_resolution=profile.time_resolution.value,
        year=profile.year,
        source=profile.source,
        filename=profile.filename,
        total_kwh=sum(profile.data),
        peak_kw=max(profile.data),
        data_points=len(profile.data)
    )
    db.add(db_profile)
    db.flush()

    # Generate timestamps
    start_date = datetime(profile.year, 1, 1)
    if profile.time_resolution.value == "15min":
        delta = timedelta(minutes=15)
    else:
        delta = timedelta(hours=1)

    # Insert data points
    for i, value in enumerate(profile.data):
        timestamp = start_date + (delta * i)
        db_data = ProfileData(
            profile_id=db_profile.id,
            timestamp=timestamp,
            value_kw=value
        )
        db.add(db_data)

    db.commit()
    db.refresh(db_profile)
    return db_profile


@app.delete("/profiles/{profile_id}")
async def delete_profile(profile_id: int, db: Session = Depends(get_db)):
    """Delete an energy profile"""
    db_profile = db.query(EnergyProfile).filter(EnergyProfile.id == profile_id).first()
    if not db_profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    db.delete(db_profile)
    db.commit()
    return {"message": "Profile deleted", "id": profile_id}


@app.get("/profiles/{profile_id}/values")
async def get_profile_values(profile_id: int, db: Session = Depends(get_db)):
    """Get profile data as simple array of values (for frontend integration)"""
    db_profile = db.query(EnergyProfile).filter(EnergyProfile.id == profile_id).first()
    if not db_profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    data = db.query(ProfileData).filter(
        ProfileData.profile_id == profile_id
    ).order_by(ProfileData.timestamp).all()

    return {
        "profile_id": profile_id,
        "profile_type": db_profile.profile_type,
        "resolution": db_profile.time_resolution,
        "year": db_profile.year,
        "data_points": len(data),
        "values": [float(d.value_kw) for d in data]
    }


class BulkProfileCreate(BaseModel):
    project_id: int
    profile_type: str
    time_resolution: str = "hourly"
    year: int = 2024
    source: str = "upload"
    filename: Optional[str] = None
    values: List[float]
    timestamps: Optional[List[str]] = None


@app.post("/profiles/bulk")
async def create_profile_bulk(
    data: BulkProfileCreate,
    db: Session = Depends(get_db)
):
    """
    Bulk create profile with all data points.
    Optimized for large profiles (8760 or 35040 points).

    Accepts JSON body with 'values' array and optional 'timestamps' array.
    """
    project_id = data.project_id
    profile_type = data.profile_type
    time_resolution = data.time_resolution
    year = data.year
    source = data.source
    filename = data.filename
    values = data.values
    timestamps = data.timestamps
    # Delete existing profile of same type for this project (replace)
    existing = db.query(EnergyProfile).filter(
        EnergyProfile.project_id == project_id,
        EnergyProfile.profile_type == profile_type
    ).first()

    if existing:
        db.delete(existing)
        db.flush()
        print(f"Deleted existing {profile_type} profile for project {project_id}")

    # Create new profile
    db_profile = EnergyProfile(
        project_id=project_id,
        profile_type=profile_type,
        time_resolution=time_resolution,
        year=year,
        source=source,
        filename=filename,
        total_kwh=sum(values) if values else 0,
        peak_kw=max(values) if values else 0,
        data_points=len(values) if values else 0
    )
    db.add(db_profile)
    db.flush()

    # Generate timestamps if not provided
    if not timestamps or len(timestamps) != len(values):
        start_date = datetime(year, 1, 1)
        if time_resolution == "15min":
            delta = timedelta(minutes=15)
        else:
            delta = timedelta(hours=1)
        timestamps = [(start_date + delta * i).isoformat() for i in range(len(values))]

    # Bulk insert data points
    batch_size = 1000
    for i in range(0, len(values), batch_size):
        batch_values = values[i:i+batch_size]
        batch_timestamps = timestamps[i:i+batch_size]

        for ts_str, value in zip(batch_timestamps, batch_values):
            ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00')) if isinstance(ts_str, str) else ts_str
            db.add(ProfileData(
                profile_id=db_profile.id,
                timestamp=ts,
                value_kw=value
            ))

        db.flush()

    db.commit()
    db.refresh(db_profile)

    return {
        "message": "Profile created",
        "id": db_profile.id,
        "project_id": project_id,
        "profile_type": profile_type,
        "data_points": len(values),
        "total_kwh": round(db_profile.total_kwh, 2),
        "peak_kw": round(db_profile.peak_kw, 2)
    }


# ===========================================
# Price Scenarios
# ===========================================

@app.get("/prices", response_model=List[PriceScenarioResponse])
async def list_price_scenarios(
    scenario_type: Optional[str] = None,
    year: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """List price scenarios"""
    query = db.query(PriceScenario)
    if scenario_type:
        query = query.filter(PriceScenario.scenario_type == scenario_type)
    if year:
        query = query.filter(PriceScenario.year == year)
    return query.all()


@app.get("/prices/{scenario_id}/data")
async def get_price_data(
    scenario_id: int,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    db: Session = Depends(get_db)
):
    """Get price scenario time series data"""
    query = db.query(PriceData).filter(PriceData.scenario_id == scenario_id)
    if start:
        query = query.filter(PriceData.timestamp >= start)
    if end:
        query = query.filter(PriceData.timestamp <= end)

    data = query.order_by(PriceData.timestamp).all()
    return [{"timestamp": d.timestamp, "price_pln_mwh": float(d.price_pln_mwh)} for d in data]


@app.post("/prices", response_model=PriceScenarioResponse)
async def create_price_scenario(scenario: PriceScenarioCreate, db: Session = Depends(get_db)):
    """Create a new price scenario with data"""
    # Create scenario metadata
    db_scenario = PriceScenario(
        name=scenario.name,
        description=scenario.description,
        scenario_type=scenario.scenario_type.value,
        source=scenario.source,
        year=scenario.year,
        currency=scenario.currency,
        unit=scenario.unit,
        avg_price=sum(scenario.data) / len(scenario.data) if scenario.data else None,
        min_price=min(scenario.data) if scenario.data else None,
        max_price=max(scenario.data) if scenario.data else None
    )
    db.add(db_scenario)
    db.flush()

    # Generate timestamps (hourly for full year)
    start_date = datetime(scenario.year or 2024, 1, 1)
    delta = timedelta(hours=1)

    # Insert price data
    for i, price in enumerate(scenario.data):
        timestamp = start_date + (delta * i)
        db_data = PriceData(
            scenario_id=db_scenario.id,
            timestamp=timestamp,
            price_pln_mwh=price
        )
        db.add(db_data)

    db.commit()
    db.refresh(db_scenario)
    return db_scenario


@app.post("/prices/upload-csv")
async def upload_price_csv(
    name: str = Query(...),
    year: int = Query(...),
    scenario_type: str = Query(default="historical"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """Upload price scenario from CSV file"""
    content = await file.read()
    df = pd.read_csv(StringIO(content.decode('utf-8')))

    # Expect columns: timestamp or datetime, price
    price_col = None
    for col in ['price', 'price_pln_mwh', 'cena', 'PLN/MWh']:
        if col in df.columns:
            price_col = col
            break

    if not price_col:
        raise HTTPException(status_code=400, detail="CSV must have a price column")

    prices = df[price_col].tolist()

    # Create scenario
    db_scenario = PriceScenario(
        name=name,
        scenario_type=scenario_type,
        source="csv_upload",
        year=year,
        avg_price=np.mean(prices),
        min_price=np.min(prices),
        max_price=np.max(prices)
    )
    db.add(db_scenario)
    db.flush()

    # Generate timestamps
    start_date = datetime(year, 1, 1)
    for i, price in enumerate(prices):
        timestamp = start_date + timedelta(hours=i)
        db.add(PriceData(
            scenario_id=db_scenario.id,
            timestamp=timestamp,
            price_pln_mwh=price
        ))

    db.commit()
    db.refresh(db_scenario)
    return {"message": "Price scenario created", "id": db_scenario.id, "data_points": len(prices)}


@app.post("/prices/upload-tge-csv")
async def upload_tge_csv(
    name: str = Query(..., description="Scenario name"),
    year: int = Query(..., description="Year of data"),
    scenario_type: str = Query(default="historical", description="historical, forecast, custom"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    Upload TGE (Towarowa Giełda Energii) price scenario from CSV or Excel.

    Supports multiple formats:
    1. TGE Fixing Excel (.xlsx): Date/Data + Fixing 1 columns (D.MM.YYYY HH:MM format)
    2. Standard TGE CSV: Data, Godzina, Cena (PLN/MWh)
    3. RDN format: timestamp, fixing_i_price, fixing_ii_price
    4. Simple format: timestamp/datetime, price/cena

    Handles European decimal separator (comma) and negative prices.
    Returns scenario ID and statistics.
    """
    import io
    content = await file.read()
    filename = file.filename or ""
    is_excel = filename.lower().endswith(('.xlsx', '.xls'))

    # ---- STEP 1: Parse file into DataFrame ----
    if is_excel:
        try:
            df = pd.read_excel(io.BytesIO(content), engine='openpyxl')
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Cannot read Excel file: {str(e)}")
    else:
        # CSV: try different encodings for TGE files
        text = None
        for encoding in ['utf-8', 'cp1250', 'latin1']:
            try:
                text = content.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            raise HTTPException(status_code=400, detail="Cannot decode CSV file")

        # Try semicolon first (TGE standard), then auto-detect
        try:
            df = pd.read_csv(StringIO(text), sep=';', engine='python')
            if len(df.columns) < 2:
                df = pd.read_csv(StringIO(text), sep=None, engine='python')
        except Exception:
            df = pd.read_csv(StringIO(text), sep=None, engine='python')

    if df is None or len(df) == 0:
        raise HTTPException(status_code=400, detail="File is empty or unreadable")

    print(f"TGE upload: {filename}, columns={list(df.columns)}, rows={len(df)}")

    # ---- STEP 2: Detect columns ----
    date_col = None
    hour_col = None
    price_col = None

    col_lower = {c.lower().strip(): c for c in df.columns}

    # Date column detection (order matters: most specific first)
    for name_pattern in ['date', 'data', 'datetime', 'timestamp', 'dzien']:
        for key, col in col_lower.items():
            if key == name_pattern or key.startswith(name_pattern):
                date_col = col
                break
        if date_col:
            break

    # Hour column detection (TGE classic: separate Data + Godzina)
    for name_pattern in ['godzina', 'hour', 'godz']:
        for key, col in col_lower.items():
            if name_pattern in key:
                hour_col = col
                break
        if hour_col:
            break

    # Price column detection - prefer "Fixing 1" / "Fixing I" over generic "price"
    for name_pattern in ['fixing 1', 'fixing i', 'fixing_1', 'fixing_i',
                         'cena', 'price', 'pln', 'fixing', 'kurs']:
        for key, col in col_lower.items():
            if name_pattern in key and 'buy' not in key and 'ii' not in key and '2' not in key:
                price_col = col
                break
        if price_col:
            break

    if not price_col:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot find price column. Available columns: {list(df.columns)}"
        )

    print(f"TGE columns detected: date={date_col}, hour={hour_col}, price={price_col}")

    # ---- STEP 3: Parse prices (handle European comma decimals) ----
    price_series = df[price_col].copy()
    # If string column with commas as decimal separators, convert
    if price_series.dtype == object:
        price_series = price_series.astype(str).str.replace(',', '.', regex=False)
    prices_full = pd.to_numeric(price_series, errors='coerce')

    # Drop NaN rows from both prices and timestamps
    valid_mask = prices_full.notna()
    df_valid = df[valid_mask].copy()
    prices = prices_full[valid_mask].tolist()

    if len(prices) < 24:
        raise HTTPException(status_code=400, detail=f"Too few valid prices: {len(prices)}")

    # ---- STEP 4: Parse timestamps ----
    timestamps = []

    if date_col and hour_col:
        # Classic TGE format: separate Date + Godzina columns
        for _, row in df_valid.iterrows():
            try:
                date_str = str(row[date_col]).strip()
                hour_val = row[hour_col]
                for fmt in ['%Y-%m-%d', '%d.%m.%Y', '%d/%m/%Y']:
                    try:
                        dt = datetime.strptime(date_str.split()[0], fmt)
                        break
                    except ValueError:
                        continue
                else:
                    continue
                hour = int(float(hour_val)) - 1 if int(float(hour_val)) > 0 else 0
                ts = dt.replace(hour=min(max(hour, 0), 23))
                timestamps.append(ts)
            except (ValueError, KeyError, TypeError):
                continue

    elif date_col:
        # Single datetime column (TGE Fixing Excel: "1.01.2025 00:00")
        date_series = df_valid[date_col]

        # Try pandas auto-parse first
        try:
            parsed = pd.to_datetime(date_series, dayfirst=True, format='mixed')
            timestamps = [ts.to_pydatetime() for ts in parsed if pd.notna(ts)]
        except Exception:
            # Manual parsing for European formats
            for val in date_series:
                try:
                    val_str = str(val).strip()
                    # Try multiple formats
                    for fmt in ['%d.%m.%Y %H:%M', '%d.%m.%Y %H:%M:%S',
                                '%Y-%m-%d %H:%M', '%Y-%m-%d %H:%M:%S',
                                '%d/%m/%Y %H:%M', '%d.%m.%Y']:
                        try:
                            ts = datetime.strptime(val_str, fmt)
                            timestamps.append(ts)
                            break
                        except ValueError:
                            continue
                except (ValueError, TypeError):
                    continue

    else:
        # No date columns - assume hourly from Jan 1
        start_date = datetime(year, 1, 1)
        timestamps = [start_date + timedelta(hours=i) for i in range(len(prices))]

    print(f"TGE parsed: {len(prices)} prices, {len(timestamps)} timestamps")

    # Match lengths
    min_len = min(len(timestamps), len(prices))
    if min_len < 24:
        raise HTTPException(
            status_code=400,
            detail=f"Too few matched data points: {min_len} (prices={len(prices)}, timestamps={len(timestamps)})"
        )
    timestamps = timestamps[:min_len]
    prices = prices[:min_len]

    # ---- STEP 4b: Normalize timestamps to clean hours ----
    # Excel floating-point date precision can produce 16:59:59.999 instead of 17:00:00
    # Round each timestamp to the nearest hour
    normalized_ts = []
    for ts in timestamps:
        # Remove timezone info if present (work in naive UTC)
        if hasattr(ts, 'tzinfo') and ts.tzinfo is not None:
            ts = ts.replace(tzinfo=None)
        # Round to nearest hour: if minute >= 30, round up; else round down
        if ts.minute >= 30:
            ts = ts.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        else:
            ts = ts.replace(minute=0, second=0, microsecond=0)
        normalized_ts.append(ts)
    timestamps = normalized_ts

    # De-duplicate timestamps (DST change can produce duplicate hours, e.g. Oct 26)
    # Keep last occurrence for each timestamp
    seen = {}
    for i, ts in enumerate(timestamps):
        seen[ts] = i  # last occurrence wins
    unique_indices = sorted(seen.values())
    timestamps = [timestamps[i] for i in unique_indices]
    prices = [prices[i] for i in unique_indices]
    dedup_removed = min_len - len(timestamps)
    if dedup_removed > 0:
        print(f"TGE dedup: removed {dedup_removed} duplicate timestamps (DST change)")

    min_len = len(timestamps)

    # ---- STEP 5: Create scenario and insert data ----
    db_scenario = PriceScenario(
        name=name,
        description=f"TGE import: {filename} ({min_len} hours)",
        scenario_type=scenario_type,
        source="tge_excel" if is_excel else "tge_csv",
        year=year,
        avg_price=float(np.mean(prices)),
        min_price=float(np.min(prices)),
        max_price=float(np.max(prices))
    )
    db.add(db_scenario)
    db.flush()

    # Insert price data in batches
    batch_size = 500
    for i in range(0, min_len, batch_size):
        batch_ts = timestamps[i:i+batch_size]
        batch_prices = prices[i:i+batch_size]

        for ts, price in zip(batch_ts, batch_prices):
            db.add(PriceData(
                scenario_id=db_scenario.id,
                timestamp=ts,
                price_pln_mwh=price
            ))
        db.commit()

    db.refresh(db_scenario)

    return {
        "message": "TGE price scenario created",
        "id": db_scenario.id,
        "data_points": min_len,
        "date_range": {
            "start": timestamps[0].isoformat() if timestamps else None,
            "end": timestamps[-1].isoformat() if timestamps else None
        },
        "stats": {
            "avg_price": round(float(np.mean(prices)), 2),
            "min_price": round(float(np.min(prices)), 2),
            "max_price": round(float(np.max(prices)), 2),
            "std_dev": round(float(np.std(prices)), 2)
        }
    }


@app.get("/prices/{scenario_id}/hourly-array")
async def get_price_array(
    scenario_id: int,
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    db: Session = Depends(get_db)
):
    """
    Get price scenario as array for profile-analysis/arbitrage integration.

    Returns 8760 hourly prices for a full year.
    If scenario has fewer points, fills gaps with interpolation.
    """
    scenario = db.query(PriceScenario).filter(PriceScenario.id == scenario_id).first()
    if not scenario:
        raise HTTPException(status_code=404, detail="Price scenario not found")

    # Get price data
    query = db.query(PriceData).filter(PriceData.scenario_id == scenario_id)

    if start_date:
        start_dt = datetime.fromisoformat(start_date)
        query = query.filter(PriceData.timestamp >= start_dt)
    if end_date:
        end_dt = datetime.fromisoformat(end_date)
        query = query.filter(PriceData.timestamp <= end_dt)

    data_points = query.order_by(PriceData.timestamp).all()

    if not data_points:
        raise HTTPException(status_code=404, detail="No price data in scenario")

    # Build hourly price array — strip timezone so naive datetime keys match
    prices_dict = {}
    for d in data_points:
        ts = d.timestamp.replace(tzinfo=None) if d.timestamp.tzinfo else d.timestamp
        prices_dict[ts] = float(d.price_pln_mwh)

    # Get year from first data point
    year = data_points[0].timestamp.year
    start = datetime(year, 1, 1)

    print(f"hourly-array: scenario {scenario_id}, year={year}, data_points={len(data_points)}, dict_keys={len(prices_dict)}")
    # Debug: check first few matches
    sample_ts = start + timedelta(hours=2)
    print(f"  Sample lookup: ts={sample_ts}, found={sample_ts in prices_dict}, value={prices_dict.get(sample_ts, 'MISS')}")

    # Generate 8760 hourly values
    hourly_prices = []
    for i in range(8760):
        ts = start + timedelta(hours=i)
        if ts in prices_dict:
            hourly_prices.append(prices_dict[ts])
        elif hourly_prices:
            # Fill gap with last known price
            hourly_prices.append(hourly_prices[-1])
        else:
            # No previous price, use scenario average
            hourly_prices.append(float(scenario.avg_price) if scenario.avg_price else 500.0)

    return {
        "scenario_id": scenario_id,
        "scenario_name": scenario.name,
        "year": year,
        "prices_plnmwh": hourly_prices,
        "data_points": len(data_points),
        "stats": {
            "avg": round(sum(hourly_prices) / len(hourly_prices), 2),
            "min": round(min(hourly_prices), 2),
            "max": round(max(hourly_prices), 2)
        }
    }


@app.get("/prices/scenarios-for-arbitrage")
async def list_scenarios_for_arbitrage(db: Session = Depends(get_db)):
    """
    List price scenarios suitable for arbitrage analysis.
    Returns scenarios with at least 8760 data points.
    """
    scenarios = db.query(PriceScenario).all()

    result = []
    for s in scenarios:
        count = db.query(PriceData).filter(PriceData.scenario_id == s.id).count()
        if count >= 24:  # At least 24 hours of data
            result.append({
                "id": s.id,
                "name": s.name,
                "year": s.year,
                "scenario_type": s.scenario_type,
                "source": s.source,
                "data_points": count,
                "is_complete_year": count >= 8760,
                "stats": {
                    "avg_price": float(s.avg_price) if s.avg_price else None,
                    "min_price": float(s.min_price) if s.min_price else None,
                    "max_price": float(s.max_price) if s.max_price else None
                }
            })

    return result


# ===========================================
# Analysis Results
# ===========================================

@app.get("/analyses", response_model=List[AnalysisResultResponse])
async def list_analyses(
    project_id: Optional[int] = None,
    analysis_type: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """List analysis results"""
    query = db.query(AnalysisResult)
    if project_id:
        query = query.filter(AnalysisResult.project_id == project_id)
    if analysis_type:
        query = query.filter(AnalysisResult.analysis_type == analysis_type)
    return query.order_by(AnalysisResult.created_at.desc()).all()


@app.get("/analyses/{analysis_id}", response_model=AnalysisResultResponse)
async def get_analysis(analysis_id: int, db: Session = Depends(get_db)):
    """Get analysis result by ID"""
    analysis = db.query(AnalysisResult).filter(AnalysisResult.id == analysis_id).first()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return analysis


@app.post("/analyses", response_model=AnalysisResultResponse)
async def create_analysis(analysis: AnalysisResultCreate, db: Session = Depends(get_db)):
    """Save analysis results"""
    db_analysis = AnalysisResult(**analysis.model_dump())
    db.add(db_analysis)
    db.commit()
    db.refresh(db_analysis)
    return db_analysis


# ===========================================
# Profile Import from data-analysis service
# ===========================================

DATA_ANALYSIS_URL = os.getenv("DATA_ANALYSIS_URL", "http://pv-data-analysis:8001")

@app.post("/profiles/import-from-analysis")
async def import_profile_from_analysis(
    project_id: int,
    profile_type: str = Query(default="consumption"),
    db: Session = Depends(get_db)
):
    """
    Import profile data from data-analysis service into PostgreSQL.
    This allows storing uploaded profiles permanently in the database.
    """
    # Verify project exists
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Fetch data from data-analysis service
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{DATA_ANALYSIS_URL}/export-data", timeout=30.0)
            if response.status_code != 200:
                raise HTTPException(status_code=400, detail="No data available in data-analysis service")

            data = response.json()
        except httpx.RequestError as e:
            raise HTTPException(status_code=503, detail=f"Cannot connect to data-analysis service: {str(e)}")

    timestamps = data.get("timestamps", [])
    values = data.get("values", [])
    analytical_year = data.get("analytical_year", {})

    if not timestamps or not values:
        raise HTTPException(status_code=400, detail="No data in data-analysis service")

    # Determine time resolution
    if len(timestamps) > 10000:
        time_resolution = "15min"  # 35040 points
    else:
        time_resolution = "hourly"  # 8760 points

    # Determine year from first timestamp
    first_ts = datetime.fromisoformat(timestamps[0].replace('Z', '').replace('+00:00', ''))
    year = first_ts.year

    # Calculate stats
    values_array = np.array(values)
    total_kwh = float(np.sum(values_array))
    peak_kw = float(np.max(values_array))

    # Create profile metadata
    db_profile = EnergyProfile(
        project_id=project_id,
        profile_type=profile_type,
        time_resolution=time_resolution,
        year=year,
        source="data_analysis_import",
        filename=None,
        total_kwh=total_kwh,
        peak_kw=peak_kw,
        data_points=len(values)
    )
    db.add(db_profile)
    db.flush()

    # Insert data points in batches
    batch_size = 1000
    for i in range(0, len(timestamps), batch_size):
        batch_ts = timestamps[i:i+batch_size]
        batch_vals = values[i:i+batch_size]

        for ts, val in zip(batch_ts, batch_vals):
            timestamp = datetime.fromisoformat(ts.replace('Z', '').replace('+00:00', ''))
            db.add(ProfileData(
                profile_id=db_profile.id,
                timestamp=timestamp,
                value_kw=val
            ))

        # Commit batch
        db.commit()

    db.refresh(db_profile)

    return {
        "message": "Profile imported successfully",
        "profile_id": db_profile.id,
        "data_points": len(values),
        "time_resolution": time_resolution,
        "year": year,
        "total_kwh": total_kwh,
        "peak_kw": peak_kw
    }


@app.get("/profiles/{profile_id}/export")
async def export_profile_to_analysis(
    profile_id: int,
    db: Session = Depends(get_db)
):
    """
    Export profile from PostgreSQL to data-analysis service format.
    Returns data compatible with /restore-data endpoint.
    """
    profile = db.query(EnergyProfile).filter(EnergyProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    # Get all data points
    data_points = db.query(ProfileData).filter(
        ProfileData.profile_id == profile_id
    ).order_by(ProfileData.timestamp).all()

    timestamps = [d.timestamp.isoformat() for d in data_points]
    values = [float(d.value_kw) for d in data_points]

    return {
        "timestamps": timestamps,
        "values": values,
        "analytical_year": {
            "start_date": timestamps[0][:10] if timestamps else None,
            "end_date": timestamps[-1][:10] if timestamps else None,
            "total_days": len(timestamps) // 24 if profile.time_resolution == "hourly" else len(timestamps) // 96,
            "total_hours": len(timestamps) if profile.time_resolution == "hourly" else len(timestamps) // 4,
            "is_complete": len(timestamps) >= 8760
        },
        "profile_info": {
            "id": profile.id,
            "profile_type": profile.profile_type,
            "time_resolution": profile.time_resolution,
            "year": profile.year,
            "total_kwh": float(profile.total_kwh) if profile.total_kwh else None,
            "peak_kw": float(profile.peak_kw) if profile.peak_kw else None
        }
    }


@app.post("/profiles/{profile_id}/load-to-analysis")
async def load_profile_to_analysis(
    profile_id: int,
    db: Session = Depends(get_db)
):
    """
    Load profile from PostgreSQL into data-analysis service.
    This restores the profile for active analysis.
    """
    # Get profile data
    export_data = await export_profile_to_analysis(profile_id, db)

    # Send to data-analysis service
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{DATA_ANALYSIS_URL}/restore-data",
                json={
                    "timestamps": export_data["timestamps"],
                    "values": export_data["values"],
                    "analytical_year": export_data["analytical_year"]
                },
                timeout=60.0
            )

            if response.status_code != 200:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to load profile to data-analysis: {response.text}"
                )

            return {
                "message": "Profile loaded to data-analysis service",
                "profile_id": profile_id,
                "data_points": len(export_data["values"])
            }

        except httpx.RequestError as e:
            raise HTTPException(
                status_code=503,
                detail=f"Cannot connect to data-analysis service: {str(e)}"
            )


# ===========================================
# Statistics
# ===========================================

@app.get("/stats", response_model=DatabaseStats)
async def get_stats(db: Session = Depends(get_db)):
    """Get database statistics"""
    return DatabaseStats(
        companies_count=db.query(Company).count(),
        projects_count=db.query(Project).count(),
        profiles_count=db.query(EnergyProfile).count(),
        price_scenarios_count=db.query(PriceScenario).count(),
        analyses_count=db.query(AnalysisResult).count(),
        total_profile_data_points=db.query(ProfileData).count(),
        total_price_data_points=db.query(PriceData).count()
    )


# ===========================================
# Project Settings
# ===========================================

@app.get("/projects/{project_id}/settings", response_model=List[ProjectSettingsResponse])
async def list_project_settings(
    project_id: int,
    db: Session = Depends(get_db)
):
    """List all settings versions for a project"""
    settings = db.query(ProjectSettings).filter(
        ProjectSettings.project_id == project_id
    ).order_by(ProjectSettings.version.desc()).all()
    return settings


@app.get("/projects/{project_id}/settings/latest", response_model=ProjectSettingsResponse)
async def get_latest_settings(
    project_id: int,
    db: Session = Depends(get_db)
):
    """Get latest settings version for a project"""
    settings = db.query(ProjectSettings).filter(
        ProjectSettings.project_id == project_id
    ).order_by(ProjectSettings.version.desc()).first()

    if not settings:
        raise HTTPException(status_code=404, detail="No settings found for this project")
    return settings


@app.post("/projects/{project_id}/settings", response_model=ProjectSettingsResponse)
async def create_project_settings(
    project_id: int,
    settings_data: ProjectSettingsCreate,
    db: Session = Depends(get_db)
):
    """Create new settings version for a project"""
    # Get current max version
    max_version = db.query(func.max(ProjectSettings.version)).filter(
        ProjectSettings.project_id == project_id
    ).scalar() or 0

    db_settings = ProjectSettings(
        project_id=project_id,
        version=max_version + 1,
        settings=settings_data.settings,
        description=settings_data.description,
        created_by=settings_data.created_by
    )
    db.add(db_settings)
    db.commit()
    db.refresh(db_settings)
    return db_settings


# ===========================================
# Calculations CRUD
# ===========================================

@app.get("/calculations", response_model=List[CalculationResponse])
async def list_calculations(
    project_id: Optional[int] = None,
    calc_type: Optional[str] = None,
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """List calculations with optional filters"""
    query = db.query(Calculation)

    if project_id:
        query = query.filter(Calculation.project_id == project_id)
    if calc_type:
        query = query.filter(Calculation.calc_type == calc_type)
    if status:
        query = query.filter(Calculation.status == status)

    return query.order_by(Calculation.created_at.desc()).offset(skip).limit(limit).all()


@app.get("/calculations/{calc_id}", response_model=CalculationWithMetrics)
async def get_calculation(
    calc_id: int,
    db: Session = Depends(get_db)
):
    """Get calculation by ID with metrics"""
    calc = db.query(Calculation).filter(Calculation.id == calc_id).first()
    if not calc:
        raise HTTPException(status_code=404, detail="Calculation not found")

    # Get project and company names
    project_name = None
    company_name = None
    if calc.project_id:
        project = db.query(Project).filter(Project.id == calc.project_id).first()
        if project:
            project_name = project.name
            if project.company_id:
                company = db.query(Company).filter(Company.id == project.company_id).first()
                company_name = company.name if company else None

    # Get metrics
    metrics = db.query(CalculationMetric).filter(
        CalculationMetric.calculation_id == calc_id
    ).all()

    return CalculationWithMetrics(
        **{k: v for k, v in calc.__dict__.items() if not k.startswith('_')},
        metrics=metrics,
        project_name=project_name,
        company_name=company_name
    )


@app.get("/calculations/by-uuid/{calc_uuid}")
async def get_calculation_by_uuid(
    calc_uuid: str,
    db: Session = Depends(get_db)
):
    """Get calculation by UUID"""
    calc = db.query(Calculation).filter(Calculation.uuid == calc_uuid).first()
    if not calc:
        raise HTTPException(status_code=404, detail="Calculation not found")
    return calc


@app.get("/projects/{project_id}/calculations", response_model=List[CalculationResponse])
async def get_project_calculations(
    project_id: int,
    calc_type: Optional[str] = None,
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """Get all calculations for a specific project"""
    # Verify project exists
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    query = db.query(Calculation).filter(Calculation.project_id == project_id)

    if calc_type:
        query = query.filter(Calculation.calc_type == calc_type)
    if status:
        query = query.filter(Calculation.status == status)

    return query.order_by(Calculation.created_at.desc()).offset(skip).limit(limit).all()


@app.post("/calculations", response_model=CalculationResponse)
async def create_calculation(
    calc_data: CalculationCreate,
    db: Session = Depends(get_db)
):
    """Create a new calculation record"""
    db_calc = Calculation(
        project_id=calc_data.project_id,
        parent_calc_id=calc_data.parent_calc_id,
        calc_type=calc_data.calc_type,
        status="pending",
        request_payload=calc_data.request_payload,
        service_name=calc_data.service_name,
        service_version=calc_data.service_version,
        service_endpoint=calc_data.service_endpoint,
        created_by=calc_data.created_by,
        calc_metadata=calc_data.calc_metadata or {}
    )
    db.add(db_calc)
    db.commit()
    db.refresh(db_calc)
    return db_calc


@app.put("/calculations/{calc_id}", response_model=CalculationResponse)
async def update_calculation(
    calc_id: int,
    calc_update: CalculationUpdate,
    db: Session = Depends(get_db)
):
    """Update calculation (status, result, etc.)"""
    db_calc = db.query(Calculation).filter(Calculation.id == calc_id).first()
    if not db_calc:
        raise HTTPException(status_code=404, detail="Calculation not found")

    update_data = calc_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if key == 'status':
            setattr(db_calc, key, value.value if hasattr(value, 'value') else value)
        else:
            setattr(db_calc, key, value)

    db.commit()
    db.refresh(db_calc)
    return db_calc


@app.get("/calculations/{calc_id}/metrics")
async def get_calculation_metrics(
    calc_id: int,
    db: Session = Depends(get_db)
):
    """Get extracted metrics for a calculation"""
    metrics = db.query(CalculationMetric).filter(
        CalculationMetric.calculation_id == calc_id
    ).all()

    return {m.metric_name: float(m.metric_value) if m.metric_value else None for m in metrics}


@app.get("/calculations/{calc_id}/chain")
async def get_calculation_chain(
    calc_id: int,
    db: Session = Depends(get_db)
):
    """Get full calculation chain (parent → children)"""
    calc = db.query(Calculation).filter(Calculation.id == calc_id).first()
    if not calc:
        raise HTTPException(status_code=404, detail="Calculation not found")

    # Find root
    root = calc
    while root.parent_calc_id:
        parent = db.query(Calculation).filter(Calculation.id == root.parent_calc_id).first()
        if parent:
            root = parent
        else:
            break

    # Build tree from root
    def build_chain(node):
        children = db.query(Calculation).filter(Calculation.parent_calc_id == node.id).all()
        return {
            "id": node.id,
            "uuid": str(node.uuid),
            "calc_type": node.calc_type,
            "status": node.status,
            "created_at": node.created_at.isoformat() if node.created_at else None,
            "children": [build_chain(c) for c in children]
        }

    return build_chain(root)


# ===========================================
# Exports (Excel/PDF files)
# ===========================================

@app.get("/exports", response_model=List[ExportResponse])
async def list_exports(
    project_id: Optional[int] = None,
    calculation_id: Optional[int] = None,
    file_type: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """List exports with optional filters"""
    query = db.query(Export)

    if project_id:
        query = query.filter(Export.project_id == project_id)
    if calculation_id:
        query = query.filter(Export.calculation_id == calculation_id)
    if file_type:
        query = query.filter(Export.file_type == file_type)

    return query.order_by(Export.created_at.desc()).offset(skip).limit(limit).all()


@app.get("/exports/{export_id}")
async def get_export(
    export_id: int,
    db: Session = Depends(get_db)
):
    """Get export metadata by ID"""
    export = db.query(Export).filter(Export.id == export_id).first()
    if not export:
        raise HTTPException(status_code=404, detail="Export not found")
    return export


@app.get("/exports/{export_id}/download")
async def download_export(
    export_id: int,
    db: Session = Depends(get_db)
):
    """Download export file"""
    from fastapi.responses import Response

    export = db.query(Export).filter(Export.id == export_id).first()
    if not export:
        raise HTTPException(status_code=404, detail="Export not found")

    if not export.file_data:
        raise HTTPException(status_code=404, detail="File data not available")

    media_types = {
        'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'pdf': 'application/pdf',
        'csv': 'text/csv',
        'json': 'application/json'
    }

    return Response(
        content=export.file_data,
        media_type=media_types.get(export.file_type, 'application/octet-stream'),
        headers={
            'Content-Disposition': f'attachment; filename="{export.file_name}"'
        }
    )


@app.get("/exports/by-uuid/{export_uuid}/download")
async def download_export_by_uuid(
    export_uuid: str,
    db: Session = Depends(get_db)
):
    """Download export file by UUID"""
    from fastapi.responses import Response

    export = db.query(Export).filter(Export.uuid == export_uuid).first()
    if not export:
        raise HTTPException(status_code=404, detail="Export not found")

    if not export.file_data:
        raise HTTPException(status_code=404, detail="File data not available")

    media_types = {
        'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'pdf': 'application/pdf',
        'csv': 'text/csv',
        'json': 'application/json'
    }

    return Response(
        content=export.file_data,
        media_type=media_types.get(export.file_type, 'application/octet-stream'),
        headers={
            'Content-Disposition': f'attachment; filename="{export.file_name}"'
        }
    )


@app.post("/exports", response_model=ExportResponse)
async def create_export(
    project_id: int,
    file_type: str,
    file_name: str,
    export_type: Optional[str] = None,
    calculation_id: Optional[int] = None,
    created_by: Optional[str] = None,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """Upload and store an export file"""
    file_data = await file.read()

    db_export = Export(
        project_id=project_id,
        calculation_id=calculation_id,
        file_type=file_type,
        file_name=file_name,
        file_size=len(file_data),
        file_data=file_data,
        export_type=export_type,
        created_by=created_by
    )
    db.add(db_export)
    db.commit()
    db.refresh(db_export)
    return db_export


@app.delete("/exports/{export_id}")
async def delete_export(
    export_id: int,
    db: Session = Depends(get_db)
):
    """Delete an export"""
    export = db.query(Export).filter(Export.id == export_id).first()
    if not export:
        raise HTTPException(status_code=404, detail="Export not found")

    db.delete(export)
    db.commit()
    return {"message": "Export deleted", "id": export_id}


# ===========================================
# API Keys (for external portal)
# ===========================================

import secrets
import hashlib


def generate_api_key() -> tuple:
    """Generate API key and return (full_key, prefix, hash)"""
    key = f"pva_{secrets.token_urlsafe(32)}"
    prefix = key[:12]
    key_hash = hashlib.sha256(key.encode()).hexdigest()
    return key, prefix, key_hash


def verify_api_key(key: str, key_hash: str) -> bool:
    """Verify API key against stored hash"""
    return hashlib.sha256(key.encode()).hexdigest() == key_hash


@app.get("/api-keys", response_model=List[ApiKeyResponse])
async def list_api_keys(
    company_id: Optional[int] = None,
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db)
):
    """List API keys (without secrets)"""
    query = db.query(ApiKey)

    if company_id:
        query = query.filter(ApiKey.company_id == company_id)
    if is_active is not None:
        query = query.filter(ApiKey.is_active == is_active)

    return query.order_by(ApiKey.created_at.desc()).all()


@app.post("/api-keys", response_model=ApiKeyWithSecret)
async def create_api_key(
    key_data: ApiKeyCreate,
    db: Session = Depends(get_db)
):
    """Create a new API key - returns full key ONLY ONCE"""
    full_key, prefix, key_hash = generate_api_key()

    db_key = ApiKey(
        company_id=key_data.company_id,
        key_prefix=prefix,
        key_hash=key_hash,
        name=key_data.name,
        permissions=key_data.permissions,
        allowed_ips=key_data.allowed_ips,
        rate_limit_per_hour=key_data.rate_limit_per_hour,
        expires_at=key_data.expires_at,
        created_by=key_data.created_by
    )
    db.add(db_key)
    db.commit()
    db.refresh(db_key)

    return ApiKeyWithSecret(
        **{k: v for k, v in db_key.__dict__.items() if not k.startswith('_')},
        api_key=full_key
    )


@app.delete("/api-keys/{key_id}")
async def delete_api_key(
    key_id: int,
    db: Session = Depends(get_db)
):
    """Delete/revoke an API key"""
    key = db.query(ApiKey).filter(ApiKey.id == key_id).first()
    if not key:
        raise HTTPException(status_code=404, detail="API key not found")

    db.delete(key)
    db.commit()
    return {"message": "API key deleted", "id": key_id}


@app.put("/api-keys/{key_id}/deactivate")
async def deactivate_api_key(
    key_id: int,
    db: Session = Depends(get_db)
):
    """Deactivate API key without deleting"""
    key = db.query(ApiKey).filter(ApiKey.id == key_id).first()
    if not key:
        raise HTTPException(status_code=404, detail="API key not found")

    key.is_active = False
    db.commit()
    return {"message": "API key deactivated", "id": key_id}


# ===========================================
# Webhooks
# ===========================================

@app.get("/webhooks", response_model=List[WebhookResponse])
async def list_webhooks(
    company_id: Optional[int] = None,
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db)
):
    """List webhooks"""
    query = db.query(Webhook)

    if company_id:
        query = query.filter(Webhook.company_id == company_id)
    if is_active is not None:
        query = query.filter(Webhook.is_active == is_active)

    return query.order_by(Webhook.created_at.desc()).all()


@app.post("/webhooks", response_model=WebhookResponse)
async def create_webhook(
    webhook_data: WebhookCreate,
    db: Session = Depends(get_db)
):
    """Create a new webhook"""
    # Generate secret if not provided
    secret = webhook_data.secret or secrets.token_urlsafe(32)

    db_webhook = Webhook(
        company_id=webhook_data.company_id,
        name=webhook_data.name,
        url=webhook_data.url,
        secret=secret,
        events=webhook_data.events,
        max_retries=webhook_data.max_retries,
        retry_delay_seconds=webhook_data.retry_delay_seconds
    )
    db.add(db_webhook)
    db.commit()
    db.refresh(db_webhook)
    return db_webhook


@app.put("/webhooks/{webhook_id}", response_model=WebhookResponse)
async def update_webhook(
    webhook_id: int,
    webhook_update: WebhookUpdate,
    db: Session = Depends(get_db)
):
    """Update webhook"""
    webhook = db.query(Webhook).filter(Webhook.id == webhook_id).first()
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")

    update_data = webhook_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(webhook, key, value)

    db.commit()
    db.refresh(webhook)
    return webhook


@app.delete("/webhooks/{webhook_id}")
async def delete_webhook(
    webhook_id: int,
    db: Session = Depends(get_db)
):
    """Delete webhook"""
    webhook = db.query(Webhook).filter(Webhook.id == webhook_id).first()
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")

    db.delete(webhook)
    db.commit()
    return {"message": "Webhook deleted", "id": webhook_id}


@app.get("/webhooks/{webhook_id}/deliveries", response_model=List[WebhookDeliveryResponse])
async def list_webhook_deliveries(
    webhook_id: int,
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """List webhook delivery history"""
    query = db.query(WebhookDelivery).filter(WebhookDelivery.webhook_id == webhook_id)

    if status:
        query = query.filter(WebhookDelivery.status == status)

    return query.order_by(WebhookDelivery.created_at.desc()).offset(skip).limit(limit).all()


@app.post("/webhooks/trigger")
async def trigger_webhook_event(
    event_type: str,
    payload: dict,
    db: Session = Depends(get_db)
):
    """
    Trigger webhooks for an event.
    Called internally when events occur (calculation.completed, etc.)
    """
    import hmac
    import hashlib
    import json

    # Find active webhooks listening to this event
    webhooks = db.query(Webhook).filter(
        Webhook.is_active == True,
        Webhook.events.contains([event_type])
    ).all()

    results = []

    for webhook in webhooks:
        # Create delivery record
        delivery = WebhookDelivery(
            webhook_id=webhook.id,
            event_type=event_type,
            payload=payload,
            status="pending"
        )
        db.add(delivery)
        db.flush()

        # Prepare request
        body = json.dumps({
            "event": event_type,
            "timestamp": datetime.utcnow().isoformat(),
            "data": payload
        })

        # Calculate signature
        signature = hmac.new(
            webhook.secret.encode() if webhook.secret else b'',
            body.encode(),
            hashlib.sha256
        ).hexdigest()

        # Send webhook
        try:
            async with httpx.AsyncClient() as client:
                start_time = datetime.utcnow()
                response = await client.post(
                    webhook.url,
                    content=body,
                    headers={
                        'Content-Type': 'application/json',
                        'X-Webhook-Signature': f'sha256={signature}',
                        'X-Webhook-Event': event_type
                    },
                    timeout=30.0
                )
                end_time = datetime.utcnow()

                delivery.status_code = response.status_code
                delivery.response_time_ms = int((end_time - start_time).total_seconds() * 1000)
                delivery.status = "success" if response.status_code < 400 else "failed"

                webhook.last_triggered_at = datetime.utcnow()
                webhook.last_status_code = response.status_code
                webhook.total_triggers += 1

                if response.status_code >= 400:
                    webhook.failure_count += 1
                    delivery.response_body = response.text[:1000]

                results.append({
                    "webhook_id": webhook.id,
                    "status": delivery.status,
                    "status_code": response.status_code
                })

        except Exception as e:
            delivery.status = "failed"
            delivery.response_body = str(e)[:1000]
            webhook.failure_count += 1

            results.append({
                "webhook_id": webhook.id,
                "status": "failed",
                "error": str(e)
            })

    db.commit()
    return {"triggered": len(webhooks), "results": results}


# ===========================================
# Audit Log
# ===========================================

@app.get("/audit-log", response_model=List[AuditLogResponse])
async def list_audit_log(
    company_id: Optional[int] = None,
    resource_type: Optional[str] = None,
    action: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """List audit log entries"""
    query = db.query(AuditLog)

    if company_id:
        query = query.filter(AuditLog.company_id == company_id)
    if resource_type:
        query = query.filter(AuditLog.resource_type == resource_type)
    if action:
        query = query.filter(AuditLog.action == action)

    return query.order_by(AuditLog.created_at.desc()).offset(skip).limit(limit).all()


# ===========================================
# External API (for external portal)
# ===========================================

from fastapi import Header, Security
from fastapi.security import APIKeyHeader

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_external_api_key(
    api_key: Optional[str] = Security(api_key_header),
    db: Session = Depends(get_db)
):
    """Verify API key for external access"""
    if not api_key:
        raise HTTPException(status_code=401, detail="API key required")

    # Find key by prefix
    prefix = api_key[:12] if len(api_key) >= 12 else api_key
    db_key = db.query(ApiKey).filter(
        ApiKey.key_prefix == prefix,
        ApiKey.is_active == True
    ).first()

    if not db_key:
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Verify full key
    if not verify_api_key(api_key, db_key.key_hash):
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Check expiration
    if db_key.expires_at and db_key.expires_at < datetime.utcnow():
        raise HTTPException(status_code=401, detail="API key expired")

    # Update usage stats
    db_key.last_used_at = datetime.utcnow()
    db_key.total_requests += 1
    db.commit()

    return db_key


# External API endpoints (accessible with API key)
@app.get("/api/v1/projects", response_model=List[ExternalProjectResponse])
async def external_list_projects(
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    api_key: ApiKey = Depends(verify_external_api_key),
    db: Session = Depends(get_db)
):
    """External API: List projects for company associated with API key"""
    query = db.query(Project).join(Company).filter(
        Company.id == api_key.company_id
    )

    if status:
        query = query.filter(Project.status == status)

    projects = query.offset(skip).limit(limit).all()

    company = db.query(Company).filter(Company.id == api_key.company_id).first()
    company_name = company.name if company else None

    return [
        ExternalProjectResponse(
            uuid=p.uuid,
            name=p.name,
            description=p.description,
            location_name=p.location_name,
            latitude=float(p.latitude) if p.latitude else None,
            longitude=float(p.longitude) if p.longitude else None,
            analysis_mode=p.analysis_mode,
            status=p.status,
            created_at=p.created_at,
            updated_at=p.updated_at,
            company_name=company_name
        )
        for p in projects
    ]


@app.get("/api/v1/projects/{project_uuid}/calculations", response_model=List[ExternalCalculationListResponse])
async def external_list_calculations(
    project_uuid: str,
    calc_type: Optional[str] = None,
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    api_key: ApiKey = Depends(verify_external_api_key),
    db: Session = Depends(get_db)
):
    """External API: List calculations for a project"""
    # Verify project belongs to company
    project = db.query(Project).join(Company).filter(
        Project.uuid == project_uuid,
        Company.id == api_key.company_id
    ).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    query = db.query(Calculation).filter(Calculation.project_id == project.id)

    if calc_type:
        query = query.filter(Calculation.calc_type == calc_type)
    if status:
        query = query.filter(Calculation.status == status)

    calcs = query.order_by(Calculation.created_at.desc()).offset(skip).limit(limit).all()

    result = []
    for c in calcs:
        metrics = db.query(CalculationMetric).filter(
            CalculationMetric.calculation_id == c.id
        ).all()
        metrics_dict = {m.metric_name: float(m.metric_value) if m.metric_value else None for m in metrics}

        result.append(ExternalCalculationListResponse(
            uuid=c.uuid,
            calc_type=c.calc_type,
            status=c.status,
            created_at=c.created_at,
            metrics=metrics_dict if metrics_dict else None
        ))

    return result


@app.get("/api/v1/calculations/{calc_uuid}", response_model=ExternalCalculationResponse)
async def external_get_calculation(
    calc_uuid: str,
    api_key: ApiKey = Depends(verify_external_api_key),
    db: Session = Depends(get_db)
):
    """External API: Get full calculation details"""
    # Find calculation and verify access
    calc = db.query(Calculation).join(Project).join(Company).filter(
        Calculation.uuid == calc_uuid,
        Company.id == api_key.company_id
    ).first()

    if not calc:
        raise HTTPException(status_code=404, detail="Calculation not found")

    # Get metrics
    metrics = db.query(CalculationMetric).filter(
        CalculationMetric.calculation_id == calc.id
    ).all()
    metrics_dict = {m.metric_name: float(m.metric_value) if m.metric_value else None for m in metrics}

    return ExternalCalculationResponse(
        uuid=calc.uuid,
        calc_type=calc.calc_type,
        status=calc.status,
        result_payload=calc.result_payload,
        metrics=metrics_dict if metrics_dict else None,
        duration_ms=calc.duration_ms,
        created_at=calc.created_at,
        completed_at=calc.completed_at
    )


@app.get("/api/v1/exports/{export_uuid}/download")
async def external_download_export(
    export_uuid: str,
    api_key: ApiKey = Depends(verify_external_api_key),
    db: Session = Depends(get_db)
):
    """External API: Download export file"""
    from fastapi.responses import Response

    # Find export and verify access
    export = db.query(Export).join(Project).join(Company).filter(
        Export.uuid == export_uuid,
        Company.id == api_key.company_id
    ).first()

    if not export:
        raise HTTPException(status_code=404, detail="Export not found")

    if not export.file_data:
        raise HTTPException(status_code=404, detail="File data not available")

    media_types = {
        'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'pdf': 'application/pdf',
        'csv': 'text/csv',
        'json': 'application/json'
    }

    return Response(
        content=export.file_data,
        media_type=media_types.get(export.file_type, 'application/octet-stream'),
        headers={
            'Content-Disposition': f'attachment; filename="{export.file_name}"'
        }
    )


# ===========================================
# Economics Snapshot V2 Endpoints
# ===========================================

from models import ProjectEconomicsSnapshot, ProjectEconomicsCashflowYearly
from schemas import (
    EconomicsSnapshotCreate, EconomicsSnapshotResponse,
    EconomicsSnapshotWithCashflows, EconomicsSnapshotSummary,
    EconomicsCashflowYearlyCreate
)


@app.post("/projects/{project_id}/economics-snapshot", response_model=EconomicsSnapshotResponse)
async def create_economics_snapshot(
    project_id: int,
    snapshot_data: EconomicsSnapshotCreate,
    db: Session = Depends(get_db)
):
    """Create a new economics snapshot for a project (investor-ready v2)"""
    # Verify project exists
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # =========================================================================
    # CASHFLOW VALIDATION - Model-specific year ranges
    # =========================================================================
    # Contract: Client analysis horizon = 30 years (CAPEX_CLIENT, EAAS_CLIENT)
    #           Investor horizon = EaaS contract duration (EAAS_INVESTOR, max 25 years)
    # =========================================================================
    CLIENT_ANALYSIS_PERIOD = 30  # Fixed for client models
    MAX_EAAS_DURATION = 25       # Max EaaS contract duration

    if snapshot_data.cashflows:
        eaas_duration = snapshot_data.eaas_client_duration_years or 10

        # Validate eaas_duration_years
        if eaas_duration > MAX_EAAS_DURATION:
            raise HTTPException(
                status_code=400,
                detail=f"EaaS duration {eaas_duration} exceeds maximum {MAX_EAAS_DURATION} years"
            )

        # Define expected year ranges per model type
        expected_ranges = {
            'CAPEX_CLIENT': (0, CLIENT_ANALYSIS_PERIOD),      # Years 0..30 (31 records)
            'EAAS_CLIENT': (1, CLIENT_ANALYSIS_PERIOD),       # Years 1..30 (30 records)
            'EAAS_INVESTOR': (0, eaas_duration),              # Years 0..duration (duration+1 records)
        }

        # Calculate max expected cashflows
        max_expected_cashflows = (
            (CLIENT_ANALYSIS_PERIOD + 1) +  # CAPEX_CLIENT: 31 records
            CLIENT_ANALYSIS_PERIOD +         # EAAS_CLIENT: 30 records
            (eaas_duration + 1)              # EAAS_INVESTOR: duration+1 records
        )

        if len(snapshot_data.cashflows) > max_expected_cashflows:
            raise HTTPException(
                status_code=400,
                detail=f"Too many cashflows: {len(snapshot_data.cashflows)} > max {max_expected_cashflows}"
            )

        # Collect years per model type
        model_years = {}
        for cf in snapshot_data.cashflows:
            model = cf.model_type.value
            if model not in model_years:
                model_years[model] = set()
            if cf.year in model_years[model]:
                raise HTTPException(
                    status_code=400,
                    detail=f"Duplicate year {cf.year} for model type {model}"
                )
            model_years[model].add(cf.year)

        # Validate each model type
        for model_type, years in model_years.items():
            if model_type not in expected_ranges:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unknown model type: {model_type}"
                )

            min_year, max_year = expected_ranges[model_type]

            # Check year range
            for year in years:
                if year < min_year or year > max_year:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Year {year} out of range [{min_year}, {max_year}] for {model_type}"
                    )

            # Validate year 0 exists for models that require it
            if model_type in ['CAPEX_CLIENT', 'EAAS_INVESTOR'] and 0 not in years:
                raise HTTPException(
                    status_code=400,
                    detail=f"Year 0 (initial investment) is required for {model_type}"
                )

            # Validate completeness (no gaps)
            expected_years = set(range(min_year, max_year + 1))
            missing_years = expected_years - years
            if missing_years:
                raise HTTPException(
                    status_code=400,
                    detail=f"Missing years {sorted(missing_years)} for {model_type}. "
                           f"Expected complete range [{min_year}, {max_year}]."
                )

        # Validate that if EAAS models exist, eaas_duration_years must be provided
        if ('EAAS_CLIENT' in model_years or 'EAAS_INVESTOR' in model_years):
            if not snapshot_data.eaas_client_duration_years:
                raise HTTPException(
                    status_code=400,
                    detail="eaas_client_duration_years is required when EAAS cashflows are provided"
                )

    # Determine next snapshot version
    latest = db.query(func.max(ProjectEconomicsSnapshot.snapshot_version)).filter(
        ProjectEconomicsSnapshot.project_id == project_id
    ).scalar() or 0

    # Create snapshot
    db_snapshot = ProjectEconomicsSnapshot(
        project_id=project_id,
        snapshot_version=latest + 1,
        production_scenario=snapshot_data.production_scenario,
        variant_key=snapshot_data.variant_key,
        pv_capacity_kwp=snapshot_data.pv_capacity_kwp,
        pv_type=snapshot_data.pv_type,
        bess_power_kw=snapshot_data.bess_power_kw or 0,
        bess_energy_kwh=snapshot_data.bess_energy_kwh or 0,
        analysis_period_years=snapshot_data.analysis_period_years,
        discount_rate_pct=snapshot_data.discount_rate_pct,
        inflation_rate_pct=snapshot_data.inflation_rate_pct or 2.50,
        # CAPEX Client
        capex_client_npv25=snapshot_data.capex_client_npv25,
        capex_client_irr=snapshot_data.capex_client_irr,
        capex_client_irr_mode=snapshot_data.capex_client_irr_mode or "real",
        capex_client_simple_payback=snapshot_data.capex_client_simple_payback,
        capex_client_discounted_payback=snapshot_data.capex_client_discounted_payback,
        capex_client_capex0_pln=snapshot_data.capex_client_capex0_pln,
        # CAPEX Deal
        capex_deal_sell_price_pln=snapshot_data.capex_deal_sell_price_pln,
        capex_deal_direct_cost_pln=snapshot_data.capex_deal_direct_cost_pln,
        capex_deal_gross_margin_pct=snapshot_data.capex_deal_gross_margin_pct,
        capex_deal_gross_margin_pln=snapshot_data.capex_deal_gross_margin_pln,
        # EaaS Client
        eaas_client_npv25=snapshot_data.eaas_client_npv25,
        eaas_client_duration_years=snapshot_data.eaas_client_duration_years or 10,
        eaas_client_subscription_annual=snapshot_data.eaas_client_subscription_annual,
        # EaaS Investor
        eaas_investor_npv25=snapshot_data.eaas_investor_npv25,
        eaas_investor_irr=snapshot_data.eaas_investor_irr,
        eaas_investor_capex0_pln=snapshot_data.eaas_investor_capex0_pln,
        eaas_investor_revenue_annual=snapshot_data.eaas_investor_revenue_annual,
        eaas_investor_opex_annual=snapshot_data.eaas_investor_opex_annual,
        # Full payload backup
        full_payload=snapshot_data.full_payload,
        created_by=snapshot_data.created_by
    )

    db.add(db_snapshot)
    db.flush()  # Get the ID

    # Add cashflows if provided
    if snapshot_data.cashflows:
        for cf in snapshot_data.cashflows:
            db_cf = ProjectEconomicsCashflowYearly(
                snapshot_id=db_snapshot.id,
                model_type=cf.model_type.value,
                year=cf.year,
                capex_pln=cf.capex_pln or 0,
                revenue_pln=cf.revenue_pln or 0,
                opex_pln=cf.opex_pln or 0,
                net_cashflow_pln=cf.net_cashflow_pln,
                cumulative_cashflow_pln=cf.cumulative_cashflow_pln,
                discounted_cashflow_pln=cf.discounted_cashflow_pln,
                cumulative_discounted_pln=cf.cumulative_discounted_pln,
                production_kwh=cf.production_kwh,
                self_consumed_kwh=cf.self_consumed_kwh,
                pv_degradation_pct=cf.pv_degradation_pct,
                bess_degradation_pct=cf.bess_degradation_pct
            )
            db.add(db_cf)

    db.commit()
    db.refresh(db_snapshot)
    return db_snapshot


@app.get("/projects/{project_id}/economics-snapshot", response_model=List[EconomicsSnapshotSummary])
async def get_project_economics_snapshots(
    project_id: int,
    db: Session = Depends(get_db)
):
    """Get all economics snapshots for a project"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return db.query(ProjectEconomicsSnapshot).filter(
        ProjectEconomicsSnapshot.project_id == project_id
    ).order_by(ProjectEconomicsSnapshot.created_at.desc()).all()


@app.get("/projects/{project_id}/economics-snapshot/latest", response_model=EconomicsSnapshotWithCashflows)
async def get_latest_economics_snapshot(
    project_id: int,
    db: Session = Depends(get_db)
):
    """Get the latest economics snapshot with cashflows"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    snapshot = db.query(ProjectEconomicsSnapshot).filter(
        ProjectEconomicsSnapshot.project_id == project_id
    ).order_by(ProjectEconomicsSnapshot.snapshot_version.desc()).first()

    if not snapshot:
        raise HTTPException(status_code=404, detail="No economics snapshot found for this project")

    return snapshot


@app.get("/economics-snapshot/{snapshot_id}", response_model=EconomicsSnapshotWithCashflows)
async def get_economics_snapshot_by_id(
    snapshot_id: int,
    db: Session = Depends(get_db)
):
    """Get a specific economics snapshot with cashflows by ID"""
    snapshot = db.query(ProjectEconomicsSnapshot).filter(
        ProjectEconomicsSnapshot.id == snapshot_id
    ).first()

    if not snapshot:
        raise HTTPException(status_code=404, detail="Economics snapshot not found")

    return snapshot


@app.delete("/economics-snapshot/{snapshot_id}")
async def delete_economics_snapshot(
    snapshot_id: int,
    db: Session = Depends(get_db)
):
    """Delete an economics snapshot"""
    snapshot = db.query(ProjectEconomicsSnapshot).filter(
        ProjectEconomicsSnapshot.id == snapshot_id
    ).first()

    if not snapshot:
        raise HTTPException(status_code=404, detail="Economics snapshot not found")

    db.delete(snapshot)
    db.commit()
    return {"status": "ok", "message": f"Snapshot {snapshot_id} deleted"}


# ===========================================
# Main
# ===========================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8050)
