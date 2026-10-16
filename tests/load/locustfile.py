"""Invariants under real parallelism, not only latency. Run with `make load`, never against a
shared stage.

Setup: one workshop with 20 seats and one Cognito test user per Locust user (created one after
the other because of Cognito quotas). Every Locust user books 1 seat. It stops on 201 or 422 and
tries again on 409. At the end the items are read directly from DynamoDB with the same helper as
the E2E tests, and a violated invariant sets the exit code:

- exactly 20 active seats: no overbooking and no unused seat despite demand
- no 5xx responses
"""

import random
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

import gevent
from locust import HttpUser, constant, events, task
from locust.env import Environment
from locust.exception import StopUser

from tests.support.api import ApiClient, expect
from tests.support.aws import aws_session, stage_config
from tests.support.cognito import CognitoTestUsers, run_id
from tests.support.dynamodb import DynamoDbStateReader, DynamoDbTable

CAPACITY = 20
STOP_ON = {201, 422}
RETRY_ON = 409

run: dict[str, Any] = {}
statuses: Counter[int] = Counter()


@events.test_start.add_listener
def set_up(environment: Environment, **_: Any) -> None:
    session = aws_session()
    stage = stage_config(session)
    rid = run_id()
    users = CognitoTestUsers(session.client("cognito-idp"), stage)
    table = DynamoDbTable(client=session.client("dynamodb"), name=stage.table_name)
    run.update(users=users, table=table, finished=0)

    owner = users.create(f"load-{rid}-owner")
    starts_at = datetime.now(UTC) + timedelta(days=7)
    workshop = expect(
        ApiClient(stage.api_url, owner.id_token).create_workshop(
            f"load {rid}", starts_at, CAPACITY
        ),
        201,
    )
    table.track(workshop["id"])
    run["workshop_id"] = workshop["id"]

    count = environment.parsed_options.num_users if environment.parsed_options else 100
    print(f"creating {count} Cognito test users ...")
    run["tokens"] = [users.create(f"load-{rid}-{n:03}").id_token for n in range(count)]
    run["users_total"] = count
    WorkshopUser.host = stage.api_url


class WorkshopUser(HttpUser):
    wait_time = constant(0)

    def on_start(self) -> None:
        self.client.headers["Authorization"] = run["tokens"].pop()

    @task
    def book_one_seat(self) -> None:
        path = f"/workshops/{run['workshop_id']}/registrations"
        with self.client.post(
            path, json={"seats": 1}, name="POST /registrations", catch_response=True
        ) as response:
            statuses[response.status_code] += 1
            if response.status_code in STOP_ON or response.status_code == RETRY_ON:
                response.success()
            else:
                response.failure(f"{response.status_code} {response.text}")
        if response.status_code == RETRY_ON:
            time.sleep(random.uniform(0, 0.2))
            return
        self._finish()

    def _finish(self) -> None:
        run["finished"] += 1
        if run["finished"] == run["users_total"]:
            # Everybody got an answer: end the run instead of waiting for --run-time.
            gevent.spawn_later(0.1, self.environment.runner.quit)
        raise StopUser()


@events.quitting.add_listener
def check_invariants_and_tear_down(environment: Environment, **_: Any) -> None:
    if "workshop_id" not in run:
        return
    try:
        state = DynamoDbStateReader(run["table"]).read(run["workshop_id"])
        active = state.active_seats if state else 0
        server_errors = sum(n for code, n in statuses.items() if code >= 500)
        stats = environment.stats.get("POST /registrations", "POST")
        print(f"responses per status: {dict(sorted(statuses.items()))}")
        print(
            f"p50 {stats.get_response_time_percentile(0.5)} ms, "
            f"p95 {stats.get_response_time_percentile(0.95)} ms"
        )
        print(f"active seats in DynamoDB: {active} of {CAPACITY}")
        violations = []
        if active != CAPACITY:
            violations.append(f"expected exactly {CAPACITY} active seats, found {active}")
        if server_errors:
            violations.append(f"{server_errors} responses with 5xx")
        if violations:
            print("INVARIANTS VIOLATED: " + "; ".join(violations))
            environment.process_exit_code = 1
        else:
            print("invariants hold")
    finally:
        run["users"].delete_all()
        run["table"].cleanup()
