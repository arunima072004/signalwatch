"""
scripts/manage_watchlist.py
============================
Manage the SignalWatch product watchlist.

Usage:
  python scripts/manage_watchlist.py list
  python scripts/manage_watchlist.py add --query "Samsung Galaxy Book"
  python scripts/manage_watchlist.py add --product-id mzM8m2o
  python scripts/manage_watchlist.py remove --product-id mzM8m2o
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("manage_watchlist")

DB_PATH = ROOT / "data" / "signalwatch.db"


def cmd_list(repo) -> None:
    wl = repo.get_watchlist(active_only=False)
    if not wl:
        print("Watchlist is empty.")
        return
    print(f"{'ID':<15} {'Name':<55} {'Active'}")
    print("-" * 80)
    for row in wl:
        status = "YES" if row["active"] else "no"
        print(f"{row['product_id']:<15} {row['product_name'][:53]:<55} {status}")


def cmd_add_by_query(repo, query: str) -> None:
    from src.adapters.channel3_adapter import Channel3Source
    source = Channel3Source()
    print(f"Searching Channel3 for: {query!r}")
    products = source.search_products(query, max_results=10)
    if not products:
        print("No products found.")
        return

    print()
    print(f"{'#':<4} {'ID':<12} {'Title'}")
    print("-" * 80)
    for i, p in enumerate(products, 1):
        title = p.get("title", "?")[:60]
        pid = p.get("id", "?")
        offers = p.get("offers", [])
        n_offers = len(offers)
        print(f"{i:<4} {pid:<12} {title}  [{n_offers} retailer(s)]")

    print()
    choice = input("Enter number(s) to add (comma-separated), or press Enter to cancel: ").strip()
    if not choice:
        print("Cancelled.")
        return

    try:
        indices = [int(x.strip()) - 1 for x in choice.split(",")]
    except ValueError:
        print("Invalid input.")
        return

    for idx in indices:
        if 0 <= idx < len(products):
            p = products[idx]
            pid = p.get("id", "")
            name = p.get("title", pid)
            if pid:
                repo.add_to_watchlist(pid, name)
                print(f"Added: {pid}  {name}")
        else:
            print(f"Invalid selection: {idx+1}")


def cmd_add_by_id(repo, product_id: str) -> None:
    from src.adapters.channel3_adapter import Channel3Source
    import requests, os
    headers = {"x-api-key": os.getenv("CHANNEL3_API_KEY", ""), "Content-Type": "application/json"}
    try:
        resp = requests.get(
            f"https://api.trychannel3.com/v1/products/{product_id}",
            headers=headers, timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            name = data.get("title", product_id)
            repo.add_to_watchlist(product_id, name)
            offers = data.get("offers", [])
            print(f"Added: {product_id}  {name}  [{len(offers)} retailer(s)]")
        else:
            print(f"Could not fetch product {product_id}: HTTP {resp.status_code}")
    except Exception as exc:
        print(f"Error fetching product {product_id}: {exc}")


def cmd_remove(repo, product_id: str) -> None:
    repo.remove_from_watchlist(product_id)
    print(f"Removed (deactivated): {product_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage SignalWatch watchlist")
    parser.add_argument("command", choices=["list", "add", "remove"])
    parser.add_argument("--query", help="Search query for add command")
    parser.add_argument("--product-id", help="Channel3 product ID")
    parser.add_argument("--db", default=str(DB_PATH))
    args = parser.parse_args()

    from src.storage.sqlite_repository import SqliteRepository
    repo = SqliteRepository(args.db)

    if args.command == "list":
        cmd_list(repo)

    elif args.command == "add":
        if args.product_id:
            cmd_add_by_id(repo, args.product_id)
        elif args.query:
            cmd_add_by_query(repo, args.query)
        else:
            print("Provide --query or --product-id")
            sys.exit(1)

    elif args.command == "remove":
        if not args.product_id:
            print("Provide --product-id")
            sys.exit(1)
        cmd_remove(repo, args.product_id)

    repo.close()


if __name__ == "__main__":
    main()
