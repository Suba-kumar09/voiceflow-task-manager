"""Password hashing with argon2id."""

from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import get_settings

MIN_PASSWORD_LENGTH = 12


@lru_cache
def _hasher() -> PasswordHasher:
    if get_settings().environment == "test":
        # Fast parameters for the test suite only. Never used outside VOICEFLOW_ENVIRONMENT=test.
        return PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
    return PasswordHasher()  # argon2id with library-recommended defaults


@lru_cache
def _dummy_hash() -> str:
    return _hasher().hash("dummy-password-for-timing-equalisation")


def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    return _hasher().hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher().verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def burn_verification_time(password: str) -> None:
    """Spend the same work as a real check, so unknown usernames are not revealed by timing."""
    verify_password(_dummy_hash(), password)


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher().check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def clear_caches() -> None:
    _hasher.cache_clear()
    _dummy_hash.cache_clear()
