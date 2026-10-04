"""
src/models/search.py
"""
from __future__ import annotations
import hashlib
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional


@dataclass
class SearchQuery:
    query_id: str
    event_id: str
    hypothesis_type: str
    query_text: str
    purpose: str
    priority: int
    generated_by: str
    product_name: str
    brand: str
    merchant: str
    category: str
    date_window: str
    asin: Optional[str] = None
    upc: Optional[str] = None
    manufacturer_number: Optional[str] = None
    execution_status: str = "pending"
    executed_at: Optional[str] = None
    provider_used: Optional[str] = None
    result_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SearchQuery":
        return cls(**data)


@dataclass
class SearchResult:
    result_id: str
    query_id: str
    event_id: str
    title: str
    url: str
    snippet: str
    source_domain: str
    retrieved_at: str
    provider: str
    full_content: Optional[str] = None
    publication_date: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SearchResult":
        return cls(**data)


def make_result_id(query_id: str, url: str) -> str:
    raw = f"{query_id}|{url}"
    return "res_" + hashlib.sha256(raw.encode()).hexdigest()[:12]