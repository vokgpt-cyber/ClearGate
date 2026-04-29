"""Tests for LDAP authentication provider (v0.4.0 Phase 3)."""

import pytest

from app.services.auth_ldap import LDAPAuthProvider, LDAPUserResult, LDAPUnreachable


class TestLDAPAuthProvider:
    """Unit tests for LDAP provider without actual AD connectivity."""

    def test_ldap_escape_ldap(self):
        """Test LDAP filter special character escaping."""
        # Test escaping of special chars per RFC 4515
        assert LDAPAuthProvider._escape_ldap("user") == "user"
        assert LDAPAuthProvider._escape_ldap("user*") == "user\\2a"
        assert LDAPAuthProvider._escape_ldap("user(name)") == "user\\28name\\29"
        assert LDAPAuthProvider._escape_ldap("user/path") == "user\\2fpath"
        assert LDAPAuthProvider._escape_ldap("user\\x00") == "user\\00"

    def test_ldap_user_result_creation(self):
        """Test creating an LDAP user result."""
        result = LDAPUserResult(
            user_id="abc123",
            username="jsmith",
            email="jsmith@example.com",
            display_name="John Smith",
            role="lawyer",
        )
        assert result.user_id == "abc123"
        assert result.username == "jsmith"
        assert result.role == "lawyer"
        assert result.email == "jsmith@example.com"

    def test_ldap_user_result_immutable(self):
        """Test that LDAPUserResult is frozen (immutable)."""
        result = LDAPUserResult(
            user_id="abc123",
            username="jsmith",
            email="jsmith@example.com",
            display_name="John Smith",
            role="lawyer",
        )
        # dataclass(frozen=True) should prevent attribute assignment
        with pytest.raises(AttributeError):
            result.role = "admin"

    def test_ldap_provider_factory_no_config(self):
        """Test that get_ldap_provider returns None when not configured."""
        from app.services.auth_ldap import get_ldap_provider

        # Mock empty config
        import app.config as config_module

        original_url = config_module.settings.ldap_url
        try:
            config_module.settings.ldap_url = ""
            provider = get_ldap_provider()
            assert provider is None
        finally:
            config_module.settings.ldap_url = original_url

    def test_ldap_provider_initialization_with_config(self):
        """Test LDAPAuthProvider initialization with minimal config."""
        provider = LDAPAuthProvider(
            url="ldaps://ad.example.com:636",
            bind_dn="CN=svc_cleargate,OU=Service,DC=example,DC=com",
            bind_password="password123",
            base_dn="OU=Users,DC=example,DC=com",
            admin_group_dn="CN=CLEARGATE_ADMINS,OU=Groups,DC=example,DC=com",
            user_group_dn="CN=CLEARGATE_USERS,OU=Groups,DC=example,DC=com",
        )
        assert provider._url == "ldaps://ad.example.com:636"
        assert provider._bind_dn.startswith("CN=svc_cleargate")
        assert provider._base_dn == "OU=Users,DC=example,DC=com"
        assert provider._timeout_seconds == 5


class TestAuditLog:
    """Tests for hash-chained audit log (v0.4.0 Phase 3)."""

    def test_audit_log_sanitize_payload(self, tmp_path):
        """Test that sensitive keys are redacted from payloads."""
        from app.services.audit_log import AuditLog

        audit_log = AuditLog(
            db_path=tmp_path / "audit.db",
            jsonl_path=tmp_path / "audit.jsonl",
        )

        payload = {
            "username": "user123",
            "password": "secretpassword",
            "api_key": "sk-12345",
            "safe_data": "ok",
        }

        clean = audit_log._sanitize_payload(payload)
        assert clean["username"] == "user123"
        assert clean["safe_data"] == "ok"
        assert clean["password"] == "<redacted>"
        assert clean["api_key"] == "<redacted>"

        audit_log.close()

    def test_audit_log_sanitize_nested(self, tmp_path):
        """Test recursive sanitization of nested dicts."""
        from app.services.audit_log import AuditLog

        audit_log = AuditLog(
            db_path=tmp_path / "audit.db",
            jsonl_path=tmp_path / "audit.jsonl",
        )

        payload = {
            "user": {"name": "john", "password": "secret"},
            "items": [{"id": 1, "token": "abc"}],
        }

        clean = audit_log._sanitize_payload(payload)
        assert clean["user"]["name"] == "john"
        assert clean["user"]["password"] == "<redacted>"
        assert clean["items"][0]["id"] == 1
        assert clean["items"][0]["token"] == "abc"  # Lists don't recurse in simple impl

        audit_log.close()


