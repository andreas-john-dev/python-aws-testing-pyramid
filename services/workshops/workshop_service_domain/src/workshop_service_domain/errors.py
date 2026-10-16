class DomainError(Exception):
    """Base class for domain errors. Adapters translate technical errors into these."""


class WorkshopNotFound(DomainError):
    pass


class RegistrationNotFound(DomainError):
    pass


class CapacityExceeded(DomainError):
    pass


class SeatLimitExceeded(DomainError):
    pass


class CancellationTooLate(DomainError):
    pass


class WorkshopAlreadyStarted(DomainError):
    pass


class RegistrationNotOwned(DomainError):
    pass


class ConcurrentUpdateError(DomainError):
    """The workshop was changed by someone else since it was loaded."""
