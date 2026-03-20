"""Grain and color fingerprint analysis per film stock."""

import json
import random
import warnings
from pathlib import Path

import numpy as np
from numpy.exceptions import RankWarning
from PIL import Image
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from negclone.models import (
    ColorBias,
    GrainProfile,
    StockFingerprint,
    TonalRolloff,
)
from negclone.utils import atomic_write_json

console = Console()

# Analysis constants
MIN_SAMPLE_SIZE: int = 5
SHADOW_PERCENTILE: float = 25.0
HIGHLIGHT_PERCENTILE: float = 75.0
GRAIN_PATCH_SIZE: int = 64
NUM_GRAIN_PATCHES: int = 20
POLY_DEGREE: int = 5
AUTOCORRELATION_LAG: int = 2


def fingerprint_stock(
    image_paths: list[Path],
    stock: str,
    sample_size: int = 20,
    verbose: bool = False,
) -> StockFingerprint | None:
    """Compute a fingerprint for a film stock from cached images.

    Args:
        image_paths: Paths to cached images for this stock.
        stock: Film stock name.
        sample_size: Max images to analyze.
        verbose: Enable verbose output.

    Returns:
        StockFingerprint or None if insufficient samples.
    """
    if len(image_paths) < MIN_SAMPLE_SIZE:
        console.print(
            f"[yellow]Warning: {stock} has only {len(image_paths)} images "
            f"(minimum {MIN_SAMPLE_SIZE}). Skipping.[/yellow]"
        )
        return None

    # Sample if needed
    if len(image_paths) > sample_size:
        paths = random.sample(image_paths, sample_size)
    else:
        paths = list(image_paths)

    grain_profiles: list[GrainProfile] = []
    color_biases: list[ColorBias] = []
    tonal_rolloffs: list[TonalRolloff] = []

    for path in paths:
        try:
            img = Image.open(path).convert("RGB")
            arr = np.array(img, dtype=np.float64) / 255.0

            grain = _analyze_grain(arr)
            color = _analyze_color_bias(arr)
            tone = _analyze_tonal_rolloff(arr)

            grain_profiles.append(grain)
            color_biases.append(color)
            tonal_rolloffs.append(tone)

            if verbose:
                console.print(f"[dim]  Analyzed: {path.name}[/dim]")

        except (OSError, ValueError) as e:
            console.print(f"[yellow]  Warning: Failed to analyze {path.name}: {e}[/yellow]")
            continue

    if len(grain_profiles) < MIN_SAMPLE_SIZE:
        console.print(
            f"[yellow]Warning: Only {len(grain_profiles)} valid samples for {stock}. "
            f"Skipping.[/yellow]"
        )
        return None

    # Aggregate with median
    agg_grain = _aggregate_grain(grain_profiles)
    agg_color = _aggregate_color(color_biases)
    agg_tone = _aggregate_tone(tonal_rolloffs)
    confidence = _compute_confidence(grain_profiles, color_biases, tonal_rolloffs)

    fingerprint = StockFingerprint(
        stock=stock,
        sample_count=len(grain_profiles),
        grain=agg_grain,
        color=agg_color,
        tone=agg_tone,
        confidence=confidence,
    )

    return fingerprint


