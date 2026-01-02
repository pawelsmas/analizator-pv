"""
Unit tests for Share v2 (v3.8.0).

Tests for auth_store share functions:
- Password-protected shares
- Single-use shares
- Max access count
- Access tracking
- verify_share_access
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Add bess-dispatch to path
BESS_DIR = Path(__file__).parent.parent.parent / "services" / "bess-dispatch"
sys.path.insert(0, str(BESS_DIR))


@pytest.fixture
def temp_db():
    """Create temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    # Cleanup
    try:
        os.unlink(db_path)
    except FileNotFoundError:
        pass


@pytest.fixture
def auth_store(temp_db):
    """Create AuthStore with temporary database."""
    from auth_store import AuthStore
    store = AuthStore(db_path=temp_db)
    # Create default tenant and user
    store.create_tenant("test_tenant", "Test Tenant")
    from auth_config import Role
    store.create_user("test_tenant", "test@test.com", "password123", Role.ADMIN)
    return store


class TestSharePasswordHashing:
    """Tests for share password hashing functions."""

    def test_hash_share_password_returns_string(self):
        """hash_share_password returns a string."""
        from auth_store import hash_share_password
        result = hash_share_password("password1234")
        assert isinstance(result, str)
        assert result.startswith("$2")  # bcrypt prefix

    def test_verify_share_password_correct(self):
        """verify_share_password returns True for correct password."""
        from auth_store import hash_share_password, verify_share_password
        password = "mysecretpassword"
        hashed = hash_share_password(password)
        assert verify_share_password(password, hashed) is True

    def test_verify_share_password_incorrect(self):
        """verify_share_password returns False for incorrect password."""
        from auth_store import hash_share_password, verify_share_password
        hashed = hash_share_password("correctpassword")
        assert verify_share_password("wrongpassword", hashed) is False

    def test_verify_share_password_handles_empty(self):
        """verify_share_password returns False for empty inputs."""
        from auth_store import verify_share_password
        assert verify_share_password("", "") is False
        assert verify_share_password("password", "") is False

    def test_min_share_password_length(self):
        """MIN_SHARE_PASSWORD_LENGTH should be 10."""
        from auth_store import MIN_SHARE_PASSWORD_LENGTH
        assert MIN_SHARE_PASSWORD_LENGTH == 10


class TestCreateShareV2:
    """Tests for create_share with v3.8.0 options."""

    def test_create_share_basic(self, auth_store):
        """Create basic share without v3.8.0 options."""
        share = auth_store.create_share(
            tenant_id="test_tenant",
            resource_type="run",
            resource_id="run_123",
            created_by="user_123",
        )
        assert share["id"] is not None
        assert share["token"] is not None
        assert share["requires_password"] is False
        assert share["single_use"] is False
        assert share["max_access_count"] is None
        assert share["access_count"] == 0
        assert share["token_version"] == 1

    def test_create_share_with_password(self, auth_store):
        """Create share with password protection."""
        share = auth_store.create_share(
            tenant_id="test_tenant",
            resource_type="run",
            resource_id="run_123",
            created_by="user_123",
            requires_password=True,
            password="validpassword",
        )
        assert share["requires_password"] is True
        assert "password" not in share  # Plaintext not returned
        assert "password_hash" not in share  # Hash not returned

    def test_create_share_password_required_no_password(self, auth_store):
        """Create share with requires_password=True but no password fails."""
        with pytest.raises(ValueError) as exc:
            auth_store.create_share(
                tenant_id="test_tenant",
                resource_type="run",
                resource_id="run_123",
                created_by="user_123",
                requires_password=True,
            )
        assert "SHARE_PASSWORD_REQUIRED" in str(exc.value)

    def test_create_share_password_too_short(self, auth_store):
        """Create share with password < 10 chars fails."""
        with pytest.raises(ValueError) as exc:
            auth_store.create_share(
                tenant_id="test_tenant",
                resource_type="run",
                resource_id="run_123",
                created_by="user_123",
                requires_password=True,
                password="short",
            )
        assert "SHARE_PASSWORD_TOO_WEAK" in str(exc.value)

    def test_create_share_single_use(self, auth_store):
        """Create single-use share."""
        share = auth_store.create_share(
            tenant_id="test_tenant",
            resource_type="run",
            resource_id="run_123",
            created_by="user_123",
            single_use=True,
        )
        assert share["single_use"] is True
        assert share["access_count"] == 0

    def test_create_share_max_access_count(self, auth_store):
        """Create share with max_access_count."""
        share = auth_store.create_share(
            tenant_id="test_tenant",
            resource_type="run",
            resource_id="run_123",
            created_by="user_123",
            max_access_count=5,
        )
        assert share["max_access_count"] == 5
        assert share["access_count"] == 0


