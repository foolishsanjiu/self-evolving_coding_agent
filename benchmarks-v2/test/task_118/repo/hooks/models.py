from dataclasses import dataclass


@dataclass(frozen=True)
class HookResult:
    value: str
    continue_processing: bool = True
