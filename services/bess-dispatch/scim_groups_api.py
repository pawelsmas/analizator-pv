"""
SCIM 2.0 Groups API (v4.4.0 PR5).

Implements RFC 7644 SCIM 2.0 Groups endpoint:
- POST /Groups - Create group
- GET /Groups - List/filter groups
- GET /Groups/<id> - Get group with members
- PATCH /Groups/<id> - Update group/members
- DELETE /Groups/<id> - Delete group

All endpoints require SCIM bearer token authentication.
"""

import re
from typing import Optional

from flask import Blueprint, g, jsonify, request

from scim_auth import require_scim_token
from scim_store import ScimStore
from scim_base_endpoints import SCIM_BASE, SCHEMA_GROUP, SCHEMA_LIST_RESPONSE


scim_groups_bp = Blueprint("scim_groups", __name__, url_prefix=f"{SCIM_BASE}/Groups")


def get_scim_store() -> ScimStore:
    """Get or create ScimStore instance."""
    if not hasattr(g, "scim_store"):
        g.scim_store = ScimStore()
    return g.scim_store


def format_group_response(group: dict, members: list = None) -> dict:
    """Format a SCIM group record for API response."""
    response = {
        "schemas": [SCHEMA_GROUP],
        "id": group["id"],
        "externalId": group.get("external_id"),
        "displayName": group["display_name"],
        "meta": {
            "resourceType": "Group",
            "created": group.get("created_at"),
            "lastModified": group.get("updated_at") or group.get("created_at"),
            "location": f"{SCIM_BASE}/Groups/{group['id']}"
        }
    }

    if members is not None:
        response["members"] = format_members(members)

    return response


def format_members(members: list) -> list:
    """Format group members for SCIM response."""
    return [
        {
            "value": m["id"],
            "display": m.get("display_name") or m.get("user_name"),
            "$ref": f"{SCIM_BASE}/Users/{m['id']}",
            "type": "User"
        }
        for m in members
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
    - displayName eq "value"
    - externalId eq "value"

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
        "displayname": "display_name",
        "externalid": "external_id"
    }

    if field not in field_map:
        return None

    return {
        "field": field_map[field],
        "value": value
    }


@scim_groups_bp.route("", methods=["POST"])
@require_scim_token
def create_group():
    """
    Create a new SCIM group.

    Request body per RFC 7643:
    {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
        "displayName": "Engineering",
        "externalId": "group-123",
        "members": [
            {"value": "user-id-1"},
            {"value": "user-id-2"}
        ]
    }
    """
    tenant_id = g.scim_tenant_id
    data = request.get_json() or {}

    # Validate required fields
    display_name = data.get("displayName")
    if not display_name:
        return scim_error("400", "displayName is required", 400)

    external_id = data.get("externalId")
    members_data = data.get("members", [])

    store = get_scim_store()

    try:
        group = store.create_scim_group(
            tenant_id=tenant_id,
            display_name=display_name,
            external_id=external_id
        )
    except Exception as e:
        if "UNIQUE constraint" in str(e):
            return scim_error("409", f"Group with displayName '{display_name}' already exists", 409)
        raise

    # Add initial members
    if members_data:
        for member in members_data:
            member_id = member.get("value")
            if member_id:
                store.add_group_member(group["id"], member_id)

    # Get members for response
    members = store.get_group_members(group["id"])
    response = format_group_response(group, members)

    return jsonify(response), 201


