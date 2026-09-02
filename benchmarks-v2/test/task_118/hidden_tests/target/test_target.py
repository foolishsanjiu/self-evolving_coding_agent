import asyncio

import pytest
from hooks import HookResult, dispatch


def test_unsupported_signature_is_rejected_before_invocation() -> None:
    calls = 0

    def unsupported(*args: object, **kwargs: object) -> HookResult:
        nonlocal calls
        calls += 1
        return HookResult("called")

    with pytest.raises(TypeError, match="unsupported hook signature"):
        asyncio.run(dispatch([unsupported], event="push", context={}))

    assert calls == 0


def test_current_hook_type_error_is_not_retried_or_replaced() -> None:
    failure = TypeError("inside hook")
    calls = 0

    def current(*, event: str, context: dict[str, str]) -> HookResult:
        nonlocal calls
        calls += 1
        raise failure

    with pytest.raises(TypeError) as caught:
        asyncio.run(dispatch([current], event="push", context={}))

    assert caught.value is failure
    assert calls == 1


def test_legacy_async_result_is_normalized() -> None:
    async def legacy(event: str, context: dict[str, str], /) -> HookResult:
        return HookResult(f"{event}:{context['id']}")

    assert asyncio.run(
        dispatch([legacy], event="push", context={"id": "9"})
    ) == [HookResult("push:9")]


def test_legacy_positional_or_keyword_signature_is_recognized() -> None:
    def legacy(event: str, context: dict[str, str]) -> HookResult:
        return HookResult(f"{event}:{context['id']}")

    assert asyncio.run(
        dispatch([legacy], event="push", context={"id": "11"})
    ) == [HookResult("push:11")]
