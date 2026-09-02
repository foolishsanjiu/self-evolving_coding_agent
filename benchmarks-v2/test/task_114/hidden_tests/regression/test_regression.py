from permissions import Grant, GroupDirectory, PermissionResolver


def test_cycle_terminates_without_losing_an_acyclic_parent_grant() -> None:
    directory = GroupDirectory()
    directory.add_user("team", "alice")
    directory.add_group("loop-a", "team")
    directory.add_group("loop-b", "loop-a")
    directory.add_group("loop-a", "loop-b")
    directory.add_group("root", "loop-b")
    resolver = PermissionResolver(
        directory,
        [Grant("group", "root", "repo:one", "read", "allow")],
    )

    assert resolver.is_allowed("alice", "read", "repo:one") is True


def test_repeated_checks_do_not_share_traversal_state() -> None:
    directory = GroupDirectory()
    directory.add_user("team", "alice")
    directory.add_user("team", "bob")
    directory.add_group("root", "team")
    resolver = PermissionResolver(
        directory,
        [Grant("group", "root", "repo:one", "read", "allow")],
    )

    assert resolver.is_allowed("alice", "read", "repo:one") is True
    assert resolver.is_allowed("bob", "read", "repo:one") is True
    assert resolver.is_allowed("alice", "read", "repo:two") is False
