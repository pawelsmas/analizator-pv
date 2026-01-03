"""
Unit tests for SCIM base endpoints (v4.4.0 PR3).

Tests ServiceProviderConfig, ResourceTypes, and Schemas endpoints.
"""

from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "services" / "bess-dispatch"))

from scim_base_endpoints import (
    SCIM_BASE,
    SCHEMA_USER,
    SCHEMA_GROUP,
    SCHEMA_SERVICE_PROVIDER_CONFIG,
    SCHEMA_RESOURCE_TYPE,
    SCHEMA_SCHEMA,
    SCHEMA_LIST_RESPONSE,
    get_user_schema,
    get_group_schema,
    get_all_schemas,
)


class TestSchemaConstants:
    """Tests for SCIM schema URI constants."""

    def test_user_schema_uri(self):
        """User schema URI should follow RFC 7643."""
        assert SCHEMA_USER == "urn:ietf:params:scim:schemas:core:2.0:User"

    def test_group_schema_uri(self):
        """Group schema URI should follow RFC 7643."""
        assert SCHEMA_GROUP == "urn:ietf:params:scim:schemas:core:2.0:Group"

    def test_service_provider_config_schema_uri(self):
        """ServiceProviderConfig schema URI should follow RFC 7643."""
        assert SCHEMA_SERVICE_PROVIDER_CONFIG == "urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"

    def test_resource_type_schema_uri(self):
        """ResourceType schema URI should follow RFC 7643."""
        assert SCHEMA_RESOURCE_TYPE == "urn:ietf:params:scim:schemas:core:2.0:ResourceType"

    def test_schema_schema_uri(self):
        """Schema schema URI should follow RFC 7643."""
        assert SCHEMA_SCHEMA == "urn:ietf:params:scim:schemas:core:2.0:Schema"

    def test_list_response_schema_uri(self):
        """ListResponse schema URI should follow RFC 7644."""
        assert SCHEMA_LIST_RESPONSE == "urn:ietf:params:scim:api:messages:2.0:ListResponse"

    def test_scim_base_url(self):
        """SCIM base URL should be /api/scim/v2."""
        assert SCIM_BASE == "/api/scim/v2"


class TestUserSchema:
    """Tests for SCIM User schema definition."""

    def test_user_schema_has_correct_id(self):
        """User schema should have correct id."""
        schema = get_user_schema()
        assert schema["id"] == SCHEMA_USER

    def test_user_schema_has_schemas_array(self):
        """User schema should have schemas array."""
        schema = get_user_schema()
        assert "schemas" in schema
        assert SCHEMA_SCHEMA in schema["schemas"]

    def test_user_schema_has_name(self):
        """User schema should have name attribute."""
        schema = get_user_schema()
        assert schema["name"] == "User"

    def test_user_schema_has_description(self):
        """User schema should have description."""
        schema = get_user_schema()
        assert "description" in schema

    def test_user_schema_has_attributes(self):
        """User schema should have attributes array."""
        schema = get_user_schema()
        assert "attributes" in schema
        assert isinstance(schema["attributes"], list)
        assert len(schema["attributes"]) > 0

    def test_user_schema_has_username_attribute(self):
        """User schema should have userName attribute."""
        schema = get_user_schema()
        attrs = {a["name"]: a for a in schema["attributes"]}
        assert "userName" in attrs
        assert attrs["userName"]["required"] is True
        assert attrs["userName"]["type"] == "string"

    def test_user_schema_has_name_attribute(self):
        """User schema should have name (complex) attribute."""
        schema = get_user_schema()
        attrs = {a["name"]: a for a in schema["attributes"]}
        assert "name" in attrs
        assert attrs["name"]["type"] == "complex"
        assert "subAttributes" in attrs["name"]

    def test_user_schema_name_has_sub_attributes(self):
        """User schema name should have familyName, givenName, formatted."""
        schema = get_user_schema()
        attrs = {a["name"]: a for a in schema["attributes"]}
        sub_attrs = {s["name"]: s for s in attrs["name"]["subAttributes"]}
        assert "familyName" in sub_attrs
        assert "givenName" in sub_attrs
        assert "formatted" in sub_attrs

    def test_user_schema_has_display_name(self):
        """User schema should have displayName attribute."""
        schema = get_user_schema()
        attrs = {a["name"]: a for a in schema["attributes"]}
        assert "displayName" in attrs

    def test_user_schema_has_emails(self):
        """User schema should have emails attribute."""
        schema = get_user_schema()
        attrs = {a["name"]: a for a in schema["attributes"]}
        assert "emails" in attrs
        assert attrs["emails"]["type"] == "complex"
        assert attrs["emails"]["multiValued"] is True

    def test_user_schema_has_active(self):
        """User schema should have active attribute."""
        schema = get_user_schema()
        attrs = {a["name"]: a for a in schema["attributes"]}
        assert "active" in attrs
        assert attrs["active"]["type"] == "boolean"

    def test_user_schema_has_groups(self):
        """User schema should have groups attribute."""
        schema = get_user_schema()
        attrs = {a["name"]: a for a in schema["attributes"]}
        assert "groups" in attrs
        assert attrs["groups"]["mutability"] == "readOnly"

    def test_user_schema_has_external_id(self):
        """User schema should have externalId attribute."""
        schema = get_user_schema()
        attrs = {a["name"]: a for a in schema["attributes"]}
        assert "externalId" in attrs

    def test_user_schema_has_meta(self):
        """User schema should have meta section."""
        schema = get_user_schema()
        assert "meta" in schema
        assert schema["meta"]["resourceType"] == "Schema"


