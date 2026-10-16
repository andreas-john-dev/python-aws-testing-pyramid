from datetime import datetime

from workshop_service_domain.errors import ConcurrentUpdateError
from workshop_service_domain.models import Workshop


class FakeWorkshopRepository:
    """In-memory WorkshopRepository. The contract tests keep it honest against DynamoDB.

    It stores deep copies, so a test that changes a loaded workshop and forgets to save fails.
    """

    def __init__(self) -> None:
        self._workshops: dict[str, Workshop] = {}
        self._conflicts_to_raise = 0
        self.save_calls = 0

    def get(self, workshop_id: str) -> Workshop | None:
        workshop = self._workshops.get(workshop_id)
        return workshop.model_copy(deep=True) if workshop else None

    def save(self, workshop: Workshop) -> None:
        self.save_calls += 1
        if self._conflicts_to_raise:
            self._conflicts_to_raise -= 1
            raise ConcurrentUpdateError(workshop.id)
        stored = self._workshops.get(workshop.id)
        stored_version = stored.version if stored else 0
        if stored_version != workshop.version:
            raise ConcurrentUpdateError(workshop.id)
        workshop.version += 1
        self._workshops[workshop.id] = workshop.model_copy(deep=True)

    def list_upcoming(self, now: datetime) -> list[Workshop]:
        upcoming = (w for w in self._workshops.values() if w.starts_at > now)
        return [w.model_copy(deep=True) for w in sorted(upcoming, key=lambda w: w.starts_at)]

    # Test controls, no patching needed.
    def fail_next_save_with_conflict(self, times: int = 1) -> None:
        self._conflicts_to_raise += times
