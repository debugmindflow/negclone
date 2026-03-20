"""Darktable .dtstyle XML preset generator."""

import base64
import struct
import xml.etree.ElementTree as ET
from pathlib import Path

from negclone.models import StockFingerprint

# Darktable module version constants
GRAIN_MODULE_VERSION: int = 1
FILMIC_MODULE_VERSION: int = 6
COLORBALANCE_MODULE_VERSION: int = 3

# Default grain params struct (darktable grain module)
# Format: channel, strength, scale (3 floats)
GRAIN_PARAM_FORMAT: str = "<iff"

# Filmic RGB base params — these are approximations using documented offsets
# In v2, this should use proper C struct encoding
FILMIC_PARAM_FORMAT: str = "<" + "f" * 20


def generate_dtstyle(fingerprint: StockFingerprint, output_dir: Path) -> Path:
    """Generate a Darktable .dtstyle XML file from a fingerprint.

    Args:
        fingerprint: StockFingerprint with analysis data.
        output_dir: Directory to write the .dtstyle file.

    Returns:
        Path to the generated .dtstyle file.
    """
    root = ET.Element("darktable_style")

    # Info section
    info = ET.SubElement(root, "info")
    _add_text_element(info, "name", f"{_format_stock_name(fingerprint.stock)} — Desert Paul")
    _add_text_element(
        info,
        "description",
        f"Fingerprinted from {fingerprint.sample_count} real "
        f"{_format_stock_name(fingerprint.stock)} scans "
        f"(confidence: {fingerprint.confidence:.0%})",
    )
    _add_text_element(info, "author", "Desert Paul")
    _add_text_element(info, "version", "1")

    # Style section with modules
    style = ET.SubElement(root, "style")

    # Grain module
    _add_grain_plugin(style, fingerprint, plugin_num=1)

    # Filmic RGB module
    _add_filmic_plugin(style, fingerprint, plugin_num=2)

    # Color Balance RGB module
    _add_colorbalance_plugin(style, fingerprint, plugin_num=3)

    # Write XML
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{fingerprint.stock}.dtstyle"

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")

    with open(output_path, "wb") as f:
        tree.write(f, encoding="UTF-8", xml_declaration=True)
        f.write(b"\n")

    return output_path


def _add_text_element(parent: ET.Element, tag: str, text: str) -> ET.Element:
    """Add a text child element.

    Args:
        parent: Parent XML element.
        tag: Element tag name.
        text: Text content.

    Returns:
        The created element.
    """
    elem = ET.SubElement(parent, tag)
    elem.text = text
    return elem


def _add_plugin(
    style: ET.Element,
    num: int,
    module: str,
    params_b64: str,
    enabled: int = 1,
) -> ET.Element:
    """Add a plugin element to the style.

    Args:
        style: Parent style element.
        num: Plugin number.
        module: Module name.
        params_b64: Base64-encoded params.
        enabled: Whether module is enabled (1/0).

    Returns:
        The created plugin element.
    """
    plugin = ET.SubElement(style, "plugin")
    _add_text_element(plugin, "num", str(num))
    _add_text_element(plugin, "module", module)
    _add_text_element(plugin, "enabled", str(enabled))
    _add_text_element(plugin, "params", params_b64)
    multi_name = ET.SubElement(plugin, "multi_name")
    multi_name.text = ""
    _add_text_element(plugin, "multi_priority", "0")
    return plugin


def _add_grain_plugin(
    style: ET.Element,
    fp: StockFingerprint,
    plugin_num: int,
) -> None:
    """Add grain module plugin.

    Args:
        style: Parent style element.
        fp: StockFingerprint.
        plugin_num: Plugin number.
    """
    # Map fingerprint grain values to darktable grain params
    # Channel: 0 = all, strength: 0-100, scale: 100-6400
    channel = 0
    strength = _map_grain_strength(fp.grain.mean_intensity)
    scale = _map_grain_size(fp.grain.size_estimate)

    params = struct.pack(GRAIN_PARAM_FORMAT, channel, strength, scale)
    params_b64 = base64.b64encode(params).decode("ascii")

    _add_plugin(style, plugin_num, "grain", params_b64)


