from dataclasses import dataclass


@dataclass(frozen=True)
class Item:
    item_id: str
    value: str


@dataclass(frozen=True)
class Page:
    items: tuple[Item, ...]
    next_cursor: str | None
