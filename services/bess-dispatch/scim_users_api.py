"""
SCIM 2.0 Users API (v4.4.0 PR4).

Implements RFC 7644 SCIM 2.0 Users endpoint:
- POST /Users - Create user
- GET /Users - List/filter users
- GET /Users/<id> - Get user
- PATCH /Users/<id> - Update user
- DELETE /Users/<id> - Delete user

All endpoints require SCIM bearer token authentication.
"""

import re
from typing import Optional

from flask import Blueprint, g, jsonify, request

from scim_auth import require_scim_token
from scim_store import ScimStore
from scim_base_endpoints import SCIM_BASE, SCHEMA_USER, SCHEMA_LIST_RESPONSE


scim_users_bp = Blueprint("scim_users", __name__, url_prefix=f"{SCIM_BASE}/Users")


def get_scim_store() -> ScimStore:
    """Get or create ScimStore instance."""
    if not hasattr(g, "scim_store"):
        g.scim_store = ScimStore()
    return g.scim_store


def format_user_response(user: dict) -> dict:
    """Format a SCIM user record for API response."""
    return {
        "schemas": [SCHEMA_USER],
        "id": user["id"],
        "externalId": user.get("external_id"),
        "userName": user["user_name"],
        "name": {
            "formatted": user.get("display_name"),
            "givenName": user.get("given_name"),
            "familyName": user.get("family_name")
        },
        "displayName": user.get("display_name"),
        "emails": format_emails(user.get("email")),
        "active": user.get("active", True),
        "meta": {
            "resourceType": "User",
            "created": user.get("created_at"),
            "lastModified": user.get("updated_at") or user.get("created_at"),
            "location": f"{SCIM_BASE}/Users/{user['id']}"
        }
    }


def format_emails(email: Optional[str]) -> list:
    """Format email for SCIM response."""
    if not email:
        return []
    return [
        {
            "value": email,
            "type": "work",
            "primary": True
        }
    ]


def scim_error(status: str, detail: str, status_code: int = 400):
    """Return a SCIM error response."""
    return jsonify({
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:Error"],
        "status": status,
        "detail": detail
    }), status_code


def parse_filter(filter_str: Optional[str]) -> Optional[dict]:
    """
    Parse a SCIM filter string.

    Supports:
    - userName eq "value"
    - externalId eq "value"
    - email eq "value"

    Returns dict with field and value, or None if invalid.
    """
    if not filter_str:
        return None

    # Pattern: field eq "value" or field eq 'value'
    pattern = r'^(\w+)\s+eq\s+["\'](.+)["\']$'
    match = re.match(pattern, filter_str.strip(), re.IGNORECASE)

    if not match:
        return None

    field = match.group(1).lower()
    value = match.group(2)

    # Map SCIM fields to DB columns
    field_map = {
        "username": "user_name",
        "externalid": "external_id",
        "email": "email"
    }

    if field not in field_map:
        return None

    return {
        "field": field_map[field],
        "value": value
    }


@scim_users_bp.route("", methods=["POST"])
@require_scim_token
def create_user():
    """
    Create a new SCIM user.

    Request body per RFC 7643:
    {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
        "userName": "jdoe",
        "externalId": "12345",
        "name": {"givenName": "John", "familyName": "Doe"},
        "displayName": "John Doe",
        "emails": [{"value": "jdoe@example.com", "primary": true}],
        "active": true
    }
    """
    tenant_id = g.scim_tenant_id
    data = request.get_json() or {}

    # Validate required fields
    user_name = data.get("userName")
    if not user_name:
        return scim_error("400", "userName is required", 400)

    # Extract fields
    external_id = data.get("externalId")
    name = data.get("name", {})
    given_name = name.get("givenName")
    family_name = name.get("familyName")
    display_name = data.get("displayName") or name.get("formatted")

    # Extract primary email
    emails = data.get("emails", [])
    email = None
    for e in emails:
        if e.get("primary"):
            email = e.get("value")
            break
    if not email and emails:
        email = emails[0].get("value")

    active = data.get("active", True)

    store = get_scim_store()

    try:
        user = store.create_scim_user(
            tenant_id=tenant_id,
            external_id=external_id,
            user_name=user_name,
            email=email,
            display_name=display_name,
            given_name=given_name,
            family_name=family_name,
            active=active
        )
    except Exception as e:
        if "UNIQUE constraint" in str(e):
            # Check if userName or externalId conflict
            if "user_name" in str(e):
                return scim_error("409", f"User with userName '{user_name}' already exists", 409)
            if "external_id" in str(e):
                return scim_error("409", f"User with externalId '{external_id}' already exists", 409)
            return scim_error("409", "User already exists", 409)
        raise

    response = format_user_response(user)
    return jsonify(response), 201


@scim_users_bp.route("", methods=["GET"])
@require_scim_token
def list_users():
    """
    List/filter SCIM users.

    Query params:
    - filter: SCIM filter (e.g., userName eq "jdoe")
    - startIndex: Pagination start (1-based)
    - count: Max results per page
    """
    tenant_id = g.scim_tenant_id
    store = get_scim_store()

    # Parse query params
    filter_str = request.args.get("filter")
    start_index = int(request.args.get("startIndex", 1))
    count = int(request.args.get("count", 100))

    # Limit count to prevent abuse
    count = min(count, 100)

    # Parse filter
    filter_parsed = parse_filter(filter_str)

    if filter_str and not filter_parsed:
        return scim_error("400", f"Invalid filter: {filter_str}", 400)

    # Get users
    if filter_parsed:
        users = store.find_scim_users(
            tenant_id=tenant_id,
            field=filter_parsed["field"],
            value=filter_parsed["value"]
        )
    else:
        users = store.list_scim_users(
            tenant_id=tenant_id,
            offset=start_index - 1,
            limit=count
        )

    # Get total count for pagination
    total = store.count_scim_users(tenant_id)

    resources = [format_user_response(u) for u in users]

    return jsonify({
        "schemas": [SCHEMA_LIST_RESPONSE],
        "totalResults": total,
        "startIndex": start_index,
        "itemsPerPage": len(resources),
        "Resources": resources
    })


