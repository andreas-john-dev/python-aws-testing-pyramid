import pytest

from tests.fakes import FakeClock, FakeWorkshopRepository
from tests.unit.builders import NOW


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(NOW)


@pytest.fixture
def repository() -> FakeWorkshopRepository:
    return FakeWorkshopRepository()
