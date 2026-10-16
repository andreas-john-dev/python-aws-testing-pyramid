from collections.abc import Iterator

import pytest
from workshop_service_domain.ports import WorkshopRepository

from tests.conftest import AWS, MOTO
from tests.fakes import FakeWorkshopRepository
from tests.support.dynamodb import tracked_repository
from tests.support.moto import moto_table

FAKE = "fake"


# One parameter per adapter. Part 2 adds "sql" here and nothing else.
@pytest.fixture(params=[FAKE, MOTO, pytest.param(AWS, marks=pytest.mark.aws)])
def repository(request: pytest.FixtureRequest) -> Iterator[WorkshopRepository]:
    if request.param == FAKE:
        yield FakeWorkshopRepository()
    elif request.param == MOTO:
        with moto_table() as table:
            yield tracked_repository(table)
    else:
        yield tracked_repository(request.getfixturevalue("aws_table"))
