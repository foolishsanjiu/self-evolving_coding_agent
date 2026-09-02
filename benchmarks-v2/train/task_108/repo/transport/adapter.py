from collections.abc import Mapping

from transport.models import Response


def dispatch_request(
    transport: object,
    *,
    method: str,
    url: str,
    headers: Mapping[str, str],
    timeout: float,
) -> Response:
    return transport.send(method, url, headers, timeout)
