from permissions.directory import GroupDirectory
from permissions.models import Grant


class PermissionResolver:
    def __init__(self, directory: GroupDirectory, grants: list[Grant]) -> None:
        self.directory = directory
        self.grants = grants

    def is_allowed(self, user: str, permission: str, resource: str) -> bool:
        principals = {("user", user)}
        principals.update(
            ("group", group)
            for group, members in self.directory.memberships.items()
            if f"user:{user}" in members
        )
        effects = {
            grant.effect
            for grant in self.grants
            if (grant.principal_kind, grant.principal_id) in principals
            and grant.permission == permission
            and grant.resource == resource
        }
        return "allow" in effects
