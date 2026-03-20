"""Analysis tools for NegClone: fingerprint comparison and report generation."""

import math
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from negclone.models import StockFingerprint

console = Console()


def compare_fingerprints(
    fp_a: StockFingerprint,
    fp_b: StockFingerprint,
) -> dict[str, Any]:
    """Compare two fingerprints and return a structured diff.

    Args:
        fp_a: First fingerprint.
        fp_b: Second fingerprint.

    Returns:
        Dict with grain, color, tonal differences, and an overall
        similarity score between 0 (completely different) and 1 (identical).
    """
    # Grain differences
    grain_diff = {
        "intensity": fp_b.grain.mean_intensity - fp_a.grain.mean_intensity,
        "size": fp_b.grain.size_estimate - fp_a.grain.size_estimate,
        "clumping": fp_b.grain.clumping_factor - fp_a.grain.clumping_factor,
    }

    # Color differences per region
    color_diff: dict[str, dict[str, float]] = {}
    for region in ("shadows", "midtones", "highlights"):
        a_vals: tuple[float, float, float] = getattr(fp_a.color, region)
        b_vals: tuple[float, float, float] = getattr(fp_b.color, region)
        color_diff[region] = {
            "r": b_vals[0] - a_vals[0],
            "g": b_vals[1] - a_vals[1],
            "b": b_vals[2] - a_vals[2],
        }

    # Tonal differences
    tonal_diff = {
        "shadow_lift": fp_b.tone.shadow_lift - fp_a.tone.shadow_lift,
        "highlight_compression": (
            fp_b.tone.highlight_compression - fp_a.tone.highlight_compression
        ),
        "midtone_contrast": fp_b.tone.midtone_contrast - fp_a.tone.midtone_contrast,
    }

    # Overall similarity score (1 = identical, 0 = maximally different)
    similarity = _compute_similarity(fp_a, fp_b)

    return {
        "stock_a": fp_a.stock,
        "stock_b": fp_b.stock,
        "grain": grain_diff,
        "color": color_diff,
        "tone": tonal_diff,
        "similarity": similarity,
    }


def _compute_similarity(
    fp_a: StockFingerprint,
    fp_b: StockFingerprint,
) -> float:
    """Compute a 0-1 similarity score between two fingerprints.

    Uses weighted Euclidean distance across normalized feature dimensions,
    mapped to [0, 1] via an exponential decay.

    Args:
        fp_a: First fingerprint.
        fp_b: Second fingerprint.

    Returns:
        Similarity score between 0 and 1.
    """
    diffs: list[float] = []

    # Grain (normalize to typical ranges)
    diffs.append((fp_a.grain.mean_intensity - fp_b.grain.mean_intensity) / 0.05)
    diffs.append((fp_a.grain.size_estimate - fp_b.grain.size_estimate) / 2.0)
    diffs.append((fp_a.grain.clumping_factor - fp_b.grain.clumping_factor) / 0.5)

    # Color bias (all regions, each channel)
    for region in ("shadows", "midtones", "highlights"):
        a_vals: tuple[float, float, float] = getattr(fp_a.color, region)
        b_vals: tuple[float, float, float] = getattr(fp_b.color, region)
        for i in range(3):
            diffs.append((a_vals[i] - b_vals[i]) / 0.02)

    # Tonal
    diffs.append((fp_a.tone.shadow_lift - fp_b.tone.shadow_lift) / 0.3)
    diffs.append((fp_a.tone.highlight_compression - fp_b.tone.highlight_compression) / 0.3)
    diffs.append((fp_a.tone.midtone_contrast - fp_b.tone.midtone_contrast) / 0.5)

    # RMS distance mapped through exponential decay
    rms = math.sqrt(sum(d * d for d in diffs) / len(diffs))
    similarity = math.exp(-rms * 0.8)
    return round(max(0.0, min(1.0, similarity)), 4)


def _delta_style(value: float, threshold_small: float = 0.01, threshold_large: float = 0.05) -> str:
    """Return a Rich style string based on the magnitude of a delta.

    Args:
        value: The delta value.
        threshold_small: Below this magnitude, the delta is small (green).
        threshold_large: Above this magnitude, the delta is large (red).

    Returns:
        Rich style string: "green", "yellow", or "red".
    """
    mag = abs(value)
    if mag < threshold_small:
        return "green"
    if mag < threshold_large:
        return "yellow"
    return "red"


