# NegClone

NegClone is a Python CLI tool that analyzes your film photography archive on Flickr, extracts a grain and color fingerprint per film stock, and auto-generates Darktable `.dtstyle` and Lightroom/ACR `.xmp` preset files. The result is a publishable preset pack derived from real scanned negatives — not synthetic emulations.

## Use Cases

- **Sell your own preset pack.** If you shoot film and scan your negatives, NegClone can extract the look of each stock you shoot and turn it into a distributable preset pack (Darktable + Lightroom) that you can sell on Gumroad, Etsy, or your own site.
- **Match your digital edits to your film scans.** Use NegClone to fingerprint your favorite stocks, then apply those presets to your digital photos for a consistent look across both formats.
- **Compare film stocks objectively.** NegClone gives you measurable grain, color, and tonal data per stock — useful if you want to see how Portra 400 actually differs from Ektar 100 in your own scans, not someone else's description.
- **Preserve your film look.** If you're switching from film to digital (or hybrid shooting), fingerprint your go-to stocks before you stop buying them. The presets capture the characteristics of your actual scans.
- **Build presets from a specific body of work.** Point NegClone at a tagged subset of your Flickr archive (e.g., `--tags desert`) to generate presets that capture the look of a specific project or series.

## Prerequisites

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) (recommended) or pip
- A Flickr API key (non-commercial)
- Film photos uploaded to Flickr with stock names in tags, titles, or descriptions

## Getting a Flickr API Key

1. Go to <https://www.flickr.com/services/apps/create/>
2. Click "Apply for a Non-Commercial Key"
3. Fill in the application details
4. Copy your **API Key** and **API Secret**

## Install

```bash
uv pip install -e .
```

Or with dev dependencies:

```bash
uv pip install -e ".[dev]"
```

## Configuration

Set your Flickr credentials as environment variables:

```bash
export FLICKR_API_KEY=your_api_key_here
export FLICKR_API_SECRET=your_api_secret_here
```

## Quick Start

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

## Commands

### `negclone auth`

Authenticates with Flickr via OAuth 1.0a. Opens your browser to authorize the app, then prompts for the verifier code. Tokens are stored securely at `~/.negclone/flickr_tokens.json` (file permissions 600). You only need to do this once.

```bash
negclone auth
negclone auth --verifier 123-456-789   # skip interactive prompt
```

### `negclone inventory`

Scans your Flickr photostream and groups photos by detected film stock. Outputs an `inventory.json` with photo IDs, URLs, detected stock names, and metadata.

```bash
# Scan your own photostream
negclone inventory

# Scan a specific user
negclone inventory --user paul-frederiksen

# Filter by tag and date
negclone inventory --tags film --min-date 2023-01-01

# Use a custom tag-to-stock mapping
negclone inventory --tag-map my_tags.json
```

The `--tag-map` option accepts a JSON file like `{"myportra": "portra400", "bw": "hp5"}` for custom tag aliases.

### `negclone download`

Downloads original-resolution images from Flickr to a local cache. Skips already-cached files. Images are stored at `cache/<stock>/<photo_id>.jpg`.

```bash
# Download 20 samples of a specific stock
negclone download inventory.json --stock portra400

# Download all stocks, 30 samples each
negclone download inventory.json --sample-size 30

# Custom cache directory
negclone download inventory.json --cache-dir /path/to/cache
```

### `negclone fingerprint`

Analyzes cached images and computes a fingerprint per film stock. Each fingerprint includes:

- **Grain profile** — intensity, size, and clumping factor
- **Color bias** — R/G/B channel shifts in shadows, midtones, and highlights
- **Tonal rolloff** — shadow lift, highlight compression, midtone contrast
- **Confidence score** — how consistent the measurements are across samples

```bash
# Fingerprint a specific stock
negclone fingerprint inventory.json --stock portra400

# Fingerprint all stocks in the inventory
negclone fingerprint inventory.json

# Use more samples for higher confidence
negclone fingerprint inventory.json --stock ektar100 --sample-size 40
```

