"""Tests for fingerprint analysis — grain, color, and tonal rolloff."""

from pathlib import Path

import numpy as np
import pytest

from negclone.fingerprint import (
    _analyze_color_bias,
    _analyze_grain,
    _analyze_tonal_rolloff,
    fingerprint_stock,
    load_fingerprint,
    save_fingerprint,
)
from negclone.models import StockFingerprint
from tests.conftest import create_synthetic_image


class TestGrainAnalysis:
    """Tests for grain metric calculation."""

    def test_basic_grain_analysis(self) -> None:
        img = create_synthetic_image(50, 50, noise_level=15.0)
        arr = np.array(img, dtype=np.float64) / 255.0

        grain = _analyze_grain(arr)

        assert grain.mean_intensity >= 0.0
        assert grain.size_estimate >= 1.0
        assert 0.0 <= grain.clumping_factor <= 1.0

    def test_low_noise_low_intensity(self) -> None:
        img = create_synthetic_image(50, 50, noise_level=1.0)
        arr = np.array(img, dtype=np.float64) / 255.0

        grain = _analyze_grain(arr)

        # Low noise should give low intensity
        assert grain.mean_intensity < 0.1

    def test_high_noise_higher_intensity(self) -> None:
        img = create_synthetic_image(50, 50, noise_level=40.0)
        arr = np.array(img, dtype=np.float64) / 255.0

        grain = _analyze_grain(arr)

        # Higher noise should give higher intensity
        assert grain.mean_intensity > 0.01

    def test_tiny_image_returns_defaults(self) -> None:
        arr = np.full((4, 4, 3), 0.5)
        grain = _analyze_grain(arr)
        assert grain.mean_intensity == 0.0


class TestColorBiasAnalysis:
    """Tests for color channel bucketing."""

    def test_neutral_image(self) -> None:
        arr = np.full((50, 50, 3), 0.5)
        color = _analyze_color_bias(arr)

        # Neutral image should have near-zero bias
        for channel in color.shadows:
            assert abs(channel) < 0.01
        for channel in color.midtones:
            assert abs(channel) < 0.01

    def test_warm_image(self) -> None:
        # Create image with luminance variation + red bias
        rng = np.random.default_rng(42)
        arr = rng.uniform(0.1, 0.9, (100, 100, 3))
        arr[:, :, 0] += 0.1  # Boost red
        arr[:, :, 2] -= 0.1  # Reduce blue
        arr = np.clip(arr, 0.0, 1.0)

        color = _analyze_color_bias(arr)

        # Midtones should clearly show warm bias (red > blue)
        r, g, b = color.midtones
        assert r > b  # Red should be stronger than blue

    @pytest.mark.parametrize(
        "stock_color",
        [
            (180, 160, 140),  # Warm (portra-like)
            (128, 128, 128),  # Neutral (B&W)
            (150, 130, 110),  # Warm saturated (ektar-like)
        ],
    )
    def test_parametrized_stocks(self, stock_color: tuple[int, int, int]) -> None:
        img = create_synthetic_image(50, 50, color=stock_color)
        arr = np.array(img, dtype=np.float64) / 255.0
        color = _analyze_color_bias(arr)

        # Should produce valid output
        assert len(color.shadows) == 3
        assert len(color.midtones) == 3
        assert len(color.highlights) == 3


class TestTonalRolloff:
    """Tests for tonal rolloff fitting."""

    def test_basic_rolloff(self) -> None:
        img = create_synthetic_image(50, 50)
        arr = np.array(img, dtype=np.float64) / 255.0

        tone = _analyze_tonal_rolloff(arr)

        assert tone.shadow_lift >= 0.0
        assert tone.highlight_compression >= 0.0
        assert tone.midtone_contrast > 0.0
        assert len(tone.curve_coefficients) > 0

    def test_curve_coefficients_polynomial(self) -> None:
        arr = np.random.default_rng(42).random((100, 100, 3))
        tone = _analyze_tonal_rolloff(arr)

        # Should produce POLY_DEGREE + 1 coefficients
        assert len(tone.curve_coefficients) == 6  # POLY_DEGREE=5 -> 6 coeffs


class TestFingerprintStock:
    """Tests for full stock fingerprinting pipeline."""

    def test_fingerprint_with_enough_images(self, synthetic_images: dict[str, list[Path]]) -> None:
        paths = synthetic_images["portra400"]
        fp = fingerprint_stock(paths, "portra400", sample_size=8)

        assert fp is not None
        assert fp.stock == "portra400"
        assert fp.sample_count == 8
        assert 0.0 <= fp.confidence <= 1.0

    def test_skip_when_too_few_images(self, tmp_cache: Path) -> None:
        stock_dir = tmp_cache / "rare_stock"
        stock_dir.mkdir()

        # Create only 3 images (below MIN_SAMPLE_SIZE of 5)
        paths: list[Path] = []
        for i in range(3):
            img = create_synthetic_image(50, 50, seed=i)
            path = stock_dir / f"test_{i}.jpg"
            img.save(path)
            paths.append(path)

        fp = fingerprint_stock(paths, "rare_stock")
        assert fp is None

    @pytest.mark.parametrize("stock", ["portra400", "hp5", "ektar100"])
    def test_parametrized_stocks(self, stock: str, synthetic_images: dict[str, list[Path]]) -> None:
        paths = synthetic_images[stock]
        fp = fingerprint_stock(paths, stock, sample_size=8)

        assert fp is not None
        assert fp.stock == stock

    def test_save_and_load_fingerprint(
        self,
        sample_fingerprint: StockFingerprint,
        tmp_output: Path,
    ) -> None:
        path = save_fingerprint(sample_fingerprint, tmp_output)

        assert path.exists()
        assert path.suffix == ".json"

        loaded = load_fingerprint(path)
        assert loaded.stock == sample_fingerprint.stock
        assert loaded.grain.mean_intensity == sample_fingerprint.grain.mean_intensity
        assert loaded.confidence == sample_fingerprint.confidence
