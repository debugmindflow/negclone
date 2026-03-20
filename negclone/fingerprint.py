"""Grain and color fingerprint analysis per film stock."""

import json
import random
import warnings
from collections import Counter
from pathlib import Path

import numpy as np
from numpy.exceptions import RankWarning
from PIL import Image
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from scipy.interpolate import PchipInterpolator

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
GRAIN_PATCH_SIZE: int = 128
NUM_GRAIN_PATCHES: int = 20
POLY_DEGREE: int = 5
AUTOCORRELATION_LAG: int = 2
FFT_RADIAL_BINS: int = 32
TONE_CURVE_POINTS: int = 17  # Number of spline sample points for export


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
    scanner_models: list[str] = []

    for path in paths:
        try:
            img = Image.open(path).convert("RGB")
            arr = np.array(img, dtype=np.float64) / 255.0

            grain = _analyze_grain(arr)
            color = _analyze_color_bias(arr)
            tone = _analyze_tonal_rolloff(arr)

            # Scanner detection
            scanner = _detect_scanner_from_image(path)
            if scanner:
                scanner_models.append(scanner)

            grain_profiles.append(grain)
            color_biases.append(color)
            tonal_rolloffs.append(tone)

            if verbose:
                scanner_info = f" [scanner: {scanner}]" if scanner else ""
                console.print(f"[dim]  Analyzed: {path.name}{scanner_info}[/dim]")

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

    # Apply scanner compensation if we detected a consistent scanner
    detected_scanner: str | None = None
    if scanner_models:
        most_common = Counter(scanner_models).most_common(1)[0]
        if most_common[1] >= len(scanner_models) // 2:
            detected_scanner = most_common[0]
            try:
                from negclone.scanner_profiles import (
                    compensate_color_bias,
                    get_scanner_compensation,
                )

                profile = get_scanner_compensation(detected_scanner)
                if profile:
                    agg_color = compensate_color_bias(agg_color, profile)
                    if verbose:
                        console.print(
                            f"[dim]  Applied scanner compensation for {detected_scanner}[/dim]"
                        )
            except ImportError:
                pass

    fingerprint = StockFingerprint(
        stock=stock,
        sample_count=len(grain_profiles),
        grain=agg_grain,
        color=agg_color,
        tone=agg_tone,
        confidence=confidence,
        scanner_model=detected_scanner,
    )

    return fingerprint


def _detect_scanner_from_image(path: Path) -> str | None:
    """Detect scanner model from image EXIF data.

    Args:
        path: Path to image file.

    Returns:
        Scanner model string or None.
    """
    try:
        img = Image.open(path)
        exif = img.getexif()
        if not exif:
            return None

        # Check Model (0x0110), Software (0x0131), ImageDescription (0x010E)
        for tag_id in (0x0110, 0x0131, 0x010E):
            value = exif.get(tag_id)
            if value and isinstance(value, str):
                lower = value.lower()
                for keyword in (
                    "epson",
                    "noritsu",
                    "frontier",
                    "plustek",
                    "pacific image",
                    "pakon",
                    "coolscan",
                    "flextight",
                ):
                    if keyword in lower:
                        return value.strip()
    except (OSError, ValueError):
        pass
    return None


