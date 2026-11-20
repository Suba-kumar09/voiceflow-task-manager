"""Domain errors raised by services and mapped to HTTP responses in one place."""


class DomainError(Exception):
    status_code = 400
    code = "domain_error"

    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code


class NotFoundError(DomainError):
    status_code = 404
    code = "not_found"


class PermissionDeniedError(DomainError):
    status_code = 403
    code = "forbidden"


class ConflictError(DomainError):
    """The request is valid but clashes with current state (409)."""

    status_code = 409
    code = "conflict"


class RuleViolationError(DomainError):
    """The request breaks a business rule (422)."""

    status_code = 422
    code = "rule_violation"
