"""
Projects API router for BESS API (v3.7.0).

Endpoints:
- GET /projects - List projects for current user
- POST /projects - Create new project (admin only)
- GET /projects/{project_id} - Get project details
- PATCH /projects/{project_id} - Update project settings (owner only)
- POST /projects/{project_id}/archive - Archive project (owner only)
- POST /projects/{project_id}/unarchive - Unarchive project (owner only)

Members:
- GET /projects/{project_id}/members - List project members
- POST /projects/{project_id}/members - Add member (owner only)
- PATCH /projects/{project_id}/members/{user_id} - Update member role (owner only)
- DELETE /projects/{project_id}/members/{user_id} - Remove member (owner only)

Current Project:
- Header: X-Project-Id
- Used for scoping runs, jobs, reports to specific project
"""

import sqlite3
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel

from auth_config import AuthContext, Role
from auth_deps import get_auth_context, require_role
from auth_store import get_auth_store, ProjectRole


router = APIRouter(prefix="/projects", tags=["projects"])


# -------------------------------------------------------------------------
# Request/Response models
# -------------------------------------------------------------------------

class ProjectResponse(BaseModel):
    """Project response."""
    id: str
    tenant_id: str
    name: str
    created_at: str
    archived_at: Optional[str] = None
    created_by_user_id: Optional[str] = None
    allow_public_shares: bool = True
    share_max_expiry_hours: Optional[int] = None
    role: Optional[str] = None  # User's role in project (if applicable)


class ProjectCreateRequest(BaseModel):
    """Request to create a new project."""
    name: str
    allow_public_shares: bool = True
    share_max_expiry_hours: Optional[int] = None


class ProjectUpdateRequest(BaseModel):
    """Request to update project settings."""
    name: Optional[str] = None
    allow_public_shares: Optional[bool] = None
    share_max_expiry_hours: Optional[int] = None


class ProjectListResponse(BaseModel):
    """Response for listing projects."""
    items: List[ProjectResponse]
    total: int


class MemberResponse(BaseModel):
    """Project member response."""
    id: str
    user_id: str
    user_email: str
    role: str
    created_at: str


class MemberAddRequest(BaseModel):
    """Request to add a member to project."""
    user_id: str
    role: str = "viewer"  # owner, editor, viewer


class MemberUpdateRequest(BaseModel):
    """Request to update member role."""
    role: str


class MemberListResponse(BaseModel):
    """Response for listing members."""
    items: List[MemberResponse]
    total: int


# -------------------------------------------------------------------------
# Helper: Get current project from header
# -------------------------------------------------------------------------

def get_project_id_header(
    x_project_id: Optional[str] = Header(None, alias="X-Project-Id"),
) -> Optional[str]:
    """Extract project ID from X-Project-Id header."""
    return x_project_id


def require_project_access(
    min_role: Optional[ProjectRole] = None,
):
    """
    Create a dependency that requires project access with optional minimum role.

    Usage:
        @router.get("/", dependencies=[Depends(require_project_access(ProjectRole.EDITOR))])
    """
    def project_checker(
        project_id: str,
        auth: AuthContext = Depends(get_auth_context),
    ) -> str:
        auth_store = get_auth_store()

        # Check if project exists in tenant
        project = auth_store.get_project(project_id, auth.tenant_id)
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error_code": "PROJECT_NOT_FOUND", "message": "Project not found"},
            )

        # Check user's project access
        if auth.user_id:
            if not auth_store.user_has_project_access(auth.user_id, project_id, min_role):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={"error_code": "PROJECT_ACCESS_DENIED", "message": "Insufficient project permissions"},
                )

        return project_id

    return project_checker


# -------------------------------------------------------------------------
# Project CRUD Endpoints
# -------------------------------------------------------------------------