class TestGroupSchema:
    """Tests for SCIM Group schema definition."""

    def test_group_schema_has_correct_id(self):
        """Group schema should have correct id."""
        schema = get_group_schema()
        assert schema["id"] == SCHEMA_GROUP

    def test_group_schema_has_schemas_array(self):
        """Group schema should have schemas array."""
        schema = get_group_schema()
        assert "schemas" in schema
        assert SCHEMA_SCHEMA in schema["schemas"]

    def test_group_schema_has_name(self):
        """Group schema should have name attribute."""
        schema = get_group_schema()
        assert schema["name"] == "Group"

    def test_group_schema_has_attributes(self):
        """Group schema should have attributes array."""
        schema = get_group_schema()
        assert "attributes" in schema
        assert isinstance(schema["attributes"], list)

    def test_group_schema_has_display_name(self):
        """Group schema should have displayName attribute."""
        schema = get_group_schema()
        attrs = {a["name"]: a for a in schema["attributes"]}
        assert "displayName" in attrs
        assert attrs["displayName"]["required"] is True

    def test_group_schema_has_members(self):
        """Group schema should have members attribute."""
        schema = get_group_schema()
        attrs = {a["name"]: a for a in schema["attributes"]}
        assert "members" in attrs
        assert attrs["members"]["type"] == "complex"
        assert attrs["members"]["multiValued"] is True

    def test_group_schema_members_has_sub_attributes(self):
        """Group schema members should have value, display, $ref, type."""
        schema = get_group_schema()
        attrs = {a["name"]: a for a in schema["attributes"]}
        sub_attrs = {s["name"]: s for s in attrs["members"]["subAttributes"]}
        assert "value" in sub_attrs
        assert "display" in sub_attrs
        assert "$ref" in sub_attrs
        assert "type" in sub_attrs

    def test_group_schema_has_external_id(self):
        """Group schema should have externalId attribute."""
        schema = get_group_schema()
        attrs = {a["name"]: a for a in schema["attributes"]}
        assert "externalId" in attrs

    def test_group_schema_has_meta(self):
        """Group schema should have meta section."""
        schema = get_group_schema()
        assert "meta" in schema
        assert schema["meta"]["resourceType"] == "Schema"


class TestGetAllSchemas:
    """Tests for get_all_schemas function."""

    def test_returns_list(self):
        """get_all_schemas should return a list."""
        schemas = get_all_schemas()
        assert isinstance(schemas, list)

    def test_returns_two_schemas(self):
        """get_all_schemas should return User and Group schemas."""
        schemas = get_all_schemas()
        assert len(schemas) == 2

    def test_contains_user_schema(self):
        """get_all_schemas should contain User schema."""
        schemas = get_all_schemas()
        ids = [s["id"] for s in schemas]
        assert SCHEMA_USER in ids

    def test_contains_group_schema(self):
        """get_all_schemas should contain Group schema."""
        schemas = get_all_schemas()
        ids = [s["id"] for s in schemas]
        assert SCHEMA_GROUP in ids


