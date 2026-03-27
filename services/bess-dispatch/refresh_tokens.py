"""
Refresh token module for BESS API (v3.2.0 PR4).

Implements refresh token generation, rotation, and validation.
Refresh tokens are long-lived opaque tokens stored server-side.

Configuration via environment variables:
- REFRESH_TOKEN_EXPIRE_DAYS: Refresh token lifetime (default: 30)
- REFRESH_TOKEN_ROTATE: If 'true', issue new refresh token on each refresh (default: true)
"""
import os
import secrets
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple
from dataclasses import dataclass, field
from prometheus_client import Counter, Gauge


# Configuration
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30"))
REFRESH_TOKEN_ROTATE = os.getenv("REFRESH_TOKEN_ROTATE", "true").lower() == "true"
REFRESH_TOKEN_LENGTH = 64  # Characters in the raw token


# Prometheus metrics
REFRESH_TOKENS_ISSUED_TOTAL = Counter(
    "bess_refresh_tokens_issued_total",
    "Total number of refresh tokens issued"
)
REFRESH_TOKENS_USED_TOTAL = Counter(
    "bess_refresh_tokens_used_total",
    "Total number of refresh token uses"
)
REFRESH_TOKENS_REVOKED_TOTAL = Counter(
    "bess_refresh_tokens_revoked_total",
    "Total number of refresh tokens revoked",
    ["reason"]  # logout, rotation, admin
)
REFRESH_TOKENS_REJECTED_TOTAL = Counter(
    "bess_refresh_tokens_rejected_total",
    "Total number of refresh token rejections",
    ["reason"]  # expired, not_found, already_used
)
REFRESH_TOKENS_ACTIVE = Gauge(
    "bess_refresh_tokens_active",
    "Number of currently active refresh tokens"
)


@dataclass
class RefreshTokenRecord:
    """Server-side refresh token record."""
    token_hash: str
    user_id: str
    tenant_id: str
    email: str
    role: str
    created_at: datetime
    expires_at: datetime
    used: bool = False
    revoked: bool = False
    family_id: str = ""  # For token rotation tracking


