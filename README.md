# NegClone

[![PyPI version](https://img.shields.io/pypi/v/negclone.svg)](https://pypi.org/project/negclone/)
[![Python 3.12+](https://img.shields.io/pypi/pyversions/negclone.svg)](https://pypi.org/project/negclone/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

NegClone is a Python CLI tool that analyzes your film photography archive (on Flickr or locally), extracts a grain and color fingerprint per film stock, and auto-generates Darktable `.dtstyle` and Lightroom/ACR `.xmp` preset files. The result is a publishable preset pack derived from real scanned negatives — not synthetic emulations.

## Use Cases

- **Sell your own preset pack.** If you shoot film and scan your negatives, NegClone can extract the look of each stock you shoot and turn it into a distributable preset pack (Darktable + Lightroom) that you can sell on Gumroad, Etsy, or your own site.
- **Match your digital edits to your film scans.** Use NegClone to fingerprint your favorite stocks, then apply those presets to your digital photos for a consistent look across both formats.
- **Compare film stocks objectively.** Use `negclone compare` to see exactly how Portra 400 differs from Ektar 100 in your scans — grain, color bias, tonal response, all measured.
- **Preserve your film look.** If you're switching from film to digital (or hybrid shooting), fingerprint your go-to stocks before you stop buying them. The presets capture the characteristics of your actual scans.
- **Build presets from a specific body of work.** Point NegClone at a tagged subset of your Flickr archive (e.g., `--tags desert`) or a local folder to generate presets that capture the look of a specific project or series.
- **Generate visual reports.** Use `negclone report` to create an HTML page with fingerprint cards, color swatches, and a similarity matrix — useful for blog posts, Gumroad listings, or your own reference.

## Prerequisites

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) (recommended) or pip
- Film photos either uploaded to Flickr or in a local directory

## Getting a Flickr API Key

Only needed if you're pulling photos from Flickr (not needed for local scans):

1. Go to <https://www.flickr.com/services/apps/create/>
2. Click "Apply for a Non-Commercial Key"
3. Fill in the application details
4. Copy your **API Key** and **API Secret**

## Install

From PyPI:

```bash
pip install negclone
```

Or with [uv](https://github.com/astral-sh/uv):

```bash
uv pip install negclone
```

For development:

```bash
git clone https://github.com/pfrederiksen/negclone.git
cd negclone
uv pip install -e ".[dev]"
```

## Configuration

For Flickr mode, set your credentials as environment variables:

```bash
export FLICKR_API_KEY=your_api_key_here
export FLICKR_API_SECRET=your_api_secret_here
```

For local mode, no configuration is needed.

## Quick Start (Flickr)

```bash
# 1. Authenticate with Flickr (opens browser for OAuth)
negclone auth

# 2. Build an inventory of your film photos
negclone inventory --output inventory.json

# 3. Download original images for a specific stock
negclone download inventory.json --stock portra400 --sample-size 30

# 4. Analyze and fingerprint the stock
negclone fingerprint inventory.json --stock portra400 --sample-size 30

# 5. Generate Darktable + Lightroom presets
negclone generate fingerprint_portra400.json --format both --output-dir ./output

# 6. Package everything into a distributable zip
negclone pack --output-dir ./output --name "Desert Paul Film Presets"
```

## Quick Start (Local Scans)

```bash
# Organize scans in folders by stock name:
#   scans/portra400/IMG_001.tif
#   scans/hp5/scan_042.jpg

# 1. Build inventory from local directory
negclone inventory --local ./scans --output inventory.json

# 2. Link local files into the cache
negclone download inventory.json

# 3. Fingerprint, generate, and pack — same as Flickr workflow
negclone fingerprint inventory.json
negclone generate fingerprint_portra400.json --output-dir ./output
negclone pack --output-dir ./output
```

## Commands

### `negclone auth`

Authenticates with Flickr via OAuth 1.0a. Opens your browser to authorize the app, then prompts for the verifier code. Tokens are stored securely at `~/.negclone/flickr_tokens.json` (file permissions 600). You only need to do this once.

```bash
negclone auth
negclone auth --verifier 123-456-789   # skip interactive prompt
```

### `negclone inventory`

Scans your Flickr photostream or a local directory and groups photos by detected film stock. Outputs an `inventory.json` with photo IDs, URLs/paths, detected stock names, and metadata.

```bash
# Flickr: scan your own photostream
negclone inventory

# Flickr: scan a specific user with filters
negclone inventory --user paul-frederiksen --tags film --min-date 2023-01-01

# Local: scan a directory of scans
negclone inventory --local ./scans

# Use a custom tag-to-stock mapping
negclone inventory --tag-map my_tags.json
```

For local mode, stock detection works by checking:
1. **Parent folder name** (e.g., `scans/portra400/`)
2. **Filename** (e.g., `portra400_001.jpg`)
3. **EXIF metadata** (ImageDescription, UserComment)

The `--tag-map` option accepts a JSON file like `{"myportra": "portra400", "bw": "hp5"}` for custom aliases.

### `negclone download`

Downloads original-resolution images from Flickr to a local cache, or creates symlinks for local scans. Skips already-cached files.

```bash
negclone download inventory.json --stock portra400
negclone download inventory.json --sample-size 30   # all stocks, 30 each
```

### `negclone fingerprint`

Analyzes cached images and computes a fingerprint per film stock. Each fingerprint includes:

- **Grain profile** — intensity, FFT-derived size (peak spatial frequency), clumping factor, spectral slope
- **Color bias** — R/G/B channel shifts in shadows, midtones, and highlights (with optional scanner compensation)
- **Tonal rolloff** — shadow lift, highlight compression, midtone contrast, plus a PCHIP monotone spline tone curve
- **Confidence score** — how consistent the measurements are across samples
- **Scanner model** — auto-detected from EXIF, used to compensate for scanner color bias

```bash
negclone fingerprint inventory.json --stock portra400
negclone fingerprint inventory.json                        # all stocks
negclone fingerprint inventory.json --sample-size 40       # more samples
```

### `negclone generate`

Generates preset files from a fingerprint JSON. Supports Darktable `.dtstyle` and Lightroom/ACR `.xmp` formats. Lightroom presets include spline-based tone curves when available.

```bash
negclone generate fingerprint_portra400.json --format both
negclone generate fingerprint_portra400.json --format darktable
negclone generate fingerprint_portra400.json --dry-run
negclone generate fingerprint_portra400.json --force
```

### `negclone compare`

Compare two fingerprints side-by-side with a detailed diff table showing grain, color, tonal differences, and an overall similarity score.

```bash
negclone compare fingerprint_portra400.json fingerprint_ektar100.json
```

### `negclone report`

Generate an HTML report with fingerprint cards, color swatches, and a similarity matrix across all provided fingerprints.

```bash
negclone report fingerprint_portra400.json fingerprint_ektar100.json fingerprint_hp5.json
negclone report fingerprint_*.json -o my_stocks.html
```

### `negclone pack`

Bundles all generated presets into a zip archive with a README.txt containing import instructions. Prints a Gumroad upload checklist.

```bash
negclone pack --output-dir ./output --name "Desert Paul Film Presets"
negclone pack --dry-run  # preview contents
```

## How the Analysis Works

### Grain (FFT Spectral Analysis)

NegClone samples patches across each scanned image, applies a 2D Hann window, and computes the FFT power spectrum. The radially averaged spectrum gives a frequency profile of the grain texture. From this it extracts:
- **Peak frequency** — dominant spatial frequency in cycles/pixel (inverted to get grain size in pixels)
- **Spectral slope** — steepness of the log-log power spectrum (steep = soft/large grain, shallow = sharp/fine)
- **Spectral centroid** — weighted mean frequency for robust size estimation

Local standard deviation and spatial autocorrelation are also computed for backward-compatible intensity and clumping metrics.

### Color (with Scanner Compensation)

For each image, pixel luminance is bucketed into shadows (bottom 25%), midtones (25-75%), and highlights (top 25%). Within each bucket, the mean R, G, B channel values are compared to the per-bucket neutral mean, producing a color shift vector per region.

When scanner model detection finds a known scanner (Epson V600/V700/V850, Noritsu, Frontier, Plustek, etc.), the scanner's inherent color bias is subtracted from the measurements, so the fingerprint reflects the film stock rather than the scanner.

### Tone (PCHIP Spline Curve)

Tonal analysis measures the luminance histogram shape: shadow lift (deep vs. near shadow density), highlight compression, and midtone contrast. A PCHIP (Piecewise Cubic Hermite Interpolating Polynomial) monotone spline is fitted to the luminance CDF, producing a smooth, non-inverting tone curve that is exported directly into Lightroom presets as a multi-point `ToneCurvePV2012`.

## Supported Film Stocks

NegClone auto-detects these film stocks from tags, titles, descriptions, folder names, and filenames:

| Stock | Type | Key Characteristics |
|---|---|---|
| Portra 160 | Color Negative | Fine grain, neutral-warm tones |
| Portra 400 | Color Negative | Medium grain, warm midtones, lifted shadows |
| Portra 800 | Color Negative | Visible grain, warm tones, good in low light |
| Ektar 100 | Color Negative | Fine grain, saturated, warm shadows |
| Gold 200 | Color Negative | Moderate grain, warm/yellow bias |
| HP5 Plus | B&W Negative | Pronounced grain, high contrast |
| Delta 100 | B&W Negative | Fine grain, smooth tones |
| Tri-X 400 | B&W Negative | Classic grain, rich midtones |
| Fomapan 100 | B&W Negative | Fine grain, soft tones |
| CineStill 800T | Color Negative (Tungsten) | Halation, cool tones, visible grain |

Custom tag-to-stock mappings:

```json
{"portra": "portra400", "bw_street": "hp5", "cine": "cinestill800t"}
```

## Importing Presets

### Darktable

1. Open Darktable and switch to the **lighttable** view
2. Find the **styles** module in the right panel
3. Click **import** and select the `.dtstyle` file(s)
4. Apply: select a photo, then click the style name

**Note:** Darktable module params use approximated binary encoding in v1. Grain, tone, and color grading are functional, but exact C struct encoding for all Darktable versions is a v2 feature.

### Lightroom / Adobe Camera Raw

1. Copy `.xmp` file(s) to your presets directory:
   - **macOS:** `~/Library/Application Support/Adobe/CameraRaw/Settings/`
   - **Windows:** `C:\Users\<username>\AppData\Roaming\Adobe\CameraRaw\Settings\`
2. Restart Lightroom
3. Find presets in the **Develop** module preset panel

## Tips

- **More samples = better fingerprints.** `--sample-size 40` gives higher confidence and more stable results.
- **Local scans are best.** TIFFs from your scanner give better fingerprints than re-compressed Flickr JPEGs.
- **Organize by folder.** For local mode, put scans in folders named after the stock (e.g., `portra400/`) — this is the most reliable detection method.
- **Use `--dry-run`** on `generate` and `pack` to preview before writing.
- **Compare stocks** with `negclone compare` to understand how they actually differ in your workflow.
- **Generate reports** with `negclone report` for blog posts or preset pack marketing pages.

## Development

```bash
uv pip install -e ".[dev]"
pytest                  # 65 tests
ruff check . && ruff format .
mypy negclone
```

## License

MIT
