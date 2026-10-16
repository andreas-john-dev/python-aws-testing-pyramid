from datetime import datetime
from typing import Protocol

from workshop_service_domain.models import Workshop


class WorkshopRepository(Protocol):
    def get(self, workshop_id: str) -> Workshop | None: ...

    def save(self, workshop: Workshop) -> None:
        """Stores the workshop and increments `workshop.version`.

        Raises ConcurrentUpdateError if the stored version is no longer `workshop.version`.
        """
        ...

    def list_upcoming(self, now: datetime) -> list[Workshop]:
        """Workshops with `starts_at > now`, ordered by `starts_at`."""
        ...


class Clock(Protocol):
    def now(self) -> datetime: ...