class RefreshTokenStore:
    """
    In-memory refresh token store.

    For production, consider Redis or database-backed implementation.
    """

    def __init__(self, expire_days: int = REFRESH_TOKEN_EXPIRE_DAYS):
        self.expire_days = expire_days
        self._tokens: Dict[str, RefreshTokenRecord] = {}  # token_hash -> record
        self._user_tokens: Dict[str, set] = {}  # user_id -> set of token_hashes

    def _hash_token(self, raw_token: str) -> str:
        """Hash a raw token for storage."""
        return hashlib.sha256(raw_token.encode()).hexdigest()

    def _generate_family_id(self) -> str:
        """Generate a unique family ID for token rotation tracking."""
        return secrets.token_hex(16)

    def create_token(
        self,
        user_id: str,
        tenant_id: str,
        email: str,
        role: str,
        family_id: Optional[str] = None,
    ) -> Tuple[str, datetime]:
        """
        Create a new refresh token.

        Returns:
            (raw_token, expires_at)
        """
        raw_token = secrets.token_urlsafe(REFRESH_TOKEN_LENGTH)
        token_hash = self._hash_token(raw_token)

        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=self.expire_days)

        record = RefreshTokenRecord(
            token_hash=token_hash,
            user_id=user_id,
            tenant_id=tenant_id,
            email=email,
            role=role,
            created_at=now,
            expires_at=expires_at,
            family_id=family_id or self._generate_family_id(),
        )

        self._tokens[token_hash] = record

        if user_id not in self._user_tokens:
            self._user_tokens[user_id] = set()
        self._user_tokens[user_id].add(token_hash)

        REFRESH_TOKENS_ISSUED_TOTAL.inc()
        REFRESH_TOKENS_ACTIVE.inc()

        return raw_token, expires_at

    def validate_token(self, raw_token: str) -> Optional[RefreshTokenRecord]:
        """
        Validate a refresh token.

        Returns:
            Token record if valid, None otherwise
        """
        token_hash = self._hash_token(raw_token)
        record = self._tokens.get(token_hash)

        if record is None:
            REFRESH_TOKENS_REJECTED_TOTAL.labels(reason="not_found").inc()
            return None

        if record.revoked:
            REFRESH_TOKENS_REJECTED_TOTAL.labels(reason="revoked").inc()
            return None

        if record.used and REFRESH_TOKEN_ROTATE:
            # Token already used (replay attack detection)
            REFRESH_TOKENS_REJECTED_TOTAL.labels(reason="already_used").inc()
            # Revoke entire family (potential token theft)
            self._revoke_family(record.family_id, "replay_detection")
            return None

        now = datetime.now(timezone.utc)
        if now >= record.expires_at:
            REFRESH_TOKENS_REJECTED_TOTAL.labels(reason="expired").inc()
            return None

        return record

    def use_token(self, raw_token: str) -> Optional[Tuple[RefreshTokenRecord, Optional[str], Optional[datetime]]]:
        """
        Use a refresh token to get user info and optionally rotate.

        Returns:
            (record, new_raw_token, new_expires_at) or None if invalid
            new_raw_token is None if rotation is disabled
        """
        record = self.validate_token(raw_token)
        if record is None:
            return None

        token_hash = self._hash_token(raw_token)
        REFRESH_TOKENS_USED_TOTAL.inc()

        if REFRESH_TOKEN_ROTATE:
            # Mark old token as used
            record.used = True

            # Issue new token in same family
            new_token, new_expires = self.create_token(
                user_id=record.user_id,
                tenant_id=record.tenant_id,
                email=record.email,
                role=record.role,
                family_id=record.family_id,
            )

            # Revoke old token
            record.revoked = True
            REFRESH_TOKENS_REVOKED_TOTAL.labels(reason="rotation").inc()
            REFRESH_TOKENS_ACTIVE.dec()

            return record, new_token, new_expires

        return record, None, None

    def revoke_token(self, raw_token: str, reason: str = "logout") -> bool:
        """
        Revoke a specific refresh token.

        Returns True if token was found and revoked.
        """
        token_hash = self._hash_token(raw_token)
        record = self._tokens.get(token_hash)

        if record is None or record.revoked:
            return False

        record.revoked = True
        REFRESH_TOKENS_REVOKED_TOTAL.labels(reason=reason).inc()
        REFRESH_TOKENS_ACTIVE.dec()

        return True

    def revoke_all_user_tokens(self, user_id: str, reason: str = "logout_all") -> int:
        """
        Revoke all refresh tokens for a user.

        Returns number of tokens revoked.
        """
        token_hashes = self._user_tokens.get(user_id, set())
        revoked_count = 0

        for token_hash in token_hashes:
            record = self._tokens.get(token_hash)
            if record and not record.revoked:
                record.revoked = True
                revoked_count += 1
                REFRESH_TOKENS_REVOKED_TOTAL.labels(reason=reason).inc()
                REFRESH_TOKENS_ACTIVE.dec()

        return revoked_count

    def _revoke_family(self, family_id: str, reason: str) -> int:
        """Revoke all tokens in a family (for replay attack handling)."""
        revoked_count = 0

        for record in self._tokens.values():
            if record.family_id == family_id and not record.revoked:
                record.revoked = True
                revoked_count += 1
                REFRESH_TOKENS_REVOKED_TOTAL.labels(reason=reason).inc()
                REFRESH_TOKENS_ACTIVE.dec()

        return revoked_count

    def cleanup_expired(self) -> int:
        """
        Remove expired tokens from memory.

        Returns number of tokens cleaned up.
        """
        now = datetime.now(timezone.utc)
        to_remove = []

        for token_hash, record in self._tokens.items():
            if now >= record.expires_at or record.revoked:
                to_remove.append(token_hash)
                if not record.revoked:
                    REFRESH_TOKENS_ACTIVE.dec()

        for token_hash in to_remove:
            record = self._tokens.pop(token_hash)
            if record.user_id in self._user_tokens:
                self._user_tokens[record.user_id].discard(token_hash)

        return len(to_remove)


# Global instance
_store = RefreshTokenStore()


def create_refresh_token(
    user_id: str,
    tenant_id: str,
    email: str,
    role: str,
) -> Tuple[str, datetime]:
    """
    Create a new refresh token.

    Returns (raw_token, expires_at).
    """
    return _store.create_token(user_id, tenant_id, email, role)


def use_refresh_token(raw_token: str) -> Optional[Tuple[dict, Optional[str], Optional[datetime]]]:
    """
    Use a refresh token.

    Returns (user_info_dict, new_token, new_expires) or None if invalid.
    new_token is None if rotation is disabled.
    """
    result = _store.use_token(raw_token)
    if result is None:
        return None

    record, new_token, new_expires = result
    user_info = {
        "user_id": record.user_id,
        "tenant_id": record.tenant_id,
        "email": record.email,
        "role": record.role,
    }

    return user_info, new_token, new_expires


def revoke_refresh_token(raw_token: str) -> bool:
    """Revoke a specific refresh token."""
    return _store.revoke_token(raw_token, reason="logout")


def revoke_all_user_refresh_tokens(user_id: str) -> int:
    """Revoke all refresh tokens for a user."""
    return _store.revoke_all_user_tokens(user_id, reason="logout_all")


def get_refresh_token_expiry_seconds() -> int:
    """Get refresh token expiry time in seconds."""
    return REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
