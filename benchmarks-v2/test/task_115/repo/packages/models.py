from dataclasses import dataclass


@dataclass(frozen=True)
class Package:
    name: str
    dependencies: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "dependencies", tuple(dict.fromkeys(self.dependencies)))
