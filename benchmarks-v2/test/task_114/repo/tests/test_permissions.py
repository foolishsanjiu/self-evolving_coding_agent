from permissions import Grant, GroupDirectory, PermissionResolver


def test_direct_user_grant_is_resource_scoped() -> None:
    resolver = PermissionResolver(
        GroupDirectory(),
        [Grant("user", "alice", "repo:one", "read", "allow")],
    )

    assert resolver.is_allowed("alice", "read", "repo:one") is True
    assert resolver.is_allowed("alice", "read", "repo:two") is False


def test_direct_group_grant_is_supported() -> None:
    directory = GroupDirectory()
    directory.add_user("developers", "alice")
    resolver = PermissionResolver(
        directory,
        [Grant("group", "developers", "repo:one", "write", "allow")],
    )

    assert resolver.is_allowed("alice", "write", "repo:one") is True