def _analyze_grain(arr: np.ndarray) -> GrainProfile:
    """Analyze grain characteristics from an image array.

    Measures noise in shadow/uniform regions using local standard deviation
    on the luminance channel.

    Args:
        arr: Image as float64 array, shape (H, W, 3), range [0, 1].

    Returns:
        GrainProfile with grain metrics.
    """
    # Convert to luminance
    luminance = 0.2126 * arr[:, :, 0] + 0.7152 * arr[:, :, 1] + 0.0722 * arr[:, :, 2]

    h, w = luminance.shape
    patch_size = min(GRAIN_PATCH_SIZE, h // 2, w // 2)

    if patch_size < 8:
        return GrainProfile(mean_intensity=0.0, size_estimate=1.0, clumping_factor=0.0)

    # Sample patches from shadow regions (lower luminance areas)
    intensities: list[float] = []
    autocorrs: list[float] = []

    for _ in range(NUM_GRAIN_PATCHES):
        y = random.randint(0, h - patch_size)
        x = random.randint(0, w - patch_size)
        patch = luminance[y : y + patch_size, x : x + patch_size]

        # Local std dev as grain intensity
        local_std = float(np.std(patch))
        intensities.append(local_std)

        # Spatial autocorrelation for clumping
        if patch_size > AUTOCORRELATION_LAG:
            shifted = patch[AUTOCORRELATION_LAG:, AUTOCORRELATION_LAG:]
            original = patch[: patch_size - AUTOCORRELATION_LAG, : patch_size - AUTOCORRELATION_LAG]
            if original.std() > 1e-10 and shifted.std() > 1e-10:
                corr = float(np.corrcoef(original.ravel(), shifted.ravel())[0, 1])
                autocorrs.append(max(0.0, min(1.0, corr)))

    mean_intensity = float(np.median(intensities)) if intensities else 0.0

    # Size estimate: higher autocorrelation = larger grain
    clumping = float(np.median(autocorrs)) if autocorrs else 0.0
    size_estimate = 1.0 + clumping * 4.0  # Scale to approximate pixel size

    return GrainProfile(
        mean_intensity=mean_intensity,
        size_estimate=size_estimate,
        clumping_factor=clumping,
    )


def _analyze_color_bias(arr: np.ndarray) -> ColorBias:
    """Analyze color channel bias in shadows, midtones, and highlights.

    Args:
        arr: Image as float64 array, shape (H, W, 3), range [0, 1].

    Returns:
        ColorBias with per-region channel means.
    """
    luminance = 0.2126 * arr[:, :, 0] + 0.7152 * arr[:, :, 1] + 0.0722 * arr[:, :, 2]

    shadow_thresh = np.percentile(luminance, SHADOW_PERCENTILE)
    highlight_thresh = np.percentile(luminance, HIGHLIGHT_PERCENTILE)

    shadow_mask = luminance < shadow_thresh
    highlight_mask = luminance > highlight_thresh
    midtone_mask = ~shadow_mask & ~highlight_mask

    def _channel_means(mask: np.ndarray) -> tuple[float, float, float]:
        if not np.any(mask):
            return (0.0, 0.0, 0.0)
        r = float(np.mean(arr[:, :, 0][mask]))
        g = float(np.mean(arr[:, :, 1][mask]))
        b = float(np.mean(arr[:, :, 2][mask]))
        # Return as shift from neutral gray
        mean = (r + g + b) / 3.0
        return (r - mean, g - mean, b - mean)

    return ColorBias(
        shadows=_channel_means(shadow_mask),
        midtones=_channel_means(midtone_mask),
        highlights=_channel_means(highlight_mask),
    )


def _analyze_tonal_rolloff(arr: np.ndarray) -> TonalRolloff:
    """Analyze tonal characteristics from the luminance histogram.

    Measures shadow density, highlight rolloff, and midtone contrast by
    analyzing the luminance histogram shape rather than fitting a transfer
    curve (which requires a known linear reference).

    Args:
        arr: Image as float64 array, shape (H, W, 3), range [0, 1].

    Returns:
        TonalRolloff with curve characteristics.
    """
    luminance = 0.2126 * arr[:, :, 0] + 0.7152 * arr[:, :, 1] + 0.0722 * arr[:, :, 2]
    flat = luminance.ravel()

    # Histogram-based analysis (256 bins)
    hist, bin_edges = np.histogram(flat, bins=256, range=(0.0, 1.0))
    hist_norm = hist.astype(np.float64) / hist.sum()

    # Shadow lift: how much density is in the deep shadows (0-10%)
    # Film with lifted shadows will have less density in the 0-5% range
    # compared to the 5-15% range
    deep_shadow = hist_norm[:13].sum()  # 0-5%
    near_shadow = hist_norm[13:38].sum()  # 5-15%
    # If near_shadow >> deep_shadow, shadows are lifted (film look)
    if deep_shadow > 0.001:
        shadow_lift = float(min(1.0, max(0.0, 1.0 - deep_shadow / max(near_shadow, 0.001))))
    else:
        shadow_lift = 0.8  # Very little deep shadow = strong lift

    # Highlight compression: how much density falls off in bright highlights
    # Film typically compresses highlights gracefully
    bright_highlight = hist_norm[243:].sum()  # 95-100%
    near_highlight = hist_norm[218:243].sum()  # 85-95%
    if near_highlight > 0.001:
        highlight_compression = float(
            min(1.0, max(0.0, 1.0 - bright_highlight / max(near_highlight, 0.001)))
        )
    else:
        highlight_compression = 0.5

    # Midtone contrast: ratio of density in mid-range vs overall spread
    # Measured as the steepness of the CDF through the midtones
    p10 = float(np.percentile(flat, 10))
    p90 = float(np.percentile(flat, 90))
    p35 = float(np.percentile(flat, 35))
    p65 = float(np.percentile(flat, 65))
    total_range = max(p90 - p10, 0.01)
    mid_range = max(p65 - p35, 0.001)
    # Contrast > 1 means midtones are compressed (high contrast)
    # Contrast < 1 means midtones are spread (low contrast)
    midtone_contrast = float((0.30 / mid_range) * (total_range / 0.80))

    # Fit polynomial to the CDF for preset generation
    sorted_vals = np.sort(flat)
    n = len(sorted_vals)
    cdf_y = np.linspace(0.0, 1.0, n)
    step = max(1, n // 1000)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RankWarning)
        coeffs = np.polyfit(sorted_vals[::step], cdf_y[::step], POLY_DEGREE)

    return TonalRolloff(
        shadow_lift=round(shadow_lift, 4),
        highlight_compression=round(highlight_compression, 4),
        midtone_contrast=round(midtone_contrast, 3),
        curve_coefficients=[float(c) for c in coeffs],
    )


def _aggregate_grain(profiles: list[GrainProfile]) -> GrainProfile:
    """Aggregate grain profiles using median values.

    Args:
        profiles: List of per-image grain profiles.

    Returns:
        Aggregated GrainProfile.
    """
    return GrainProfile(
        mean_intensity=float(np.median([p.mean_intensity for p in profiles])),
        size_estimate=float(np.median([p.size_estimate for p in profiles])),
        clumping_factor=float(np.median([p.clumping_factor for p in profiles])),
    )


def _aggregate_color(biases: list[ColorBias]) -> ColorBias:
    """Aggregate color biases using median values.

    Args:
        biases: List of per-image color biases.

    Returns:
        Aggregated ColorBias.
    """

    def _median_tuple(
        values: list[tuple[float, float, float]],
    ) -> tuple[float, float, float]:
        arr = np.array(values)
        return (
            float(np.median(arr[:, 0])),
            float(np.median(arr[:, 1])),
            float(np.median(arr[:, 2])),
        )

    return ColorBias(
        shadows=_median_tuple([b.shadows for b in biases]),
        midtones=_median_tuple([b.midtones for b in biases]),
        highlights=_median_tuple([b.highlights for b in biases]),
    )


def _aggregate_tone(rolloffs: list[TonalRolloff]) -> TonalRolloff:
    """Aggregate tonal rolloffs using median values.

    Args:
        rolloffs: List of per-image tonal rolloffs.

    Returns:
        Aggregated TonalRolloff.
    """
    # Median of polynomial coefficients
    coeff_arrays = [r.curve_coefficients for r in rolloffs]
    max_len = max(len(c) for c in coeff_arrays)
    padded = [c + [0.0] * (max_len - len(c)) for c in coeff_arrays]
    median_coeffs = [float(np.median([p[i] for p in padded])) for i in range(max_len)]

    return TonalRolloff(
        shadow_lift=float(np.median([r.shadow_lift for r in rolloffs])),
        highlight_compression=float(np.median([r.highlight_compression for r in rolloffs])),
        midtone_contrast=float(np.median([r.midtone_contrast for r in rolloffs])),
        curve_coefficients=median_coeffs,
    )


def _compute_confidence(
    grains: list[GrainProfile],
    colors: list[ColorBias],
    tones: list[TonalRolloff],
) -> float:
    """Compute confidence score based on consistency (inverse IQR spread).

    Args:
        grains: List of grain profiles.
        colors: List of color biases.
        tones: List of tonal rolloffs.

    Returns:
        Confidence score between 0 and 1.
    """
    # Use grain intensity IQR as primary consistency indicator
    intensities = [g.mean_intensity for g in grains]
    if len(intensities) < 4:
        return 0.5

    q1 = float(np.percentile(intensities, 25))
    q3 = float(np.percentile(intensities, 75))
    iqr = q3 - q1
    median = float(np.median(intensities))

    if median < 1e-10:
        return 0.5

    # Use coefficient of quartile dispersion: IQR / (Q1 + Q3)
    # This is bounded 0-1 and less sensitive to small medians
    cqd = iqr / max(q1 + q3, 0.001)

    # Also factor in color consistency
    mid_r = [c.midtones[0] for c in colors]
    mid_b = [c.midtones[2] for c in colors]
    color_std = float(np.std(mid_r) + np.std(mid_b))

    # Combined confidence: lower dispersion + lower color variance = higher confidence
    # CQD of 0 = perfect, CQD of 0.5 = very spread
    grain_conf = max(0.0, 1.0 - 2.0 * cqd)
    color_conf = max(0.0, 1.0 - color_std * 20.0)
    confidence = 0.7 * grain_conf + 0.3 * color_conf
    return round(max(0.0, min(1.0, confidence)), 3)


def save_fingerprint(fingerprint: StockFingerprint, output_dir: Path) -> Path:
    """Save a fingerprint to JSON.

    Args:
        fingerprint: StockFingerprint to save.
        output_dir: Directory to write the JSON file.

    Returns:
        Path to the written file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"fingerprint_{fingerprint.stock}.json"
    atomic_write_json(path, fingerprint)
    return path


def load_fingerprint(path: Path) -> StockFingerprint:
    """Load a fingerprint from JSON.

    Args:
        path: Path to fingerprint JSON.

    Returns:
        Loaded StockFingerprint.
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return StockFingerprint.model_validate(data)


def print_fingerprint_summary(fp: StockFingerprint) -> None:
    """Print a summary card for a fingerprint.

    Args:
        fp: StockFingerprint to display.
    """
    table = Table(show_header=False, box=None)
    table.add_column("Property", style="bold")
    table.add_column("Value")

    table.add_row("Stock", fp.stock)
    table.add_row("Samples", str(fp.sample_count))
    table.add_row("Confidence", f"{fp.confidence:.1%}")
    table.add_row("", "")
    table.add_row("Grain Intensity", f"{fp.grain.mean_intensity:.4f}")
    table.add_row("Grain Size", f"{fp.grain.size_estimate:.2f} px")
    table.add_row("Grain Clumping", f"{fp.grain.clumping_factor:.3f}")
    table.add_row("", "")
    table.add_row("Shadow Lift", f"{fp.tone.shadow_lift:.4f}")
    table.add_row("Highlight Compression", f"{fp.tone.highlight_compression:.4f}")
    table.add_row("Midtone Contrast", f"{fp.tone.midtone_contrast:.3f}")
    table.add_row("", "")
    table.add_row("Shadow Color", _format_rgb(fp.color.shadows))
    table.add_row("Midtone Color", _format_rgb(fp.color.midtones))
    table.add_row("Highlight Color", _format_rgb(fp.color.highlights))

    panel = Panel(table, title=f"[bold cyan]{fp.stock}[/bold cyan] Fingerprint")
    console.print(panel)


def _format_rgb(values: tuple[float, float, float]) -> str:
    """Format RGB shift values for display.

    Args:
        values: Tuple of R, G, B shift values.

    Returns:
        Formatted string.
    """
    r, g, b = values
    return f"R:{r:+.4f}  G:{g:+.4f}  B:{b:+.4f}"