class TestListSharesV2:
    """Tests for list_shares returning v3.8.0 fields."""

    def test_list_shares_includes_v2_fields(self, auth_store):
        """list_shares includes v3.8.0 fields."""
        # Create share with v3.8.0 options
        auth_store.create_share(
            tenant_id="test_tenant",
            resource_type="run",
            resource_id="run_123",
            created_by="user_123",
            requires_password=True,
            password="mypassword10",
            single_use=True,
            max_access_count=10,
        )

        shares = auth_store.list_shares("test_tenant")
        assert len(shares) == 1
        share = shares[0]

        assert share["requires_password"] is True
        assert share["single_use"] is True
        assert share["max_access_count"] == 10
        assert share["access_count"] == 0
        assert "last_access_at" in share
        assert share["token_version"] == 1
        # Password hash should NOT be in list response
        assert "password_hash" not in share


class TestGetShareByToken:
    """Tests for get_share_by_token returning v3.8.0 fields."""

    def test_get_share_by_token_includes_password_hash(self, auth_store):
        """get_share_by_token includes password_hash for verification."""
        share_result = auth_store.create_share(
            tenant_id="test_tenant",
            resource_type="run",
            resource_id="run_123",
            created_by="user_123",
            requires_password=True,
            password="validpass12",
        )
        token = share_result["token"]

        share = auth_store.get_share_by_token(token)
        assert share is not None
        assert share["requires_password"] is True
        assert "password_hash" in share  # Needed for verification
        assert share["password_hash"] is not None


class TestRecordShareAccess:
    """Tests for record_share_access."""

    def test_record_access_increments_count(self, auth_store):
        """record_share_access increments access_count."""
        share = auth_store.create_share(
            tenant_id="test_tenant",
            resource_type="run",
            resource_id="run_123",
            created_by="user_123",
        )

        result = auth_store.record_share_access(share["id"])
        assert result["access_count"] == 1
        assert result["auto_revoked"] is False

        result2 = auth_store.record_share_access(share["id"])
        assert result2["access_count"] == 2

    def test_record_access_updates_last_access_at(self, auth_store):
        """record_share_access updates last_access_at."""
        share = auth_store.create_share(
            tenant_id="test_tenant",
            resource_type="run",
            resource_id="run_123",
            created_by="user_123",
        )

        # Initially last_access_at is None
        share_before = auth_store.get_share_by_id(share["id"], "test_tenant")
        assert share_before["last_access_at"] is None

        auth_store.record_share_access(share["id"])

        share_after = auth_store.get_share_by_id(share["id"], "test_tenant")
        assert share_after["last_access_at"] is not None

    def test_record_access_auto_revokes_single_use(self, auth_store):
        """record_share_access auto-revokes single-use shares."""
        share = auth_store.create_share(
            tenant_id="test_tenant",
            resource_type="run",
            resource_id="run_123",
            created_by="user_123",
            single_use=True,
        )

        result = auth_store.record_share_access(share["id"])
        assert result["auto_revoked"] is True

        # Share should now be revoked
        share_after = auth_store.get_share_by_token(share["token"])
        assert share_after is None  # Revoked shares not returned


class TestIsShareMaxAccessExceeded:
    """Tests for is_share_max_access_exceeded."""

    def test_no_limit_never_exceeded(self, auth_store):
        """Share without max_access_count is never exceeded."""
        share = {"max_access_count": None, "access_count": 1000}
        assert auth_store.is_share_max_access_exceeded(share) is False

    def test_limit_not_reached(self, auth_store):
        """Share with access_count < max_access_count is not exceeded."""
        share = {"max_access_count": 10, "access_count": 5}
        assert auth_store.is_share_max_access_exceeded(share) is False

    def test_limit_exactly_reached(self, auth_store):
        """Share with access_count == max_access_count is exceeded."""
        share = {"max_access_count": 10, "access_count": 10}
        assert auth_store.is_share_max_access_exceeded(share) is True

    def test_limit_exceeded(self, auth_store):
        """Share with access_count > max_access_count is exceeded."""
        share = {"max_access_count": 10, "access_count": 15}
        assert auth_store.is_share_max_access_exceeded(share) is True


