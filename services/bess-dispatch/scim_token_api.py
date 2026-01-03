"""
SCIM token management API (v4.4.0 PR2).

Endpoints for managing SCIM bearer tokens (admin-only).
"""

from flask import Blueprint, g, jsonify, request

from auth_decorators import require_admin
from scim_store import ScimStore


scim_token_bp = Blueprint("scim_tokens", __name__, url_prefix="/api/provisioning/tokens")


def get_scim_store() -> ScimStore:
    """Get or create ScimStore instance."""
    if not hasattr(g, "scim_store"):
        g.scim_store = ScimStore()
    return g.scim_store


@scim_token_bp.route("", methods=["GET"])
@require_admin
def list_tokens():
    """
    List all SCIM tokens for the tenant.

    Returns token metadata (not the secret).
    """
    tenant_id = g.tenant_id
    store = get_scim_store()

    tokens = store.list_scim_tokens(tenant_id)

    return jsonify({
        "tokens": tokens,
        "total": len(tokens)
    })


@scim_token_bp.route("", methods=["POST"])
@require_admin
def create_token():
    """
    Create a new SCIM token.

    Request body:
    {
        "name": "My SCIM Token"
    }

    Response includes the plaintext token (shown only once).
    """
    tenant_id = g.tenant_id
    data = request.get_json() or {}

    name = data.get("name")
    if not name:
        return jsonify({"error": "name is required"}), 400

    if len(name) > 100:
        return jsonify({"error": "name must be 100 characters or less"}), 400

    store = get_scim_store()

    try:
        plaintext, record = store.create_scim_token(tenant_id, name)
    except Exception as e:
        if "UNIQUE constraint" in str(e):
            return jsonify({"error": f"Token with name '{name}' already exists"}), 409
        raise

    return jsonify({
        "token": plaintext,
        "id": record["id"],
        "name": record["name"],
        "created_at": record["created_at"],
        "message": "Store this token securely. It will not be shown again."
    }), 201


@scim_token_bp.route("/<token_id>", methods=["GET"])
@require_admin
def get_token(token_id: str):
    """
    Get a SCIM token by ID.

    Returns token metadata (not the secret).
    """
    tenant_id = g.tenant_id
    store = get_scim_store()

    token = store.get_scim_token(token_id)

    if not token:
        return jsonify({"error": "Token not found"}), 404

    if token["tenant_id"] != tenant_id:
        return jsonify({"error": "Token not found"}), 404

    # Don't expose the hash
    result = {
        "id": token["id"],
        "name": token["name"],
        "created_at": token["created_at"],
        "revoked_at": token["revoked_at"],
        "last_used_at": token["last_used_at"]
    }

    return jsonify(result)


@scim_token_bp.route("/<token_id>", methods=["DELETE"])
@require_admin
def revoke_token(token_id: str):
    """
    Revoke a SCIM token.

    The token will no longer be valid for authentication.
    """
    tenant_id = g.tenant_id
    store = get_scim_store()

    # Check token exists and belongs to tenant
    token = store.get_scim_token(token_id)
    if not token:
        return jsonify({"error": "Token not found"}), 404

    if token["tenant_id"] != tenant_id:
        return jsonify({"error": "Token not found"}), 404

    if token["revoked_at"]:
        return jsonify({"error": "Token already revoked"}), 400

    success = store.revoke_scim_token(token_id)

    if not success:
        return jsonify({"error": "Failed to revoke token"}), 500

    return jsonify({"message": "Token revoked successfully"})


@scim_token_bp.route("/<token_id>/rotate", methods=["POST"])
@require_admin
def rotate_token(token_id: str):
    """
    Rotate a SCIM token.

    Deletes the old token and creates a new one with the same name.
    Returns the new plaintext token (shown only once).
    """
    tenant_id = g.tenant_id
    store = get_scim_store()

    # Check token exists and belongs to tenant
    token = store.get_scim_token(token_id)
    if not token:
        return jsonify({"error": "Token not found"}), 404

    if token["tenant_id"] != tenant_id:
        return jsonify({"error": "Token not found"}), 404

    if token["revoked_at"]:
        return jsonify({"error": "Cannot rotate revoked token"}), 400

    result = store.rotate_scim_token(token_id)

    if not result:
        return jsonify({"error": "Failed to rotate token"}), 500

    plaintext, new_record = result

    return jsonify({
        "token": plaintext,
        "id": new_record["id"],
        "name": new_record["name"],
        "created_at": new_record["created_at"],
        "message": "Store this token securely. It will not be shown again."
    })
