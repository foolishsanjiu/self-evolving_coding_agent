from collections.abc import Mapping

from paging.models import Page


class InMemoryPageClient:
    def __init__(self, pages: Mapping[str | None, Page]) -> None:
        self.pages = dict(pages)
        self.requested_cursors: list[str | None] = []

    def fetch(self, cursor: str | None) -> Page:
        self.requested_cursors.append(cursor)
        return self.pages[cursor]