@router.get("", response_model=ProjectListResponse)
def list_projects(
    include_archived: bool = False,
    auth: AuthContext = Depends(get_auth_context),
):
    """
    List projects the current user has access to.

    For admins: lists all projects in tenant.
    For regular users: lists only projects they are members of.
    """
    auth_store = get_auth_store()

    # Admin sees all projects in tenant
    if auth.role == Role.ADMIN or auth.user_id is None:
        projects = auth_store.list_projects(auth.tenant_id, include_archived=include_archived)
        items = [
            ProjectResponse(
                id=p["id"],
                tenant_id=p["tenant_id"],
                name=p["name"],
                created_at=p["created_at"],
                archived_at=p["archived_at"],
                created_by_user_id=p["created_by_user_id"],
                allow_public_shares=p["allow_public_shares"],
                share_max_expiry_hours=p["share_max_expiry_hours"],
            )
            for p in projects
        ]
    else:
        # Regular user sees only their projects (with role)
        projects = auth_store.list_user_projects(auth.user_id, auth.tenant_id)
        items = [
            ProjectResponse(
                id=p["id"],
                tenant_id=p["tenant_id"],
                name=p["name"],
                created_at=p["created_at"],
                archived_at=p["archived_at"],
                created_by_user_id=p["created_by_user_id"],
                allow_public_shares=p["allow_public_shares"],
                share_max_expiry_hours=p["share_max_expiry_hours"],
                role=p["role"],
            )
            for p in projects
        ]

    return ProjectListResponse(items=items, total=len(items))


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(
    request: ProjectCreateRequest,
    auth: AuthContext = Depends(require_role(Role.ADMIN)),
):
    """
    Create a new project.

    Requires admin role.
    The creating user is automatically added as project owner.
    """
    auth_store = get_auth_store()

    # Check for duplicate name
    if auth_store.project_name_exists(request.name, auth.tenant_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": "PROJECT_NAME_EXISTS", "message": f"Project '{request.name}' already exists"},
        )

    # Create project
    project = auth_store.create_project(
        tenant_id=auth.tenant_id,
        name=request.name,
        created_by_user_id=auth.user_id,
        allow_public_shares=request.allow_public_shares,
        share_max_expiry_hours=request.share_max_expiry_hours,
    )

    # Add creator as owner if they have a user_id
    if auth.user_id:
        try:
            auth_store.add_project_member(
                tenant_id=auth.tenant_id,
                project_id=project["id"],
                user_id=auth.user_id,
                role=ProjectRole.OWNER,
            )
        except sqlite3.IntegrityError:
            pass  # Already a member (shouldn't happen)

    return ProjectResponse(
        id=project["id"],
        tenant_id=project["tenant_id"],
        name=project["name"],
        created_at=project["created_at"],
        archived_at=project["archived_at"],
        created_by_user_id=project["created_by_user_id"],
        allow_public_shares=project["allow_public_shares"],
        share_max_expiry_hours=project["share_max_expiry_hours"],
        role="owner" if auth.user_id else None,
    )


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: str,
    auth: AuthContext = Depends(get_auth_context),
):
    """
    Get project details.

    User must have access to the project or be an admin.
    """
    auth_store = get_auth_store()

    project = auth_store.get_project(project_id, auth.tenant_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "PROJECT_NOT_FOUND", "message": "Project not found"},
        )

    # Check access (admin or member)
    role = None
    if auth.user_id:
        membership = auth_store.get_project_membership(project_id, auth.user_id)
        if membership:
            role = membership["role"]
        elif auth.role != Role.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error_code": "PROJECT_ACCESS_DENIED", "message": "You don't have access to this project"},
            )

    return ProjectResponse(
        id=project["id"],
        tenant_id=project["tenant_id"],
        name=project["name"],
        created_at=project["created_at"],
        archived_at=project["archived_at"],
        created_by_user_id=project["created_by_user_id"],
        allow_public_shares=project["allow_public_shares"],
        share_max_expiry_hours=project["share_max_expiry_hours"],
        role=role,
    )


@router.patch("/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: str,
    request: ProjectUpdateRequest,
    auth: AuthContext = Depends(get_auth_context),
):
    """
    Update project settings.

    Requires project owner role or tenant admin.
    """
    auth_store = get_auth_store()

    project = auth_store.get_project(project_id, auth.tenant_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "PROJECT_NOT_FOUND", "message": "Project not found"},
        )

    # Check permission (owner or admin)
    role = None
    if auth.user_id:
        membership = auth_store.get_project_membership(project_id, auth.user_id)
        if membership:
            role = membership["role"]

        if role != "owner" and auth.role != Role.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error_code": "OWNER_REQUIRED", "message": "Project owner role required"},
            )

    # Check for duplicate name (if changing)
    if request.name and request.name != project["name"]:
        if auth_store.project_name_exists(request.name, auth.tenant_id, exclude_project_id=project_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error_code": "PROJECT_NAME_EXISTS", "message": f"Project '{request.name}' already exists"},
            )

    updated = auth_store.update_project(
        project_id=project_id,
        tenant_id=auth.tenant_id,
        name=request.name,
        allow_public_shares=request.allow_public_shares,
        share_max_expiry_hours=request.share_max_expiry_hours,
    )

    return ProjectResponse(
        id=updated["id"],
        tenant_id=updated["tenant_id"],
        name=updated["name"],
        created_at=updated["created_at"],
        archived_at=updated["archived_at"],
        created_by_user_id=updated["created_by_user_id"],
        allow_public_shares=updated["allow_public_shares"],
        share_max_expiry_hours=updated["share_max_expiry_hours"],
        role=role,
    )


