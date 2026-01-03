"""
SCIM 2.0 Base Endpoints (v4.4.0 PR3).

Implements RFC 7644 discovery endpoints:
- /ServiceProviderConfig - Server capabilities
- /ResourceTypes - Supported resource types
- /Schemas - Schema definitions

These endpoints are public (no auth required) per SCIM spec.
"""

from flask import Blueprint, jsonify

# SCIM Base URL prefix
SCIM_BASE = "/api/scim/v2"

scim_base_bp = Blueprint("scim_base", __name__, url_prefix=SCIM_BASE)


# Schema URIs
SCHEMA_USER = "urn:ietf:params:scim:schemas:core:2.0:User"
SCHEMA_GROUP = "urn:ietf:params:scim:schemas:core:2.0:Group"
SCHEMA_SERVICE_PROVIDER_CONFIG = "urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"
SCHEMA_RESOURCE_TYPE = "urn:ietf:params:scim:schemas:core:2.0:ResourceType"
SCHEMA_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Schema"
SCHEMA_LIST_RESPONSE = "urn:ietf:params:scim:api:messages:2.0:ListResponse"


@scim_base_bp.route("/ServiceProviderConfig", methods=["GET"])
def get_service_provider_config():
    """
    Return SCIM Service Provider Configuration.

    Per RFC 7644 Section 4, describes server's SCIM capabilities.
    """
    config = {
        "schemas": [SCHEMA_SERVICE_PROVIDER_CONFIG],
        "documentationUri": "https://docs.example.com/scim",
        "patch": {
            "supported": True
        },
        "bulk": {
            "supported": False,
            "maxOperations": 0,
            "maxPayloadSize": 0
        },
        "filter": {
            "supported": True,
            "maxResults": 100
        },
        "changePassword": {
            "supported": False
        },
        "sort": {
            "supported": False
        },
        "etag": {
            "supported": False
        },
        "authenticationSchemes": [
            {
                "name": "OAuth Bearer Token",
                "description": "SCIM bearer token authentication",
                "specUri": "http://www.rfc-editor.org/info/rfc6750",
                "type": "oauthbearertoken",
                "primary": True
            }
        ],
        "meta": {
            "resourceType": "ServiceProviderConfig",
            "location": f"{SCIM_BASE}/ServiceProviderConfig"
        }
    }
    return jsonify(config)


@scim_base_bp.route("/ResourceTypes", methods=["GET"])
def list_resource_types():
    """
    Return list of supported SCIM resource types.

    Per RFC 7644 Section 4.
    """
    resource_types = [
        {
            "schemas": [SCHEMA_RESOURCE_TYPE],
            "id": "User",
            "name": "User",
            "description": "User Account",
            "endpoint": f"{SCIM_BASE}/Users",
            "schema": SCHEMA_USER,
            "schemaExtensions": [],
            "meta": {
                "resourceType": "ResourceType",
                "location": f"{SCIM_BASE}/ResourceTypes/User"
            }
        },
        {
            "schemas": [SCHEMA_RESOURCE_TYPE],
            "id": "Group",
            "name": "Group",
            "description": "Group",
            "endpoint": f"{SCIM_BASE}/Groups",
            "schema": SCHEMA_GROUP,
            "schemaExtensions": [],
            "meta": {
                "resourceType": "ResourceType",
                "location": f"{SCIM_BASE}/ResourceTypes/Group"
            }
        }
    ]

    return jsonify({
        "schemas": [SCHEMA_LIST_RESPONSE],
        "totalResults": len(resource_types),
        "Resources": resource_types
    })


