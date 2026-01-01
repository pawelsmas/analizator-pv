"""
Login lockout policy module (v3.2.0 PR3).

Implements per-user lockout after consecutive failed login attempts.
Returns 423 Locked when account is locked.

Configuration via environment variables:
- LOCKOUT_MAX_ATTEMPTS: Max failed attempts before lockout (default: 5)
- LOCKOUT_WINDOW_SECONDS: Window for counting failures (default: 300 = 5 min)
- LOCKOUT_DURATION_SECONDS: How long account stays locked (default: 900 = 15 min)
"""
import os
import time
from dataclasses import dataclass, field
from typing import Dict, Optional
from prometheus_client import Counter, Gauge


# Configuration from environment
LOCKOUT_MAX_ATTEMPTS = int(os.getenv("LOCKOUT_MAX_ATTEMPTS", "5"))
LOCKOUT_WINDOW_SECONDS = int(os.getenv("LOCKOUT_WINDOW_SECONDS", "300"))
LOCKOUT_DURATION_SECONDS = int(os.getenv("LOCKOUT_DURATION_SECONDS", "900"))


# Prometheus metrics
LOGIN_FAILURES_TOTAL = Counter(
    "bess_login_failures_total",
    "Total number of failed login attempts"
)
ACCOUNTS_LOCKED_TOTAL = Counter(
    "bess_accounts_locked_total",
    "Total number of accounts locked due to failed attempts"
)
ACCOUNTS_CURRENTLY_LOCKED = Gauge(
    "bess_accounts_currently_locked",
    "Number of accounts currently locked"
)
LOGIN_BLOCKED_TOTAL = Counter(
    "bess_login_blocked_total",
    "Total number of login attempts blocked due to lockout"
)


@dataclass
class UserLockoutState:
    """Track failed login attempts for a user."""
    failed_attempts: list = field(default_factory=list)  # List of timestamps
    locked_until: Optional[float] = None


class LoginLockoutManager:
    """
    Manages per-user login lockout state.

    Uses in-memory storage (suitable for single-instance deployments).
    For multi-instance, consider Redis-backed implementation.
    """

    def __init__(
        self,
        max_attempts: int = LOCKOUT_MAX_ATTEMPTS,
        window_seconds: int = LOCKOUT_WINDOW_SECONDS,
        lockout_duration: int = LOCKOUT_DURATION_SECONDS
    ):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self.lockout_duration = lockout_duration
        self._states: Dict[str, UserLockoutState] = {}

    def _get_state(self, username: str) -> UserLockoutState:
        """Get or create lockout state for user."""
        if username not in self._states:
            self._states[username] = UserLockoutState()
        return self._states[username]

    def _cleanup_old_attempts(self, state: UserLockoutState, now: float) -> None:
        """Remove failed attempts outside the window."""
        cutoff = now - self.window_seconds
        state.failed_attempts = [ts for ts in state.failed_attempts if ts > cutoff]

    def is_locked(self, username: str) -> tuple[bool, Optional[int]]:
        """
        Check if user account is locked.

        Returns:
            (is_locked, remaining_seconds) - remaining_seconds is None if not locked
        """
        state = self._get_state(username)
        now = time.time()

        if state.locked_until is not None:
            if now < state.locked_until:
                remaining = int(state.locked_until - now)
                return True, remaining
            else:
                # Lockout expired, clear state
                state.locked_until = None
                state.failed_attempts = []
                ACCOUNTS_CURRENTLY_LOCKED.dec()

        return False, None

    def record_failure(self, username: str) -> tuple[bool, Optional[int]]:
        """
        Record a failed login attempt.

        Returns:
            (is_now_locked, lockout_seconds) - if locked, how long until unlock
        """
        state = self._get_state(username)
        now = time.time()

        # First check if already locked
        is_locked, remaining = self.is_locked(username)
        if is_locked:
            LOGIN_BLOCKED_TOTAL.inc()
            return True, remaining

        # Clean up old attempts and add new one
        self._cleanup_old_attempts(state, now)
        state.failed_attempts.append(now)
        LOGIN_FAILURES_TOTAL.inc()

        # Check if we hit the limit
        if len(state.failed_attempts) >= self.max_attempts:
            state.locked_until = now + self.lockout_duration
            ACCOUNTS_LOCKED_TOTAL.inc()
            ACCOUNTS_CURRENTLY_LOCKED.inc()
            return True, self.lockout_duration

        return False, None

    def record_success(self, username: str) -> None:
        """Record a successful login, clearing failure state."""
        if username in self._states:
            state = self._states[username]
            if state.locked_until is not None:
                ACCOUNTS_CURRENTLY_LOCKED.dec()
            del self._states[username]

    def get_attempts_remaining(self, username: str) -> int:
        """Get number of attempts remaining before lockout."""
        state = self._get_state(username)
        now = time.time()
        self._cleanup_old_attempts(state, now)
        return max(0, self.max_attempts - len(state.failed_attempts))

    def unlock_user(self, username: str) -> bool:
        """
        Manually unlock a user account (admin action).

        Returns True if user was locked and is now unlocked.
        """
        if username in self._states:
            state = self._states[username]
            if state.locked_until is not None:
                state.locked_until = None
                state.failed_attempts = []
                ACCOUNTS_CURRENTLY_LOCKED.dec()
                return True
        return False

    def cleanup_expired(self) -> int:
        """
        Remove expired lockout states to free memory.

        Returns number of states cleaned up.
        """
        now = time.time()
        to_remove = []

        for username, state in self._states.items():
            # Remove if lockout expired and no recent failures
            if state.locked_until is not None and now >= state.locked_until:
                state.locked_until = None
                ACCOUNTS_CURRENTLY_LOCKED.dec()

            self._cleanup_old_attempts(state, now)

            # Remove empty states
            if not state.failed_attempts and state.locked_until is None:
                to_remove.append(username)

        for username in to_remove:
            del self._states[username]

        return len(to_remove)


# Global instance
lockout_manager = LoginLockoutManager()


def check_lockout(username: str) -> tuple[bool, Optional[int]]:
    """
    Check if user is locked out.

    Returns (is_locked, remaining_seconds).
    Use this before attempting authentication.
    """
    return lockout_manager.is_locked(username)


def record_login_failure(username: str) -> tuple[bool, Optional[int]]:
    """
    Record a failed login attempt.

    Returns (is_now_locked, lockout_duration_seconds).
    """
    return lockout_manager.record_failure(username)


def record_login_success(username: str) -> None:
    """Record successful login, clearing any failure state."""
    lockout_manager.record_success(username)


def get_lockout_response_body(username: str, remaining_seconds: int) -> dict:
    """
    Generate 423 Locked response body.

    Returns dict suitable for JSONResponse.
    """
    return {
        "error_code": "ACCOUNT_LOCKED",
        "message": "Account temporarily locked due to too many failed login attempts",
        "locked_until_seconds": remaining_seconds,
        "max_attempts": LOCKOUT_MAX_ATTEMPTS,
        "lockout_duration_seconds": LOCKOUT_DURATION_SECONDS
    }
