"""Request bodies. They mirror the existing documents in neerus.inventory."""
from typing import Annotated, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

Text = Annotated[str, Field(min_length=1, max_length=120)]


class _ItemBase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @field_validator("stock", "suppliers", check_fields=False)
    @classmethod
    def _no_negative(cls, v):
        if isinstance(v, dict) and any(q < 0 for q in v.values()):
            raise ValueError("stock quantities cannot be negative")
        return v


class ItemCreate(_ItemBase):
    sku: Text
    name: Text
    type: Text
    department: Text
    category: Text
    subCategory: Optional[str] = Field(None, max_length=120)
    style: Optional[str] = Field(None, max_length=120)
    fabric: Optional[str] = Field(None, max_length=120)
    occasion: Optional[str] = Field(None, max_length=120)
    colour: Optional[str] = Field(None, max_length=120)
    price: int = Field(ge=0, le=10_000_000)
    cost: int = Field(0, ge=0, le=10_000_000)
    suppliers: list[int] = []
    stock: dict[str, int] = Field(description="Quantity per store, e.g. {'Gachibowli': 5}")


class ItemUpdate(_ItemBase):
    """Every field is optional; only the fields you send are changed."""
    sku: Optional[Text] = None
    name: Optional[Text] = None
    type: Optional[Text] = None
    department: Optional[Text] = None
    category: Optional[Text] = None
    subCategory: Optional[str] = Field(None, max_length=120)
    style: Optional[str] = Field(None, max_length=120)
    fabric: Optional[str] = Field(None, max_length=120)
    occasion: Optional[str] = Field(None, max_length=120)
    colour: Optional[str] = Field(None, max_length=120)
    price: Optional[int] = Field(None, ge=0, le=10_000_000)
    cost: Optional[int] = Field(None, ge=0, le=10_000_000)
    suppliers: Optional[list[int]] = None
    stock: Optional[dict[str, int]] = Field(
        None, description="Only the stores listed here are changed; other stores keep their quantity."
    )
