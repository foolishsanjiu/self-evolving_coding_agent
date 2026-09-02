from dataclasses import dataclass


@dataclass(frozen=True)
class Profile:
    name: str
    display_name: str | None