@scim_groups_bp.route("", methods=["GET"])
@require_scim_token
def list_groups():
    """
    List/filter SCIM groups.

    Query params:
    - filter: SCIM filter (e.g., displayName eq "Engineering")
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

    # Get groups
    if filter_parsed:
        groups = store.find_scim_groups(
            tenant_id=tenant_id,
            field=filter_parsed["field"],
            value=filter_parsed["value"]
        )
        total = len(groups)
    else:
        groups = store.list_scim_groups(
            tenant_id=tenant_id,
            offset=start_index - 1,
            limit=count
        )
        total = store.count_scim_groups(tenant_id)

    resources = [format_group_response(g) for g in groups]

    return jsonify({
        "schemas": [SCHEMA_LIST_RESPONSE],
        "totalResults": total,
        "startIndex": start_index,
        "itemsPerPage": len(resources),
        "Resources": resources
    })


@scim_groups_bp.route("/<group_id>", methods=["GET"])
@require_scim_token
def get_group(group_id: str):
    """Get a SCIM group by ID with members."""
    tenant_id = g.scim_tenant_id
    store = get_scim_store()

    group = store.get_scim_group(group_id)

    if not group:
        return scim_error("404", f"Group '{group_id}' not found", 404)

    if group["tenant_id"] != tenant_id:
        return scim_error("404", f"Group '{group_id}' not found", 404)

    members = store.get_group_members(group_id)
    return jsonify(format_group_response(group, members))


@scim_groups_bp.route("/<group_id>", methods=["PATCH"])
@require_scim_token
def patch_group(group_id: str):
    """
    Update a SCIM group using PATCH.

    Request body per RFC 7644:
    {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
        "Operations": [
            {"op": "replace", "path": "displayName", "value": "New Name"},
            {"op": "add", "path": "members", "value": [{"value": "user-id"}]},
            {"op": "remove", "path": "members", "value": [{"value": "user-id"}]}
        ]
    }
    """
    tenant_id = g.scim_tenant_id
    store = get_scim_store()

    # Check group exists and belongs to tenant
    group = store.get_scim_group(group_id)

    if not group:
        return scim_error("404", f"Group '{group_id}' not found", 404)

    if group["tenant_id"] != tenant_id:
        return scim_error("404", f"Group '{group_id}' not found", 404)

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

        if path == "displayName" and op_type in ["replace", "add"]:
            updates["display_name"] = value
        elif path == "externalId" and op_type in ["replace", "add"]:
            updates["external_id"] = value
        elif path == "members":
            if op_type == "add" and isinstance(value, list):
                for member in value:
                    member_id = member.get("value")
                    if member_id:
                        store.add_group_member(group_id, member_id)
            elif op_type == "remove" and isinstance(value, list):
                for member in value:
                    member_id = member.get("value")
                    if member_id:
                        store.remove_group_member(group_id, member_id)
            elif op_type == "replace" and isinstance(value, list):
                # Replace all members
                member_ids = [m.get("value") for m in value if m.get("value")]
                store.set_group_members(group_id, member_ids)

    if updates:
        store.update_scim_group(group_id, updates)

    # Return updated group
    group = store.get_scim_group(group_id)
    members = store.get_group_members(group_id)
    return jsonify(format_group_response(group, members))


@scim_groups_bp.route("/<group_id>", methods=["PUT"])
@require_scim_token
def replace_group(group_id: str):
    """
    Replace a SCIM group entirely.

    Same body as POST /Groups but replaces existing group.
    """
    tenant_id = g.scim_tenant_id
    store = get_scim_store()

    # Check group exists and belongs to tenant
    group = store.get_scim_group(group_id)

    if not group:
        return scim_error("404", f"Group '{group_id}' not found", 404)

    if group["tenant_id"] != tenant_id:
        return scim_error("404", f"Group '{group_id}' not found", 404)

    data = request.get_json() or {}

    # Validate required fields
    display_name = data.get("displayName")
    if not display_name:
        return scim_error("400", "displayName is required", 400)

    external_id = data.get("externalId")
    members_data = data.get("members", [])

    # Update group
    store.update_scim_group(group_id, {
        "display_name": display_name,
        "external_id": external_id
    })

    # Replace all members
    member_ids = [m.get("value") for m in members_data if m.get("value")]
    store.set_group_members(group_id, member_ids)

    # Return updated group
    group = store.get_scim_group(group_id)
    members = store.get_group_members(group_id)
    return jsonify(format_group_response(group, members))


@scim_groups_bp.route("/<group_id>", methods=["DELETE"])
@require_scim_token
def delete_group(group_id: str):
    """Delete a SCIM group."""
    tenant_id = g.scim_tenant_id
    store = get_scim_store()

    # Check group exists and belongs to tenant
    group = store.get_scim_group(group_id)

    if not group:
        return scim_error("404", f"Group '{group_id}' not found", 404)

    if group["tenant_id"] != tenant_id:
        return scim_error("404", f"Group '{group_id}' not found", 404)

    success = store.delete_scim_group(group_id)

    if not success:
        return scim_error("500", "Failed to delete group", 500)

    return "", 204
