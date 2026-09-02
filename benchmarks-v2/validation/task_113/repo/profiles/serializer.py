from typing import Any

from profiles.models import Profile


def load_profile(payload: dict[str, Any]) -> Profile:
    version = payload.get("schema_version")
    if version not in {1, 2}:
        raise ValueError(f"unsupported schema version: {version}")
    display_name = payload.get("display_name") or payload.get("displayName")
    return Profile(name=str(payload["name"]), display_name=display_name)


def dump_profile(profile: Profile, schema_version: int) -> dict[str, Any]:
    if schema_version not in {1, 2}:
        raise ValueError(f"unsupported schema version: {schema_version}")
    return {
        "schema_version": schema_version,
        "name": profile.name,
        "displayName": profile.display_name,
        "display_name": profile.display_name,
    }
