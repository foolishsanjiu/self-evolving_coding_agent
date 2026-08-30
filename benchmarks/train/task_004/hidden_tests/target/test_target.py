import inspect

import users


def test_shared_normalization_helper_exists() -> None:
    source = inspect.getsource(users)
    assert "def _normalize_name" in source
    assert source.count('" ".join(name.strip().split()).title()') == 1
