from transport import Response


def test_response_preserves_raw_body() -> None:
    response = Response(status_code=204, body=b"\x00payload")

    assert response.status_code == 204
    assert response.body == b"\x00payload"


def test_response_values_are_immutable() -> None:
    response = Response(status_code=200, body=b"ok")

    assert hash(response) == hash(Response(status_code=200, body=b"ok"))
