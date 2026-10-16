"""Reads raw items, not through the adapter.

A mapping bug that writes and reads the same wrong value is invisible through the adapter. The
state reader translates raw items into a neutral state that does not depend on DynamoDB, so Part 2
can add a SQL state reader for the same assertions.
"""

from dataclasses import dataclass, field
from typing import Any

from boto3.dynamodb.types import TypeDeserializer
from botocore.client import BaseClient
from workshop_service_domain.models import Workshop
from workshop_service_infra import schema
from workshop_service_infra.dynamodb import DynamoDBWorkshopRepository

_deserializer = TypeDeserializer()


@dataclass(frozen=True)
class RegistrationState:
    user_id: str
    seats: int
    status: str


@dataclass(frozen=True)
class WorkshopState:
    version: int
    registrations: list[RegistrationState]

    @property
    def active_seats(self) -> int:
        return sum(r.seats for r in self.registrations if r.status == "active")


@dataclass
class DynamoDbTable:
    """A table plus the partitions a test wrote, so a finalizer can delete exactly those."""

    client: BaseClient
    name: str
    written_pks: set[str] = field(default_factory=set)

    def track(self, workshop_id: str) -> None:
        self.written_pks.add(schema.workshop_pk(workshop_id))

    def cleanup(self) -> None:
        for pk in self.written_pks:
            for item in self._query_pk(pk):
                self.client.delete_item(
                    TableName=self.name,
                    Key={k: item[k] for k in (schema.PARTITION_KEY, schema.SORT_KEY)},
                )
        self.written_pks.clear()

    def _query_pk(self, pk: str) -> list[dict[str, Any]]:
        paginator = self.client.get_paginator("query")
        pages = paginator.paginate(
            TableName=self.name,
            KeyConditionExpression="#pk = :pk",
            ExpressionAttributeNames={"#pk": schema.PARTITION_KEY},
            ExpressionAttributeValues={":pk": {"S": pk}},
            ConsistentRead=True,
        )
        return [item for page in pages for item in page["Items"]]


class DynamoDbStateReader:
    def __init__(self, table: DynamoDbTable) -> None:
        self._table = table

    def raw_items(self, workshop_id: str) -> list[dict[str, Any]]:
        items = self._table._query_pk(schema.workshop_pk(workshop_id))
        return [{k: _deserializer.deserialize(v) for k, v in item.items()} for item in items]

    def read(self, workshop_id: str) -> WorkshopState | None:
        items = self.raw_items(workshop_id)
        meta = next((i for i in items if i[schema.SORT_KEY] == schema.META_SORT_KEY), None)
        if meta is None:
            return None
        registrations = sorted(
            (
                RegistrationState(i["user_id"], int(i["seats"]), i["status"])
                for i in items
                if i[schema.SORT_KEY].startswith(schema.REGISTRATION_PREFIX)
            ),
            key=lambda r: (r.user_id, r.seats, r.status),
        )
        return WorkshopState(version=int(meta["version"]), registrations=registrations)


def tracked_repository(table: DynamoDbTable) -> DynamoDBWorkshopRepository:
    """The real adapter, remembering each saved workshop for the table's finalizer."""
    return _TrackedRepository(table)


class _TrackedRepository(DynamoDBWorkshopRepository):
    def __init__(self, table: DynamoDbTable) -> None:
        super().__init__(table.client, table.name)
        self._table = table

    def save(self, workshop: Workshop) -> None:
        self._table.track(workshop.id)
        super().save(workshop)
