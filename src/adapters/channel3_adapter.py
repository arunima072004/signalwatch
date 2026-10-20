"""
src/adapters/channel3_adapter.py
==================================
Channel3Source: fetches live prices from the Channel3 API.

Field mapping (from confirmed fixture tests/fixtures/channel3_product_sample.json):
    product.id          -> product_id
    product.title       -> product_name
    product.brands[0].name -> brand  (None if brands is empty)
    product.category.title -> category
    offer.domain        -> merchant
    offer.url           -> product_url
    offer.price.price   -> price  (numeric float; skip offer if null/missing)
    offer.price.currency -> currency
    offer.availability  -> availability
    offer.condition     -> condition
    observed_at         -> UTC timestamp of the API fetch (not in the response)

Fields NOT present in the API response (always None):
    is_sale, shipping, manufacturer, asin, ean, upc, manufacturer_number

Budget guard
------------
The adapter tracks API calls and refuses to make more than
max_calls_per_cycle calls in a single fetch_observations() invocation.
Excess products are skipped and logged; they will be fetched in the
next cycle.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.adapters.base import PriceSource
from src.adapters.price_observation import PriceObservation

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.trychannel3.com"
_DEFAULT_MAX_CALLS_PER_CYCLE = 50
_DEFAULT_MAX_CALLS_PER_DAY = 200
_BACKOFF = [1, 2, 4]


class Channel3Source(PriceSource):
    """
    Fetches current prices from Channel3 for every watchlist product.

    Parameters
    ----------
    api_key : str, optional
        Channel3 API key.  Defaults to os.getenv("CHANNEL3_API_KEY").
    max_calls_per_cycle : int
        Hard cap on API calls within one fetch_observations() call.
    max_calls_per_day : int
        Soft daily cap tracked across instances via a class variable.
    """

    _day_call_count: int = 0
    _day_date: Optional[str] = None

    def __init__(
        self,
        api_key: Optional[str] = None,
        max_calls_per_cycle: int = _DEFAULT_MAX_CALLS_PER_CYCLE,
        max_calls_per_day: int = _DEFAULT_MAX_CALLS_PER_DAY,
    ) -> None:
        self._api_key = api_key or os.getenv("CHANNEL3_API_KEY")
        if not self._api_key:
            raise ValueError(
                "CHANNEL3_API_KEY not set.  "
                "Add it to .env or pass api_key= explicitly."
            )
        self._max_cycle = max_calls_per_cycle
        self._max_day = max_calls_per_day
        self._cycle_calls = 0

    @property
    def source_name(self) -> str:
        return "channel3"

    def _headers(self) -> Dict[str, str]:
        return {"x-api-key": self._api_key, "Content-Type": "application/json"}

    @classmethod
    def _reset_day_counter_if_needed(cls) -> None:
        today = datetime.now(timezone.utc).date().isoformat()
        if cls._day_date != today:
            cls._day_date = today
            cls._day_call_count = 0

    def _get(self, url: str) -> Optional[Dict[str, Any]]:
        """GET with retry on 429/5xx. Returns None on unrecoverable failure."""
        import requests
        self._reset_day_counter_if_needed()

        for attempt in range(len(_BACKOFF) + 1):
            if Channel3Source._day_call_count >= self._max_day:
                logger.warning(
                    "Channel3Source: daily call budget exhausted (%d). Skipping %s",
                    self._max_day, url
                )
                return None
            try:
                resp = requests.get(url, headers=self._headers(), timeout=15)
                Channel3Source._day_call_count += 1
                self._cycle_calls += 1

                if resp.status_code == 200:
                    return resp.json()

                if resp.status_code in (429, 503) and attempt < len(_BACKOFF):
                    wait = _BACKOFF[attempt]
                    logger.warning(
                        "Channel3Source: %d on %s — retrying in %ds (attempt %d)",
                        resp.status_code, url, wait, attempt + 1
                    )
                    time.sleep(wait)
                    continue

                logger.error(
                    "Channel3Source: %d for %s: %s",
                    resp.status_code, url, resp.text[:200]
                )
                return None

            except Exception as exc:
                logger.error("Channel3Source: request error for %s: %s", url, exc)
                return None
        return None

    def fetch_observations(
        self,
        watchlist: List[str],
        since: Optional[str] = None,
    ) -> List[PriceObservation]:
        """
        Fetch one PriceObservation per active offer for each watchlist product.

        An offer that disappears produces NO observation.
        An offer with a missing/invalid price is skipped and logged.
        observed_at is the UTC timestamp of this fetch.
        """
        self._cycle_calls = 0
        now_utc = datetime.now(timezone.utc).isoformat()
        observations: List[PriceObservation] = []

        for product_id in watchlist:
            if self._cycle_calls >= self._max_cycle:
                logger.warning(
                    "Channel3Source: cycle call budget (%d) reached. "
                    "%d products not fetched this cycle.",
                    self._max_cycle, len(watchlist) - watchlist.index(product_id)
                )
                break

            url = f"{_BASE_URL}/v1/products/{product_id}"
            data = self._get(url)
            if data is None:
                continue

            product_name = data.get("title") or product_id
            brands = data.get("brands") or []
            brand = brands[0].get("name") if brands else None
            cat_obj = data.get("category") or {}
            category = cat_obj.get("title")

            offers = data.get("offers") or []
            if not offers:
                logger.debug("Channel3Source: product %s has no offers", product_id)
                continue

            for offer in offers:
                try:
                    price_obj = offer.get("price") or {}
                    price_val = price_obj.get("price")
                    if price_val is None:
                        logger.debug(
                            "Channel3Source: skipping offer for %s/%s — null price",
                            product_id, offer.get("domain")
                        )
                        continue
                    price = float(price_val)
                except (TypeError, ValueError) as exc:
                    logger.warning(
                        "Channel3Source: invalid price for %s/%s: %s",
                        product_id, offer.get("domain"), exc
                    )
                    continue

                currency = (price_obj.get("currency") or "USD").strip()
                domain = offer.get("domain") or "unknown"
                availability = offer.get("availability")
                condition = offer.get("condition")
                product_url = offer.get("url")

                observations.append(PriceObservation(
                    product_id=product_id,
                    product_name=product_name,
                    merchant=domain,
                    observed_at=now_utc,
                    price=price,
                    currency=currency,
                    availability=availability if availability else None,
                    condition=condition if condition else None,
                    is_sale=None,       # not present in Channel3 API
                    shipping=None,      # not present in Channel3 API
                    product_url=product_url,
                    brand=brand,
                    category=category,
                    manufacturer=None,  # not present in Channel3 API
                    asin=None,
                    ean=None,
                    upc=None,
                    manufacturer_number=None,
                    source="channel3",
                ))

        logger.info(
            "Channel3Source: fetched %d observations for %d products "
            "(%d API calls this cycle)",
            len(observations), len(watchlist), self._cycle_calls
        )
        return observations

    def search_products(self, query: str, max_results: int = 20) -> List[Dict[str, Any]]:
        """
        Search for products by query string.
        Returns list of raw product dicts (for watchlist management).
        """
        import requests
        self._reset_day_counter_if_needed()

        if Channel3Source._day_call_count >= self._max_day:
            logger.warning("Channel3Source: daily budget exhausted, cannot search")
            return []

        try:
            resp = requests.post(
                f"{_BASE_URL}/v1/search",
                headers=self._headers(),
                json={"query": query},
                timeout=15,
            )
            Channel3Source._day_call_count += 1
            if resp.status_code == 200:
                return resp.json().get("products", [])[:max_results]
            logger.error("Channel3Source.search: %d: %s", resp.status_code, resp.text[:200])
        except Exception as exc:
            logger.error("Channel3Source.search error: %s", exc)
        return []
