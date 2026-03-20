# Preset Format Documentation

How NegClone maps fingerprint values to Darktable and Lightroom preset parameters.

## Fingerprint → Darktable `.dtstyle`

### Grain Module

| Fingerprint Value | Darktable Param | Mapping |
|---|---|---|
| `grain.mean_intensity` | `strength` (0–100) | `intensity × 500`, clamped |
| `grain.size_estimate` | `scale` (100–6400) | `size × 800`, clamped |
| `grain.clumping_factor` | (encoded in scale) | Higher clumping → larger scale |

### Filmic RGB Module

| Fingerprint Value | Darktable Param | Mapping |
|---|---|---|
| `tone.shadow_lift` | `black_point_source` | `-8 + lift × 4` |
| `tone.highlight_compression` | `white_point_source` | `4 - compression × 2` |
| `tone.midtone_contrast` | `contrast` | Direct pass-through |

### Color Balance RGB Module

| Fingerprint Value | Darktable Param | Mapping |
|---|---|---|
| `color.shadows` (R,G,B) | Shadow lift RGBA | `shift × 50` scale factor |
| `color.midtones` (R,G,B) | Power RGBA | `shift × 50` scale factor |
| `color.highlights` (R,G,B) | Gain RGBA | `shift × 50` scale factor |

**Known limitation (v1):** Darktable module params are base64-encoded C structs. The current implementation uses `struct.pack` with approximated field layouts. Exact binary encoding matching Darktable's internal format is a v2 feature. The generated styles will load in Darktable but field offsets may not perfectly match all Darktable versions.

## Fingerprint → Lightroom `.xmp`

### Grain

| Fingerprint Value | XMP Attribute | Mapping |
|---|---|---|
| `grain.mean_intensity` | `crs:GrainAmount` (0–100) | `intensity × 300`, clamped |
| `grain.size_estimate` | `crs:GrainSize` (10–100) | Linear map from 1–5px → 10–100 |
| `grain.clumping_factor` | `crs:GrainFrequency` (0–100) | `(1 - clumping) × 100` |

### Tone Curve

| Fingerprint Value | XMP Element | Mapping |
|---|---|---|
| `tone.shadow_lift` | `crs:ToneCurvePV2012` points | Lifts shadow output values |
| `tone.highlight_compression` | `crs:ToneCurvePV2012` points | Compresses highlight output |
| `tone.midtone_contrast` | `crs:Contrast2012` | `(contrast - 1.0) × 30` |

### Color Grading

| Fingerprint Value | XMP Attributes | Mapping |
|---|---|---|
| `color.shadows` | `crs:ColorGradeShadow{Hue,Sat,Lum}` | RGB shift → hue/sat conversion |
| `color.midtones` | `crs:ColorGradeMidtone{Hue,Sat,Lum}` | RGB shift → hue/sat conversion |
| `color.highlights` | `crs:ColorGradeHighlight{Hue,Sat,Lum}` | RGB shift → hue/sat conversion |
| `color.shadows` | `crs:ShadowTint` | Magenta-green axis: `(R+B-2G) × 200` |