def _analyze_grain(arr: np.ndarray) -> GrainProfile:
    """Analyze grain characteristics using FFT spectral analysis.

    Uses both local standard deviation (for intensity) and 2D FFT with
    radial averaging (for frequency/size characterization).

    Args:
        arr: Image as float64 array, shape (H, W, 3), range [0, 1].

    Returns:
        GrainProfile with grain metrics including spectral data.
    """
    # Convert to luminance
    luminance = 0.2126 * arr[:, :, 0] + 0.7152 * arr[:, :, 1] + 0.0722 * arr[:, :, 2]

    h, w = luminance.shape
    patch_size = min(GRAIN_PATCH_SIZE, h // 2, w // 2)

    if patch_size < 16:
        return GrainProfile(mean_intensity=0.0, size_estimate=1.0, clumping_factor=0.0)

    intensities: list[float] = []
    autocorrs: list[float] = []
    peak_freqs: list[float] = []
    spectral_slopes: list[float] = []
    spectral_centroids: list[float] = []

    # 2D Hann window for FFT (reduces spectral leakage)
    hann_1d = np.hanning(patch_size)
    window = np.outer(hann_1d, hann_1d)

    for _ in range(NUM_GRAIN_PATCHES):
        y = random.randint(0, h - patch_size)
        x = random.randint(0, w - patch_size)
        patch = luminance[y : y + patch_size, x : x + patch_size]

        # Local std dev as grain intensity
        local_std = float(np.std(patch))
        intensities.append(local_std)

        # Spatial autocorrelation for clumping (legacy metric)
        if patch_size > AUTOCORRELATION_LAG:
            shifted = patch[AUTOCORRELATION_LAG:, AUTOCORRELATION_LAG:]
            original = patch[: patch_size - AUTOCORRELATION_LAG, : patch_size - AUTOCORRELATION_LAG]
            if original.std() > 1e-10 and shifted.std() > 1e-10:
                corr = float(np.corrcoef(original.ravel(), shifted.ravel())[0, 1])
                autocorrs.append(max(0.0, min(1.0, corr)))

        # FFT spectral analysis
        windowed = (patch - patch.mean()) * window
        fft_result = np.fft.fft2(windowed)
        power_spectrum = np.abs(fft_result) ** 2

        # Radial average of power spectrum
        radial_profile = _radial_average(power_spectrum, FFT_RADIAL_BINS)

        if len(radial_profile) > 2:
            freqs = np.linspace(0, 0.5, len(radial_profile))  # 0 to Nyquist

            # Skip DC component (index 0)
            freqs_ndc = freqs[1:]
            profile_ndc = radial_profile[1:]

            if len(profile_ndc) > 0 and np.max(profile_ndc) > 0:
                # Peak frequency
                peak_idx = int(np.argmax(profile_ndc))
                peak_freqs.append(float(freqs_ndc[peak_idx]))

                # Spectral centroid (weighted mean frequency)
                total_power = np.sum(profile_ndc)
                if total_power > 0:
                    centroid = float(np.sum(freqs_ndc * profile_ndc) / total_power)
                    spectral_centroids.append(centroid)

                # Spectral slope (log-log fit)
                valid = profile_ndc > 0
                if np.sum(valid) > 3:
                    log_f = np.log10(freqs_ndc[valid])
                    log_p = np.log10(profile_ndc[valid])
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", RankWarning)
                        slope_coeffs = np.polyfit(log_f, log_p, 1)
                    spectral_slopes.append(float(slope_coeffs[0]))

    mean_intensity = float(np.median(intensities)) if intensities else 0.0
    clumping = float(np.median(autocorrs)) if autocorrs else 0.0

    # FFT-derived size estimate: 1 / peak_frequency
    peak_freq = float(np.median(peak_freqs)) if peak_freqs else 0.0
    size_estimate = 1.0 / peak_freq if peak_freq > 0.01 else 1.0 + clumping * 4.0

    return GrainProfile(
        mean_intensity=mean_intensity,
        size_estimate=round(size_estimate, 2),
        clumping_factor=clumping,
        peak_frequency=round(peak_freq, 4),
        spectral_slope=round(float(np.median(spectral_slopes)) if spectral_slopes else 0.0, 3),
        spectral_centroid=round(
            float(np.median(spectral_centroids)) if spectral_centroids else 0.0, 4
        ),
    )


def _radial_average(power_spectrum: np.ndarray, n_bins: int) -> np.ndarray:
    """Compute radially averaged power spectrum.

    Args:
        power_spectrum: 2D power spectrum from FFT.
        n_bins: Number of radial bins.

    Returns:
        1D array of radially averaged power values.
    """
    h, w = power_spectrum.shape
    cy, cx = h // 2, w // 2

    # Shift DC to center
    shifted = np.fft.fftshift(power_spectrum)

    # Build radius map
    y_coords, x_coords = np.ogrid[-cy : h - cy, -cx : w - cx]
    radius = np.sqrt(y_coords**2 + x_coords**2)

    # Normalize radius to [0, 1] where 1 = Nyquist
    max_radius = min(cy, cx)
    radius_norm = radius / max(max_radius, 1)

    # Bin edges
    bin_edges = np.linspace(0, 1.0, n_bins + 1)
    profile = np.zeros(n_bins)

    for i in range(n_bins):
        mask = (radius_norm >= bin_edges[i]) & (radius_norm < bin_edges[i + 1])
        if np.any(mask):
            profile[i] = float(np.mean(shifted[mask]))

    return profile


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
    """Analyze tonal characteristics and fit a monotone spline tone curve.

    Uses histogram shape analysis for shadow lift, highlight compression,
    and midtone contrast, plus a PCHIP monotone spline for smooth curve export.

    Args:
        arr: Image as float64 array, shape (H, W, 3), range [0, 1].

    Returns:
        TonalRolloff with curve characteristics and spline sample points.
    """
    luminance = 0.2126 * arr[:, :, 0] + 0.7152 * arr[:, :, 1] + 0.0722 * arr[:, :, 2]
    flat = luminance.ravel()

    # Histogram-based analysis (256 bins)
    hist, _bin_edges = np.histogram(flat, bins=256, range=(0.0, 1.0))
    hist_norm = hist.astype(np.float64) / hist.sum()

    # Shadow lift
    deep_shadow = hist_norm[:13].sum()
    near_shadow = hist_norm[13:38].sum()
    if deep_shadow > 0.001:
        shadow_lift = float(min(1.0, max(0.0, 1.0 - deep_shadow / max(near_shadow, 0.001))))
    else:
        shadow_lift = 0.8

    # Highlight compression
    bright_highlight = hist_norm[243:].sum()
    near_highlight = hist_norm[218:243].sum()
    if near_highlight > 0.001:
        highlight_compression = float(
            min(1.0, max(0.0, 1.0 - bright_highlight / max(near_highlight, 0.001)))
        )
    else:
        highlight_compression = 0.5

    # Midtone contrast
    p10 = float(np.percentile(flat, 10))
    p90 = float(np.percentile(flat, 90))
    p35 = float(np.percentile(flat, 35))
    p65 = float(np.percentile(flat, 65))
    total_range = max(p90 - p10, 0.01)
    mid_range = max(p65 - p35, 0.001)
    midtone_contrast = float((0.30 / mid_range) * (total_range / 0.80))

    # Build CDF-based tone curve using PCHIP monotone spline
    sorted_vals = np.sort(flat)
    n = len(sorted_vals)
    cdf_y = np.linspace(0.0, 1.0, n)

    # Subsample for fitting
    step = max(1, n // 500)
    x_sub = sorted_vals[::step]
    y_sub = cdf_y[::step]

    # Remove duplicate x values (PCHIP requires strictly increasing x)
    unique_mask = np.diff(x_sub, prepend=-1.0) > 1e-10
    x_unique = x_sub[unique_mask]
    y_unique = y_sub[unique_mask]

    # Fit PCHIP spline and sample at evenly spaced points
    curve_points: list[tuple[float, float]] = []
    coeffs: list[float] = []

    if len(x_unique) >= 4:
        try:
            pchip = PchipInterpolator(x_unique, y_unique)

            # Sample at TONE_CURVE_POINTS evenly spaced input values (0-255 scale)
            sample_inputs = np.linspace(0.0, 1.0, TONE_CURVE_POINTS)
            sample_outputs = pchip(sample_inputs)
            sample_outputs = np.clip(sample_outputs, 0.0, 1.0)

            curve_points = [
                (round(float(x) * 255.0, 1), round(float(y) * 255.0, 1))
                for x, y in zip(sample_inputs, sample_outputs, strict=True)
            ]
        except ValueError:
            pass

        # Also keep polynomial coefficients for backward compatibility
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RankWarning)
            coeffs_arr = np.polyfit(x_unique, y_unique, POLY_DEGREE)
            coeffs = [float(c) for c in coeffs_arr]

    return TonalRolloff(
        shadow_lift=round(shadow_lift, 4),
        highlight_compression=round(highlight_compression, 4),
        midtone_contrast=round(midtone_contrast, 3),
        curve_coefficients=coeffs,
        curve_points=curve_points,
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
        peak_frequency=float(np.median([p.peak_frequency for p in profiles])),
        spectral_slope=float(np.median([p.spectral_slope for p in profiles])),
        spectral_centroid=float(np.median([p.spectral_centroid for p in profiles])),
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
    if coeff_arrays and all(coeff_arrays):
        max_len = max(len(c) for c in coeff_arrays)
        padded = [c + [0.0] * (max_len - len(c)) for c in coeff_arrays]
        median_coeffs = [float(np.median([p[i] for p in padded])) for i in range(max_len)]
    else:
        median_coeffs = []

    # Median of curve points
    point_arrays = [r.curve_points for r in rolloffs if r.curve_points]
    median_points: list[tuple[float, float]] = []
    if point_arrays:
        min_len = min(len(p) for p in point_arrays)
        for i in range(min_len):
            x_vals = [p[i][0] for p in point_arrays]
            y_vals = [p[i][1] for p in point_arrays]
            median_points.append((float(np.median(x_vals)), float(np.median(y_vals))))

    return TonalRolloff(
        shadow_lift=float(np.median([r.shadow_lift for r in rolloffs])),
        highlight_compression=float(np.median([r.highlight_compression for r in rolloffs])),
        midtone_contrast=float(np.median([r.midtone_contrast for r in rolloffs])),
        curve_coefficients=median_coeffs,
        curve_points=median_points,
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
    intensities = [g.mean_intensity for g in grains]
    if len(intensities) < 4:
        return 0.5

    q1 = float(np.percentile(intensities, 25))
    q3 = float(np.percentile(intensities, 75))
    iqr = q3 - q1

    if q1 + q3 < 1e-10:
        return 0.5

    cqd = iqr / max(q1 + q3, 0.001)

    mid_r = [c.midtones[0] for c in colors]
    mid_b = [c.midtones[2] for c in colors]
    color_std = float(np.std(mid_r) + np.std(mid_b))

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
    if fp.scanner_model:
        table.add_row("Scanner", fp.scanner_model)
    table.add_row("", "")
    table.add_row("Grain Intensity", f"{fp.grain.mean_intensity:.4f}")
    table.add_row("Grain Size", f"{fp.grain.size_estimate:.2f} px")
    table.add_row("Grain Clumping", f"{fp.grain.clumping_factor:.3f}")
    if fp.grain.peak_frequency > 0:
        table.add_row("Peak Frequency", f"{fp.grain.peak_frequency:.4f} cy/px")
        table.add_row("Spectral Slope", f"{fp.grain.spectral_slope:.3f}")
    table.add_row("", "")
    table.add_row("Shadow Lift", f"{fp.tone.shadow_lift:.4f}")
    table.add_row("Highlight Compression", f"{fp.tone.highlight_compression:.4f}")
    table.add_row("Midtone Contrast", f"{fp.tone.midtone_contrast:.3f}")
    if fp.tone.curve_points:
        table.add_row("Tone Curve", f"{len(fp.tone.curve_points)}-point spline")
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
