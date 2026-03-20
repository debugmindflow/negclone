"""Local directory scanning — build an inventory from a folder of film scans."""

from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import typer
from PIL import Image
from PIL.ExifTags import Base as ExifBase
from rich.console import Console
from rich.table import Table

from negclone.models import FlickrPhotoRecord, Inventory
from negclone.utils import atomic_write_json, detect_stock, load_tag_map

console = Console()

IMAGE_EXTENSIONS: set[str] = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".dng"}


def _parse_exif_date(exif_data: dict) -> datetime | None:
    """Parse DateTimeOriginal from EXIF data.

    Args:
        exif_data: Dictionary of EXIF tag ID to value.

    Returns:
        Parsed datetime or None.
    """
    date_str = exif_data.get(ExifBase.DateTimeOriginal)
    if not date_str:
        return None
    if not isinstance(date_str, str):
        return None
    try:
        return datetime.strptime(date_str, "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None


def _read_exif_text_fields(image_path: Path) -> list[str]:
    """Read text-bearing EXIF fields from an image.

    Reads ImageDescription (0x010E) and UserComment (0x9286).

    Args:
        image_path: Path to the image file.

    Returns:
        List of non-empty text values found.
    """
    texts: list[str] = []
    try:
        with Image.open(image_path) as img:
            exif_data = img.getexif()
            if not exif_data:
                return texts

            for tag_id in (ExifBase.ImageDescription, ExifBase.UserComment):
                value = exif_data.get(tag_id)
                if value and isinstance(value, (str, bytes)):
                    text = (
                        value.decode("utf-8", errors="ignore")
                        if isinstance(value, bytes)
                        else value
                    )
                    if text.strip():
                        texts.append(text.strip())
    except (OSError, SyntaxError):
        pass
    return texts


def _get_image_dimensions(image_path: Path) -> tuple[int | None, int | None]:
    """Get image width and height.

    Args:
        image_path: Path to the image file.

    Returns:
        Tuple of (width, height), or (None, None) on failure.
    """
    try:
        with Image.open(image_path) as img:
            return img.size
    except (OSError, SyntaxError):
        return (None, None)


def _get_exif_data(image_path: Path) -> dict:
    """Read EXIF data from an image file.

    Args:
        image_path: Path to the image file.

    Returns:
        Dictionary of EXIF tag ID to value, empty dict on failure.
    """
    try:
        with Image.open(image_path) as img:
            return dict(img.getexif()) if img.getexif() else {}
    except (OSError, SyntaxError):
        return {}


def _detect_stock_from_path(
    image_path: Path,
    tag_map: dict[str, str] | None,
) -> str | None:
    """Detect film stock from an image using the priority chain.

    Priority:
        1. Ancestor folder name
        2. Filename stem
        3. EXIF text fields (ImageDescription, UserComment)
        4. Tag map applied across all text fields

    Args:
        image_path: Path to the image file.
        tag_map: Optional user-defined tag-to-stock mappings.

    Returns:
        Normalized stock name if found, None otherwise.
    """
    # 1. Folder name: check each ancestor directory
    for parent in image_path.parents:
        result = detect_stock(parent.name, tag_map=None)
        if result:
            return result

    # 2. Filename stem
    result = detect_stock(image_path.stem, tag_map=None)
    if result:
        return result

    # 3. EXIF text fields
    exif_texts = _read_exif_text_fields(image_path)
    for text in exif_texts:
        result = detect_stock(text, tag_map=None)
        if result:
            return result

    # 4. Tag map across all text fields (folder names, filename, EXIF)
    if tag_map:
        all_texts = [p.name for p in image_path.parents]
        all_texts.append(image_path.stem)
        all_texts.extend(exif_texts)
        for text in all_texts:
            result = detect_stock(text, tag_map=tag_map)
            if result:
                return result

    return None


def build_local_inventory(
    scan_dir: Path,
    tag_map_path: Path | None,
    output: Path,
    verbose: bool,
) -> Inventory:
    """Build an inventory from a local directory of film scans.

    Walks scan_dir recursively for image files, detects film stock from
    folder names, filenames, and EXIF metadata, then groups results by stock.

    Args:
        scan_dir: Root directory containing film scans.
        tag_map_path: Optional path to JSON tag-to-stock mapping file.
        output: Output path for the inventory JSON.
        verbose: Enable verbose output.

    Returns:
        The built Inventory.

    Raises:
        FileNotFoundError: If scan_dir does not exist.
    """
    if not scan_dir.is_dir():
        raise FileNotFoundError(f"Scan directory not found: {scan_dir}")

    tag_map: dict[str, str] | None = None
    if tag_map_path:
        tag_map = load_tag_map(tag_map_path)
        typer.echo(f"Loaded {len(tag_map)} tag mappings from {tag_map_path}")

    # Collect image files
    image_files: list[Path] = sorted(
        p for p in scan_dir.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    )

    typer.echo(f"Found {len(image_files)} image files in {scan_dir}")

    stocks: dict[str, list[FlickrPhotoRecord]] = {}
    total_matched = 0
    total_skipped = 0

    for image_path in image_files:
        stock = _detect_stock_from_path(image_path, tag_map)
        if not stock:
            total_skipped += 1
            if verbose:
                typer.echo(f"  Skip: {image_path.name} (no stock detected)")
            continue

        total_matched += 1

        # Read dimensions
        width, height = _get_image_dimensions(image_path)

        # Read EXIF date
        exif_data = _get_exif_data(image_path)
        date_taken = _parse_exif_date(exif_data)

        # Build file URI
        abs_path = image_path.resolve()
        url_original = f"file://{quote(str(abs_path))}"

        record = FlickrPhotoRecord(
            photo_id=image_path.stem,
            title=image_path.name,
            stock=stock,
            date_taken=date_taken,
            url_original=url_original,
            width=width,
            height=height,
        )

        stocks.setdefault(stock, []).append(record)

    inventory = Inventory(stocks=stocks, user="local")

    # Write output
    atomic_write_json(output, inventory)
    typer.echo(f"Inventory written to {output}")
    typer.echo(f"Matched {total_matched} images, skipped {total_skipped}")

    # Print summary table
    _print_summary(stocks)

    return inventory


def _print_summary(stocks: dict[str, list[FlickrPhotoRecord]]) -> None:
    """Print a summary table of detected stocks.

    Args:
        stocks: Dictionary of stock name to photo records.
    """
    table = Table(title="Film Stock Inventory (Local)")
    table.add_column("Stock", style="bold cyan")
    table.add_column("Photos", justify="right")
    table.add_column("Date Range")

    for stock_name in sorted(stocks.keys()):
        records = stocks[stock_name]
        dates = [r.date_taken for r in records if r.date_taken]
        date_range = f"{min(dates):%Y-%m-%d} — {max(dates):%Y-%m-%d}" if dates else "—"
        table.add_row(stock_name, str(len(records)), date_range)

    console.print(table)


def populate_local_cache(inventory: Inventory, cache_dir: Path) -> None:
    """Create symlinks in the cache directory so the fingerprint command works.

    For each photo in the inventory, creates a symlink at
    cache/<stock>/<photo_id>.<ext> pointing to the original file.

    Args:
        inventory: An Inventory built from local scans.
        cache_dir: Root cache directory (e.g. Path("cache")).
    """
    total_links = 0

    for stock_name, records in inventory.stocks.items():
        stock_dir = cache_dir / stock_name
        stock_dir.mkdir(parents=True, exist_ok=True)

        for record in records:
            # Extract the original path from the file URI
            url = record.url_original
            if not url.startswith("file://"):
                typer.echo(f"  Skip: {record.photo_id} (not a local file URI)")
                continue

            from urllib.parse import unquote

            original_path = Path(unquote(url[len("file://") :])).resolve()

            if not original_path.exists():
                typer.echo(f"  Warning: Source file missing: {original_path}")
                continue

            if not original_path.is_file():
                typer.echo(f"  Warning: Not a regular file: {original_path}")
                continue

            link_name = f"{record.photo_id}{original_path.suffix}"
            link_path = stock_dir / link_name

            if link_path.exists() or link_path.is_symlink():
                link_path.unlink()

            link_path.symlink_to(original_path)
            total_links += 1

    typer.echo(f"Created {total_links} symlinks in {cache_dir}")