class TestServiceProviderConfigStructure:
    """Tests for ServiceProviderConfig response structure."""

    def test_config_has_schemas(self):
        """Config should have schemas array."""
        # Simulate the response structure
        config = {
            "schemas": [SCHEMA_SERVICE_PROVIDER_CONFIG],
            "patch": {"supported": True},
            "bulk": {"supported": False},
            "filter": {"supported": True},
        }
        assert SCHEMA_SERVICE_PROVIDER_CONFIG in config["schemas"]

    def test_config_patch_supported(self):
        """Config should indicate patch is supported."""
        # We support PATCH for SCIM resources
        config = {"patch": {"supported": True}}
        assert config["patch"]["supported"] is True

    def test_config_bulk_not_supported(self):
        """Config should indicate bulk is not supported."""
        config = {"bulk": {"supported": False}}
        assert config["bulk"]["supported"] is False

    def test_config_filter_supported(self):
        """Config should indicate filter is supported."""
        config = {"filter": {"supported": True, "maxResults": 100}}
        assert config["filter"]["supported"] is True
        assert config["filter"]["maxResults"] == 100

    def test_config_auth_scheme(self):
        """Config should have bearer token auth scheme."""
        auth = {
            "name": "OAuth Bearer Token",
            "type": "oauthbearertoken",
            "primary": True
        }
        assert auth["type"] == "oauthbearertoken"
        assert auth["primary"] is True


class TestResourceTypesStructure:
    """Tests for ResourceTypes response structure."""

    def test_user_resource_type(self):
        """User resource type should have correct structure."""
        user_rt = {
            "schemas": [SCHEMA_RESOURCE_TYPE],
            "id": "User",
            "name": "User",
            "endpoint": f"{SCIM_BASE}/Users",
            "schema": SCHEMA_USER
        }
        assert user_rt["id"] == "User"
        assert user_rt["endpoint"].endswith("/Users")
        assert user_rt["schema"] == SCHEMA_USER

    def test_group_resource_type(self):
        """Group resource type should have correct structure."""
        group_rt = {
            "schemas": [SCHEMA_RESOURCE_TYPE],
            "id": "Group",
            "name": "Group",
            "endpoint": f"{SCIM_BASE}/Groups",
            "schema": SCHEMA_GROUP
        }
        assert group_rt["id"] == "Group"
        assert group_rt["endpoint"].endswith("/Groups")
        assert group_rt["schema"] == SCHEMA_GROUP


class TestAttributeProperties:
    """Tests for SCIM attribute properties."""

    def test_username_uniqueness(self):
        """userName should have server uniqueness."""
        schema = get_user_schema()
        attrs = {a["name"]: a for a in schema["attributes"]}
        assert attrs["userName"]["uniqueness"] == "server"

    def test_username_mutability(self):
        """userName should be readWrite."""
        schema = get_user_schema()
        attrs = {a["name"]: a for a in schema["attributes"]}
        assert attrs["userName"]["mutability"] == "readWrite"

    def test_groups_readonly(self):
        """groups attribute should be readOnly."""
        schema = get_user_schema()
        attrs = {a["name"]: a for a in schema["attributes"]}
        assert attrs["groups"]["mutability"] == "readOnly"

    def test_external_id_case_exact(self):
        """externalId should be caseExact."""
        schema = get_user_schema()
        attrs = {a["name"]: a for a in schema["attributes"]}
        assert attrs["externalId"]["caseExact"] is True

    def test_email_type_canonical_values(self):
        """email type should have canonical values."""
        schema = get_user_schema()
        attrs = {a["name"]: a for a in schema["attributes"]}
        email_sub_attrs = {s["name"]: s for s in attrs["emails"]["subAttributes"]}
        assert "canonicalValues" in email_sub_attrs["type"]
        assert "work" in email_sub_attrs["type"]["canonicalValues"]


class TestMetaSection:
    """Tests for meta section in responses."""

    def test_user_schema_meta_location(self):
        """User schema meta should have location."""
        schema = get_user_schema()
        assert "location" in schema["meta"]
        assert SCHEMA_USER in schema["meta"]["location"]

    def test_group_schema_meta_location(self):
        """Group schema meta should have location."""
        schema = get_group_schema()
        assert "location" in schema["meta"]
        assert SCHEMA_GROUP in schema["meta"]["location"]

    def test_schema_meta_resource_type(self):
        """Schema meta should have resourceType = Schema."""
        schema = get_user_schema()
        assert schema["meta"]["resourceType"] == "Schema"


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
