"""
SCIM Group Project Mapping API (v4.4.0 PR7).

Admin endpoints for managing SCIM group → project mappings.
- Map a SCIM group to a project with a role
- Unmap (delete) a mapping
- List mappings for a tenant/group/project
- Enable/disable mappings
"""

from flask import Blueprint, g, jsonify, request

from auth_decorators import require_admin
from scim_store import ScimStore
from group_sync_engine import GroupSyncEngine


mapping_api_bp = Blueprint("mapping_api", __name__, url_prefix="/api/provisioning/mappings")


def get_scim_store() -> ScimStore:
    """Get or create ScimStore instance."""
    if not hasattr(g, "scim_store"):
        g.scim_store = ScimStore()
    return g.scim_store


def get_sync_engine() -> GroupSyncEngine:
    """Get or create GroupSyncEngine instance."""
    if not hasattr(g, "sync_engine"):
        g.sync_engine = GroupSyncEngine()
    return g.sync_engine


@mapping_api_bp.route("", methods=["GET"])
@require_admin
def list_mappings():
    """
    List all SCIM group project mappings for the tenant.

    Query params:
    - scim_group_id: Filter by SCIM group
    - project_id: Filter by project
    """
    tenant_id = g.tenant_id
    store = get_scim_store()

    scim_group_id = request.args.get("scim_group_id")
    project_id = request.args.get("project_id")

    mappings = store.list_group_project_mappings(
        tenant_id=tenant_id,
        scim_group_id=scim_group_id,
        project_id=project_id
    )

    # Enrich with group display names
    enriched = []
    for m in mappings:
        group = store.get_scim_group(m["scim_group_id"])
        enriched.append({
            **m,
            "group_display_name": group["display_name"] if group else None
        })

    return jsonify({
        "mappings": enriched,
        "total": len(enriched)
    })


@mapping_api_bp.route("", methods=["POST"])
@require_admin
def create_mapping():
    """
    Create a new SCIM group project mapping.

    Request body:
    {
        "scim_group_id": "uuid",
        "project_id": "uuid",
        "role": "viewer" | "editor" | "admin"
    }

    Creates the mapping and triggers initial sync.
    """
    tenant_id = g.tenant_id
    store = get_scim_store()
    engine = get_sync_engine()

    data = request.get_json() or {}

    scim_group_id = data.get("scim_group_id")
    project_id = data.get("project_id")
    role = data.get("role")

    # Validate required fields
    if not scim_group_id:
        return jsonify({"error": "scim_group_id is required"}), 400
    if not project_id:
        return jsonify({"error": "project_id is required"}), 400
    if not role:
        return jsonify({"error": "role is required"}), 400

    valid_roles = {"viewer", "editor", "admin"}
    if role not in valid_roles:
        return jsonify({"error": f"role must be one of: {', '.join(valid_roles)}"}), 400

    # Verify group exists and belongs to tenant
    group = store.get_scim_group(scim_group_id)
    if not group:
        return jsonify({"error": "SCIM group not found"}), 404
    if group["tenant_id"] != tenant_id:
        return jsonify({"error": "SCIM group not found"}), 404

    # Create mapping
    try:
        mapping = store.create_group_project_mapping(
            tenant_id=tenant_id,
            scim_group_id=scim_group_id,
            project_id=project_id,
            role=role,
            enabled=True
        )
    except Exception as e:
        if "UNIQUE constraint" in str(e):
            return jsonify({"error": "Mapping already exists"}), 409
        raise

    # Trigger initial sync
    sync_result = engine.sync_group(scim_group_id)

    return jsonify({
        "mapping": {
            **mapping,
            "group_display_name": group["display_name"]
        },
        "sync_result": {
            "members_added": sync_result["members_added"],
            "errors": sync_result["errors"]
        }
    }), 201


@mapping_api_bp.route("/<mapping_id>", methods=["GET"])
@require_admin
def get_mapping(mapping_id: str):
    """Get a specific mapping by ID."""
    tenant_id = g.tenant_id
    store = get_scim_store()

    mapping = store.get_group_project_mapping(mapping_id)

    if not mapping:
        return jsonify({"error": "Mapping not found"}), 404

    if mapping["tenant_id"] != tenant_id:
        return jsonify({"error": "Mapping not found"}), 404

    # Enrich with group info
    group = store.get_scim_group(mapping["scim_group_id"])

    return jsonify({
        **mapping,
        "group_display_name": group["display_name"] if group else None
    })


