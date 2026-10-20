"""
scripts/fetch_channel3_sample.py
=================================
Stage 0 discovery: fetch real Channel3 API responses and save as fixtures.

Usage:
    python scripts/fetch_channel3_sample.py

Requires CHANNEL3_API_KEY in .env (or environment).
Saves:
    tests/fixtures/channel3_search_sample.json
    tests/fixtures/channel3_product_sample.json

NEVER prints the API key. Prints only status codes, counts, and headers.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

import requests

BASE_URL = "https://api.trychannel3.com"
FIXTURES = ROOT / "tests" / "fixtures"
FIXTURES.mkdir(parents=True, exist_ok=True)

SEARCH_QUERY = "Samsung Galaxy Book laptop"
MAX_RETRIES = 2


def get_headers() -> dict:
    key = os.getenv("CHANNEL3_API_KEY")
    if not key:
        print("ERROR: CHANNEL3_API_KEY not set in .env or environment.")
        sys.exit(1)
    return {"x-api-key": key, "Content-Type": "application/json"}


def print_rate_headers(resp: requests.Response) -> None:
    """Print any rate-limit or credit headers — never print the key."""
    interesting = [h for h in resp.headers if any(
        kw in h.lower() for kw in ["rate", "limit", "credit", "quota", "retry", "remaining", "reset"]
    )]
    if interesting:
        print("  Response headers of interest:")
        for h in interesting:
            print(f"    {h}: {resp.headers[h]}")


def call_with_retry(method: str, url: str, **kwargs) -> requests.Response:
    backoff = [1, 2, 4]
    for attempt in range(MAX_RETRIES + 1):
        resp = requests.request(method, url, timeout=15, **kwargs)
        if resp.status_code == 429 and attempt < MAX_RETRIES:
            wait = backoff[min(attempt, len(backoff) - 1)]
            print(f"  429 rate limit — waiting {wait}s before retry {attempt + 1}/{MAX_RETRIES}")
            time.sleep(wait)
            continue
        return resp
    return resp  # return last response after exhausting retries


def main() -> None:
    headers = get_headers()

    # -----------------------------------------------------------------------
    # 1. POST /v1/search
    # -----------------------------------------------------------------------
    print(f"\nPOST {BASE_URL}/v1/search  query={SEARCH_QUERY!r}")
    resp = call_with_retry(
        "POST",
        f"{BASE_URL}/v1/search",
        headers=headers,
        json={"query": SEARCH_QUERY},
    )
    print(f"  Status: {resp.status_code}")
    print_rate_headers(resp)

    if resp.status_code in (401, 403):
        print("  Auth error — check CHANNEL3_API_KEY in .env")
        sys.exit(1)
    if resp.status_code != 200:
        print(f"  Unexpected status {resp.status_code}: {resp.text[:200]}")
        sys.exit(1)

    search_data = resp.json()
    products = search_data.get("products", [])
    paging_token = search_data.get("paging_token")
    print(f"  Products returned: {len(products)}")
    print(f"  paging_token present: {paging_token is not None}")

    out_search = FIXTURES / "channel3_search_sample.json"
    out_search.write_text(json.dumps(search_data, indent=2), encoding="utf-8")
    print(f"  Saved: {out_search}")

    if not products:
        print("  No products returned — cannot fetch product detail.")
        sys.exit(0)

    # -----------------------------------------------------------------------
    # 2. GET /v1/products/{id}  — first product in search results
    # -----------------------------------------------------------------------
    first_id = products[0].get("id") or products[0].get("product_id")
    if not first_id:
        print(f"  Could not find 'id' field in first product. Keys: {list(products[0].keys())}")
        sys.exit(1)

    print(f"\nGET {BASE_URL}/v1/products/{first_id}")
    resp2 = call_with_retry(
        "GET",
        f"{BASE_URL}/v1/products/{first_id}",
        headers=headers,
    )
    print(f"  Status: {resp2.status_code}")
    print_rate_headers(resp2)

    if resp2.status_code != 200:
        print(f"  Unexpected status {resp2.status_code}: {resp2.text[:200]}")
        sys.exit(1)

    product_data = resp2.json()
    offers = product_data.get("offers", [])
    print(f"  Offers (retailers): {len(offers)}")

    out_product = FIXTURES / "channel3_product_sample.json"
    out_product.write_text(json.dumps(product_data, indent=2), encoding="utf-8")
    print(f"  Saved: {out_product}")

    # -----------------------------------------------------------------------
    # 3. Report offer field names
    # -----------------------------------------------------------------------
    if offers:
        print(f"\nFirst offer field names: {list(offers[0].keys())}")
        print(f"First offer sample:\n{json.dumps(offers[0], indent=4)[:600]}")

    print("\nDone. Fixtures saved to tests/fixtures/")


if __name__ == "__main__":
    main()
