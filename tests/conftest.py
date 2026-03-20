"""Shared test fixtures for NegClone."""

from datetime import datetime
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from negclone.models import (
    ColorBias,
    GrainProfile,
    StockFingerprint,
    TonalRolloff,
)


@pytest.fixture
def tmp_output(tmp_path: Path) -> Path:
    """Provide a temporary output directory."""
    out = tmp_path / "output"
    out.mkdir()
    return out


@pytest.fixture
def tmp_cache(tmp_path: Path) -> Path:
    """Provide a temporary cache directory."""
    cache = tmp_path / "cache"
    cache.mkdir()
    return cache


@pytest.fixture
def sample_fingerprint() -> StockFingerprint:
    """Create a sample fingerprint for testing."""
    return StockFingerprint(
        stock="portra400",
        sample_count=15,
        grain=GrainProfile(
            mean_intensity=0.045,
            size_estimate=2.3,
            clumping_factor=0.35,
        ),
        color=ColorBias(
            shadows=(0.02, -0.01, -0.01),
            midtones=(0.01, 0.005, -0.015),
            highlights=(-0.005, 0.01, -0.005),
        ),
        tone=TonalRolloff(
            shadow_lift=0.03,
            highlight_compression=0.05,
            midtone_contrast=1.1,
            curve_coefficients=[0.1, -0.3, 0.5, 0.2, 0.8, 0.01],
        ),
        confidence=0.82,
        generated_at=datetime(2025, 1, 15, 12, 0, 0),
    )


def create_synthetic_image(
    width: int = 50,
    height: int = 50,
    color: tuple[int, int, int] = (128, 120, 110),
    noise_level: float = 10.0,
    seed: int = 42,
) -> Image.Image:
    """Create a synthetic test image with controllable properties.

    Args:
        width: Image width in pixels.
        height: Image height in pixels.
        color: Base RGB color.
        noise_level: Standard deviation of Gaussian noise.
        seed: Random seed for reproducibility.

    Returns:
        PIL Image.
    """
    rng = np.random.default_rng(seed)
    arr = np.full((height, width, 3), color, dtype=np.float64)
    noise = rng.normal(0, noise_level, arr.shape)
    arr = np.clip(arr + noise, 0, 255).astype(np.uint8)
    return Image.fromarray(arr, "RGB")


@pytest.fixture
def synthetic_images(tmp_cache: Path) -> dict[str, list[Path]]:
    """Create synthetic test images for multiple stocks.

    Returns dict mapping stock name to list of image paths.
    """
    stocks = {
        "portra400": (180, 160, 140),  # Warm tones
        "hp5": (128, 128, 128),  # Neutral B&W
        "ektar100": (150, 130, 110),  # Warm, saturated
    }

    result: dict[str, list[Path]] = {}

    for stock, base_color in stocks.items():
        stock_dir = tmp_cache / stock
        stock_dir.mkdir()
        paths: list[Path] = []

        for i in range(8):  # 8 images per stock (above MIN_SAMPLE_SIZE)
            img = create_synthetic_image(
                width=50,
                height=50,
                color=base_color,
                noise_level=10.0 + i * 2,
                seed=42 + i,
            )
            path = stock_dir / f"test_{i:03d}.jpg"
            img.save(path, "JPEG", quality=95)
            paths.append(path)

        result[stock] = paths

    return result
