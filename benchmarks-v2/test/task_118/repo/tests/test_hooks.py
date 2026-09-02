import asyncio

from hooks import HookResult, dispatch


def test_current_async_keyword_only_hook() -> None:
    async def current(*, event: str, context: dict[str, str]) -> HookResult:
        return HookResult(f"{event}:{context['id']}")

    results = asyncio.run(dispatch([current], event="push", context={"id": "7"}))

    assert results == [HookResult("push:7")]


def test_legacy_sync_positional_hook_and_short_circuit() -> None:
    calls: list[str] = []

    def legacy(event: str, context: dict[str, str], /) -> HookResult:
        calls.append(event)
        return HookResult(context["id"], continue_processing=False)

    def unreachable(event: str, context: dict[str, str], /) -> HookResult:
        calls.append("unreachable")
        return HookResult(event)

    results = asyncio.run(
        dispatch([legacy, unreachable], event="push", context={"id": "7"})
    )

    assert results == [HookResult("7", continue_processing=False)]
    assert calls == ["push"]