@router.post("/{project_id}/archive", status_code=status.HTTP_204_NO_CONTENT)
def archive_project(
    project_id: str,
    auth: AuthContext = Depends(get_auth_context),
):
    """
    Archive a project.

    Requires project owner role or tenant admin.
    """
    auth_store = get_auth_store()

    project = auth_store.get_project(project_id, auth.tenant_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "PROJECT_NOT_FOUND", "message": "Project not found"},
        )

    # Check permission
    if auth.user_id:
        if not auth_store.user_has_project_access(auth.user_id, project_id, ProjectRole.OWNER):
            if auth.role != Role.ADMIN:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={"error_code": "OWNER_REQUIRED", "message": "Project owner role required"},
                )

    auth_store.archive_project(project_id, auth.tenant_id)


@router.post("/{project_id}/unarchive", status_code=status.HTTP_204_NO_CONTENT)
def unarchive_project(
    project_id: str,
    auth: AuthContext = Depends(get_auth_context),
):
    """
    Unarchive a project.

    Requires project owner role or tenant admin.
    """
    auth_store = get_auth_store()

    project = auth_store.get_project(project_id, auth.tenant_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "PROJECT_NOT_FOUND", "message": "Project not found"},
        )

    # Check permission
    if auth.user_id:
        if not auth_store.user_has_project_access(auth.user_id, project_id, ProjectRole.OWNER):
            if auth.role != Role.ADMIN:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={"error_code": "OWNER_REQUIRED", "message": "Project owner role required"},
                )

    auth_store.unarchive_project(project_id, auth.tenant_id)


# -------------------------------------------------------------------------
# Member Management Endpoints
# -------------------------------------------------------------------------

@router.get("/{project_id}/members", response_model=MemberListResponse)
def list_members(
    project_id: str,
    auth: AuthContext = Depends(get_auth_context),
):
    """
    List project members.

    Any project member can view the member list.
    """
    auth_store = get_auth_store()

    project = auth_store.get_project(project_id, auth.tenant_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "PROJECT_NOT_FOUND", "message": "Project not found"},
        )

    # Check access
    if auth.user_id and auth.role != Role.ADMIN:
        if not auth_store.user_has_project_access(auth.user_id, project_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error_code": "PROJECT_ACCESS_DENIED", "message": "You don't have access to this project"},
            )

    members = auth_store.list_project_members(project_id)
    items = [
        MemberResponse(
            id=m["id"],
            user_id=m["user_id"],
            user_email=m["user_email"],
            role=m["role"],
            created_at=m["created_at"],
        )
        for m in members
    ]

    return MemberListResponse(items=items, total=len(items))


@router.post("/{project_id}/members", response_model=MemberResponse, status_code=status.HTTP_201_CREATED)
def add_member(
    project_id: str,
    request: MemberAddRequest,
    auth: AuthContext = Depends(get_auth_context),
):
    """
    Add a member to the project.

    Requires project owner role or tenant admin.
    """
    auth_store = get_auth_store()

    project = auth_store.get_project(project_id, auth.tenant_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "PROJECT_NOT_FOUND", "message": "Project not found"},
        )

    # Check permission
    if auth.user_id:
        if not auth_store.user_has_project_access(auth.user_id, project_id, ProjectRole.OWNER):
            if auth.role != Role.ADMIN:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={"error_code": "OWNER_REQUIRED", "message": "Project owner role required"},
                )

    # Validate role
    try:
        role = ProjectRole(request.role)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "INVALID_ROLE", "message": f"Invalid role: {request.role}. Must be owner, editor, or viewer"},
        )

    # Verify user exists in tenant
    user = auth_store.get_user_by_id(request.user_id)
    if user is None or user["tenant_id"] != auth.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "USER_NOT_FOUND", "message": "User not found in tenant"},
        )

    # Add member
    try:
        membership = auth_store.add_project_member(
            tenant_id=auth.tenant_id,
            project_id=project_id,
            user_id=request.user_id,
            role=role,
        )
    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": "ALREADY_MEMBER", "message": "User is already a project member"},
        )

    return MemberResponse(
        id=membership["id"],
        user_id=membership["user_id"],
        user_email=user["email"],
        role=membership["role"],
        created_at=membership["created_at"],
    )


