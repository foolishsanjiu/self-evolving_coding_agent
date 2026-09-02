from datetime import datetime

from tokens.models import Token


def is_expired(token: Token, now: datetime) -> bool:
    return token.expires_at < now.replace(tzinfo=None)
