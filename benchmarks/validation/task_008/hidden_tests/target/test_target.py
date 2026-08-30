import pytest
from config_reader import require_name


@pytest.mark.parametrize("data", [{}, {"name": "  "}, {"name": 42}])
def test_invalid_name_is_normalized_to_value_error(data: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="name is required"):
        require_name(data)