class TestVerifyShareAccess:
    """Tests for verify_share_access."""

    def test_valid_share_returns_valid(self, auth_store):
        """Valid share without restrictions returns valid."""
        share = auth_store.create_share(
            tenant_id="test_tenant",
            resource_type="run",
            resource_id="run_123",
            created_by="user_123",
        )

        result = auth_store.verify_share_access(share["token"])
        assert result["valid"] is True
        assert result["error_code"] is None
        assert result["share"] is not None

    def test_invalid_token_returns_not_found(self, auth_store):
        """Invalid token returns SHARE_NOT_FOUND."""
        result = auth_store.verify_share_access("invalid_token")
        assert result["valid"] is False
        assert result["error_code"] == "SHARE_NOT_FOUND"

    def test_password_required_no_password(self, auth_store):
        """Password-protected share without password returns SHARE_PASSWORD_REQUIRED."""
        share = auth_store.create_share(
            tenant_id="test_tenant",
            resource_type="run",
            resource_id="run_123",
            created_by="user_123",
            requires_password=True,
            password="secretpass1",
        )

        result = auth_store.verify_share_access(share["token"])
        assert result["valid"] is False
        assert result["error_code"] == "SHARE_PASSWORD_REQUIRED"

    def test_password_required_wrong_password(self, auth_store):
        """Password-protected share with wrong password returns SHARE_PASSWORD_INVALID."""
        share = auth_store.create_share(
            tenant_id="test_tenant",
            resource_type="run",
            resource_id="run_123",
            created_by="user_123",
            requires_password=True,
            password="correctpass1",
        )

        result = auth_store.verify_share_access(share["token"], password="wrongpassword")
        assert result["valid"] is False
        assert result["error_code"] == "SHARE_PASSWORD_INVALID"

    def test_password_required_correct_password(self, auth_store):
        """Password-protected share with correct password returns valid."""
        password = "correctpass1"
        share = auth_store.create_share(
            tenant_id="test_tenant",
            resource_type="run",
            resource_id="run_123",
            created_by="user_123",
            requires_password=True,
            password=password,
        )

        result = auth_store.verify_share_access(share["token"], password=password)
        assert result["valid"] is True
        assert result["error_code"] is None

    def test_max_access_exceeded(self, auth_store):
        """Share with exceeded max_access_count returns SHARE_MAX_ACCESS_EXCEEDED."""
        share = auth_store.create_share(
            tenant_id="test_tenant",
            resource_type="run",
            resource_id="run_123",
            created_by="user_123",
            max_access_count=2,
        )

        # Record 2 accesses
        auth_store.record_share_access(share["id"])
        auth_store.record_share_access(share["id"])

        # Third verify should fail
        result = auth_store.verify_share_access(share["token"])
        assert result["valid"] is False
        assert result["error_code"] == "SHARE_MAX_ACCESS_EXCEEDED"

    def test_single_use_already_used(self, auth_store):
        """Single-use share already accessed returns error."""
        share = auth_store.create_share(
            tenant_id="test_tenant",
            resource_type="run",
            resource_id="run_123",
            created_by="user_123",
            single_use=True,
        )

        # First access
        auth_store.record_share_access(share["id"])

        # Second verify should fail (share is revoked)
        result = auth_store.verify_share_access(share["token"])
        assert result["valid"] is False
        # Token is revoked so it's not found
        assert result["error_code"] in ("SHARE_NOT_FOUND", "SHARE_ALREADY_USED")


class TestMigrationV2:
    """Tests for v3.8.0 migration."""

    def test_migration_adds_columns(self, temp_db):
        """Migration adds v3.8.0 columns to existing database."""
        import sqlite3

        # Create database with old schema (without v3.8.0 columns)
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()

        # Create minimal tables needed
        cursor.execute("CREATE TABLE tenants (id TEXT PRIMARY KEY)")
        cursor.execute("INSERT INTO tenants (id) VALUES ('test')")

        # Create shares table without v3.8.0 columns
        cursor.execute("""
            CREATE TABLE shares (
                id TEXT PRIMARY KEY,
                tenant_id TEXT,
                resource_type TEXT,
                resource_id TEXT,
                token_hash TEXT,
                created_at TEXT,
                expires_at TEXT,
                revoked_at TEXT,
                created_by TEXT,
                label TEXT,
                project_id TEXT
            )
        """)
        conn.commit()
        conn.close()

        # Import AuthStore which should run migration
        from auth_store import AuthStore
        store = AuthStore(db_path=temp_db)

        # Check that new columns exist
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(shares)")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()

        assert "requires_password" in columns
        assert "password_hash" in columns
        assert "single_use" in columns
        assert "max_access_count" in columns
        assert "access_count" in columns
        assert "last_access_at" in columns
        assert "token_version" in columns


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
