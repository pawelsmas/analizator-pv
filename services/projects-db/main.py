"""
PV Optimizer Projects Database Service
Port: 8012

Manages project storage, retrieval, and export for external service integration.
"""
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime
import database

# Prometheus metrics
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI(
    title="PV Optimizer Projects API",
    description="Project storage and management for PV Optimizer",
    version="1.8.0"
)

# Initialize Prometheus metrics
Instrumentator().instrument(app).expose(app)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============== Pydantic Models ==============

class ProjectCreate(BaseModel):
    """Model for creating a new project"""
    project_name: str = Field(..., min_length=1, max_length=255, description="Project name")
    client_name: str = Field(..., min_length=1, max_length=255, description="Client name")
    client_nip: Optional[str] = Field(None, max_length=20, description="Client NIP (tax ID)")
    description: Optional[str] = Field(None, max_length=1000, description="Project description")

class ProjectUpdate(BaseModel):
    """Model for updating project"""
    project_name: Optional[str] = Field(None, max_length=255)
    client_name: Optional[str] = Field(None, max_length=255)
    client_nip: Optional[str] = Field(None, max_length=20)
    description: Optional[str] = Field(None, max_length=1000)
    status: Optional[str] = Field(None, pattern="^(active|archived|deleted)$")

class ProjectDataSave(BaseModel):
    """Model for saving project data"""
    data_type: str = Field(..., description="Type of data: consumption, pvConfig, analysisResults, hourlyData, settings, economics, masterVariant")
    data: Dict[str, Any] = Field(..., description="Data to save as JSON")

class FullProjectSave(BaseModel):
    """Model for saving complete project state"""
    project_name: str
    client_name: str
    client_nip: Optional[str] = None
    description: Optional[str] = None
    consumption_data: Optional[Dict[str, Any]] = None
    pv_config: Optional[Dict[str, Any]] = None
    analysis_results: Optional[Dict[str, Any]] = None
    hourly_data: Optional[Dict[str, Any]] = None
    settings: Optional[Dict[str, Any]] = None
    economics: Optional[Dict[str, Any]] = None
    master_variant: Optional[Dict[str, Any]] = None
    current_scenario: Optional[str] = "P50"

class ProjectResponse(BaseModel):
    """Response model for project"""
    id: int
    project_name: str
    client_name: str
    client_nip: Optional[str]
    description: Optional[str]
    status: str
    created_at: str
    updated_at: str

# ============== Startup Event ==============

@app.on_event("startup")
async def startup():
    """Initialize database on startup"""
    await database.init_db()
    print("Projects DB Service started on port 8012")

# ============== Health Check ==============

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "projects-db",
        "version": "1.8.0",
        "timestamp": datetime.now().isoformat()
    }

# ============== Project CRUD Endpoints ==============

@app.post("/projects", response_model=Dict[str, Any])
async def create_project(project: ProjectCreate):
    """Create a new project"""
    project_id = await database.create_project(
        project_name=project.project_name,
        client_name=project.client_name,
        client_nip=project.client_nip,
        description=project.description
    )
    return {
        "success": True,
        "project_id": project_id,
        "message": f"Project '{project.project_name}' created successfully"
    }

@app.get("/projects", response_model=Dict[str, Any])
async def list_projects(
    status: Optional[str] = Query(None, description="Filter by status: active, archived, deleted"),
    search: Optional[str] = Query(None, description="Search in name, client, NIP"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0)
):
    """List all projects with optional filtering"""
    projects = await database.get_all_projects(
        status=status,
        search=search,
        limit=limit,
        offset=offset
    )
    return {
        "success": True,
        "count": len(projects),
        "projects": projects
    }

@app.get("/projects/{project_id}", response_model=Dict[str, Any])
async def get_project(project_id: int):
    """Get project by ID"""
    project = await database.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return {
        "success": True,
        "project": project
    }

@app.put("/projects/{project_id}", response_model=Dict[str, Any])
async def update_project(project_id: int, project: ProjectUpdate):
    """Update project information"""
    success = await database.update_project(
        project_id=project_id,
        project_name=project.project_name,
        client_name=project.client_name,
        client_nip=project.client_nip,
        description=project.description,
        status=project.status
    )
    if not success:
        raise HTTPException(status_code=404, detail="Project not found or no changes made")
    return {
        "success": True,
        "message": "Project updated successfully"
    }

@app.delete("/projects/{project_id}", response_model=Dict[str, Any])
async def delete_project(project_id: int):
    """Delete project and all its data"""
    success = await database.delete_project(project_id)
    if not success:
        raise HTTPException(status_code=404, detail="Project not found")
    return {
        "success": True,
        "message": "Project deleted successfully"
    }

# ============== Project Data Endpoints ==============

@app.post("/projects/{project_id}/data", response_model=Dict[str, Any])
async def save_project_data(project_id: int, data: ProjectDataSave):
    """Save specific data type for project"""
    # Verify project exists
    project = await database.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    data_id = await database.save_project_data(
        project_id=project_id,
        data_type=data.data_type,
        data=data.data
    )
    return {
        "success": True,
        "data_id": data_id,
        "message": f"Data type '{data.data_type}' saved successfully"
    }

