# KaroSpaceBuilder

![KaroSpaceBuilder logo](assets/logo_KSB.png)

KaroSpaceBuilder is a desktop GUI for building KaroSpace HTML viewers from `.h5ad` files.

It is a front-end for KaroSpace backend functions:
- `karospace.load_spatial_data(...)`
- `karospace.export_to_html(...)`

The builder output is a static HTML viewer:

```text
<output_dir>/KaroSpace_YYYYMMDD_HHMMSS.html
```

## Download A Release (Recommended)

Prebuilt app bundles can be distributed so users do not need Python/terminal.

Download the correct binary from [GitHub Releases](https://github.com/christoffermattssonlangseth/KaroSpaceBuilder/releases):
- Apple Silicon (M1/M2/M3/M4): `KaroSpaceBuilder-macos-arm64.zip`
- Intel Mac: `KaroSpaceBuilder-macos-intel.zip`
- Windows: `KaroSpaceBuilder-windows.zip`
- Linux (x86_64): `KaroSpaceBuilder-linux.zip`

Linux run command after unzip:

```bash
cd KaroSpaceBuilder
./KaroSpaceBuilder
```

## Installation (GitHub)

```bash
git clone https://github.com/christoffermattssonlangseth/KaroSpaceBuilder
cd KaroSpaceBuilder
```

Create and activate a Python environment (Python 3.10-3.12 recommended), then install dependencies.

### 1) Install KaroSpace backend

If you have local source:

```bash
python -m pip install -e /path/to/spatial-viewer
```

Or install directly from GitHub:

```bash
python -m pip install "git+https://github.com/christoffermattssonlangseth/KaroSpace.git"
```

### 2) Install KaroSpaceBuilder

```bash
python -m pip install -e .
```

## Launch

```bash
KaroSpaceBuilder
```

Fallback launch commands:

```bash
karospace-builder
# or
python -m karospace_export.app
```

## GUI Workflow

1. Set input `.h5ad` and output directory. SpatialData `.zarr` paths can be typed manually.
2. Click **Inspect H5AD** to populate searchable dropdowns from `adata.obs` and `adata.var_names`.
3. Pick:
   - Section key
   - Main cell annotation
   - Cell annotations
   - Feature list from inspected `var_names`
4. Configure optional feature storage, section metadata, pseudobulk, pathway, neighbor, interaction, and overlay settings.
5. Click **Export**.

Result: `KaroSpace_YYYYMMDD_HHMMSS.html` in the selected output directory.

## What The Builder Maps To

The GUI fields map directly to KaroSpace export arguments, including:
- `main_cell_annotation`, `title`, `outline_by`
- `min_panel_size`, `spot_size`, `downsample`
- `cell_annotations`, `features`, `feature_encoding`, `feature_storage`
- `feature_value_encoding`, `feature_manifest_path`, `feature_sidecar_shard_size`
- `section_metadata`, `section_metadata_extra`, `metadata_value_order`, `metadata_labels`
- `pseudobulk`, `pseudobulk_additional_annotations`, pseudobulk thresholds, and pathway settings
- `neighbor_stats_annotations`, `neighbor_stats_permutations`, `neighbor_stats_seed`
- `interaction_markers`, interaction marker limits, `section_rotations`, `deconvolutions`, `section_images`

The builder exports only explicitly selected features.

Coordinates modes:
- `auto`
- `obsm:spatial`
- `obs:centroid_x_y` (converted to temporary `obsm['spatial']` before export)

## Desktop Builds For Non-technical Users

Build locally:

```bash
python -m pip install -e .[build]
python scripts/build_desktop.py
```

Outputs:
- macOS: `dist/KaroSpaceBuilder.app`
- Windows: `dist/KaroSpaceBuilder/KaroSpaceBuilder.exe`
- Linux: `dist/KaroSpaceBuilder/KaroSpaceBuilder`

## Troubleshooting

### `No module named '_tkinter'`

Use a Python build with Tk support (or conda with `tk`).

### `Could not import 'karospace'`

Install KaroSpace in the same environment, e.g.:

```bash
python -m pip install -e /path/to/spatial-viewer
```

If you see `scanpy`/`numba` import errors, use Python 3.10-3.12.

### `KaroSpaceBuilder` command not found

Reinstall in the active environment:

```bash
python -m pip install -e .
```

Then run `KaroSpaceBuilder` again.
