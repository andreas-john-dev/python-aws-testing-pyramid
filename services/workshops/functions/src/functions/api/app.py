from http import HTTPStatus
from typing import Any

from aws_lambda_powertools import Logger
from aws_lambda_powertools.event_handler import APIGatewayRestResolver, Response, content_types
from pydantic import AwareDatetime, BaseModel, Field, ValidationError
from workshop_service_domain.errors import (
    CancellationTooLate,
    CapacityExceeded,
    ConcurrentUpdateError,
    DomainError,
    RegistrationNotFound,
    RegistrationNotOwned,
    SeatLimitExceeded,
    WorkshopAlreadyStarted,
    WorkshopNotFound,
)
from workshop_service_domain.models import Registration, Workshop
from workshop_service_domain.ports import Clock, WorkshopRepository
from workshop_service_domain.use_cases import (
    DEFAULT_RETRY,
    CancelRegistration,
    CreateWorkshop,
    GetWorkshop,
    ListUpcomingWorkshops,
    RegisterForWorkshop,
    RetryPolicy,
)

logger = Logger(service="workshops")

# Rule violations are 422, a conflict that survived all retries is 409.
ERROR_STATUS: dict[type[DomainError], HTTPStatus] = {
    WorkshopNotFound: HTTPStatus.NOT_FOUND,
    RegistrationNotFound: HTTPStatus.NOT_FOUND,
    RegistrationNotOwned: HTTPStatus.FORBIDDEN,
    CapacityExceeded: HTTPStatus.UNPROCESSABLE_ENTITY,
    SeatLimitExceeded: HTTPStatus.UNPROCESSABLE_ENTITY,
    CancellationTooLate: HTTPStatus.UNPROCESSABLE_ENTITY,
    WorkshopAlreadyStarted: HTTPStatus.UNPROCESSABLE_ENTITY,
    ConcurrentUpdateError: HTTPStatus.CONFLICT,
}


class Unauthorized(Exception):
    pass


class BadRequest(Exception):
    pass


class CreateWorkshopRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    starts_at: AwareDatetime
    capacity: int = Field(ge=1, le=1000)


class RegisterRequest(BaseModel):
    seats: int = Field(ge=1)


def workshop_view(workshop: Workshop) -> dict[str, Any]:
    return {
        "id": workshop.id,
        "title": workshop.title,
        "starts_at": workshop.starts_at.isoformat(),
        "capacity": workshop.capacity,
        "free_seats": workshop.free_seats,
    }


def registration_view(workshop_id: str, registration: Registration) -> dict[str, Any]:
    return {
        "id": registration.id,
        "workshop_id": workshop_id,
        "user_id": registration.user_id,
        "seats": registration.seats,
        "status": registration.status.value,
        "created_at": registration.created_at.isoformat(),
    }


def _error(status: HTTPStatus, error: str, message: str) -> Response:
    return Response(
        status_code=status,
        content_type=content_types.APPLICATION_JSON,
        body={"error": error, "message": message},
    )


def build_app(
    repository: WorkshopRepository, clock: Clock, retry: RetryPolicy = DEFAULT_RETRY
) -> APIGatewayRestResolver:
    """Wires use cases to routes. The handler module builds the production instance."""
    app = APIGatewayRestResolver()

    create_workshop = CreateWorkshop(repository, clock)
    get_workshop = GetWorkshop(repository)
    list_upcoming = ListUpcomingWorkshops(repository, clock)
    register = RegisterForWorkshop(repository, clock, retry)
    cancel = CancelRegistration(repository, clock, retry)

    def current_user() -> str:
        claims = app.current_event.request_context.authorizer.claims or {}
        user_id = claims.get("sub")
        if not user_id:
            raise Unauthorized("missing sub claim")
        return user_id

    def parse[M: BaseModel](model: type[M]) -> M:
        try:
            return model.model_validate_json(app.current_event.body or "")
        except ValidationError as error:
            raise BadRequest(error.json(include_url=False)) from error

    @app.post("/workshops")
    def post_workshop() -> tuple[dict[str, Any], int]:
        current_user()
        request = parse(CreateWorkshopRequest)
        workshop = create_workshop(request.title, request.starts_at, request.capacity)
        return workshop_view(workshop), HTTPStatus.CREATED

    @app.get("/workshops")
    def get_workshops() -> dict[str, Any]:
        current_user()
        return {"workshops": [workshop_view(w) for w in list_upcoming()]}

    @app.get("/workshops/<workshop_id>")
    def get_workshop_by_id(workshop_id: str) -> dict[str, Any]:
        current_user()
        return workshop_view(get_workshop(workshop_id))

    @app.post("/workshops/<workshop_id>/registrations")
    def post_registration(workshop_id: str) -> tuple[dict[str, Any], int]:
        user_id = current_user()
        request = parse(RegisterRequest)
        registration = register(workshop_id, user_id, request.seats)
        return registration_view(workshop_id, registration), HTTPStatus.CREATED

    @app.delete("/workshops/<workshop_id>/registrations/<registration_id>")
    def delete_registration(workshop_id: str, registration_id: str) -> Response:
        cancel(workshop_id, registration_id, current_user())
        return Response(status_code=HTTPStatus.NO_CONTENT, body=None)

    @app.exception_handler(Unauthorized)
    def handle_unauthorized(error: Unauthorized) -> Response:
        return _error(HTTPStatus.UNAUTHORIZED, "Unauthorized", str(error))

    @app.exception_handler(BadRequest)
    def handle_bad_request(error: BadRequest) -> Response:
        return _error(HTTPStatus.BAD_REQUEST, "BadRequest", str(error))

    @app.exception_handler(Exception)
    def handle_error(error: Exception) -> Response:
        status = ERROR_STATUS.get(type(error))
        if status is None:
            logger.exception("unhandled error")
            return _error(HTTPStatus.INTERNAL_SERVER_ERROR, "InternalServerError", "internal error")
        return _error(status, type(error).__name__, str(error))

    return app
