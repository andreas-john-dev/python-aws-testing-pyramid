from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from botocore.client import BaseClient
from botocore.exceptions import ClientError
from workshop_service_domain.errors import ConcurrentUpdateError
from workshop_service_domain.models import Registration, Workshop

from workshop_service_infra import schema

# Cancellation reasons that mean "someone else changed this workshop".
_CONFLICT_CODES = {"ConditionalCheckFailed", "TransactionConflict"}
_MAX_TRANSACTION_ITEMS = 100

_serializer = TypeSerializer()
_deserializer = TypeDeserializer()


def _serialize(item: dict[str, Any]) -> dict[str, Any]:
    return {key: _serializer.serialize(value) for key, value in item.items()}


def _deserialize(item: dict[str, Any]) -> dict[str, Any]:
    return {key: _deserializer.deserialize(value) for key, value in item.items()}


def _iso(value: datetime) -> str:
    """Fixed-width UTC timestamp, so string order in the GSI sort key equals time order."""
    return value.astimezone(UTC).isoformat(timespec="microseconds")


class DynamoDBWorkshopRepository:
    """One item per workshop (`sk=META`) and one per registration (`sk=REG#<id>`), same pk."""

    def __init__(self, client: BaseClient, table_name: str) -> None:
        self._client = client
        self._table_name = table_name

    def get(self, workshop_id: str) -> Workshop | None:
        items = list(
            self._query(
                KeyConditionExpression="#pk = :pk",
                ExpressionAttributeNames={"#pk": schema.PARTITION_KEY},
                ExpressionAttributeValues=_serialize({":pk": schema.workshop_pk(workshop_id)}),
                ConsistentRead=True,
            )
        )
        meta = next((i for i in items if i[schema.SORT_KEY] == schema.META_SORT_KEY), None)
        if meta is None:
            return None
        registrations = [
            _registration_from_item(i)
            for i in items
            if i[schema.SORT_KEY].startswith(schema.REGISTRATION_PREFIX)
        ]
        return _workshop_from_item(meta, registrations)

    def save(self, workshop: Workshop) -> None:
        if workshop.version == 0:
            condition = "attribute_not_exists(#version)"
            values: dict[str, Any] = {}
        else:
            condition = "#version = :expected"
            values = {":expected": workshop.version}
        meta_update = {
            "Update": {
                "TableName": self._table_name,
                "Key": _serialize(
                    {
                        schema.PARTITION_KEY: schema.workshop_pk(workshop.id),
                        schema.SORT_KEY: schema.META_SORT_KEY,
                    }
                ),
                "UpdateExpression": (
                    "SET #title = :title, #starts_at = :starts_at, #capacity = :capacity, "
                    "#version = :version, #gsi1pk = :gsi1pk, #gsi1sk = :gsi1sk"
                ),
                "ConditionExpression": condition,
                "ExpressionAttributeNames": {
                    "#title": "title",
                    "#starts_at": "starts_at",
                    "#capacity": "capacity",
                    "#version": "version",
                    "#gsi1pk": schema.GSI1_PARTITION_KEY,
                    "#gsi1sk": schema.GSI1_SORT_KEY,
                },
                "ExpressionAttributeValues": _serialize(
                    {
                        ":title": workshop.title,
                        ":starts_at": _iso(workshop.starts_at),
                        ":capacity": workshop.capacity,
                        ":version": workshop.version + 1,
                        ":gsi1pk": schema.UPCOMING_PARTITION,
                        ":gsi1sk": _iso(workshop.starts_at),
                        **values,
                    }
                ),
            }
        }
        registration_puts = [
            {
                "Put": {
                    "TableName": self._table_name,
                    "Item": _serialize(_registration_to_item(workshop.id, registration)),
                }
            }
            for registration in workshop.pending_registrations
        ]
        if len(registration_puts) > _MAX_TRANSACTION_ITEMS - 1:
            raise ValueError(f"at most {_MAX_TRANSACTION_ITEMS - 1} changed registrations per save")
        try:
            self._client.transact_write_items(TransactItems=[meta_update, *registration_puts])
        except ClientError as error:
            if _is_conflict(error):
                raise ConcurrentUpdateError(workshop.id) from error
            raise
        workshop.version += 1

    def list_upcoming(self, now: datetime) -> list[Workshop]:
        # The GSI is eventually consistent: it only yields candidate ids. Each workshop is then
        # read with a strongly consistent query on its own partition.
        items = self._query(
            IndexName=schema.GSI1_NAME,
            KeyConditionExpression="#gsi1pk = :gsi1pk AND #gsi1sk > :now",
            ExpressionAttributeNames={
                "#gsi1pk": schema.GSI1_PARTITION_KEY,
                "#gsi1sk": schema.GSI1_SORT_KEY,
            },
            ExpressionAttributeValues=_serialize(
                {":gsi1pk": schema.UPCOMING_PARTITION, ":now": _iso(now)}
            ),
        )
        workshop_ids = [i[schema.PARTITION_KEY].removeprefix(schema.WORKSHOP_PREFIX) for i in items]
        workshops = (self.get(workshop_id) for workshop_id in workshop_ids)
        return sorted((w for w in workshops if w is not None), key=lambda w: w.starts_at)

    def _query(self, **kwargs: Any) -> Iterator[dict[str, Any]]:
        paginator = self._client.get_paginator("query")
        for page in paginator.paginate(TableName=self._table_name, **kwargs):
            for item in page["Items"]:
                yield _deserialize(item)


def _is_conflict(error: ClientError) -> bool:
    if error.response["Error"]["Code"] != "TransactionCanceledException":
        return False
    reasons = error.response.get("CancellationReasons", [])
    return any(reason.get("Code") in _CONFLICT_CODES for reason in reasons)


def _registration_to_item(workshop_id: str, registration: Registration) -> dict[str, Any]:
    return {
        schema.PARTITION_KEY: schema.workshop_pk(workshop_id),
        schema.SORT_KEY: schema.registration_sk(registration.id),
        "user_id": registration.user_id,
        "seats": registration.seats,
        "status": registration.status.value,
        "created_at": _iso(registration.created_at),
        "changed_in_version": registration.changed_in_version,
    }


def _registration_from_item(item: dict[str, Any]) -> Registration:
    return Registration(
        id=item[schema.SORT_KEY].removeprefix(schema.REGISTRATION_PREFIX),
        user_id=item["user_id"],
        seats=int(item["seats"]),
        status=item["status"],
        created_at=datetime.fromisoformat(item["created_at"]),
        changed_in_version=int(item["changed_in_version"]),
    )


def _workshop_from_item(item: dict[str, Any], registrations: list[Registration]) -> Workshop:
    return Workshop(
        id=item[schema.PARTITION_KEY].removeprefix(schema.WORKSHOP_PREFIX),
        title=item["title"],
        starts_at=datetime.fromisoformat(item["starts_at"]),
        capacity=int(item["capacity"]),
        version=int(item["version"]),
        registrations=sorted(registrations, key=lambda r: (r.created_at, r.id)),
    )