def print_comparison(
    fp_a: StockFingerprint,
    fp_b: StockFingerprint,
) -> None:
    """Print a Rich table comparing two fingerprints side-by-side.

    Columns: Property | Stock A | Stock B | Delta.
    Deltas are color-coded green (small), yellow (moderate), red (large).

    Args:
        fp_a: First fingerprint.
        fp_b: Second fingerprint.
    """
    diff = compare_fingerprints(fp_a, fp_b)

    table = Table(title=f"{fp_a.stock} vs {fp_b.stock}")
    table.add_column("Property", style="bold")
    table.add_column(fp_a.stock, justify="right")
    table.add_column(fp_b.stock, justify="right")
    table.add_column("Delta", justify="right")

    # --- Grain section ---
    table.add_row("[bold underline]Grain[/bold underline]", "", "", "")

    grain_rows: list[tuple[str, str, str, float, float, float]] = [
        (
            "Intensity",
            f"{fp_a.grain.mean_intensity:.4f}",
            f"{fp_b.grain.mean_intensity:.4f}",
            diff["grain"]["intensity"],
            0.005,
            0.02,
        ),
        (
            "Size (px)",
            f"{fp_a.grain.size_estimate:.2f}",
            f"{fp_b.grain.size_estimate:.2f}",
            diff["grain"]["size"],
            0.3,
            1.0,
        ),
        (
            "Clumping",
            f"{fp_a.grain.clumping_factor:.3f}",
            f"{fp_b.grain.clumping_factor:.3f}",
            diff["grain"]["clumping"],
            0.05,
            0.15,
        ),
    ]
    for label, val_a, val_b, delta, t_small, t_large in grain_rows:
        style = _delta_style(delta, t_small, t_large)
        table.add_row(f"  {label}", val_a, val_b, Text(f"{delta:+.4f}", style=style))

    # --- Color section ---
    table.add_row("[bold underline]Color Bias[/bold underline]", "", "", "")

    for region in ("shadows", "midtones", "highlights"):
        a_vals: tuple[float, float, float] = getattr(fp_a.color, region)
        b_vals: tuple[float, float, float] = getattr(fp_b.color, region)
        region_diff = diff["color"][region]
        for ch, ch_name in enumerate(("R", "G", "B")):
            delta = region_diff[ch_name.lower()]
            style = _delta_style(delta, 0.005, 0.02)
            table.add_row(
                f"  {region.capitalize()} {ch_name}",
                f"{a_vals[ch]:+.4f}",
                f"{b_vals[ch]:+.4f}",
                Text(f"{delta:+.4f}", style=style),
            )

    # --- Tonal section ---
    table.add_row("[bold underline]Tone[/bold underline]", "", "", "")

    tonal_rows: list[tuple[str, str, str, float, float, float]] = [
        (
            "Shadow Lift",
            f"{fp_a.tone.shadow_lift:.4f}",
            f"{fp_b.tone.shadow_lift:.4f}",
            diff["tone"]["shadow_lift"],
            0.05,
            0.15,
        ),
        (
            "Highlight Compression",
            f"{fp_a.tone.highlight_compression:.4f}",
            f"{fp_b.tone.highlight_compression:.4f}",
            diff["tone"]["highlight_compression"],
            0.05,
            0.15,
        ),
        (
            "Midtone Contrast",
            f"{fp_a.tone.midtone_contrast:.3f}",
            f"{fp_b.tone.midtone_contrast:.3f}",
            diff["tone"]["midtone_contrast"],
            0.1,
            0.3,
        ),
    ]
    for label, val_a, val_b, delta, t_small, t_large in tonal_rows:
        style = _delta_style(delta, t_small, t_large)
        table.add_row(f"  {label}", val_a, val_b, Text(f"{delta:+.4f}", style=style))

    # --- Similarity ---
    sim = diff["similarity"]
    sim_style = "green" if sim > 0.8 else ("yellow" if sim > 0.5 else "red")
    table.add_row("", "", "", "")
    table.add_row(
        "[bold]Similarity[/bold]",
        "",
        "",
        Text(f"{sim:.1%}", style=f"bold {sim_style}"),
    )

    panel = Panel(table, title="[bold cyan]Fingerprint Comparison[/bold cyan]")
    console.print(panel)