@mapping_api_bp.route("/<mapping_id>", methods=["PATCH"])
@require_admin
def update_mapping(mapping_id: str):
    """
    Update a mapping.

    Request body:
    {
        "role": "viewer" | "editor" | "admin",
        "enabled": true | false
    }

    If enabled changes to false, revokes related memberships.
    If enabled changes to true, triggers sync.
    """
    tenant_id = g.tenant_id
    store = get_scim_store()
    engine = get_sync_engine()

    # Check mapping exists and belongs to tenant
    mapping = store.get_group_project_mapping(mapping_id)
    if not mapping:
        return jsonify({"error": "Mapping not found"}), 404
    if mapping["tenant_id"] != tenant_id:
        return jsonify({"error": "Mapping not found"}), 404

    data = request.get_json() or {}

    role = data.get("role")
    enabled = data.get("enabled")

    if role is not None:
        valid_roles = {"viewer", "editor", "admin"}
        if role not in valid_roles:
            return jsonify({"error": f"role must be one of: {', '.join(valid_roles)}"}), 400

    # Update mapping
    updated = store.update_group_project_mapping(
        mapping_id=mapping_id,
        role=role,
        enabled=enabled
    )

    sync_result = None

    # Handle enabled state changes
    if enabled is not None:
        if enabled and not mapping["enabled"]:
            # Re-enabled: trigger sync
            sync_result = engine.sync_group(mapping["scim_group_id"])
        elif not enabled and mapping["enabled"]:
            # Disabled: revoke memberships
            revoked = engine.revoke_scim_memberships(
                tenant_id=tenant_id,
                scim_group_id=mapping["scim_group_id"],
                project_id=mapping["project_id"]
            )
            sync_result = {"memberships_revoked": revoked}

    # Role change on enabled mapping: re-sync
    if role is not None and role != mapping["role"] and updated["enabled"]:
        # Revoke old and sync new
        engine.revoke_scim_memberships(
            tenant_id=tenant_id,
            scim_group_id=mapping["scim_group_id"],
            project_id=mapping["project_id"]
        )
        sync_result = engine.sync_group(mapping["scim_group_id"])

    response = {"mapping": updated}
    if sync_result:
        response["sync_result"] = sync_result

    return jsonify(response)


@mapping_api_bp.route("/<mapping_id>", methods=["DELETE"])
@require_admin
def delete_mapping(mapping_id: str):
    """
    Delete a mapping.

    Revokes all related SCIM memberships before deleting.
    """
    tenant_id = g.tenant_id
    store = get_scim_store()
    engine = get_sync_engine()

    # Check mapping exists and belongs to tenant
    mapping = store.get_group_project_mapping(mapping_id)
    if not mapping:
        return jsonify({"error": "Mapping not found"}), 404
    if mapping["tenant_id"] != tenant_id:
        return jsonify({"error": "Mapping not found"}), 404

    # Revoke memberships first
    revoked = engine.revoke_scim_memberships(
        tenant_id=tenant_id,
        scim_group_id=mapping["scim_group_id"],
        project_id=mapping["project_id"]
    )

    # Delete mapping
    store.delete_group_project_mapping(mapping_id)

    return jsonify({
        "message": "Mapping deleted",
        "memberships_revoked": revoked
    })


@mapping_api_bp.route("/sync", methods=["POST"])
@require_admin
def trigger_sync():
    """
    Trigger a full sync for the tenant.

    Optional body:
    {
        "scim_group_id": "uuid"  // Sync only this group
    }
    """
    tenant_id = g.tenant_id
    engine = get_sync_engine()

    data = request.get_json() or {}
    scim_group_id = data.get("scim_group_id")

    if scim_group_id:
        result = engine.sync_group(scim_group_id)
    else:
        result = engine.sync_all_groups(tenant_id)

    return jsonify(result)


@mapping_api_bp.route("/status", methods=["GET"])
@require_admin
def get_sync_status():
    """Get sync status for the tenant."""
    tenant_id = g.tenant_id
    engine = get_sync_engine()

    status = engine.get_sync_status(tenant_id)

    return jsonify(status)
