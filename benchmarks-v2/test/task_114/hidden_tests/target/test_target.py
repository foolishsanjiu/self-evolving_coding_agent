from permissions import Grant, GroupDirectory, PermissionResolver


def test_transitive_group_membership_resolves_through_multiple_levels() -> None:
    directory = GroupDirectory()
    directory.add_user("team", "alice")
    directory.add_group("engineering", "team")
    directory.add_group("company", "engineering")
    resolver = PermissionResolver(
        directory,
        [Grant("group", "company", "repo:one", "deploy", "allow")],
    )

    assert resolver.is_allowed("alice", "deploy", "repo:one") is True


def test_explicit_deny_overrides_direct_and_inherited_allows() -> None:
    directory = GroupDirectory()
    directory.add_user("developers", "alice")
    resolver = PermissionResolver(
        directory,
        [
            Grant("user", "alice", "repo:one", "write", "allow"),
            Grant("group", "developers", "repo:one", "write", "allow"),
            Grant("group", "developers", "repo:one", "write", "deny"),
        ],
    )

    assert resolver.is_allowed("alice", "write", "repo:one") is False
