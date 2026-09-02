from dataclasses import dataclass


@dataclass(frozen=True)
class AppSettings:
    timeout: int
    debug: bool
    region: str