@scim_base_bp.route("/ResourceTypes/<resource_type>", methods=["GET"])
def get_resource_type(resource_type: str):
    """
    Return a specific resource type definition.
    """
    resource_types = {
        "User": {
            "schemas": [SCHEMA_RESOURCE_TYPE],
            "id": "User",
            "name": "User",
            "description": "User Account",
            "endpoint": f"{SCIM_BASE}/Users",
            "schema": SCHEMA_USER,
            "schemaExtensions": [],
            "meta": {
                "resourceType": "ResourceType",
                "location": f"{SCIM_BASE}/ResourceTypes/User"
            }
        },
        "Group": {
            "schemas": [SCHEMA_RESOURCE_TYPE],
            "id": "Group",
            "name": "Group",
            "description": "Group",
            "endpoint": f"{SCIM_BASE}/Groups",
            "schema": SCHEMA_GROUP,
            "schemaExtensions": [],
            "meta": {
                "resourceType": "ResourceType",
                "location": f"{SCIM_BASE}/ResourceTypes/Group"
            }
        }
    }

    if resource_type not in resource_types:
        return jsonify({
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:Error"],
            "status": "404",
            "detail": f"Resource type '{resource_type}' not found"
        }), 404

    return jsonify(resource_types[resource_type])


@scim_base_bp.route("/Schemas", methods=["GET"])
def list_schemas():
    """
    Return all SCIM schema definitions.

    Per RFC 7644 Section 4.
    """
    schemas = get_all_schemas()

    return jsonify({
        "schemas": [SCHEMA_LIST_RESPONSE],
        "totalResults": len(schemas),
        "Resources": schemas
    })


@scim_base_bp.route("/Schemas/<path:schema_uri>", methods=["GET"])
def get_schema(schema_uri: str):
    """
    Return a specific schema definition by URI.
    """
    # Handle URL encoding
    schema_uri = schema_uri.replace("%3A", ":").replace("%2F", "/")

    schemas = {s["id"]: s for s in get_all_schemas()}

    if schema_uri not in schemas:
        return jsonify({
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:Error"],
            "status": "404",
            "detail": f"Schema '{schema_uri}' not found"
        }), 404

    return jsonify(schemas[schema_uri])


def get_all_schemas() -> list:
    """Return all SCIM schema definitions."""
    return [
        get_user_schema(),
        get_group_schema()
    ]


def get_user_schema() -> dict:
    """Return SCIM User schema definition."""
    return {
        "schemas": [SCHEMA_SCHEMA],
        "id": SCHEMA_USER,
        "name": "User",
        "description": "User Account",
        "attributes": [
            {
                "name": "userName",
                "type": "string",
                "multiValued": False,
                "description": "Unique identifier for the User",
                "required": True,
                "caseExact": False,
                "mutability": "readWrite",
                "returned": "default",
                "uniqueness": "server"
            },
            {
                "name": "name",
                "type": "complex",
                "multiValued": False,
                "description": "The components of the user's name",
                "required": False,
                "subAttributes": [
                    {
                        "name": "formatted",
                        "type": "string",
                        "multiValued": False,
                        "description": "The full name",
                        "required": False,
                        "mutability": "readWrite",
                        "returned": "default"
                    },
                    {
                        "name": "familyName",
                        "type": "string",
                        "multiValued": False,
                        "description": "The family name",
                        "required": False,
                        "mutability": "readWrite",
                        "returned": "default"
                    },
                    {
                        "name": "givenName",
                        "type": "string",
                        "multiValued": False,
                        "description": "The given name",
                        "required": False,
                        "mutability": "readWrite",
                        "returned": "default"
                    }
                ],
                "mutability": "readWrite",
                "returned": "default"
            },
            {
                "name": "displayName",
                "type": "string",
                "multiValued": False,
                "description": "The name to display",
                "required": False,
                "mutability": "readWrite",
                "returned": "default"
            },
            {
                "name": "emails",
                "type": "complex",
                "multiValued": True,
                "description": "Email addresses for the User",
                "required": False,
                "subAttributes": [
                    {
                        "name": "value",
                        "type": "string",
                        "multiValued": False,
                        "description": "Email address value",
                        "required": False,
                        "mutability": "readWrite",
                        "returned": "default"
                    },
                    {
                        "name": "type",
                        "type": "string",
                        "multiValued": False,
                        "description": "Type of email (work, home, etc)",
                        "required": False,
                        "canonicalValues": ["work", "home", "other"],
                        "mutability": "readWrite",
                        "returned": "default"
                    },
                    {
                        "name": "primary",
                        "type": "boolean",
                        "multiValued": False,
                        "description": "Indicates if this is the primary email",
                        "required": False,
                        "mutability": "readWrite",
                        "returned": "default"
                    }
                ],
                "mutability": "readWrite",
                "returned": "default"
            },
            {
                "name": "active",
                "type": "boolean",
                "multiValued": False,
                "description": "Indicates if the User is active",
                "required": False,
                "mutability": "readWrite",
                "returned": "default"
            },
            {
                "name": "groups",
                "type": "complex",
                "multiValued": True,
                "description": "A list of groups the user belongs to",
                "required": False,
                "subAttributes": [
                    {
                        "name": "value",
                        "type": "string",
                        "multiValued": False,
                        "description": "The group id",
                        "required": False,
                        "mutability": "readOnly",
                        "returned": "default"
                    },
                    {
                        "name": "display",
                        "type": "string",
                        "multiValued": False,
                        "description": "The group display name",
                        "required": False,
                        "mutability": "readOnly",
                        "returned": "default"
                    },
                    {
                        "name": "$ref",
                        "type": "reference",
                        "multiValued": False,
                        "description": "The reference to the group",
                        "required": False,
                        "mutability": "readOnly",
                        "returned": "default"
                    }
                ],
                "mutability": "readOnly",
                "returned": "default"
            },
            {
                "name": "externalId",
                "type": "string",
                "multiValued": False,
                "description": "External identifier from the IdP",
                "required": False,
                "caseExact": True,
                "mutability": "readWrite",
                "returned": "default"
            }
        ],
        "meta": {
            "resourceType": "Schema",
            "location": f"{SCIM_BASE}/Schemas/{SCHEMA_USER}"
        }
    }


