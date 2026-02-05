"""
Webhooks API router for BESS API (v4.1.0).

Endpoints:
- GET /webhooks - List webhooks for tenant/project
- POST /webhooks - Create webhook (admin only)
- GET /webhooks/{webhook_id} - Get webhook details
- PATCH /webhooks/{webhook_id} - Update webhook
- DELETE /webhooks/{webhook_id} - Delete webhook
- POST /webhooks/{webhook_id}/rotate-secret - Rotate webhook secret

RBAC:
- Admin: full access to all webhooks in tenant
- Project owner/editor: manage project-scoped webhooks
- Viewer: read-only access to project webhooks
"""

import secrets
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Header, status
from pydantic import BaseModel, HttpUrl

from auth_config import AuthContext, Role
from auth_deps import get_auth_context, require_role
from auth_store import get_auth_store, ProjectRole
from webhook_store import WebhookStore, Webhook


router = APIRouter(prefix="/webhooks", tags=["webhooks"])


# -------------------------------------------------------------------------
# Events endpoint (for discovery) - must be before /{webhook_id} routes
# -------------------------------------------------------------------------

class EventInfo(BaseModel):
    """Event type info."""
    name: str
    description: str


class EventsListResponse(BaseModel):
    """Response for listing events."""
    events: List[EventInfo]


EVENT_DESCRIPTIONS = {
    "job.succeeded": "Fired when a sizing/validation job completes successfully",
    "job.failed": "Fired when a sizing/validation job fails",
    "report.generated": "Fired when a PDF report is generated",
    "share.accessed": "Fired when a shared link is accessed",
    "quota.exceeded": "Fired when a usage quota is exceeded (once per day per quota)",
    "run.created": "Fired when a new sizing run is created",
}


@router.get("/events/types", response_model=EventsListResponse)
def list_event_types():
    """
    List supported webhook event types.

    Public endpoint - no authentication required.
    """
    events = [
        EventInfo(name=name, description=EVENT_DESCRIPTIONS.get(name, ""))
        for name in SUPPORTED_EVENTS
    ]
    return EventsListResponse(events=events)


# -------------------------------------------------------------------------
# Singleton for webhook store
# -------------------------------------------------------------------------

_webhook_store: Optional[WebhookStore] = None


def get_webhook_store() -> WebhookStore:
    """Get or create webhook store singleton."""
    global _webhook_store
    if _webhook_store is None:
        _webhook_store = WebhookStore()
    return _webhook_store


def set_webhook_store(store: WebhookStore):
    """Set webhook store (for testing)."""
    global _webhook_store
    _webhook_store = store


# -------------------------------------------------------------------------
# Supported events
# -------------------------------------------------------------------------

SUPPORTED_EVENTS = [
    "job.succeeded",
    "job.failed",
    "report.generated",
    "share.accessed",
    "quota.exceeded",
    "run.created",
]


# -------------------------------------------------------------------------
# Request/Response models
# -------------------------------------------------------------------------

class WebhookResponse(BaseModel):
    """Webhook response."""
    id: str
    tenant_id: str
    project_id: Optional[str]
    name: str
    url: str
    events: List[str]
    enabled: bool
    secret_version: int
    created_at: str
    updated_at: str
    last_delivery_at: Optional[str] = None


class WebhookCreateRequest(BaseModel):
    """Request to create a webhook."""
    name: str
    url: str
    events: List[str]
    enabled: bool = True


class WebhookCreateResponse(BaseModel):
    """Response after creating webhook (includes secret)."""
    webhook: WebhookResponse
    secret: str  # Only returned on create and rotate


class WebhookUpdateRequest(BaseModel):
    """Request to update webhook."""
    name: Optional[str] = None
    url: Optional[str] = None
    events: Optional[List[str]] = None
    enabled: Optional[bool] = None


class WebhookListResponse(BaseModel):
    """Response for listing webhooks."""
    items: List[WebhookResponse]
    total: int


class RotateSecretResponse(BaseModel):
    """Response after rotating secret."""
    webhook_id: str
    secret: str
    secret_version: int


# -------------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------------

def webhook_to_response(webhook: Webhook) -> WebhookResponse:
    """Convert Webhook dataclass to response model."""
    return WebhookResponse(
        id=webhook.id,
        tenant_id=webhook.tenant_id,
        project_id=webhook.project_id,
        name=webhook.name,
        url=webhook.url,
        events=webhook.events,
        enabled=webhook.enabled,
        secret_version=webhook.secret_version,
        created_at=webhook.created_at,
        updated_at=webhook.updated_at,
        last_delivery_at=webhook.last_delivery_at,
    )


