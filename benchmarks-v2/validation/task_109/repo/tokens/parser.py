from datetime import datetime

from tokens.models import Token


def parse_token(payload: dict[str, str]) -> Token:
    try:
        expires_at = datetime.fromisoformat(payload["expires_at"].replace("Z", "+00:00"))
        token_id = payload["token_id"]
    except (KeyError, ValueError) as exc:
        raise ValueError("invalid token payload") from exc
    return Token(token_id=token_id, expires_at=expires_at.replace(tzinfo=None))
