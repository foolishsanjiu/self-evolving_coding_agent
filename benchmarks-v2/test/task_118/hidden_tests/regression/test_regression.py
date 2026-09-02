import asyncio

import pytest
from hooks import HookResult, dispatch


def test_invalid_return_type_is_rejected() -> None:
    def legacy(event: str, context: dict[str, str], /) -> str:
        return event

    with pytest.raises(TypeError, match="hook must return HookResult"):
        asyncio.run(dispatch([legacy], event="push", context={}))


def test_hook_order_is_preserved_for_mixed_styles() -> None:
    async def current(*, event: str, context: dict[str, str]) -> HookResult:
        return HookResult(f"current:{event}")

    def legacy(event: str, context: dict[str, str], /) -> HookResult:
        return HookResult(f"legacy:{event}")

    assert asyncio.run(dispatch([current, legacy], event="push", context={})) == [
        HookResult("current:push"),
        HookResult("legacy:push"),
    ]
