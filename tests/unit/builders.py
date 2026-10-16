from datetime import UTC, datetime, timedelta

from workshop_service_domain.models import Workshop
from workshop_service_domain.use_cases import RetryPolicy

NOW = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
NO_WAIT = RetryPolicy(base_delay=0)


def make_workshop(capacity: int = 10, starts_in: timedelta = timedelta(days=7)) -> Workshop:
    return Workshop(title="Testing on AWS", starts_at=NOW + starts_in, capacity=capacity)