def _color_bias_to_hex(bias: tuple[float, float, float]) -> str:
    """Convert a color bias shift to an approximate display hex color.

    Bias values are shifts from neutral gray, so we center them on mid-gray
    (128) and scale to produce a visible swatch.

    Args:
        bias: R, G, B shift values (typically small floats like -0.02 to +0.02).

    Returns:
        Hex color string like "#8a7e82".
    """
    base = 128
    scale = 800  # Amplify small shifts for visibility
    r = max(0, min(255, int(base + bias[0] * scale)))
    g = max(0, min(255, int(base + bias[1] * scale)))
    b = max(0, min(255, int(base + bias[2] * scale)))
    return f"#{r:02x}{g:02x}{b:02x}"


def generate_report(
    fingerprints: list[StockFingerprint],
    output_path: Path,
) -> None:
    """Generate an HTML report showing all fingerprints and comparisons.

    Produces a self-contained HTML file with inline CSS. Includes a card per
    stock with grain/color/tone data, color swatches, and a comparison matrix
    showing pairwise similarity scores.

    Args:
        fingerprints: List of fingerprints to include.
        output_path: Path to write the HTML file.

    Raises:
        ValueError: If fingerprints list is empty.
    """
    if not fingerprints:
        raise ValueError("Cannot generate report from an empty fingerprint list.")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Pre-compute similarity matrix
    n = len(fingerprints)
    sim_matrix: list[list[float]] = []
    for i in range(n):
        row: list[float] = []
        for j in range(n):
            if i == j:
                row.append(1.0)
            else:
                diff = compare_fingerprints(fingerprints[i], fingerprints[j])
                row.append(diff["similarity"])
        sim_matrix.append(row)

    # Build HTML
    cards_html = "\n".join(_render_stock_card(fp) for fp in fingerprints)
    matrix_html = _render_similarity_matrix(fingerprints, sim_matrix)

    html = f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NegClone Fingerprint Report</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #f5f5f5; color: #222; margin: 0; padding: 2rem;
    line-height: 1.5;
  }}
  h1 {{ text-align: center; margin-bottom: 0.25rem; color: #111; }}
  .subtitle {{ text-align: center; color: #888; font-size: 0.9rem; margin-bottom: 2rem; }}
  .cards {{ display: flex; flex-wrap: wrap; gap: 1.5rem; justify-content: center;
    margin-bottom: 3rem; }}
  .card {{
    background: #fff; border-radius: 8px; box-shadow: 0 1px 4px rgba(0,0,0,0.1);
    padding: 1.5rem; width: 340px;
  }}
  .card h2 {{ margin: 0 0 0.75rem 0; font-size: 1.2rem; color: #333; }}
  .card table {{ width: 100%; font-size: 0.85rem; border-collapse: collapse; }}
  .card td {{ padding: 0.2rem 0.4rem; }}
  .card td:first-child {{ color: #666; }}
  .card td:last-child {{ text-align: right; font-family: monospace; }}
  .section-label {{ font-weight: 600; color: #444; padding-top: 0.5rem !important; }}
  .swatches {{ display: flex; gap: 0.5rem; margin-top: 0.75rem; }}
  .swatch {{
    flex: 1; height: 32px; border-radius: 4px; border: 1px solid #ddd;
    display: flex; align-items: center; justify-content: center;
    font-size: 0.65rem; color: #fff; text-shadow: 0 1px 2px rgba(0,0,0,0.5);
  }}
  .matrix-section {{ max-width: 900px; margin: 0 auto; }}
  .matrix-section h2 {{ text-align: center; margin-bottom: 1rem; }}
  .matrix-table {{
    width: 100%; border-collapse: collapse; font-size: 0.85rem;
    background: #fff; border-radius: 8px; overflow: hidden;
    box-shadow: 0 1px 4px rgba(0,0,0,0.1);
  }}
  .matrix-table th, .matrix-table td {{
    padding: 0.5rem 0.75rem; text-align: center; border: 1px solid #eee;
  }}
  .matrix-table th {{ background: #fafafa; font-weight: 600; color: #444; }}
  .sim-high {{ background: #d4edda; }}
  .sim-med {{ background: #fff3cd; }}
  .sim-low {{ background: #f8d7da; }}
  .meta {{ font-size: 0.75rem; color: #aaa; }}
</style>
</head>
<body>
<h1>NegClone Fingerprint Report</h1>
<p class="subtitle">Generated {now} &middot; {n} stock{"s" if n != 1 else ""}</p>

<div class="cards">
{cards_html}
</div>

{matrix_html}

<p class="subtitle meta">Report generated by NegClone</p>
</body>
</html>
"""

    output_path.write_text(html, encoding="utf-8")
    console.print(f"[green]Report written to {output_path}[/green]")


def _render_stock_card(fp: StockFingerprint) -> str:
    """Render a single stock fingerprint as an HTML card.

    Args:
        fp: StockFingerprint to render.

    Returns:
        HTML string for the card.
    """
    shadow_hex = _color_bias_to_hex(fp.color.shadows)
    midtone_hex = _color_bias_to_hex(fp.color.midtones)
    highlight_hex = _color_bias_to_hex(fp.color.highlights)

    def _fmt_rgb(vals: tuple[float, float, float]) -> str:
        return f"R:{vals[0]:+.4f} G:{vals[1]:+.4f} B:{vals[2]:+.4f}"

    return f"""\
<div class="card">
  <h2>{fp.stock}</h2>
  <table>
    <tr><td class="section-label" colspan="2">Grain</td></tr>
    <tr><td>Intensity</td><td>{fp.grain.mean_intensity:.4f}</td></tr>
    <tr><td>Size</td><td>{fp.grain.size_estimate:.2f} px</td></tr>
    <tr><td>Clumping</td><td>{fp.grain.clumping_factor:.3f}</td></tr>
    <tr><td class="section-label" colspan="2">Color Bias</td></tr>
    <tr><td>Shadows</td><td>{_fmt_rgb(fp.color.shadows)}</td></tr>
    <tr><td>Midtones</td><td>{_fmt_rgb(fp.color.midtones)}</td></tr>
    <tr><td>Highlights</td><td>{_fmt_rgb(fp.color.highlights)}</td></tr>
    <tr><td class="section-label" colspan="2">Tone</td></tr>
    <tr><td>Shadow Lift</td><td>{fp.tone.shadow_lift:.4f}</td></tr>
    <tr><td>Highlight Comp.</td><td>{fp.tone.highlight_compression:.4f}</td></tr>
    <tr><td>Midtone Contrast</td><td>{fp.tone.midtone_contrast:.3f}</td></tr>
    <tr><td class="section-label" colspan="2">Meta</td></tr>
    <tr><td>Samples</td><td>{fp.sample_count}</td></tr>
    <tr><td>Confidence</td><td>{fp.confidence:.1%}</td></tr>
  </table>
  <div class="swatches">
    <div class="swatch" style="background:{shadow_hex}">Shadows</div>
    <div class="swatch" style="background:{midtone_hex}">Midtones</div>
    <div class="swatch" style="background:{highlight_hex}">Highlights</div>
  </div>
</div>"""


def _render_similarity_matrix(
    fingerprints: list[StockFingerprint],
    sim_matrix: list[list[float]],
) -> str:
    """Render the pairwise similarity matrix as an HTML table.

    Args:
        fingerprints: List of fingerprints (for stock names).
        sim_matrix: Pre-computed NxN similarity scores.

    Returns:
        HTML string for the matrix section.
    """
    n = len(fingerprints)
    if n < 2:
        return ""

    header_cells = "".join(f"<th>{fp.stock}</th>" for fp in fingerprints)
    rows: list[str] = []
    for i in range(n):
        cells: list[str] = []
        for j in range(n):
            score = sim_matrix[i][j]
            if i == j or score > 0.7:
                css_class = "sim-high"
            elif score > 0.4:
                css_class = "sim-med"
            else:
                css_class = "sim-low"
            cells.append(f'<td class="{css_class}">{score:.1%}</td>')
        rows.append(f"<tr><th>{fingerprints[i].stock}</th>{''.join(cells)}</tr>")

    return f"""\
<div class="matrix-section">
  <h2>Similarity Matrix</h2>
  <table class="matrix-table">
    <tr><th></th>{header_cells}</tr>
    {"".join(rows)}
  </table>
</div>"""
