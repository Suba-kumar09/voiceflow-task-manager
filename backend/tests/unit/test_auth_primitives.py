import pytest

from app.auth import passwords
from app.auth.throttle import LoginThrottle


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class TestThrottle:
    def test_blocks_after_max_failures_and_recovers_after_window(self):
        clock = FakeClock()
        t = LoginThrottle(max_failures=3, window_seconds=60, clock=clock)
        for _ in range(3):
            assert not t.is_blocked("user:a")
            t.record_failure("user:a")
        assert t.is_blocked("user:a")
        clock.now += 61
        assert not t.is_blocked("user:a")

    def test_any_blocked_key_blocks(self):
        t = LoginThrottle(max_failures=1, window_seconds=60, clock=FakeClock())
        t.record_failure("ip:1.2.3.4")
        assert t.is_blocked("user:someone-else", "ip:1.2.3.4")

    def test_reset_clears_one_key_only(self):
        t = LoginThrottle(max_failures=1, window_seconds=60, clock=FakeClock())
        t.record_failure("user:a", "ip:x")
        t.reset("user:a")
        assert not t.is_blocked("user:a")
        assert t.is_blocked("ip:x")


class TestPasswords:
    def test_hash_and_verify(self):
        h = passwords.hash_password("a-long-enough-password")
        assert h.startswith("$argon2id$")
        assert passwords.verify_password(h, "a-long-enough-password")
        assert not passwords.verify_password(h, "wrong-password-entirely")

    def test_garbage_hash_does_not_raise(self):
        assert not passwords.verify_password("not-a-hash", "whatever-password")

    def test_short_password_rejected(self):
        with pytest.raises(ValueError):
            passwords.hash_password("short")
