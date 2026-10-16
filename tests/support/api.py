"""A thin client for the deployed API. It always goes through API Gateway and the authorizer."""

from datetime import datetime
from typing import Any

import requests

TIMEOUT = 15


class ApiClient:
    def __init__(self, base_url: str, id_token: str | None) -> None:
        self._base_url = base_url
        self._session = requests.Session()
        if id_token is not None:
            self._session.headers["Authorization"] = id_token

    def request(self, method: str, path: str, body: Any = None) -> requests.Response:
        return self._session.request(method, f"{self._base_url}{path}", json=body, timeout=TIMEOUT)

    def create_workshop(self, title: str, starts_at: datetime, capacity: int) -> requests.Response:
        body = {"title": title, "starts_at": starts_at.isoformat(), "capacity": capacity}
        return self.request("POST", "/workshops", body)

    def list_workshops(self) -> requests.Response:
        return self.request("GET", "/workshops")

    def get_workshop(self, workshop_id: str) -> requests.Response:
        return self.request("GET", f"/workshops/{workshop_id}")

    def register(self, workshop_id: str, seats: int) -> requests.Response:
        return self.request("POST", f"/workshops/{workshop_id}/registrations", {"seats": seats})

    def cancel(self, workshop_id: str, registration_id: str) -> requests.Response:
        return self.request("DELETE", f"/workshops/{workshop_id}/registrations/{registration_id}")


def expect(response: requests.Response, status: int) -> Any:
    """Asserts the status. A 500 usually means AccessDenied in the Lambda: the request id
    leads straight to the log line."""
    assert response.status_code == status, (
        f"{response.request.method} {response.request.path_url}: expected {status}, got "
        f"{response.status_code} {response.text} "
        f"(x-amzn-RequestId: {response.headers.get('x-amzn-RequestId')})"
    )
    return response.json() if response.content else None
