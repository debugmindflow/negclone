"""Typer CLI entry point for NegClone."""

import zipfile
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer

from negclone import __version__

app = typer.Typer(
    name="negclone",
    help="Extract film grain/color fingerprints from scanned negatives and generate presets.",
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        typer.echo(f"negclone {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool | None,
        typer.Option("--version", "-v", callback=_version_callback, is_eager=True),
    ] = None,
) -> None:
    """NegClone — Real film presets from real negatives."""


@app.command()
def auth(
    verifier: Annotated[
        str | None,
        typer.Option("--verifier", help="OAuth verifier code (skips interactive prompt)"),
    ] = None,
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable debug output")] = False,
) -> None:
    """Authenticate with Flickr via OAuth 1.0a."""
    from negclone.flickr import FlickrAuthError, authenticate

    try:
        username = authenticate(verifier_code=verifier)
        typer.echo(f"Authenticated as: {username}")
    except FlickrAuthError as e:
        typer.echo(f"Authentication failed: {e}", err=True)
        raise typer.Exit(1) from e


@app.command()
def inventory(
    local: Annotated[
        Path | None,
        typer.Option("--local", "-l", help="Local scan directory (skip Flickr)"),
    ] = None,
    user: Annotated[
        str | None,
        typer.Option("--user", help="Flickr username or NSID"),
    ] = None,
    tags: Annotated[
        str | None,
        typer.Option("--tags", help="Comma-separated tags to filter"),
    ] = None,
    min_date: Annotated[
        str | None,
        typer.Option("--min-date", help="Minimum date taken (YYYY-MM-DD)"),
    ] = None,
    tag_map: Annotated[
        Path | None,
        typer.Option("--tag-map", help="JSON file mapping tags to stock names"),
    ] = None,
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Output inventory JSON path"),
    ] = Path("inventory.json"),
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable debug output")] = False,
) -> None:
    """Fetch and catalog photos from Flickr or a local directory, grouped by film stock."""
    if local and user:
        typer.echo("Cannot use --local and --user together.", err=True)
        raise typer.Exit(1)

    try:
        if local:
            from negclone.local_inventory import build_local_inventory

            build_local_inventory(
                scan_dir=local,
                tag_map_path=tag_map,
                output=output,
                verbose=verbose,
            )
        else:
            from negclone.inventory import build_inventory

            build_inventory(
                user=user,
                tags=tags,
                min_date=min_date,
                tag_map_path=tag_map,
                output=output,
                verbose=verbose,
            )
    except Exception as e:
        typer.echo(f"Inventory failed: {e}", err=True)
        raise typer.Exit(1) from e


@app.command()
def download(
    inventory_json: Annotated[Path, typer.Argument(help="Path to inventory.json")],
    stock: Annotated[
        str | None,
        typer.Option("--stock", "-s", help="Specific stock to download"),
    ] = None,
    sample_size: Annotated[
        int,
        typer.Option("--sample-size", "-n", help="Number of images to sample"),
    ] = 20,
    cache_dir: Annotated[
        Path,
        typer.Option("--cache-dir", help="Cache directory for downloads"),
    ] = Path("cache"),
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable debug output")] = False,
) -> None:
    """Download original images from Flickr (or symlink local files) to a cache."""
    from negclone.downloader import download_photos
    from negclone.inventory import load_inventory

    try:
        inv = load_inventory(inventory_json)
    except Exception as e:
        typer.echo(f"Failed to load inventory: {e}", err=True)
        raise typer.Exit(1) from e

    stocks_to_process = [stock] if stock else list(inv.stocks.keys())

    for stock_name in stocks_to_process:
        if stock_name not in inv.stocks:
            typer.echo(f"Stock '{stock_name}' not found in inventory.", err=True)
            raise typer.Exit(1)

        records = inv.stocks[stock_name]

        # Check if local source — symlink instead of download
        if records and records[0].source == "local":
            from negclone.local_inventory import populate_local_cache

            typer.echo(f"Linking {stock_name} ({len(records)} local files)...")
            populate_local_cache(inv, cache_dir)
            typer.echo(f"Done: {stock_name}")
        else:
            typer.echo(
                f"Downloading {stock_name} ({len(records)} available, sampling {sample_size})..."
            )
            download_photos(
                records=records,
                stock=stock_name,
                sample_size=sample_size,
                cache_dir=cache_dir,
                verbose=verbose,
            )
            typer.echo(f"Done: {stock_name}")


