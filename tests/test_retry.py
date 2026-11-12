import pytest

from webhook_platform.retry import RetryPolicy, is_retryable
from webhook_platform.sender import DeliveryResult


def result(error: str | None, status_code: int | None = None) -> DeliveryResult:
    return DeliveryResult(ok=False, status_code=status_code, error=error, duration_ms=1)


def test_default_policy_allows_eight_attempts() -> None:
    assert RetryPolicy().max_attempts == 8


def test_delays_follow_the_schedule_and_end_after_the_last_one() -> None:
    policy = RetryPolicy(jitter=0.0)

    delays = [policy.delay_after(attempt) for attempt in range(1, 9)]

    assert delays == [5.0, 300.0, 1800.0, 7200.0, 18000.0, 36000.0, 36000.0, None]


def test_jitter_stays_within_twenty_five_percent() -> None:
    policy = RetryPolicy()

    assert policy.delay_after(2, rng=lambda: 0.0) == 225.0
    assert policy.delay_after(2, rng=lambda: 0.5) == 300.0
    assert policy.delay_after(2, rng=lambda: 1.0) == 375.0


def test_scale_shortens_every_delay() -> None:
    policy = RetryPolicy(jitter=0.0, scale=0.01)

    assert policy.delay_after(2) == pytest.approx(3.0)


@pytest.mark.parametrize(
    "outcome",
    [
        result(None, 500),
        result(None, 429),
        result("timeout"),
        result("connection error"),
        result("dns resolution failed"),
    ],
)
def test_transient_failures_are_retried(outcome: DeliveryResult) -> None:
    assert is_retryable(outcome)


def test_blocked_destinations_are_never_retried() -> None:
    assert not is_retryable(result("destination not allowed"))
