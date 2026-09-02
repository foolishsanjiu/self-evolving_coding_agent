from dataclasses import dataclass


@dataclass(frozen=True)
class ProductView:
    product_id: str
    title: str
    total: float
