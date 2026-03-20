"""Shared utility functions for NegClone."""

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from negclone.models import KNOWN_STOCKS, STOCK_ALIASES


def detect_stock(text: str, tag_map: dict[str, str] | None = None) -> str | None:
    """Detect film stock from text (title, description, or tags).

    Args:
        text: Text to search for stock names.
        tag_map: Optional user-defined tag-to-stock mappings.

    Returns:
        Normalized stock name if found, None otherwise.
    """
    lower = text.lower().strip()

    # Check user-defined tag map first
    if tag_map:
        for tag, stock in tag_map.items():
            if tag.lower() in lower:
                return stock.lower()

    # Check exact stock names
    for stock in KNOWN_STOCKS:
        if stock in lower:
            return stock

    # Check aliases
    for alias, stock in STOCK_ALIASES.items():
        if alias in lower:
            return stock

    return None


def detect_stock_from_metadata(
    title: str,
    description: str,
    tags: list[str],
    tag_map: dict[str, str] | None = None,
) -> str | None:
    """Detect film stock from photo metadata fields.

    Args:
        title: Photo title.
        description: Photo description.
        tags: List of photo tags.
        tag_map: Optional user-defined tag-to-stock mappings.

    Returns:
        Normalized stock name if found, None otherwise.
    """
    # Search tags first (most reliable)
    for tag in tags:
        result = detect_stock(tag, tag_map)
        if result:
            return result

    # Then title
    result = detect_stock(title, tag_map)
    if result:
        return result

    # Then description
    return detect_stock(description, tag_map)


def atomic_write_json(path: Path, data: Any) -> None:
    """Write JSON data atomically using write-to-tmp-then-rename.

    Args:
        path: Target file path.
        data: Data to serialize. Can be a Pydantic model or dict.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    if isinstance(data, BaseModel):
        json_str = data.model_dump_json(indent=2)
    else:
        json_str = json.dumps(data, indent=2, default=str)

    fd, tmp_path = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json_str)
            f.write("\n")
        Path(tmp_path).rename(path)
    except BaseException:
        Path(tmp_path).unlink(missing_ok=True)
        raise


def load_tag_map(path: Path) -> dict[str, str]:
    """Load a user-defined tag-to-stock mapping from a JSON file.

    Args:
        path: Path to JSON file mapping tags to stock names.

    Returns:
        Dictionary of tag -> stock name mappings.
    """
    with open(path, encoding="utf-8") as f:
        data: dict[str, str] = json.load(f)
    return data


def ensure_dir(path: Path, force: bool = False) -> Path:
    """Ensure a directory exists, optionally checking for existing contents.

    Args:
        path: Directory path to create.
        force: If False and directory has contents, raise an error.

    Returns:
        The directory path.

    Raises:
        FileExistsError: If directory has contents and force is False.
    """
    path.mkdir(parents=True, exist_ok=True)
    if not force and any(path.iterdir()):
        raise FileExistsError(f"Output directory {path} is not empty. Use --force to overwrite.")
    return path