@router.patch("/{project_id}/members/{user_id}", response_model=MemberResponse)
def update_member(
    project_id: str,
    user_id: str,
    request: MemberUpdateRequest,
    auth: AuthContext = Depends(get_auth_context),
):
    """
    Update a member's role.

    Requires project owner role or tenant admin.
    Cannot demote the last owner.
    """
    auth_store = get_auth_store()

    project = auth_store.get_project(project_id, auth.tenant_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "PROJECT_NOT_FOUND", "message": "Project not found"},
        )

    # Check permission
    if auth.user_id:
        if not auth_store.user_has_project_access(auth.user_id, project_id, ProjectRole.OWNER):
            if auth.role != Role.ADMIN:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={"error_code": "OWNER_REQUIRED", "message": "Project owner role required"},
                )

    # Validate new role
    try:
        new_role = ProjectRole(request.role)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "INVALID_ROLE", "message": f"Invalid role: {request.role}"},
        )

    # Get current membership
    membership = auth_store.get_project_membership(project_id, user_id)
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "MEMBER_NOT_FOUND", "message": "User is not a project member"},
        )

    # Prevent demoting last owner
    if membership["role"] == "owner" and new_role != ProjectRole.OWNER:
        owner_count = auth_store.count_project_owners(project_id)
        if owner_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error_code": "LAST_OWNER", "message": "Cannot demote the last project owner"},
            )

    auth_store.update_project_member_role(project_id, user_id, new_role)

    # Get user email
    user = auth_store.get_user_by_id(user_id)

    return MemberResponse(
        id=membership["id"],
        user_id=user_id,
        user_email=user["email"] if user else "unknown",
        role=new_role.value,
        created_at=membership["created_at"],
    )


@router.delete("/{project_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    project_id: str,
    user_id: str,
    auth: AuthContext = Depends(get_auth_context),
):
    """
    Remove a member from the project.

    Requires project owner role or tenant admin.
    Cannot remove the last owner.
    """
    auth_store = get_auth_store()

    project = auth_store.get_project(project_id, auth.tenant_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "PROJECT_NOT_FOUND", "message": "Project not found"},
        )

    # Check permission
    if auth.user_id:
        if not auth_store.user_has_project_access(auth.user_id, project_id, ProjectRole.OWNER):
            if auth.role != Role.ADMIN:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={"error_code": "OWNER_REQUIRED", "message": "Project owner role required"},
                )

    # Get membership
    membership = auth_store.get_project_membership(project_id, user_id)
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "MEMBER_NOT_FOUND", "message": "User is not a project member"},
        )

    # Prevent removing last owner
    if membership["role"] == "owner":
        owner_count = auth_store.count_project_owners(project_id)
        if owner_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error_code": "LAST_OWNER", "message": "Cannot remove the last project owner"},
            )

    auth_store.remove_project_member(project_id, user_id)


# -------------------------------------------------------------------------
# Default Project Backfill Endpoint (Admin only)
# -------------------------------------------------------------------------

class BackfillResponse(BaseModel):
    """Response from backfill operation."""
    project_id: str
    project_name: str
    members_added: int
    already_existed: bool


@router.post("/backfill-default", response_model=BackfillResponse)
def backfill_default_project(
    auth: AuthContext = Depends(require_role(Role.ADMIN)),
):
    """
    Create default project for tenant and add all users as owners.

    Idempotent - safe to call multiple times.
    Requires admin role.
    """
    auth_store = get_auth_store()

    result = auth_store.backfill_default_project(
        tenant_id=auth.tenant_id,
        created_by_user_id=auth.user_id,
    )

    return BackfillResponse(
        project_id=result["project"]["id"],
        project_name=result["project"]["name"],
        members_added=result["members_added"],
        already_existed=result["already_existed"],
    )
