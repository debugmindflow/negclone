"""Lightroom/ACR .xmp preset generator."""

import xml.etree.ElementTree as ET
from pathlib import Path

from negclone.models import StockFingerprint

# XMP namespace URIs
NS_X = "adobe:ns:meta/"
NS_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
NS_CRS = "http://ns.adobe.com/camera-raw-settings/1.0/"

# Grain mapping constants
GRAIN_AMOUNT_SCALE: float = 300.0  # Max grain amount in ACR
GRAIN_SIZE_MIN: int = 10
GRAIN_SIZE_MAX: int = 100
GRAIN_FREQUENCY_MIN: int = 0
GRAIN_FREQUENCY_MAX: int = 100

# Color grade mapping scale
COLOR_GRADE_SCALE: float = 100.0
COLOR_GRADE_LUM_SCALE: float = 50.0


def generate_xmp(fingerprint: StockFingerprint, output_dir: Path) -> Path:
    """Generate a Lightroom/ACR .xmp preset file from a fingerprint.

    Args:
        fingerprint: StockFingerprint with analysis data.
        output_dir: Directory to write the .xmp file.

    Returns:
        Path to the generated .xmp file.
    """
    # Register namespaces to avoid ns0/ns1 prefixes
    ET.register_namespace("x", NS_X)
    ET.register_namespace("rdf", NS_RDF)
    ET.register_namespace("crs", NS_CRS)

    # Build XMP structure
    xmpmeta = ET.Element(f"{{{NS_X}}}xmpmeta")
    xmpmeta.set(f"{{{NS_X}}}xmptk", "Adobe XMP Core")

    rdf = ET.SubElement(xmpmeta, f"{{{NS_RDF}}}RDF")
    desc = ET.SubElement(rdf, f"{{{NS_RDF}}}Description")

    # Process version
    desc.set(f"{{{NS_CRS}}}ProcessVersion", "11.0")
    desc.set(f"{{{NS_CRS}}}PresetType", "Normal")

    # Grain params
    grain_amount = _map_grain_amount(fingerprint.grain.mean_intensity)
    grain_size = _map_grain_size(fingerprint.grain.size_estimate)
    grain_freq = _map_grain_frequency(fingerprint.grain.clumping_factor)

    desc.set(f"{{{NS_CRS}}}GrainAmount", str(grain_amount))
    desc.set(f"{{{NS_CRS}}}GrainSize", str(grain_size))
    desc.set(f"{{{NS_CRS}}}GrainFrequency", str(grain_freq))

    # Tone curve from tonal rolloff
    _add_tone_curve(desc, fingerprint)

    # Color grading from color bias
    _add_color_grading(desc, fingerprint)

    # Shadow tint from color bias
    shadow_tint = _compute_shadow_tint(fingerprint)
    desc.set(f"{{{NS_CRS}}}ShadowTint", str(shadow_tint))

    # Write XMP
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{fingerprint.stock}.xmp"

    tree = ET.ElementTree(xmpmeta)
    ET.indent(tree, space="  ")

    with open(output_path, "wb") as f:
        f.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
        tree.write(f, encoding="unicode" if False else "UTF-8", xml_declaration=False)
        f.write(b"\n")

    return output_path