def get_group_schema() -> dict:
    """Return SCIM Group schema definition."""
    return {
        "schemas": [SCHEMA_SCHEMA],
        "id": SCHEMA_GROUP,
        "name": "Group",
        "description": "Group",
        "attributes": [
            {
                "name": "displayName",
                "type": "string",
                "multiValued": False,
                "description": "A human-readable name for the Group",
                "required": True,
                "caseExact": False,
                "mutability": "readWrite",
                "returned": "default",
                "uniqueness": "server"
            },
            {
                "name": "members",
                "type": "complex",
                "multiValued": True,
                "description": "A list of members of the Group",
                "required": False,
                "subAttributes": [
                    {
                        "name": "value",
                        "type": "string",
                        "multiValued": False,
                        "description": "The member id",
                        "required": False,
                        "mutability": "immutable",
                        "returned": "default"
                    },
                    {
                        "name": "display",
                        "type": "string",
                        "multiValued": False,
                        "description": "The member display name",
                        "required": False,
                        "mutability": "readOnly",
                        "returned": "default"
                    },
                    {
                        "name": "$ref",
                        "type": "reference",
                        "multiValued": False,
                        "description": "The reference to the member",
                        "required": False,
                        "mutability": "immutable",
                        "returned": "default"
                    },
                    {
                        "name": "type",
                        "type": "string",
                        "multiValued": False,
                        "description": "The type of the member",
                        "required": False,
                        "canonicalValues": ["User", "Group"],
                        "mutability": "immutable",
                        "returned": "default"
                    }
                ],
                "mutability": "readWrite",
                "returned": "default"
            },
            {
                "name": "externalId",
                "type": "string",
                "multiValued": False,
                "description": "External identifier from the IdP",
                "required": False,
                "caseExact": True,
                "mutability": "readWrite",
                "returned": "default"
            }
        ],
        "meta": {
            "resourceType": "Schema",
            "location": f"{SCIM_BASE}/Schemas/{SCHEMA_GROUP}"
        }
    }
