from __future__ import annotations


class DockError(Exception):
    def __init__(
        self,
        status: int,
        *,
        code: str | None = None,
        message: str | None = None,
        request_id: str | None = None,
        retry_after: float | None = None,
        detail: str | None = None,
    ) -> None:
        self.status = status
        self.code = code
        self.message = message
        self.request_id = request_id
        self.retry_after = retry_after
        self.detail = detail or message
        parts = [f"dock status {status}"]
        if code:
            parts.append(code)
        if self.detail:
            parts.append(self.detail)
        if request_id:
            parts.append(f"request_id={request_id}")
        super().__init__(" ".join(parts))


class DockAuthError(DockError):
    pass


class DockNotFoundError(DockError):
    pass


class DockRateLimitError(DockError):
    pass


class DockConflictError(DockError):
    pass


class DockUnavailableError(DockError):
    pass
