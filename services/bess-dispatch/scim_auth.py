"""
SCIM authentication middleware (v4.4.0 PR2).

Validates SCIM bearer tokens for /scim/v2 endpoints.
"""

from functools import wraps
from typing import Callable, Optional

from flask import g, jsonify, request

from scim_store import ScimStore, hash_scim_token


def get_scim_store() -> ScimStore:
    """Get or create ScimStore instance."""
    if not hasattr(g, "scim_store"):
        g.scim_store = ScimStore()
    return g.scim_store


def extract_bearer_token() -> Optional[str]:
    """Extract bearer token from Authorization header."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    return auth_header[7:]  # Remove "Bearer " prefix


def validate_scim_token(token: str) -> Optional[str]:
    """
    Validate a SCIM bearer token.

    Returns:
        tenant_id if valid, None otherwise
    """
    store = get_scim_store()
    token_hash = hash_scim_token(token)
    token_record = store.get_scim_token_by_hash(token_hash)

    if not token_record:
        return None

    # Update last_used_at
    store.update_scim_token_last_used(token_record["id"])

    return token_record["tenant_id"]


def require_scim_token(f: Callable) -> Callable:
    """
    Decorator to require valid SCIM bearer token.

    Sets g.scim_tenant_id on successful auth.
    """

    @wraps(f)
    def decorated(*args, **kwargs):
        token = extract_bearer_token()
        if not token:
            return jsonify({
                "schemas": ["urn:ietf:params:scim:api:messages:2.0:Error"],
                "status": "401",
                "detail": "Missing or invalid Authorization header"
            }), 401

        tenant_id = validate_scim_token(token)
        if not tenant_id:
            return jsonify({
                "schemas": ["urn:ietf:params:scim:api:messages:2.0:Error"],
                "status": "401",
                "detail": "Invalid SCIM token"
            }), 401

        g.scim_tenant_id = tenant_id
        return f(*args, **kwargs)

    return decorated


def get_scim_tenant_id() -> str:
    """Get the authenticated tenant ID from SCIM context."""
    return getattr(g, "scim_tenant_id", None)