def validate_events(events: List[str]) -> None:
    """Validate that all events are supported."""
    invalid = [e for e in events if e not in SUPPORTED_EVENTS]
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "INVALID_EVENTS",
                "message": f"Invalid events: {invalid}. Supported: {SUPPORTED_EVENTS}",
            },
        )


def check_webhook_access(
    webhook: Webhook,
    auth: AuthContext,
    require_write: bool = False,
) -> None:
    """
    Check if user has access to webhook.

    Args:
        webhook: The webhook to check access for
        auth: Auth context
        require_write: If True, require write access (editor+)

    Raises:
        HTTPException 403 if access denied
    """
    # Admin always has access
    if auth.role == Role.ADMIN:
        return

    # Tenant-wide webhooks require admin
    if webhook.project_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "ADMIN_REQUIRED",
                "message": "Admin role required for tenant-wide webhooks",
            },
        )

    # Project-scoped: check project membership
    if auth.user_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "PROJECT_ACCESS_DENIED",
                "message": "Project access required",
            },
        )

    auth_store = get_auth_store()
    min_role = ProjectRole.EDITOR if require_write else None

    if not auth_store.user_has_project_access(auth.user_id, webhook.project_id, min_role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "PROJECT_ACCESS_DENIED",
                "message": "Insufficient project permissions" if require_write else "You don't have access to this project",
            },
        )


# -------------------------------------------------------------------------
# Endpoints
# -------------------------------------------------------------------------

@router.get("", response_model=WebhookListResponse)
def list_webhooks(
    project_id: Optional[str] = None,
    include_tenant_wide: bool = True,
    x_project_id: Optional[str] = Header(None, alias="X-Project-Id"),
    auth: AuthContext = Depends(get_auth_context),
):
    """
    List webhooks for tenant or project.

    - Admin: sees all webhooks in tenant
    - Project member: sees webhooks for their projects
    - If X-Project-Id header or project_id param is provided, filters by project
    - If include_tenant_wide=True (default), also includes tenant-wide webhooks
    """
    webhook_store = get_webhook_store()

    # Use header if query param not provided
    effective_project_id = project_id or x_project_id

    # Non-admin must provide project_id
    if auth.role != Role.ADMIN and effective_project_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "PROJECT_REQUIRED",
                "message": "Project ID required for non-admin users",
            },
        )

    # Check project access if project-scoped
    if effective_project_id and auth.role != Role.ADMIN:
        auth_store = get_auth_store()
        if auth.user_id is None or not auth_store.user_has_project_access(auth.user_id, effective_project_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error_code": "PROJECT_ACCESS_DENIED",
                    "message": "You don't have access to this project",
                },
            )

    webhooks = webhook_store.list_webhooks(
        tenant_id=auth.tenant_id,
        project_id=effective_project_id,
        include_tenant_wide=include_tenant_wide,
    )

    items = [webhook_to_response(w) for w in webhooks]
    return WebhookListResponse(items=items, total=len(items))


@router.post("", response_model=WebhookCreateResponse, status_code=status.HTTP_201_CREATED)
def create_webhook(
    request: WebhookCreateRequest,
    project_id: Optional[str] = None,
    x_project_id: Optional[str] = Header(None, alias="X-Project-Id"),
    auth: AuthContext = Depends(get_auth_context),
):
    """
    Create a new webhook.

    - Tenant-wide webhooks (no project_id) require admin role
    - Project-scoped webhooks require editor role in that project
    """
    webhook_store = get_webhook_store()

    # Use header if query param not provided
    effective_project_id = project_id or x_project_id

    # Validate events
    validate_events(request.events)

    if not request.events:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "EVENTS_REQUIRED",
                "message": "At least one event is required",
            },
        )

    # Check permissions
    if effective_project_id is None:
        # Tenant-wide: admin only
        if auth.role != Role.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error_code": "ADMIN_REQUIRED",
                    "message": "Admin role required for tenant-wide webhooks",
                },
            )
    else:
        # Project-scoped: check project access (editor+)
        auth_store = get_auth_store()

        # Check project exists
        project = auth_store.get_project(effective_project_id, auth.tenant_id)
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error_code": "PROJECT_NOT_FOUND",
                    "message": "Project not found",
                },
            )

        # Non-admin needs editor role
        if auth.role != Role.ADMIN:
            if auth.user_id is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        "error_code": "PROJECT_ACCESS_DENIED",
                        "message": "Project access required",
                    },
                )

            if not auth_store.user_has_project_access(auth.user_id, effective_project_id, ProjectRole.EDITOR):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        "error_code": "EDITOR_REQUIRED",
                        "message": "Editor role required to create webhooks",
                    },
                )

    # Create webhook
    webhook, secret = webhook_store.create_webhook(
        tenant_id=auth.tenant_id,
        name=request.name,
        url=request.url,
        events=request.events,
        project_id=effective_project_id,
        enabled=request.enabled,
    )

    return WebhookCreateResponse(
        webhook=webhook_to_response(webhook),
        secret=secret,
    )


