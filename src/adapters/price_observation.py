"""
src/adapters/price_observation.py
===================================
PriceObservation: the canonical internal model for a single price data point.

Every data source (CSV, Channel3, future sources) is converted into
PriceObservation before entering the pipeline.  This decouples Phase 1
(BOCPD detection) from the details of any particular data source.

Nullability rule
----------------
Optional fields MUST be None when the source did not provide them.
  is_sale = None   means "source did not say" — NOT "not on sale"
  availability = None  means "unknown" — NOT "in stock"
Never coerce missing booleans to False or missing strings to "".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional


@dataclass
class PriceObservation:
    """
    Canonical representation of one price observation from any source.

    Required fields
    ---------------
    product_id   : str   Source-specific identifier (Channel3 id, CSV product_id, etc.)
    product_name : str   Human-readable product name
    merchant     : str   Retailer domain or name (e.g. "staples.com")
    observed_at  : str   ISO-8601 UTC timestamp of when the price was observed
    price        : float Current price (numeric, in currency units)
    currency     : str   ISO 4217 currency code (e.g. "USD")

    Optional fields (None = not provided by source)
    ----------------
    availability     : Optional[str]   e.g. "InStock", "OutOfStock", "PreOrder"
    condition        : Optional[str]   e.g. "new", "used", "refurbished"
    is_sale          : Optional[bool]  True/False if explicitly stated; None if unknown
    shipping         : Optional[str]   Shipping information string
    product_url      : Optional[str]   Direct URL to product page at merchant
    brand            : Optional[str]   Brand name
    category         : Optional[str]   Product category
    manufacturer     : Optional[str]   Manufacturer name
    asin             : Optional[str]   Amazon ASIN
    ean              : Optional[str]   EAN barcode
    upc              : Optional[str]   UPC barcode
    manufacturer_number : Optional[str] Manufacturer model/part number
    source           : Optional[str]  Which adapter produced this (e.g. "channel3", "csv")
    """
    product_id: str
    product_name: str
    merchant: str
    observed_at: str
    price: float
    currency: str

    # Optional — None means "source did not provide this"
    availability: Optional[str] = None
    condition: Optional[str] = None
    is_sale: Optional[bool] = None
    shipping: Optional[str] = None
    product_url: Optional[str] = None
    brand: Optional[str] = None
    category: Optional[str] = None
    manufacturer: Optional[str] = None
    asin: Optional[str] = None
    ean: Optional[str] = None
    upc: Optional[str] = None
    manufacturer_number: Optional[str] = None
    source: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "product_id": self.product_id,
            "product_name": self.product_name,
            "merchant": self.merchant,
            "observed_at": self.observed_at,
            "price": self.price,
            "currency": self.currency,
            "availability": self.availability,
            "condition": self.condition,
            "is_sale": self.is_sale,
            "shipping": self.shipping,
            "product_url": self.product_url,
            "brand": self.brand,
            "category": self.category,
            "manufacturer": self.manufacturer,
            "asin": self.asin,
            "ean": self.ean,
            "upc": self.upc,
            "manufacturer_number": self.manufacturer_number,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PriceObservation":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