@app.command()
def fingerprint(
    inventory_json: Annotated[Path, typer.Argument(help="Path to inventory.json")],
    stock: Annotated[
        str | None,
        typer.Option("--stock", "-s", help="Specific stock to fingerprint"),
    ] = None,
    sample_size: Annotated[
        int,
        typer.Option("--sample-size", "-n", help="Number of images to analyze"),
    ] = 20,
    cache_dir: Annotated[
        Path,
        typer.Option("--cache-dir", help="Cache directory with downloaded images"),
    ] = Path("cache"),
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", "-o", help="Directory for fingerprint JSON files"),
    ] = Path("."),
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable debug output")] = False,
) -> None:
    """Analyze cached images and compute fingerprints per film stock."""
    from negclone.fingerprint import (
        fingerprint_stock,
        print_fingerprint_summary,
        save_fingerprint,
    )
    from negclone.inventory import load_inventory

    try:
        inv = load_inventory(inventory_json)
    except Exception as e:
        typer.echo(f"Failed to load inventory: {e}", err=True)
        raise typer.Exit(1) from e

    stocks_to_process = [stock] if stock else list(inv.stocks.keys())

    for stock_name in stocks_to_process:
        if stock_name not in inv.stocks:
            typer.echo(f"Stock '{stock_name}' not found in inventory.", err=True)
            raise typer.Exit(1)

        stock_cache = cache_dir / stock_name
        if not stock_cache.exists():
            typer.echo(
                f"Warning: No cached images for {stock_name}. Run 'negclone download' first."
            )
            continue

        valid_exts = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
        image_paths = sorted(p for p in stock_cache.glob("*.*") if p.suffix.lower() in valid_exts)

        typer.echo(f"Fingerprinting {stock_name} ({len(image_paths)} images)...")

        fp = fingerprint_stock(
            image_paths=image_paths,
            stock=stock_name,
            sample_size=sample_size,
            verbose=verbose,
        )

        if fp:
            path = save_fingerprint(fp, output_dir)
            typer.echo(f"Fingerprint saved to {path}")
            print_fingerprint_summary(fp)


@app.command()
def generate(
    fingerprint_json: Annotated[Path, typer.Argument(help="Path to fingerprint JSON")],
    output_format: Annotated[
        str,
        typer.Option("--format", "-f", help="Output format: darktable, lightroom, or both"),
    ] = "both",
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", "-o", help="Output directory for presets"),
    ] = Path("output"),
    force: Annotated[bool, typer.Option("--force", help="Overwrite existing files")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Print what would be created")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable debug output")] = False,
) -> None:
    """Generate Darktable and/or Lightroom presets from a fingerprint."""
    from negclone.fingerprint import load_fingerprint
    from negclone.presets.darktable import generate_dtstyle
    from negclone.presets.lightroom import generate_xmp

    try:
        fp = load_fingerprint(fingerprint_json)
    except Exception as e:
        typer.echo(f"Failed to load fingerprint: {e}", err=True)
        raise typer.Exit(1) from e

    valid_formats = ("darktable", "lightroom", "both")
    if output_format not in valid_formats:
        typer.echo(
            f"Invalid format: {output_format}. Use darktable, lightroom, or both.",
            err=True,
        )
        raise typer.Exit(1)

    if not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)
        if not force and any(output_dir.iterdir()):
            typer.echo(
                f"Output directory {output_dir} is not empty. Use --force to overwrite.",
                err=True,
            )
            raise typer.Exit(1)

    if output_format in ("darktable", "both"):
        if dry_run:
            typer.echo(f"Would create: {output_dir / f'{fp.stock}.dtstyle'}")
        else:
            path = generate_dtstyle(fp, output_dir)
            typer.echo(f"Generated Darktable style: {path}")

    if output_format in ("lightroom", "both"):
        if dry_run:
            typer.echo(f"Would create: {output_dir / f'{fp.stock}.xmp'}")
        else:
            path = generate_xmp(fp, output_dir)
            typer.echo(f"Generated Lightroom preset: {path}")


