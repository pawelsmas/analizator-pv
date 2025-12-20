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
    PriceScenario, PriceData, AnalysisResult, AnalysisMode
)
from schemas import (
    CompanyCreate, CompanyUpdate, CompanyResponse, CompanyWithProjects,
    ProjectCreate, ProjectUpdate, ProjectResponse, ProjectWithCompany,
    EnergyProfileCreate, EnergyProfileResponse, ProfileDataResponse,
    PriceScenarioCreate, PriceScenarioResponse,
    AnalysisResultCreate, AnalysisResultResponse,
    AnalysisModeResponse, DatabaseStats, ProjectSummary,
    BulkProfileImport, BulkPriceImport
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
    Upload TGE (Towarowa Giełda Energii) price scenario from CSV.

    Supports multiple TGE CSV formats:
    1. Standard TGE export: Data, Godzina, Cena (PLN/MWh)
    2. RDN format: timestamp, fixing_i_price, fixing_ii_price
    3. Simple format: timestamp/datetime, price/cena

    Returns scenario ID and statistics.
    """
    content = await file.read()

    # Try different encodings for TGE files
    for encoding in ['utf-8', 'cp1250', 'latin1']:
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise HTTPException(status_code=400, detail="Cannot decode CSV file")

    # Parse CSV with flexible column detection
    df = pd.read_csv(StringIO(text), sep=None, engine='python')

    # Detect date/time columns
    date_col = None
    hour_col = None
    price_col = None

    col_lower = {c.lower(): c for c in df.columns}

    # Date column detection
    for name_pattern in ['data', 'date', 'datetime', 'timestamp', 'dzien']:
        for key, col in col_lower.items():
            if name_pattern in key:
                date_col = col
                break
        if date_col:
            break

    # Hour column detection (TGE specific)
    for name_pattern in ['godzina', 'hour', 'godz']:
        for key, col in col_lower.items():
            if name_pattern in key:
                hour_col = col
                break
        if hour_col:
            break

    # Price column detection
    for name_pattern in ['cena', 'price', 'pln', 'fixing', 'kurs']:
        for key, col in col_lower.items():
            if name_pattern in key and 'buy' not in key:
                price_col = col
                break
        if price_col:
            break

    if not price_col:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot find price column. Available columns: {list(df.columns)}"
        )

    # Parse timestamps
    timestamps = []
    if date_col and hour_col:
        # TGE format: separate date and hour columns
        for _, row in df.iterrows():
            try:
                date_str = str(row[date_col])
                hour_val = row[hour_col]
                # Parse date
                for fmt in ['%Y-%m-%d', '%d.%m.%Y', '%d/%m/%Y']:
                    try:
                        dt = datetime.strptime(date_str.split()[0], fmt)
                        break
                    except ValueError:
                        continue
                else:
                    continue
                # Parse hour (TGE uses 1-24, we need 0-23)
                hour = int(hour_val) - 1 if int(hour_val) > 0 else 0
                ts = dt.replace(hour=min(hour, 23))
                timestamps.append(ts)
            except (ValueError, KeyError):
                continue
    elif date_col:
        # Single datetime column
        for _, row in df.iterrows():
            try:
                ts = pd.to_datetime(row[date_col])
                timestamps.append(ts.to_pydatetime())
            except:
                continue
    else:
        # No date columns - assume hourly from Jan 1
        start_date = datetime(year, 1, 1)
        timestamps = [start_date + timedelta(hours=i) for i in range(len(df))]

    # Extract prices
    prices = pd.to_numeric(df[price_col], errors='coerce').dropna().tolist()

    if len(prices) < 24:
        raise HTTPException(status_code=400, detail=f"Too few valid prices: {len(prices)}")

    # Match lengths
    min_len = min(len(timestamps), len(prices))
    timestamps = timestamps[:min_len]
    prices = prices[:min_len]

    # Create scenario
    db_scenario = PriceScenario(
        name=name,
        description=f"TGE import: {file.filename}",
        scenario_type=scenario_type,
        source="tge_csv",
        year=year,
        avg_price=float(np.mean(prices)),
        min_price=float(np.min(prices)),
        max_price=float(np.max(prices))
    )
    db.add(db_scenario)
    db.flush()

    # Insert price data in batches
    batch_size = 1000
    for i in range(0, len(timestamps), batch_size):
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
        "data_points": len(prices),
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

    # Build hourly price array
    prices_dict = {d.timestamp: float(d.price_pln_mwh) for d in data_points}

    # Get year from first data point
    year = data_points[0].timestamp.year
    start = datetime(year, 1, 1)

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
# Main
# ===========================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8050)
