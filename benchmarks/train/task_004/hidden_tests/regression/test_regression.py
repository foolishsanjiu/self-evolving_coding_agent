from users import admin_label, user_label


def test_label_behavior_is_preserved() -> None:
    assert user_label("  ada   lovelace ") == "User: Ada Lovelace"
    assert admin_label("grace hopper") == "Admin: Grace Hopper"
