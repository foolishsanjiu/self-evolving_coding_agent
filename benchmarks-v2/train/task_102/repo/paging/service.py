from paging.client import InMemoryPageClient
from paging.models import Item


def collect_items(client: InMemoryPageClient, max_pages: int = 100) -> list[Item]:
    cursor: str | None = None
    collected: list[Item] = []
    seen: set[str | None] = set()
    for _ in range(max_pages):
        if cursor in seen:
            raise RuntimeError("pagination cursor cycle detected")
        seen.add(cursor)
        page = client.fetch(cursor)
        collected.extend(page.items)
        if page.next_cursor is None:
            return collected
        cursor = page.items[-1].item_id if page.items else None
    raise RuntimeError("pagination exceeded max_pages")