### `negclone generate`

Generates preset files from a fingerprint JSON. Supports Darktable `.dtstyle` and Lightroom/ACR `.xmp` formats.

```bash
# Generate both formats
negclone generate fingerprint_portra400.json --format both

# Darktable only
negclone generate fingerprint_portra400.json --format darktable

# Lightroom only, custom output dir
negclone generate fingerprint_portra400.json --format lightroom -o ./presets

# Preview without writing files
negclone generate fingerprint_portra400.json --dry-run

# Overwrite existing output
negclone generate fingerprint_portra400.json --force
```

### `negclone pack`

Bundles all generated presets into a zip archive with a README.txt containing import instructions. Prints a Gumroad upload checklist.

```bash
negclone pack --output-dir ./output --name "Desert Paul Film Presets"
negclone pack --dry-run  # preview contents
```

## How the Analysis Works

### Grain

NegClone samples patches across each scanned image and measures the local standard deviation of the luminance channel — this captures the "noisiness" that is characteristic film grain. It also computes spatial autocorrelation to determine grain clumping (whether the grain is fine and uniform or coarse and clumpy). These measurements are aggregated across all sampled images for a stock using median values, giving a robust fingerprint resistant to outliers from individual scans.

### Color

For each image, pixel luminance is bucketed into shadows (bottom 25%), midtones (25-75%), and highlights (top 25%). Within each bucket, the mean R, G, B channel values are compared to the per-bucket neutral mean. This produces a color shift vector per region — for example, Portra 400 typically shows a slight green shift in shadows and a warm (blue-deficit) bias in midtones.

### Tone

Tonal analysis measures the luminance histogram shape: how much density sits in the deep shadows vs near-shadows (shadow lift), how highlights fall off (highlight compression), and how tightly packed the midtones are (midtone contrast). Film stocks with classic "lifted blacks" like Portra show high shadow lift values; high-contrast stocks like HP5 show elevated midtone contrast.

## Supported Film Stocks

NegClone auto-detects these film stocks from your Flickr photo tags, titles, and descriptions:

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

You can also provide a custom `--tag-map` JSON file to add your own tag-to-stock mappings:

```json
{"portra": "portra400", "bw_street": "hp5", "cine": "cinestill800t"}
```

## Importing Presets

### Darktable

1. Open Darktable and switch to the **lighttable** view
2. Find the **styles** module in the right panel
3. Click the **import** button
4. Select the `.dtstyle` file(s) for your desired film stocks
5. To apply: select a photo, then click the style name in the styles module

**Note:** Darktable module params use approximated binary encoding in v1. Grain strength, tonal adjustments, and color grading are functional, but exact binary struct encoding matching all Darktable versions is a v2 feature.

### Lightroom / Adobe Camera Raw

1. Copy the `.xmp` file(s) to your presets directory:
   - **macOS:** `~/Library/Application Support/Adobe/CameraRaw/Settings/`
   - **Windows:** `C:\Users\<username>\AppData\Roaming\Adobe\CameraRaw\Settings\`
2. Restart Lightroom
3. In the **Develop** module, find your new presets in the preset panel under "User Presets"

## Tips

- **More samples = better fingerprints.** The default 20 images works well, but `--sample-size 40` will give you higher confidence scores and more stable results.
- **Tag your Flickr photos.** NegClone detects stock names from tags, titles, and descriptions. The more consistently you tag (e.g., `portra400`, `kodakportra400`), the more photos it'll match.
- **Process all stocks at once.** Omit the `--stock` flag on `download` and `fingerprint` to process every detected stock in one pass.
- **Use `--dry-run`** on `generate` and `pack` to preview what will be created before writing files.
- **Flickr rate limits** are handled automatically with 1 request/second throttling and exponential backoff on 429/503 responses.

## Development

```bash
# Install with dev dependencies
uv pip install -e ".[dev]"

# Run tests (65 tests)
pytest

# Lint and format
ruff check .
ruff format .

# Type check
mypy negclone
```

## License

MIT
