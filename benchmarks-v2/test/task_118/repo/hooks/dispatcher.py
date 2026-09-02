import inspect
from collections.abc import Callable
from typing import Any

from hooks.models import HookResult


async def dispatch(
    hooks: list[Callable[..., Any]],
    *,
    event: str,
    context: dict[str, str],
) -> list[HookResult]:
    results: list[HookResult] = []
    for hook in hooks:
        try:
            result = hook(event=event, context=context)
        except TypeError:
            result = hook(event, context)
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, HookResult):
            raise TypeError("hook must return HookResult")
        results.append(result)
        if not result.continue_processing:
            break
    return results