@app.command()
def compare(
    fingerprint_a: Annotated[Path, typer.Argument(help="First fingerprint JSON")],
    fingerprint_b: Annotated[Path, typer.Argument(help="Second fingerprint JSON")],
) -> None:
    """Compare two film stock fingerprints side-by-side."""
    from negclone.analysis import print_comparison
    from negclone.fingerprint import load_fingerprint

    try:
        fp_a = load_fingerprint(fingerprint_a)
        fp_b = load_fingerprint(fingerprint_b)
    except Exception as e:
        typer.echo(f"Failed to load fingerprint: {e}", err=True)
        raise typer.Exit(1) from e

    print_comparison(fp_a, fp_b)


@app.command()
def report(
    fingerprint_files: Annotated[
        list[Path],
        typer.Argument(help="Fingerprint JSON files to include"),
    ],
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Output HTML file"),
    ] = Path("report.html"),
) -> None:
    """Generate an HTML report comparing all fingerprints."""
    from negclone.analysis import generate_report
    from negclone.fingerprint import load_fingerprint

    fingerprints = []
    for fp_path in fingerprint_files:
        try:
            fingerprints.append(load_fingerprint(fp_path))
        except Exception as e:
            typer.echo(f"Warning: Failed to load {fp_path}: {e}", err=True)

    if not fingerprints:
        typer.echo("No valid fingerprints to report on.", err=True)
        raise typer.Exit(1)

    generate_report(fingerprints, output)
    typer.echo(f"Report generated: {output}")


@app.command()
def pack(
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", "-o", help="Directory containing generated presets"),
    ] = Path("output"),
    name: Annotated[
        str,
        typer.Option("--name", "-n", help="Pack name"),
    ] = "Desert Paul Film Presets",
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Print what would be created")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable debug output")] = False,
) -> None:
    """Bundle generated presets into a distributable zip archive."""
    if not output_dir.exists():
        typer.echo(f"Output directory {output_dir} does not exist.", err=True)
        raise typer.Exit(1)

    dtstyle_files = sorted(output_dir.glob("*.dtstyle"))
    xmp_files = sorted(output_dir.glob("*.xmp"))
    all_files = dtstyle_files + xmp_files

    if not all_files:
        typer.echo(f"No preset files found in {output_dir}.", err=True)
        raise typer.Exit(1)

    zip_name = name.lower().replace(" ", "-") + ".zip"
    zip_path = output_dir / zip_name

    if dry_run:
        typer.echo(f"Would create: {zip_path}")
        typer.echo(f"Contents ({len(all_files)} presets):")
        for f in all_files:
            typer.echo(f"  {f.name}")
        return

    readme_lines = [
        f"{name}",
        "=" * len(name),
        "",
        "Authentic film presets derived from real scanned negatives.",
        "",
        "Stocks included:",
    ]

    stock_names = set()
    for f in all_files:
        stock_names.add(f.stem)
    for sn in sorted(stock_names):
        readme_lines.append(f"  - {sn}")

    readme_lines.extend(
        [
            "",
            f"Generated on {datetime.now():%Y-%m-%d} by NegClone",
            "",
            "--- Darktable Import ---",
            "1. Open Darktable",
            "2. Go to the lighttable view",
            "3. In the styles module, click 'import'",
            "4. Select the .dtstyle file(s)",
            "5. Apply to your photos from the styles module",
            "",
            "--- Lightroom / ACR Import ---",
            "1. Copy .xmp files to:",
            "   macOS: ~/Library/Application Support/Adobe/CameraRaw/Settings/",
            "   Windows: C:\\Users\\<user>\\AppData\\Roaming\\Adobe\\CameraRaw\\Settings\\",
            "2. Restart Lightroom",
            "3. Find presets in the Develop module preset panel",
            "",
            "---",
            "Built with NegClone. Real negatives, real presets.",
        ]
    )

    readme_content = "\n".join(readme_lines)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("README.txt", readme_content)
        for f in all_files:
            zf.write(f, f.name)

    typer.echo(f"Pack created: {zip_path} ({len(all_files)} presets)")

    typer.echo("\nGumroad Upload Checklist:")
    typer.echo(f"  [ ] Upload {zip_path}")
    typer.echo(f"  [ ] Set product name: {name}")
    typer.echo("  [ ] Add cover image (sample edit with preset applied)")
    typer.echo("  [ ] Set price")
    typer.echo(f"  [ ] Description: {len(stock_names)} authentic film stock presets")
    typer.echo("  [ ] Tags: film, presets, darktable, lightroom, analog, photography")
    typer.echo("  [ ] Publish!")
