"""Scanner model detection and color bias compensation.

Detects scanner models from EXIF data and provides per-scanner color bias
compensation so that generated fingerprints reflect the film stock rather
than the scanner's inherent color signature.
"""

import re
from pathlib import Path

from PIL import Image
from PIL.ExifTags import Base as ExifBase
from pydantic import BaseModel

from negclone.models import ColorBias

# EXIF tag IDs used for scanner identification.
_TAG_MODEL: int = ExifBase.Model  # 0x0110
_TAG_SOFTWARE: int = ExifBase.Software  # 0x0131
_TAG_IMAGE_DESCRIPTION: int = ExifBase.ImageDescription  # 0x010E

# Patterns mapping regex -> canonical scanner identifier.
_SCANNER_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"epson.*perfection.*v850", re.IGNORECASE), "epson_v850"),
    (re.compile(r"epson.*perfection.*v700", re.IGNORECASE), "epson_v700"),
    (re.compile(r"epson.*perfection.*v600", re.IGNORECASE), "epson_v600"),
    (re.compile(r"epson.*v850", re.IGNORECASE), "epson_v850"),
    (re.compile(r"epson.*v700", re.IGNORECASE), "epson_v700"),
    (re.compile(r"epson.*v600", re.IGNORECASE), "epson_v600"),
    (re.compile(r"noritsu", re.IGNORECASE), "noritsu"),
    (re.compile(r"frontier", re.IGNORECASE), "frontier"),
    (re.compile(r"fuji\s*frontier", re.IGNORECASE), "frontier"),
    (re.compile(r"sp[-\s]?3000", re.IGNORECASE), "frontier"),
    (re.compile(r"plustek.*8200", re.IGNORECASE), "plustek_8200i"),
    (re.compile(r"opticfilm\s*8200", re.IGNORECASE), "plustek_8200i"),
    (re.compile(r"pacific\s*image", re.IGNORECASE), "pacific_image"),
    (re.compile(r"primefilm", re.IGNORECASE), "pacific_image"),
]


class ScannerProfile(BaseModel):
    """Color bias compensation values for a specific scanner model.

    Each field is an (R, G, B) tuple representing the scanner's inherent
    color shift in that tonal region.  Subtracting these values from a
    measured ``ColorBias`` removes the scanner's contribution.

    Attributes:
        model: Human-readable scanner name.
        shadows: Scanner bias in the shadow region (R, G, B).
        midtones: Scanner bias in the midtone region (R, G, B).
        highlights: Scanner bias in the highlight region (R, G, B).
    """

    model: str
    shadows: tuple[float, float, float]
    midtones: tuple[float, float, float]
    highlights: tuple[float, float, float]


# ---------------------------------------------------------------------------
# Built-in scanner profiles
# ---------------------------------------------------------------------------
# Values are approximate compensation offsets measured from test targets.
# Positive means the scanner adds that color; compensation subtracts it.

SCANNER_PROFILES: dict[str, ScannerProfile] = {
    # Epson flatbeds — warm bias, slightly elevated red in shadows
    "epson_v600": ScannerProfile(
        model="Epson Perfection V600",
        shadows=(0.04, 0.01, -0.02),
        midtones=(0.03, 0.01, -0.01),
        highlights=(0.02, 0.00, -0.01),
    ),
    "epson_v700": ScannerProfile(
        model="Epson Perfection V700",
        shadows=(0.05, 0.02, -0.02),
        midtones=(0.03, 0.01, -0.01),
        highlights=(0.02, 0.01, -0.01),
    ),
    "epson_v850": ScannerProfile(
        model="Epson Perfection V850",
        shadows=(0.04, 0.01, -0.01),
        midtones=(0.02, 0.01, -0.01),
        highlights=(0.01, 0.00, 0.00),
    ),
    # Noritsu — neutral to slightly cool, minor green cast in midtones
    "noritsu": ScannerProfile(
        model="Noritsu",
        shadows=(-0.01, 0.01, 0.02),
        midtones=(0.00, 0.02, 0.01),
        highlights=(0.00, 0.01, 0.01),
    ),
    # Fuji Frontier — neutral-cool, slight blue push in highlights
    "frontier": ScannerProfile(
        model="Fuji Frontier",
        shadows=(-0.01, 0.00, 0.02),
        midtones=(0.00, 0.01, 0.02),
        highlights=(-0.01, 0.00, 0.03),
    ),
    # Plustek OpticFilm 8200i — slightly warm, low bias overall
    "plustek_8200i": ScannerProfile(
        model="Plustek OpticFilm 8200i",
        shadows=(0.02, 0.00, -0.01),
        midtones=(0.01, 0.00, -0.01),
        highlights=(0.01, 0.00, 0.00),
    ),
    # Pacific Image PrimeFilm — mild warm cast, slight magenta in shadows
    "pacific_image": ScannerProfile(
        model="Pacific Image PrimeFilm",
        shadows=(0.03, -0.01, 0.00),
        midtones=(0.02, 0.00, -0.01),
        highlights=(0.01, 0.00, 0.00),
    ),
}


def detect_scanner(image_path: Path) -> str | None:
    """Detect the scanner model from EXIF metadata in an image file.

    Reads the Model (0x0110), Software (0x0131), and ImageDescription
    (0x010E) EXIF tags, then pattern-matches them against known scanner
    identifiers.

    Args:
        image_path: Path to the image file.

    Returns:
        A canonical scanner identifier string (e.g. ``"epson_v700"``) if a
        known scanner is detected, or ``None`` if no match is found.
    """
    with Image.open(image_path) as img:
        exif_data = img.getexif()

    candidate_strings: list[str] = []
    for tag_id in (_TAG_MODEL, _TAG_SOFTWARE, _TAG_IMAGE_DESCRIPTION):
        value = exif_data.get(tag_id)
        if isinstance(value, str):
            candidate_strings.append(value)

    for candidate in candidate_strings:
        for pattern, scanner_id in _SCANNER_PATTERNS:
            if pattern.search(candidate):
                return scanner_id

    return None


def get_scanner_compensation(scanner_id: str) -> ScannerProfile | None:
    """Look up the compensation profile for a scanner.

    Args:
        scanner_id: Canonical scanner identifier (e.g. ``"epson_v700"``).

    Returns:
        The corresponding ``ScannerProfile``, or ``None`` if the scanner
        is not in the built-in profiles.
    """
    return SCANNER_PROFILES.get(scanner_id)


def compensate_color_bias(bias: ColorBias, profile: ScannerProfile) -> ColorBias:
    """Remove the scanner's color contribution from a measured bias.

    Subtracts the scanner profile's per-region (R, G, B) offsets from the
    measured ``ColorBias`` so the result reflects only the film stock.

    Args:
        bias: The raw measured color bias (including scanner influence).
        profile: The scanner's compensation profile.

    Returns:
        A new ``ColorBias`` with the scanner's contribution removed.
    """
    return ColorBias(
        shadows=_subtract_rgb(bias.shadows, profile.shadows),
        midtones=_subtract_rgb(bias.midtones, profile.midtones),
        highlights=_subtract_rgb(bias.highlights, profile.highlights),
    )


def _subtract_rgb(
    measured: tuple[float, float, float],
    offset: tuple[float, float, float],
) -> tuple[float, float, float]:
    """Subtract an (R, G, B) offset from a measured (R, G, B) value.

    Args:
        measured: The measured RGB bias values.
        offset: The scanner's RGB bias to subtract.

    Returns:
        The compensated (R, G, B) tuple.
    """
    return (
        measured[0] - offset[0],
        measured[1] - offset[1],
        measured[2] - offset[2],
    )