def _add_tone_curve(desc: ET.Element, fp: StockFingerprint) -> None:
    """Add tone curve settings to the XMP description.

    Args:
        desc: RDF Description element.
        fp: StockFingerprint.
    """
    # Build a simple 5-point tone curve from the rolloff data
    # Points are (input, output) pairs, 0-255
    shadow_lift_val = int(fp.tone.shadow_lift * 255)
    highlight_comp = int(fp.tone.highlight_compression * 255)

    # Tone curve points: shadows lifted, highlights compressed
    points = [
        "0, " + str(min(255, shadow_lift_val)),
        "64, " + str(min(255, 64 + shadow_lift_val // 2)),
        "128, 128",
        "192, " + str(max(0, 192 - highlight_comp // 2)),
        "255, " + str(max(0, 255 - highlight_comp)),
    ]

    tone_curve = ET.SubElement(desc, f"{{{NS_CRS}}}ToneCurvePV2012")
    seq = ET.SubElement(tone_curve, f"{{{NS_RDF}}}Seq")
    for point in points:
        li = ET.SubElement(seq, f"{{{NS_RDF}}}li")
        li.text = point

    # Also set parametric tone curve values
    contrast_bump = int((fp.tone.midtone_contrast - 1.0) * 30)
    desc.set(f"{{{NS_CRS}}}Contrast2012", str(max(-100, min(100, contrast_bump))))


def _add_color_grading(desc: ET.Element, fp: StockFingerprint) -> None:
    """Add color grading settings to the XMP description.

    Args:
        desc: RDF Description element.
        fp: StockFingerprint.
    """
    sr, sg, sb = fp.color.shadows
    mr, mg, mb = fp.color.midtones
    hr, hg, hb = fp.color.highlights

    # Convert RGB shifts to hue/saturation for ACR color grading
    # Shadow color grade
    s_hue, s_sat = _rgb_shift_to_hue_sat(sr, sg, sb)
    desc.set(f"{{{NS_CRS}}}ColorGradeShadowHue", str(s_hue))
    desc.set(f"{{{NS_CRS}}}ColorGradeShadowSat", str(s_sat))
    desc.set(f"{{{NS_CRS}}}ColorGradeShadowLum", "0")

    # Midtone color grade
    m_hue, m_sat = _rgb_shift_to_hue_sat(mr, mg, mb)
    desc.set(f"{{{NS_CRS}}}ColorGradeMidtoneHue", str(m_hue))
    desc.set(f"{{{NS_CRS}}}ColorGradeMidtoneSat", str(m_sat))
    desc.set(f"{{{NS_CRS}}}ColorGradeMidtoneLum", "0")

    # Highlight color grade
    h_hue, h_sat = _rgb_shift_to_hue_sat(hr, hg, hb)
    desc.set(f"{{{NS_CRS}}}ColorGradeHighlightHue", str(h_hue))
    desc.set(f"{{{NS_CRS}}}ColorGradeHighlightSat", str(h_sat))
    desc.set(f"{{{NS_CRS}}}ColorGradeHighlightLum", "0")


def _rgb_shift_to_hue_sat(r: float, g: float, b: float) -> tuple[int, int]:
    """Convert RGB shift values to hue (0-360) and saturation (0-100).

    Args:
        r: Red channel shift.
        g: Green channel shift.
        b: Blue channel shift.

    Returns:
        Tuple of (hue, saturation).
    """
    import math

    magnitude = math.sqrt(r * r + g * g + b * b)
    if magnitude < 0.001:
        return (0, 0)

    # Normalize
    rn, gn, bn = r / magnitude, g / magnitude, b / magnitude

    # Simple hue calculation from dominant channel
    if rn >= gn and rn >= bn:
        hue = int(60 * gn / max(rn, 0.001)) if gn > bn else int(360 - 60 * bn / max(rn, 0.001))
    elif gn >= rn and gn >= bn:
        hue = (
            int(120 - 60 * rn / max(gn, 0.001)) if rn > bn else int(120 + 60 * bn / max(gn, 0.001))
        )
    else:
        hue = (
            int(240 - 60 * gn / max(bn, 0.001)) if gn > rn else int(240 + 60 * rn / max(bn, 0.001))
        )

    hue = hue % 360
    saturation = int(min(100, magnitude * COLOR_GRADE_SCALE))

    return (hue, saturation)


def _map_grain_amount(mean_intensity: float) -> int:
    """Map fingerprint grain intensity to ACR GrainAmount (0-100).

    Args:
        mean_intensity: Grain mean intensity from fingerprint.

    Returns:
        ACR grain amount value.
    """
    return int(min(100, max(0, mean_intensity * GRAIN_AMOUNT_SCALE)))


def _map_grain_size(size_estimate: float) -> int:
    """Map fingerprint grain size to ACR GrainSize (10-100).

    Args:
        size_estimate: Grain size estimate in pixels.

    Returns:
        ACR grain size value.
    """
    # Size 1-5 px maps to 10-100
    mapped = GRAIN_SIZE_MIN + (size_estimate - 1.0) / 4.0 * (GRAIN_SIZE_MAX - GRAIN_SIZE_MIN)
    return int(min(GRAIN_SIZE_MAX, max(GRAIN_SIZE_MIN, mapped)))


def _map_grain_frequency(clumping_factor: float) -> int:
    """Map fingerprint clumping to ACR GrainFrequency (0-100).

    Args:
        clumping_factor: Grain clumping factor (0-1).

    Returns:
        ACR grain frequency value.
    """
    # Higher clumping = lower frequency (larger grain clusters)
    return int(max(0, min(100, (1.0 - clumping_factor) * 100)))


def _compute_shadow_tint(fp: StockFingerprint) -> int:
    """Compute shadow tint value from color bias.

    Args:
        fp: StockFingerprint.

    Returns:
        Shadow tint value (-100 to 100, positive = magenta, negative = green).
    """
    sr, sg, sb = fp.color.shadows
    # Magenta-green axis: positive = magenta (more red+blue), negative = green
    tint = (sr + sb - 2 * sg) * 200
    return int(max(-100, min(100, tint)))