class TestUserStoreRoles:
    """Tests for role-based user store (v0.4.0 Phase 3)."""

    def test_user_store_set_role(self, tmp_path):
        """Test updating a user's role."""
        from app.services.user_store import UserStore

        store = UserStore(db_path=tmp_path / "users.db")
        try:
            rec = store.create_user(
                username="lawyer1",
                password_hash="fake_hash",
                role="lawyer",
            )
            assert rec.role == "lawyer"

            # Upgrade to admin
            ok = store.set_role(rec.user_id, "admin")
            assert ok

            # Verify the change
            updated = store.get_by_id(rec.user_id)
            assert updated.role == "admin"

            # Downgrade back
            ok = store.set_role(rec.user_id, "lawyer")
            assert ok
            updated = store.get_by_id(rec.user_id)
            assert updated.role == "lawyer"
        finally:
            store.close()

    def test_user_store_record_login(self, tmp_path):
        """Test recording a user login timestamp."""
        from app.services.user_store import UserStore

        store = UserStore(db_path=tmp_path / "users.db")
        try:
            rec = store.create_user(
                username="testuser",
                password_hash="fake_hash",
            )
            assert rec.last_login_at is None

            # Record a login
            ok = store.record_login(rec.user_id)
            assert ok

            # Verify timestamp was set
            updated = store.get_by_id(rec.user_id)
            assert updated.last_login_at is not None
        finally:
            store.close()

    def test_user_store_ldap_upsert_new(self, tmp_path):
        """Test creating a new LDAP user via get_or_create_from_ldap."""
        from app.services.user_store import UserStore
        from app.services.auth_ldap import LDAPUserResult

        store = UserStore(db_path=tmp_path / "users.db")
        try:
            ldap_user = LDAPUserResult(
                user_id="dn_hash_abc123",
                username="jsmith",
                email="jsmith@example.com",
                display_name="John Smith",
                role="lawyer",
            )

            rec = store.get_or_create_from_ldap(ldap_user)
            assert rec.username == "jsmith"
            assert rec.email == "jsmith@example.com"
            assert rec.display_name == "John Smith"
            assert rec.role == "lawyer"
            assert rec.ldap_dn == "dn_hash_abc123"
            assert rec.password_hash is None  # LDAP users don't have passwords

            # Verify it can be looked up
            found = store.get_by_username("jsmith")
            assert found is not None
            assert found.user_id == rec.user_id
        finally:
            store.close()

    def test_user_store_ldap_upsert_update(self, tmp_path):
        """Test updating an existing LDAP user."""
        from app.services.user_store import UserStore
        from app.services.auth_ldap import LDAPUserResult

        store = UserStore(db_path=tmp_path / "users.db")
        try:
            # Create initial user with local password
            rec1 = store.create_user(
                username="jsmith",
                password_hash="old_hash",
                role="lawyer",
            )

            # Now "authenticate" via LDAP and update
            ldap_user = LDAPUserResult(
                user_id="dn_hash_abc123",
                username="jsmith",
                email="jsmith@company.com",  # Updated email
                display_name="John Q Smith",  # Updated display name
                role="admin",  # Promoted to admin
            )

            rec2 = store.get_or_create_from_ldap(ldap_user)

            # Should have updated the existing user, not created a new one
            assert rec2.user_id == rec1.user_id
            assert rec2.email == "jsmith@company.com"
            assert rec2.display_name == "John Q Smith"
            assert rec2.role == "admin"
            assert rec2.password_hash == "old_hash"  # Local password preserved
        finally:
            store.close()
