"""Small, explicit error boundary shared by API and domain code."""


class AppError(Exception):
    def __init__(
        self, code: str, message: str, status_code: int, details: list | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details if details is not None else []
