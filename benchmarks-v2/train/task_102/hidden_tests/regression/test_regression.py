import pytest
from paging.client import InMemoryPageClient
from paging.models import Item, Page
from paging.service import collect_items


def test_cursor_cycle_is_rejected_before_refetching() -> None:
    client = InMemoryPageClient(
        {
            None: Page(items=(Item("a", "A"),), next_cursor="loop"),
            "loop": Page(items=(Item("b", "B"),), next_cursor="loop"),
        }
    )

    with pytest.raises(RuntimeError, match="cursor cycle"):
        collect_items(client)

    assert client.requested_cursors == [None, "loop"]


def test_max_pages_guard_remains_active() -> None:
    client = InMemoryPageClient(
        {
            None: Page(items=(), next_cursor="two"),
            "two": Page(items=(), next_cursor="three"),
            "three": Page(items=(), next_cursor=None),
        }
    )

    with pytest.raises(RuntimeError, match="max_pages"):
        collect_items(client, max_pages=2)