@router.get("/{webhook_id}", response_model=WebhookResponse)
def get_webhook(
    webhook_id: str,
    auth: AuthContext = Depends(get_auth_context),
):
    """
    Get webhook details.

    Requires access to the project (for project-scoped) or admin (for tenant-wide).
    """
    webhook_store = get_webhook_store()

    webhook = webhook_store.get_webhook(webhook_id, auth.tenant_id)
    if webhook is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "WEBHOOK_NOT_FOUND",
                "message": "Webhook not found",
            },
        )

    check_webhook_access(webhook, auth, require_write=False)

    return webhook_to_response(webhook)


@router.patch("/{webhook_id}", response_model=WebhookResponse)
def update_webhook(
    webhook_id: str,
    request: WebhookUpdateRequest,
    auth: AuthContext = Depends(get_auth_context),
):
    """
    Update webhook settings.

    Requires editor access to the project (for project-scoped) or admin (for tenant-wide).
    """
    webhook_store = get_webhook_store()

    webhook = webhook_store.get_webhook(webhook_id, auth.tenant_id)
    if webhook is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "WEBHOOK_NOT_FOUND",
                "message": "Webhook not found",
            },
        )

    check_webhook_access(webhook, auth, require_write=True)

    # Validate events if provided
    if request.events is not None:
        validate_events(request.events)
        if not request.events:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error_code": "EVENTS_REQUIRED",
                    "message": "At least one event is required",
                },
            )

    updated = webhook_store.update_webhook(
        webhook_id=webhook_id,
        tenant_id=auth.tenant_id,
        name=request.name,
        url=request.url,
        events=request.events,
        enabled=request.enabled,
    )

    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "WEBHOOK_NOT_FOUND",
                "message": "Webhook not found",
            },
        )

    return webhook_to_response(updated)


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_webhook(
    webhook_id: str,
    auth: AuthContext = Depends(get_auth_context),
):
    """
    Delete a webhook.

    Requires editor access to the project (for project-scoped) or admin (for tenant-wide).
    """
    webhook_store = get_webhook_store()

    webhook = webhook_store.get_webhook(webhook_id, auth.tenant_id)
    if webhook is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "WEBHOOK_NOT_FOUND",
                "message": "Webhook not found",
            },
        )

    check_webhook_access(webhook, auth, require_write=True)

    webhook_store.delete_webhook(webhook_id, auth.tenant_id)


@router.post("/{webhook_id}/rotate-secret", response_model=RotateSecretResponse)
def rotate_webhook_secret(
    webhook_id: str,
    auth: AuthContext = Depends(get_auth_context),
):
    """
    Rotate webhook secret.

    Generates a new secret and increments secret_version.
    The old secret becomes invalid immediately.

    Requires editor access to the project (for project-scoped) or admin (for tenant-wide).
    """
    webhook_store = get_webhook_store()

    webhook = webhook_store.get_webhook(webhook_id, auth.tenant_id)
    if webhook is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "WEBHOOK_NOT_FOUND",
                "message": "Webhook not found",
            },
        )

    check_webhook_access(webhook, auth, require_write=True)

    new_secret, new_version = webhook_store.rotate_secret(webhook_id, auth.tenant_id)
    if new_secret is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "WEBHOOK_NOT_FOUND",
                "message": "Webhook not found",
            },
        )

    return RotateSecretResponse(
        webhook_id=webhook_id,
        secret=new_secret,
        secret_version=new_version,
    )
