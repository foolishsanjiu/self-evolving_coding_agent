from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Token:
    token_id: str
    expires_at: datetime