def _add_filmic_plugin(
    style: ET.Element,
    fp: StockFingerprint,
    plugin_num: int,
) -> None:
    """Add filmic RGB module plugin.

    Note: This uses approximated params. Exact binary encoding is a v2 feature.

    Args:
        style: Parent style element.
        fp: StockFingerprint.
        plugin_num: Plugin number.
    """
    # Map tonal rolloff to filmic params (approximated)
    # These are the first 20 float fields of the filmic RGB params struct
    white_point = 4.0 - fp.tone.highlight_compression * 2.0
    black_point = -8.0 + fp.tone.shadow_lift * 4.0
    contrast = fp.tone.midtone_contrast
    latitude = 0.5
    balance = 0.0
    saturation = 100.0

    # Pad remaining fields with sensible defaults
    params_values = [
        white_point,  # white_point_source
        black_point,  # black_point_source
        contrast,  # contrast
        latitude,  # latitude
        balance,  # balance
        saturation,  # saturation
        0.0,
        0.0,
        0.0,
        0.0,  # reserved/padding
        1.0,
        1.0,
        1.0,
        1.0,  # spline control points
        0.0,
        0.0,
        0.0,
        0.0,  # more spline
        0.0,
        0.0,  # final padding
    ]

    params = struct.pack(FILMIC_PARAM_FORMAT, *params_values)
    params_b64 = base64.b64encode(params).decode("ascii")

    _add_plugin(style, plugin_num, "filmicrgb", params_b64)


def _add_colorbalance_plugin(
    style: ET.Element,
    fp: StockFingerprint,
    plugin_num: int,
) -> None:
    """Add color balance RGB module plugin.

    Note: This uses approximated params. Exact binary encoding is a v2 feature.

    Args:
        style: Parent style element.
        fp: StockFingerprint.
        plugin_num: Plugin number.
    """
    # Map color bias to color balance params
    # Scale the small floating point shifts to the darktable param range
    scale = 50.0  # Amplify normalized shifts to darktable's expected range

    sr, sg, sb = fp.color.shadows
    mr, mg, mb = fp.color.midtones
    hr, hg, hb = fp.color.highlights

    params_values = [
        sr * scale,
        sg * scale,
        sb * scale,
        0.0,  # shadow RGBA
        mr * scale,
        mg * scale,
        mb * scale,
        0.0,  # midtone RGBA
        hr * scale,
        hg * scale,
        hb * scale,
        0.0,  # highlight RGBA
    ]
    params_format = "<" + "f" * 12
    params = struct.pack(params_format, *params_values)
    params_b64 = base64.b64encode(params).decode("ascii")

    _add_plugin(style, plugin_num, "colorbalancergb", params_b64)


def _map_grain_strength(mean_intensity: float) -> float:
    """Map fingerprint grain intensity to darktable strength (0-100).

    Args:
        mean_intensity: Grain mean intensity from fingerprint.

    Returns:
        Darktable grain strength value.
    """
    # Typical scan grain intensity is 0.01-0.15
    # Map to 0-100 darktable range
    return min(100.0, max(0.0, mean_intensity * 500.0))


def _map_grain_size(size_estimate: float) -> float:
    """Map fingerprint grain size to darktable scale (100-6400).

    Args:
        size_estimate: Grain size estimate in pixels.

    Returns:
        Darktable grain scale value.
    """
    # Size estimate is typically 1-5 pixels
    # Map to darktable's 100-6400 range
    return min(6400.0, max(100.0, size_estimate * 800.0))


def _format_stock_name(stock: str) -> str:
    """Format a stock name for display.

    Args:
        stock: Lowercase stock identifier.

    Returns:
        Human-readable stock name.
    """
    name_map: dict[str, str] = {
        "portra160": "Portra 160",
        "portra400": "Portra 400",
        "portra800": "Portra 800",
        "ektar100": "Ektar 100",
        "gold200": "Gold 200",
        "hp5": "HP5 Plus",
        "delta100": "Delta 100",
        "tri-x": "Tri-X 400",
        "fomapan100": "Fomapan 100",
        "cinestill800t": "CineStill 800T",
    }
    return name_map.get(stock, stock.title())
