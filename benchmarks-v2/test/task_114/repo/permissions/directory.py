from dataclasses import dataclass, field


@dataclass
class GroupDirectory:
    memberships: dict[str, set[str]] = field(default_factory=dict)

    def add_user(self, group: str, user: str) -> None:
        self.memberships.setdefault(group, set()).add(f"user:{user}")

    def add_group(self, parent: str, child: str) -> None:
        self.memberships.setdefault(parent, set()).add(f"group:{child}")
