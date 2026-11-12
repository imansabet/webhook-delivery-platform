import random
from collections.abc import Callable
from dataclasses import dataclass

from webhook_platform.sender import DeliveryResult

PERMANENT_ERRORS = {"destination not allowed"}


@dataclass(frozen=True)
class RetryPolicy:
    delays: tuple[float, ...] = (5.0, 300.0, 1800.0, 7200.0, 18000.0, 36000.0, 36000.0)
    jitter: float = 0.25
    scale: float = 1.0

    @property
    def max_attempts(self) -> int:
        return len(self.delays) + 1

    def delay_after(
        self, attempt_number: int, rng: Callable[[], float] = random.random
    ) -> float | None:
        if attempt_number > len(self.delays):
            return None
        base = self.delays[attempt_number - 1] * self.scale
        return base * (1 - self.jitter + 2 * self.jitter * rng())


DEFAULT_RETRY_POLICY = RetryPolicy()


def is_retryable(result: DeliveryResult) -> bool:
    return result.error not in PERMANENT_ERRORS
