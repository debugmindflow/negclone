"""Tests for inventory module — stock detection and data handling."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from negclone.models import FlickrPhotoRecord, Inventory
from negclone.utils import (
    atomic_write_json,
    detect_stock,
    detect_stock_from_metadata,
)


class TestDetectStock:
    """Tests for film stock detection from text."""

    @pytest.mark.parametrize(
        "text, expected",
        [
            ("Shot on Portra 400", "portra400"),
            ("portra400", "portra400"),
            ("Kodak Portra 160", "portra160"),
            ("HP5 Plus", "hp5"),
            ("ilford hp5", "hp5"),
            ("Tri-X 400", "tri-x"),
            ("trix", "tri-x"),
            ("CineStill 800T", "cinestill800t"),
            ("ektar100", "ektar100"),
            ("Fomapan 100", "fomapan100"),
            ("gold200", "gold200"),
            ("delta100", "delta100"),
            ("random text", None),
            ("", None),
        ],
    )
    def test_detect_stock(self, text: str, expected: str | None) -> None:
        assert detect_stock(text) == expected

    def test_detect_stock_with_tag_map(self) -> None:
        tag_map = {"myportra": "portra400", "bw": "hp5"}
        assert detect_stock("tagged myportra", tag_map) == "portra400"
        assert detect_stock("bw film", tag_map) == "hp5"

    def test_tag_map_takes_priority(self) -> None:
        tag_map = {"portra": "portra800"}  # Override default
        assert detect_stock("portra", tag_map) == "portra800"


class TestDetectStockFromMetadata:
    """Tests for stock detection across multiple metadata fields."""

    def test_detects_from_tags(self) -> None:
        result = detect_stock_from_metadata(
            title="Sunset",
            description="A nice photo",
            tags=["portra400", "film"],
        )
        assert result == "portra400"

    def test_detects_from_title(self) -> None:
        result = detect_stock_from_metadata(
            title="Shot on Portra 400",
            description="",
            tags=["landscape"],
        )
        assert result == "portra400"

    def test_detects_from_description(self) -> None:
        result = detect_stock_from_metadata(
            title="Sunset",
            description="Taken with Kodak Tri-X",
            tags=[],
        )
        assert result == "tri-x"

    def test_tags_preferred_over_title(self) -> None:
        result = detect_stock_from_metadata(
            title="portra160 vibes",
            description="",
            tags=["hp5"],
        )
        assert result == "hp5"

    def test_no_match(self) -> None:
        result = detect_stock_from_metadata(
            title="My photo",
            description="Nice shot",
            tags=["landscape"],
        )
        assert result is None


class TestAtomicWriteJson:
    """Tests for atomic JSON file writing."""

    def test_writes_dict(self, tmp_path: Path) -> None:
        path = tmp_path / "test.json"
        data = {"key": "value", "number": 42}
        atomic_write_json(path, data)

        assert path.exists()
        with open(path) as f:
            loaded = json.load(f)
        assert loaded == data

    def test_writes_pydantic_model(self, tmp_path: Path) -> None:
        path = tmp_path / "inventory.json"
        inv = Inventory(
            stocks={
                "portra400": [
                    FlickrPhotoRecord(
                        photo_id="123",
                        title="Test",
                        stock="portra400",
                        url_original="https://example.com/photo.jpg",
                    )
                ]
            },
            user="testuser",
        )
        atomic_write_json(path, inv)

        assert path.exists()
        with open(path) as f:
            loaded = json.load(f)
        assert "stocks" in loaded
        assert "portra400" in loaded["stocks"]

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        path = tmp_path / "sub" / "dir" / "test.json"
        atomic_write_json(path, {"test": True})
        assert path.exists()

    def test_no_corrupt_on_error(self, tmp_path: Path) -> None:
        path = tmp_path / "test.json"
        # Write initial data
        atomic_write_json(path, {"original": True})

        # Try to write to a read-only directory (should fail on rename)
        bad_path = tmp_path / "readonly" / "test.json"
        bad_path.parent.mkdir()
        bad_path.parent.chmod(0o444)
        try:
            with pytest.raises(PermissionError):
                atomic_write_json(bad_path, {"new": True})
        finally:
            bad_path.parent.chmod(0o755)

        # Original file should still be intact
        with open(path) as f:
            loaded = json.load(f)
        assert loaded == {"original": True}


class TestInventoryModel:
    """Tests for Inventory Pydantic model."""

    def test_round_trip_serialization(self) -> None:
        inv = Inventory(
            stocks={
                "hp5": [
                    FlickrPhotoRecord(
                        photo_id="456",
                        title="Street",
                        stock="hp5",
                        url_original="https://example.com/photo2.jpg",
                        tags=["bw", "hp5"],
                        date_taken=datetime(2024, 6, 15, 10, 30),
                    )
                ]
            },
            user="testuser",
        )

        json_str = inv.model_dump_json()
        loaded = Inventory.model_validate_json(json_str)

        assert loaded.stocks["hp5"][0].photo_id == "456"
        assert loaded.stocks["hp5"][0].stock == "hp5"
        assert loaded.user == "testuser"
