from paging.client import InMemoryPageClient
from paging.models import Item, Page
from paging.service import collect_items


def test_follows_opaque_cursors_instead_of_item_ids() -> None:
    client = InMemoryPageClient(
        {
            None: Page(items=(Item("item-a", "A"),), next_cursor="token-2"),
            "token-2": Page(items=(Item("item-b", "B"),), next_cursor="token-3"),
            "token-3": Page(items=(Item("item-c", "C"),), next_cursor=None),
        }
    )

    assert [item.value for item in collect_items(client)] == ["A", "B", "C"]
    assert client.requested_cursors == [None, "token-2", "token-3"]


def test_empty_intermediate_page_does_not_end_collection() -> None:
    client = InMemoryPageClient(
        {
            None: Page(items=(Item("item-a", "A"),), next_cursor="empty"),
            "empty": Page(items=(), next_cursor="last"),
            "last": Page(items=(Item("item-b", "B"),), next_cursor=None),
        }
    )

    assert [item.value for item in collect_items(client)] == ["A", "B"]
