import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from workshop_service_domain.errors import (
    ConcurrentUpdateError,
    WorkshopAlreadyStarted,
    WorkshopNotFound,
)
from workshop_service_domain.models import Registration, Workshop
from workshop_service_domain.ports import Clock, WorkshopRepository


@dataclass(frozen=True)
class RetryPolicy:
    """Exponential backoff with full jitter. Tests pass `RetryPolicy(base_delay=0)`."""

    attempts: int = 3
    base_delay: float = 0.05
    max_delay: float = 0.5

    def delay(self, attempt: int) -> float:
        return random.uniform(0, min(self.max_delay, self.base_delay * 2**attempt))


DEFAULT_RETRY = RetryPolicy()


def _with_retry[T](policy: RetryPolicy, operation: Callable[[], T]) -> T:
    for attempt in range(policy.attempts):
        try:
            return operation()
        except ConcurrentUpdateError:
            if attempt == policy.attempts - 1:
                raise
            time.sleep(policy.delay(attempt))
    raise AssertionError("unreachable")


class CreateWorkshop:
    def __init__(self, repository: WorkshopRepository, clock: Clock) -> None:
        self._repository = repository
        self._clock = clock

    def __call__(self, title: str, starts_at: datetime, capacity: int) -> Workshop:
        workshop = Workshop(title=title, starts_at=starts_at, capacity=capacity)
        if workshop.starts_at <= self._clock.now():
            raise WorkshopAlreadyStarted("a workshop must start in the future")
        self._repository.save(workshop)
        return workshop


class GetWorkshop:
    def __init__(self, repository: WorkshopRepository) -> None:
        self._repository = repository

    def __call__(self, workshop_id: str) -> Workshop:
        workshop = self._repository.get(workshop_id)
        if workshop is None:
            raise WorkshopNotFound(workshop_id)
        return workshop


class ListUpcomingWorkshops:
    def __init__(self, repository: WorkshopRepository, clock: Clock) -> None:
        self._repository = repository
        self._clock = clock

    def __call__(self) -> list[Workshop]:
        return self._repository.list_upcoming(self._clock.now())


class RegisterForWorkshop:
    def __init__(
        self, repository: WorkshopRepository, clock: Clock, retry: RetryPolicy = DEFAULT_RETRY
    ) -> None:
        self._get = GetWorkshop(repository)
        self._repository = repository
        self._clock = clock
        self._retry = retry

    def __call__(self, workshop_id: str, user_id: str, seats: int) -> Registration:
        def attempt() -> Registration:
            workshop = self._get(workshop_id)
            registration = workshop.register(user_id, seats, self._clock.now())
            self._repository.save(workshop)
            return registration

        return _with_retry(self._retry, attempt)


class CancelRegistration:
    def __init__(
        self, repository: WorkshopRepository, clock: Clock, retry: RetryPolicy = DEFAULT_RETRY
    ) -> None:
        self._get = GetWorkshop(repository)
        self._repository = repository
        self._clock = clock
        self._retry = retry

    def __call__(self, workshop_id: str, registration_id: str, user_id: str) -> Registration:
        def attempt() -> Registration:
            workshop = self._get(workshop_id)
            before = workshop.model_copy(deep=True)
            registration = workshop.cancel(registration_id, user_id, self._clock.now())
            if workshop != before:
                self._repository.save(workshop)
            return registration

        return _with_retry(self._retry, attempt)
