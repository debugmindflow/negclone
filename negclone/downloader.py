"""Download original images from Flickr to a local cache."""

import random
from pathlib import Path

import httpx
from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TransferSpeedColumn,
)

from negclone.models import FlickrPhotoRecord

console = Console()

DOWNLOAD_TIMEOUT: float = 60.0
MAX_DOWNLOAD_RETRIES: int = 3


def download_photos(
    records: list[FlickrPhotoRecord],
    stock: str,
    sample_size: int = 20,
    cache_dir: Path = Path("cache"),
    verbose: bool = False,
) -> list[Path]:
    """Download original images for a stock to the local cache.

    Args:
        records: List of photo records for this stock.
        stock: Film stock name.
        sample_size: Number of images to sample.
        cache_dir: Root cache directory.
        verbose: Enable verbose output.

    Returns:
        List of paths to downloaded/cached images.
    """
    stock_dir = cache_dir / stock
    stock_dir.mkdir(parents=True, exist_ok=True)

    sampled = random.sample(records, sample_size) if len(records) > sample_size else list(records)

    downloaded: list[Path] = []

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(
            f"Downloading {stock} ({len(sampled)} images)...",
            total=len(sampled),
        )

        for record in sampled:
            # Determine filename
            ext = _get_extension(record.url_original)
            filename = f"{record.photo_id}{ext}"
            dest = stock_dir / filename

            # Skip if already cached
            if dest.exists() and dest.stat().st_size > 0:
                if verbose:
                    console.print(f"[dim]  Cached: {filename}[/dim]")
                downloaded.append(dest)
                progress.advance(task)
                continue

            # Download
            try:
                _download_file(record.url_original, dest)
                downloaded.append(dest)
                if verbose:
                    console.print(f"[green]  Downloaded: {filename}[/green]")
            except httpx.HTTPError as e:
                console.print(
                    f"[yellow]  Warning: Failed to download {record.photo_id}: {e}[/yellow]"
                )

            progress.advance(task)

    console.print(f"[green]Downloaded {len(downloaded)}/{len(sampled)} images for {stock}[/green]")
    return downloaded


def _download_file(url: str, dest: Path) -> None:
    """Download a file with retries.

    Args:
        url: URL to download.
        dest: Destination path.

    Raises:
        httpx.HTTPError: If download fails after retries.
    """
    last_error: httpx.HTTPError | None = None

    for attempt in range(MAX_DOWNLOAD_RETRIES):
        try:
            with httpx.stream("GET", url, timeout=DOWNLOAD_TIMEOUT, follow_redirects=True) as resp:
                resp.raise_for_status()
                tmp_dest = dest.with_suffix(dest.suffix + ".tmp")
                with open(tmp_dest, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=8192):
                        f.write(chunk)
                tmp_dest.rename(dest)
                return
        except httpx.HTTPError as e:
            last_error = e
            if attempt < MAX_DOWNLOAD_RETRIES - 1:
                continue

    if last_error:
        raise last_error


def _get_extension(url: str) -> str:
    """Extract file extension from URL.

    Args:
        url: Image URL.

    Returns:
        File extension including dot (e.g., '.jpg').
    """
    path = url.split("?")[0]
    if "." in path.split("/")[-1]:
        ext = "." + path.split("/")[-1].rsplit(".", 1)[-1].lower()
        if ext in (".jpg", ".jpeg", ".png", ".tif", ".tiff"):
            return ext
    return ".jpg"
