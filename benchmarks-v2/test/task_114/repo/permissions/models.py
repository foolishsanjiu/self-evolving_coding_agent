from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Grant:
    principal_kind: Literal["user", "group"]
    principal_id: str
    resource: str
    permission: str
    effect: Literal["allow", "deny"]
