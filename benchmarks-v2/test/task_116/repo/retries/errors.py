class RequestError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        retry_after: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after
