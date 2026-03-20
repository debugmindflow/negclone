"""Pydantic v2 data models for NegClone."""

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

# Known film stocks for auto-detection
KNOWN_STOCKS: list[str] = [
    "portra160",
    "portra400",
    "portra800",
    "ektar100",
    "gold200",
    "hp5",
    "delta100",
    "tri-x",
    "fomapan100",
    "cinestill800t",
]

# Normalized aliases for fuzzy matching
STOCK_ALIASES: dict[str, str] = {
    "portra 160": "portra160",
    "portra 400": "portra400",
    "portra 800": "portra800",
    "ektar 100": "ektar100",
    "gold 200": "gold200",
    "hp5 plus": "hp5",
    "hp5+": "hp5",
    "ilford hp5": "hp5",
    "ilford delta 100": "delta100",
    "delta 100": "delta100",
    "kodak portra 400": "portra400",
    "kodak portra 160": "portra160",
    "kodak portra 800": "portra800",
    "kodak ektar 100": "ektar100",
    "kodak gold 200": "gold200",
    "tri-x 400": "tri-x",
    "trix": "tri-x",
    "tri-x400": "tri-x",
    "kodak tri-x": "tri-x",
    "fomapan 100": "fomapan100",
    "cinestill 800t": "cinestill800t",
    "cinestill800": "cinestill800t",
}


class FlickrPhotoRecord(BaseModel):
    """A photo record fetched from Flickr."""

    photo_id: str
    title: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    stock: str
    date_taken: datetime | None = None
    url_original: str
    width: int | None = None
    height: int | None = None


class Inventory(BaseModel):
    """Full inventory grouped by film stock."""

    stocks: dict[str, list[FlickrPhotoRecord]]
    created_at: datetime = Field(default_factory=datetime.now)
    user: str = ""


class ImageRecord(BaseModel):
    """A local cached image record for fingerprinting."""

    path: Path
    stock: str
    date: datetime | None = None
    width: int = 0
    height: int = 0
    color_space: str = "sRGB"


class GrainProfile(BaseModel):
    """Grain characteristics extracted from film scans."""

    mean_intensity: float
    size_estimate: float  # pixels
    clumping_factor: float  # 0-1


class ColorBias(BaseModel):
    """Color channel bias in shadows, midtones, and highlights."""

    shadows: tuple[float, float, float]  # R, G, B shift
    midtones: tuple[float, float, float]
    highlights: tuple[float, float, float]


class TonalRolloff(BaseModel):
    """Tonal curve characteristics."""

    shadow_lift: float
    highlight_compression: float
    midtone_contrast: float
    curve_coefficients: list[float]  # polynomial coefficients


class StockFingerprint(BaseModel):
    """Complete fingerprint for a film stock."""

    stock: str
    sample_count: int
    grain: GrainProfile
    color: ColorBias
    tone: TonalRolloff
    confidence: float  # 0-1, based on IQR spread
    generated_at: datetime = Field(default_factory=datetime.now)