@app.get("/projects/{project_id}/data", response_model=Dict[str, Any])
async def get_project_data(
    project_id: int,
    data_type: Optional[str] = Query(None, description="Specific data type to retrieve")
):
    """Get project data, optionally filtered by type"""
    # Verify project exists
    project = await database.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    data = await database.get_project_data(project_id, data_type)
    return {
        "success": True,
        "project_id": project_id,
        "data": data
    }

# ============== Full Project Save/Load ==============

@app.post("/projects/save-full", response_model=Dict[str, Any])
async def save_full_project(project_data: FullProjectSave):
    """Save complete project state in one call"""
    # Create project
    project_id = await database.create_project(
        project_name=project_data.project_name,
        client_name=project_data.client_name,
        client_nip=project_data.client_nip,
        description=project_data.description
    )

    # Save all data types
    data_types = {
        'consumptionData': project_data.consumption_data,
        'pvConfig': project_data.pv_config,
        'analysisResults': project_data.analysis_results,
        'hourlyData': project_data.hourly_data,
        'settings': project_data.settings,
        'economics': project_data.economics,
        'masterVariant': project_data.master_variant,
        'currentScenario': {'scenario': project_data.current_scenario}
    }

    saved_types = []
    for data_type, data in data_types.items():
        if data is not None:
            await database.save_project_data(project_id, data_type, data)
            saved_types.append(data_type)

    return {
        "success": True,
        "project_id": project_id,
        "saved_data_types": saved_types,
        "message": f"Project '{project_data.project_name}' saved with {len(saved_types)} data types"
    }

@app.put("/projects/{project_id}/save-full", response_model=Dict[str, Any])
async def update_full_project(project_id: int, project_data: FullProjectSave):
    """Update existing project with complete state"""
    # Verify project exists
    project = await database.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Update project info
    await database.update_project(
        project_id=project_id,
        project_name=project_data.project_name,
        client_name=project_data.client_name,
        client_nip=project_data.client_nip,
        description=project_data.description
    )

    # Save all data types
    data_types = {
        'consumptionData': project_data.consumption_data,
        'pvConfig': project_data.pv_config,
        'analysisResults': project_data.analysis_results,
        'hourlyData': project_data.hourly_data,
        'settings': project_data.settings,
        'economics': project_data.economics,
        'masterVariant': project_data.master_variant,
        'currentScenario': {'scenario': project_data.current_scenario}
    }

    saved_types = []
    for data_type, data in data_types.items():
        if data is not None:
            await database.save_project_data(project_id, data_type, data)
            saved_types.append(data_type)

    return {
        "success": True,
        "project_id": project_id,
        "saved_data_types": saved_types,
        "message": f"Project updated with {len(saved_types)} data types"
    }

@app.get("/projects/{project_id}/load-full", response_model=Dict[str, Any])
async def load_full_project(project_id: int):
    """Load complete project state for restoring in frontend"""
    project = await database.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    data = await database.get_project_data(project_id)

    return {
        "success": True,
        "project": project,
        "rawConsumptionData": data.get('rawConsumptionData'),  # KLUCZOWE: surowe dane godzinowe
        "consumptionData": data.get('consumptionData'),
        "pvConfig": data.get('pvConfig'),
        "analysisResults": data.get('analysisResults'),
        "hourlyData": data.get('hourlyData'),
        "settings": data.get('settings'),
        "economics": data.get('economics'),
        "masterVariant": data.get('masterVariant'),
        "currentScenario": data.get('currentScenario', {}).get('scenario', 'P50')
    }

# ============== Export Endpoints (for external services) ==============

@app.get("/projects/{project_id}/export", response_model=Dict[str, Any])
async def export_project(project_id: int):
    """Export complete project for external services (EaaS, etc.)"""
    export_data = await database.get_full_project_export(project_id)
    if not export_data:
        raise HTTPException(status_code=404, detail="Project not found")
    return export_data

@app.get("/clients/{client_nip}/projects", response_model=Dict[str, Any])
async def get_client_projects(client_nip: str):
    """Get all projects for a specific client by NIP"""
    projects = await database.get_projects_by_nip(client_nip)
    return {
        "success": True,
        "client_nip": client_nip,
        "count": len(projects),
        "projects": projects
    }

# ============== Utility Endpoints ==============

@app.get("/data-types")
async def get_data_types():
    """Get list of supported data types"""
    return {
        "data_types": [
            {
                "key": "consumptionData",
                "description": "Raw consumption data from uploaded file",
                "source": "Data Analysis Service (8001)"
            },
            {
                "key": "pvConfig",
                "description": "PV system configuration (type, capacity, location, etc.)",
                "source": "Configuration Module"
            },
            {
                "key": "analysisResults",
                "description": "Full PV analysis results with variants A/B/C/D",
                "source": "PV Calculation Service (8002)"
            },
            {
                "key": "hourlyData",
                "description": "8760 hourly production/consumption values",
                "source": "PV Calculation Service (8002)"
            },
            {
                "key": "settings",
                "description": "Economic parameters (prices, tariffs, etc.)",
                "source": "Settings Module"
            },
            {
                "key": "economics",
                "description": "Economic analysis results (NPV, IRR, LCOE)",
                "source": "Economics Service (8003)"
            },
            {
                "key": "masterVariant",
                "description": "Selected master variant data",
                "source": "Comparison Module"
            },
            {
                "key": "currentScenario",
                "description": "Current P50/P75/P90 scenario",
                "source": "Production Module"
            }
        ]
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8012)
