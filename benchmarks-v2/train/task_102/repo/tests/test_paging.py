from paging.client import InMemoryPageClient
from paging.models import Item, Page
from paging.service import collect_items


def test_collects_a_single_page() -> None:
    client = InMemoryPageClient(
        {None: Page(items=(Item("a", "A"), Item("b", "B")), next_cursor=None)}
    )

    assert [item.value for item in collect_items(client)] == ["A", "B"]
    assert client.requested_cursors == [None]


def test_empty_terminal_page_is_valid() -> None:
    client = InMemoryPageClient({None: Page(items=(), next_cursor=None)})

    assert collect_items(client) == []