@scim_users_bp.route("/<user_id>", methods=["GET"])
@require_scim_token
def get_user(user_id: str):
    """Get a SCIM user by ID."""
    tenant_id = g.scim_tenant_id
    store = get_scim_store()

    user = store.get_scim_user(user_id)

    if not user:
        return scim_error("404", f"User '{user_id}' not found", 404)

    if user["tenant_id"] != tenant_id:
        return scim_error("404", f"User '{user_id}' not found", 404)

    return jsonify(format_user_response(user))


@scim_users_bp.route("/<user_id>", methods=["PATCH"])
@require_scim_token
def patch_user(user_id: str):
    """
    Update a SCIM user using PATCH.

    Request body per RFC 7644:
    {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
        "Operations": [
            {"op": "replace", "path": "active", "value": false},
            {"op": "replace", "path": "displayName", "value": "New Name"}
        ]
    }
    """
    tenant_id = g.scim_tenant_id
    store = get_scim_store()

    # Check user exists and belongs to tenant
    user = store.get_scim_user(user_id)

    if not user:
        return scim_error("404", f"User '{user_id}' not found", 404)

    if user["tenant_id"] != tenant_id:
        return scim_error("404", f"User '{user_id}' not found", 404)

    data = request.get_json() or {}
    operations = data.get("Operations", [])

    if not operations:
        return scim_error("400", "Operations array is required", 400)

    # Process operations
    updates = {}
    for op in operations:
        op_type = op.get("op", "").lower()
        path = op.get("path", "")
        value = op.get("value")

        if op_type not in ["replace", "add"]:
            continue

        # Map SCIM paths to DB columns
        path_map = {
            "active": "active",
            "displayName": "display_name",
            "userName": "user_name",
            "externalId": "external_id",
            "name.givenName": "given_name",
            "name.familyName": "family_name",
            "emails": "email"
        }

        if path in path_map:
            if path == "emails" and isinstance(value, list) and value:
                # Extract primary email from list
                for e in value:
                    if e.get("primary"):
                        updates["email"] = e.get("value")
                        break
                else:
                    updates["email"] = value[0].get("value")
            else:
                updates[path_map[path]] = value
        elif path == "name" and isinstance(value, dict):
            # Handle name object update
            if "givenName" in value:
                updates["given_name"] = value["givenName"]
            if "familyName" in value:
                updates["family_name"] = value["familyName"]
            if "formatted" in value:
                updates["display_name"] = value["formatted"]

    if updates:
        success = store.update_scim_user(user_id, updates)
        if not success:
            return scim_error("500", "Failed to update user", 500)

    # Return updated user
    user = store.get_scim_user(user_id)
    return jsonify(format_user_response(user))


@scim_users_bp.route("/<user_id>", methods=["PUT"])
@require_scim_token
def replace_user(user_id: str):
    """
    Replace a SCIM user entirely.

    Same body as POST /Users but replaces existing user.
    """
    tenant_id = g.scim_tenant_id
    store = get_scim_store()

    # Check user exists and belongs to tenant
    user = store.get_scim_user(user_id)

    if not user:
        return scim_error("404", f"User '{user_id}' not found", 404)

    if user["tenant_id"] != tenant_id:
        return scim_error("404", f"User '{user_id}' not found", 404)

    data = request.get_json() or {}

    # Validate required fields
    user_name = data.get("userName")
    if not user_name:
        return scim_error("400", "userName is required", 400)

    # Extract fields
    external_id = data.get("externalId")
    name = data.get("name", {})
    given_name = name.get("givenName")
    family_name = name.get("familyName")
    display_name = data.get("displayName") or name.get("formatted")

    # Extract primary email
    emails = data.get("emails", [])
    email = None
    for e in emails:
        if e.get("primary"):
            email = e.get("value")
            break
    if not email and emails:
        email = emails[0].get("value")

    active = data.get("active", True)

    updates = {
        "user_name": user_name,
        "external_id": external_id,
        "given_name": given_name,
        "family_name": family_name,
        "display_name": display_name,
        "email": email,
        "active": active
    }

    success = store.update_scim_user(user_id, updates)
    if not success:
        return scim_error("500", "Failed to update user", 500)

    user = store.get_scim_user(user_id)
    return jsonify(format_user_response(user))


@scim_users_bp.route("/<user_id>", methods=["DELETE"])
@require_scim_token
def delete_user(user_id: str):
    """Delete a SCIM user."""
    tenant_id = g.scim_tenant_id
    store = get_scim_store()

    # Check user exists and belongs to tenant
    user = store.get_scim_user(user_id)

    if not user:
        return scim_error("404", f"User '{user_id}' not found", 404)

    if user["tenant_id"] != tenant_id:
        return scim_error("404", f"User '{user_id}' not found", 404)

    success = store.delete_scim_user(user_id)

    if not success:
        return scim_error("500", "Failed to delete user", 500)

    return "", 204
