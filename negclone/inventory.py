"""Flickr photo inventory — fetch, catalog, and group by film stock."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from negclone.flickr import (
    RateLimiter,
    flickr_call_with_retry,
    get_authenticated_client,
    get_authenticated_user_nsid,
)
from negclone.models import FlickrPhotoRecord, Inventory
from negclone.utils import atomic_write_json, detect_stock_from_metadata, load_tag_map

console = Console()

PHOTOS_PER_PAGE: int = 100


def _parse_date(date_str: str | None) -> datetime | None:
    """Parse a Flickr date string to datetime.

    Args:
        date_str: Date string from Flickr API.

    Returns:
        Parsed datetime or None.
    """
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _get_original_url(
    flickr: Any,
    photo_id: str,
    rate_limiter: RateLimiter,
) -> tuple[str, int | None, int | None]:
    """Fetch the original image URL for a photo.

    Args:
        flickr: Authenticated FlickrAPI client.
        photo_id: Flickr photo ID.
        rate_limiter: RateLimiter instance.

    Returns:
        Tuple of (url, width, height).
    """
    sizes_resp = flickr_call_with_retry(
        flickr.photos.getSizes,
        rate_limiter,
        photo_id=photo_id,
    )

    sizes = sizes_resp.get("sizes", {}).get("size", [])

    # Prefer Original, fall back to Large
    for label in ("Original", "Large"):
        for size in sizes:
            if size.get("label") == label:
                return (
                    size["source"],
                    int(size.get("width", 0)) or None,
                    int(size.get("height", 0)) or None,
                )

    # Last resort: use the largest available
    if sizes:
        largest = sizes[-1]
        return (
            largest["source"],
            int(largest.get("width", 0)) or None,
            int(largest.get("height", 0)) or None,
        )

    return ("", None, None)


def build_inventory(
    user: str | None = None,
    tags: str | None = None,
    min_date: str | None = None,
    tag_map_path: Path | None = None,
    output: Path = Path("inventory.json"),
    verbose: bool = False,
) -> Inventory:
    """Fetch photos from Flickr and group by detected film stock.

    Args:
        user: Flickr username or NSID. If None, uses authenticated user.
        tags: Comma-separated tags to filter by.
        min_date: Minimum date taken (YYYY-MM-DD).
        tag_map_path: Path to JSON tag map file.
        output: Output path for inventory JSON.
        verbose: Enable verbose output.

    Returns:
        The built Inventory.
    """
    flickr = get_authenticated_client()
    rate_limiter = RateLimiter()

    tag_map: dict[str, str] | None = None
    if tag_map_path:
        tag_map = load_tag_map(tag_map_path)
        console.print(f"[dim]Loaded {len(tag_map)} tag mappings[/dim]")

    # Resolve user ID
    resolved_user_id: str
    if user:
        # If it looks like an NSID (contains @), use directly; otherwise resolve
        if "@" in user:
            resolved_user_id = user
        else:
            try:
                lookup_resp = flickr_call_with_retry(
                    flickr.people.findByUsername,
                    rate_limiter,
                    username=user,
                )
                resolved_user_id = lookup_resp["user"]["nsid"]
                console.print(f"[dim]Resolved user '{user}' → {resolved_user_id}[/dim]")
            except Exception:
                # Fall back to using the string as-is (might be an NSID)
                resolved_user_id = user
    else:
        nsid = get_authenticated_user_nsid()
        resolved_user_id = nsid if nsid else "me"

    # Build search params
    search_kwargs: dict[str, Any] = {
        "user_id": resolved_user_id,
        "per_page": PHOTOS_PER_PAGE,
        "extras": "date_taken,tags,description",
    }

    if tags:
        search_kwargs["tags"] = tags

    if min_date:
        search_kwargs["min_taken_date"] = min_date

    stocks: dict[str, list[FlickrPhotoRecord]] = {}
    total_scanned = 0
    total_matched = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Scanning Flickr photos...", total=None)

        page = 1
        pages = 1  # Will be updated from first response

        while page <= pages:
            search_kwargs["page"] = page

            resp = flickr_call_with_retry(
                flickr.photos.search,
                rate_limiter,
                **search_kwargs,
            )

            photos_data = resp.get("photos", {})
            pages = int(photos_data.get("pages", 1))
            photo_list = photos_data.get("photo", [])

            for photo in photo_list:
                total_scanned += 1
                progress.update(
                    task,
                    description=(
                        f"Scanning photos... ({total_scanned} scanned, {total_matched} matched)"
                    ),
                )

                photo_id = str(photo["id"])

                # Title can be a string or {"_content": "..."}
                title_raw = photo.get("title", "")
                title = (
                    title_raw.get("_content", "") if isinstance(title_raw, dict) else str(title_raw)
                )

                desc_data = photo.get("description", {})
                description = (
                    desc_data.get("_content", "") if isinstance(desc_data, dict) else str(desc_data)
                )

                # Tags come as space-separated string from extras
                tags_str = photo.get("tags", "")
                tag_list = tags_str.split() if isinstance(tags_str, str) else []

                # Detect stock
                stock = detect_stock_from_metadata(title, description, tag_list, tag_map)
                if not stock:
                    if verbose:
                        console.print(f"[dim]  Skip: {title} (no stock detected)[/dim]")
                    continue

                total_matched += 1

                # Fetch original URL
                url, width, height = _get_original_url(flickr, photo_id, rate_limiter)
                if not url:
                    console.print(f"[yellow]  Warning: No URL for {photo_id}[/yellow]")
                    continue

                record = FlickrPhotoRecord(
                    photo_id=photo_id,
                    title=title,
                    description=description,
                    tags=tag_list,
                    stock=stock,
                    date_taken=_parse_date(photo.get("datetaken")),
                    url_original=url,
                    width=width,
                    height=height,
                )

                stocks.setdefault(stock, []).append(record)

            page += 1

    username = user or "me"
    inventory = Inventory(stocks=stocks, user=username)

    # Write output
    atomic_write_json(output, inventory)
    console.print(f"\n[green]Inventory written to {output}[/green]")

    # Print summary table
    _print_summary(stocks)

    return inventory


def _print_summary(stocks: dict[str, list[FlickrPhotoRecord]]) -> None:
    """Print a summary table of detected stocks.

    Args:
        stocks: Dictionary of stock name to photo records.
    """
    table = Table(title="Film Stock Inventory")
    table.add_column("Stock", style="bold cyan")
    table.add_column("Photos", justify="right")
    table.add_column("Date Range")

    for stock_name in sorted(stocks.keys()):
        records = stocks[stock_name]
        dates = [r.date_taken for r in records if r.date_taken]
        date_range = f"{min(dates):%Y-%m-%d} — {max(dates):%Y-%m-%d}" if dates else "—"
        table.add_row(stock_name, str(len(records)), date_range)

    console.print(table)


def load_inventory(path: Path) -> Inventory:
    """Load an inventory from a JSON file.

    Args:
        path: Path to inventory JSON.

    Returns:
        Loaded Inventory model.

    Raises:
        FileNotFoundError: If the file doesn't exist.
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return Inventory.model_validate(data)
