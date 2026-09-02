from collections.abc import Mapping
from typing import Protocol

from transport.models import Response


class Transport(Protocol):
    def send(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        timeout: float,
    ) -> Response: ...
