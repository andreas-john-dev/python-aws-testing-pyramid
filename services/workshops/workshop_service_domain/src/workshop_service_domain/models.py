from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, Field, field_validator, model_validator

from workshop_service_domain.errors import (
    CancellationTooLate,
    CapacityExceeded,
    RegistrationNotFound,
    RegistrationNotOwned,
    SeatLimitExceeded,
    WorkshopAlreadyStarted,
)

MAX_SEATS_PER_PERSON = 2
CANCELLATION_DEADLINE = timedelta(hours=48)


def new_id() -> str:
    return uuid4().hex


def _to_utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


def _registration_order(registration: Registration) -> tuple[datetime, str]:
    return registration.created_at, registration.id


class RegistrationStatus(StrEnum):
    ACTIVE = "active"
    CANCELLED = "cancelled"


class Registration(BaseModel):
    id: str = Field(default_factory=new_id)
    user_id: str
    seats: int = Field(ge=1)
    status: RegistrationStatus = RegistrationStatus.ACTIVE
    created_at: AwareDatetime
    # The workshop version whose save last changed this registration. Lets a repository
    # write only what changed instead of every registration.
    changed_in_version: int = Field(default=1, ge=1)

    _utc = field_validator("created_at")(_to_utc)

    @property
    def is_active(self) -> bool:
        return self.status is RegistrationStatus.ACTIVE


class Workshop(BaseModel):
    """Aggregate root. Workshops are small, so it always holds all of its registrations.

    `version` is the stored version: 0 until the first save, and every save adds 1.
    A repository only accepts a save if the stored version still equals `version`
    (optimistic locking).
    """

    id: str = Field(default_factory=new_id)
    title: str = Field(min_length=1, max_length=200)
    starts_at: AwareDatetime
    capacity: int = Field(ge=1)
    version: int = Field(default=0, ge=0)
    registrations: list[Registration] = Field(default_factory=list)

    _utc = field_validator("starts_at")(_to_utc)

    @model_validator(mode="after")
    def _canonical_order(self) -> Workshop:
        # Registrations are ordered by (created_at, id) wherever they come from, so a workshop
        # read back from any repository equals the one that was saved.
        self.registrations.sort(key=_registration_order)
        return self

    @property
    def pending_registrations(self) -> list[Registration]:
        """Registrations changed since the workshop was loaded, i.e. what the next save writes."""
        return [r for r in self.registrations if r.changed_in_version > self.version]

    @property
    def active_seats(self) -> int:
        return sum(r.seats for r in self.registrations if r.is_active)

    @property
    def free_seats(self) -> int:
        return self.capacity - self.active_seats

    def seats_held_by(self, user_id: str) -> int:
        return sum(r.seats for r in self.registrations if r.is_active and r.user_id == user_id)

    def register(self, user_id: str, seats: int, now: datetime) -> Registration:
        if now >= self.starts_at:
            raise WorkshopAlreadyStarted(self.id)
        if self.seats_held_by(user_id) + seats > MAX_SEATS_PER_PERSON:
            raise SeatLimitExceeded(f"at most {MAX_SEATS_PER_PERSON} seats per person")
        if seats > self.free_seats:
            raise CapacityExceeded(f"{self.free_seats} seats left")
        registration = Registration(
            user_id=user_id, seats=seats, created_at=now, changed_in_version=self.version + 1
        )
        self.registrations.append(registration)
        self.registrations.sort(key=_registration_order)
        return registration

    def cancel(self, registration_id: str, user_id: str, now: datetime) -> Registration:
        registration = self._registration(registration_id)
        if registration.user_id != user_id:
            raise RegistrationNotOwned(registration_id)
        if not registration.is_active:
            return registration
        if now > self.starts_at - CANCELLATION_DEADLINE:
            raise CancellationTooLate(registration_id)
        registration.status = RegistrationStatus.CANCELLED
        registration.changed_in_version = self.version + 1
        return registration

    def _registration(self, registration_id: str) -> Registration:
        for registration in self.registrations:
            if registration.id == registration_id:
                return registration
        raise RegistrationNotFound(registration_id)
