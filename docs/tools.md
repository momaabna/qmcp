# QMCP tool reference

This page describes each of the 29 MCP tools QMCP exposes, as the assistant sees them. Parameters marked **required** must be given. All others are optional and default to the value shown.

- [Conventions](#conventions)
- [General](#general): `ping`, `get_qgis_info`
- [Project](#project): `get_project_info`, `load_project`, `create_new_project`, `save_project`
- [Layers](#layers): `get_layers`, `add_vector_layer`, `add_raster_layer`, `remove_layer`, `rename_layer`, `set_layer_visibility`, `zoom_to_layer`, `get_layer_features`
- [Processing](#processing): `search_algorithms`, `get_algorithm_help`, `run_algorithm`
- [Styling](#styling): `get_layer_style`, `set_layer_style`, `set_layer_opacity`, `set_categorized_style`, `set_graduated_style`, `set_raster_style`, `set_layer_labels`, `save_layer_style`, `load_layer_style`
- [Map](#map): `set_map_extent`, `render_map`
- [Scripting](#scripting): `execute_code`

## Conventions

**Layers.** Every `layer` parameter accepts a layer ID (as returned by `get_layers`) or a layer name. An ID is matched first. If a name matches more than one layer, the call fails and lists the matching IDs.

**Colours.** Colours are strings in one of these forms:

| Form | Example | Notes |
|---|---|---|
| `#RRGGBB` | `"#E31A1C"` | Opaque |
| `#RRGGBBAA` | `"#E31A1C80"` | The last two digits are the alpha: `00` is transparent, `FF` opaque |
| `r,g,b` | `"227,26,28"` | Values 0–255 |
| `r,g,b,a` | `"227,26,28,128"` or `"227,26,28,0.5"` | Alpha 0–255, or 0–1 when written with a decimal point |

**Opacity** is a number from 0 (invisible) to 1 (opaque).

**Sizes** of symbols, outlines and label halos are in millimetres. Label text size is in points.

**Colour ramps** are QGIS' built-in ramps: Blues, BrBG, BuGn, BuPu, Cividis, GnBu, Greens, Greys, Inferno, Magma, Mako, OrRd, Oranges, PRGn, PiYG, Plasma, PuBu, PuBuGn, PuOr, PuRd, Purples, RdBu, RdGy, RdPu, RdYlBu, RdYlGn, Reds, Rocket, Spectral, Turbo, Viridis, YlGn, YlGnBu, YlOrBr and YlOrRd, plus any ramps you have added to your QGIS style library. An unknown name returns the list of available ones.

**Results.** Tools that change a layer return the layer and what was applied, for example:

```json
{"layer": "Riyadh bounding box", "layer_id": "Riyadh_bounding_box_2c94…", "applied": {"opacity": 0.5}}
```

Some also return `notes` about side effects, for example that a categorized renderer was replaced.

**Errors.** Invalid input is rejected before anything changes. This covers a missing layer, a malformed colour, a value out of range, a parameter that does not apply to the layer's geometry type, and a parameter the tool does not have. The error message says what was wrong and what to use instead.

---

## General

### `ping`

Check that QGIS is reachable. Returns `"pong"`.

### `get_qgis_info`

Returns the QGIS version and each Processing provider with its number of algorithms.

```json
{"qgis_version": "3.34.4-Prizren",
 "providers": [{"id": "native", "name": "QGIS (native c++)", "algorithm_count": 265},
               {"id": "gdal", "name": "GDAL", "algorithm_count": 56}, "…"]}
```

---

## Project

### `get_project_info`

Returns the project's file name, title, CRS, layer count and the first 20 layers (ID, name and type). Use `get_layers` for full details.

### `load_project`

Open a project file.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `path` | string | **required** | Path to a `.qgz` or `.qgs` file |

Returns `{"loaded": path, "layer_count": n}`.

### `create_new_project`

Clear the current project and save an empty one. Unsaved changes to the current project are lost.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `path` | string | **required** | Where to save the new project, e.g. `/data/project.qgz` |
| `crs` | string | none | Project CRS, e.g. `"EPSG:32638"` |

### `save_project`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `path` | string | current file | Save to this path instead. Required if the project has never been saved. |

---

## Layers

### `get_layers`

Lists every layer in the project:

| Field | Layers | Description |
|---|---|---|
| `id`, `name`, `source`, `crs` | all | |
| `type` | all | `vector` or `raster` |
| `visible` | all | Whether the layer is checked in the Layers panel |
| `geometry_type` | vector | `Point`, `Line`, `Polygon` or `No geometry` |
| `feature_count`, `fields` | vector | |
| `width`, `height`, `band_count` | raster | Size in pixels |

### `add_vector_layer`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `path` | string | **required** | File path or data source URI, e.g. `/data/roads.gpkg` or `/data/roads.gpkg\|layername=roads` |
| `name` | string | file name | Name in the Layers panel |
| `provider` | string | `"ogr"` | QGIS data provider, e.g. `ogr`, `delimitedtext`, `postgres`, `wfs` |

Returns the new layer's details, in the same form as `get_layers`.

### `add_raster_layer`

Same parameters as `add_vector_layer`. The default `provider` is `"gdal"`. Use `wms` for WMS and XYZ tiles.

### `remove_layer`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `layer` | string | **required** | Layer ID or name |

Returns `{"removed": layer_id}`.

### `rename_layer`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `layer` | string | **required** | Layer ID or name |
| `new_name` | string | **required** | Must not be empty |

Returns `applied: {"old_name", "new_name"}`. The layer ID does not change.

### `set_layer_visibility`

Check or uncheck a layer in the Layers panel.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `layer` | string | **required** | Layer ID or name |
| `visible` | boolean | **required** | |

### `zoom_to_layer`

Zoom the map to a layer's extent.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `layer` | string | **required** | Layer ID or name |

### `get_layer_features`

Read the attributes and geometry of the first features of a vector layer.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `layer` | string | **required** | Layer ID or name |
| `limit` | integer | `10` | Maximum number of features |

Returns `feature_count` (the total), `fields` and `features`, each with `id`, `attributes` and `geometry` (WKT with 4 decimals).

---

## Processing

QMCP does not register one tool per algorithm; a typical QGIS has several hundred algorithms. The assistant finds and runs algorithms in three steps instead:

1. `search_algorithms` finds the algorithm ID.
2. `get_algorithm_help` returns its parameter names and allowed values.
3. `run_algorithm` runs it.

All three read QGIS' live Processing registry, so newly installed providers and plugins (GRASS, SAGA, Semi-Automatic Classification, …) are available right away.

### `search_algorithms`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `query` | string | **required** | Words that must all appear in the algorithm's ID, name, tags or description, e.g. `"clip raster"` |
| `provider` | string | all | Only search one provider, e.g. `native`, `gdal`, `grass7`, `saga` |
| `limit` | integer | `20` | Maximum number of results |

Results matching the name come first, then native algorithms.

```json
[{"id": "native:buffer", "name": "Buffer", "group": "Vector geometry",
  "description": "This algorithm computes a buffer area for all the features in an input layer…"}]
```

### `get_algorithm_help`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `algorithm_id` | string | **required** | e.g. `native:buffer` |

Returns the algorithm's help text and, for each parameter, its `name`, `description`, `type`, `optional`, `default` and, where they apply, `options` (the values of an enum parameter), `allow_multiple`, `advanced` and `destination`. The outputs are listed too.

### `run_algorithm`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `algorithm_id` | string | **required** | e.g. `native:buffer` |
| `parameters` | object | **required** | Parameter values by name |
| `load_outputs` | boolean | `true` | Add output layers to the project |

Parameter values:

- **Layers**: a layer ID, a layer name or a file path.
- **Outputs**: a file path such as `/data/out.gpkg`, or `"TEMPORARY_OUTPUT"` for an in-memory layer.
- **Enums**: the option's number from `get_algorithm_help`.

Keep `load_outputs` on to chain algorithms: the output is added to the project and can be passed to the next call by its ID. With `load_outputs: false`, a `TEMPORARY_OUTPUT` layer is discarded when the call ends.

```json
{"algorithm_id": "native:buffer",
 "parameters": {"INPUT": "roads", "DISTANCE": 50, "DISSOLVE": true, "OUTPUT": "TEMPORARY_OUTPUT"}}
```

Returns `{"algorithm": id, "result": {"OUTPUT": "<layer id or path>"}}`. When an algorithm fails, the error includes the last lines of its log, which usually name the parameter that was wrong.

---

## Styling

### `get_layer_style`

Describes a layer's current style. Call it before changing a style.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `layer` | string | **required** | Layer ID or name |

What it returns for a **vector** layer:
- `renderer`: `singleSymbol`, `categorizedSymbol`, `graduatedSymbol`, …
- `opacity` and `visible`.
- For a single symbol, `symbol`: its type, colour and opacity, plus all properties of its first symbol layer (fill style, outline colour and width, …).
- For a categorized style, `field` and `categories`: value, label, colour and whether each is shown.
- For a graduated style, `field`, `mode` and `classes`: lower and upper bound, label and colour.
- `labels`: whether they're on, plus field or expression, size, colour and `buffer_size`.

What it returns for a **raster** layer:
- `renderer`: `singlebandpseudocolor`, `singlebandgray`, `multibandcolor`, …
- `opacity`, `band_count` and `visible`.
- For single-band renderers, `band` with `min` and `max`.
- For pseudocolor, `color_stops` (up to 20).
- For multiband, `bands` ([red, green, blue]).

### `set_layer_style`

Give a vector layer a single-symbol style. Only the parameters you pass change. The rest of the current symbol is kept.

| Parameter | Geometry | Type | Description |
|---|---|---|---|
| `layer` | all | string, **required** | Layer ID or name |
| `fill_color` | polygon | colour | Fill colour. Use an alpha value for a see-through fill. |
| `fill_style` | polygon | enum | `solid`, `no` (no fill), `horizontal`, `vertical`, `cross`, `b_diagonal`, `f_diagonal`, `diagonal_x`, `dense1` … `dense7` |
| `outline_color` | polygon, point | colour | |
| `outline_width` | polygon, point | number (mm) | |
| `outline_style` | polygon | enum | `solid`, `no`, `dash`, `dot`, `dash dot`, `dash dot dot` |
| `color` | line, point | colour | Line colour, or marker fill colour |
| `width` | line | number (mm) | |
| `line_style` | line | enum | Same values as `outline_style` |
| `size` | point | number (mm) | Marker size |
| `shape` | point | enum | `circle`, `square`, `diamond`, `pentagon`, `hexagon`, `octagon`, `triangle`, `equilateral_triangle`, `star`, `arrow`, `cross`, `cross2`, `line`, `heart`, `rounded_square` |

A parameter that doesn't apply to the layer's geometry, such as `color` on a polygon layer, is rejected with the list of parameters that do apply.

If the layer had a categorized or graduated style, it is replaced by a single symbol, and the result's `notes` say so. A complex symbol (SVG marker, gradient fill, several symbol layers) is also replaced by a simple one that keeps its colour, and `notes` says so.

```json
{"layer": "Riyadh bounding box", "fill_style": "no", "outline_color": "#E31A1C", "outline_width": 0.8}
```

### `set_layer_opacity`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `layer` | string | **required** | Layer ID or name |
| `opacity` | number 0–1 | unchanged | Opacity of the whole layer, vector or raster |
| `symbol_opacity` | number 0–1 | unchanged | Vector only: opacity of every symbol (fill and outline together), including each class of a categorized or graduated style |

Give at least one of the two. For a transparent fill with a solid outline, use `set_layer_style` with a `fill_color` that has alpha, e.g. `"#ff000040"`.

### `set_categorized_style`

Colour a vector layer by the values of a field.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `layer` | string | **required** | Layer ID or name |
| `field` | string | **required** | Field to classify by |
| `color_ramp` | string | `"Spectral"` | Ramp used for categories without an explicit colour |
| `invert_ramp` | boolean | `false` | Reverse the ramp |
| `categories` | list | all unique values | Explicit classes: `[{"value": …, "label": …, "color": …}]`. `label` and `color` are optional. |

Without `categories`, every unique value gets a class. This fails if there are more than 200; use `set_graduated_style` or pass `categories` instead.

```json
{"layer": "districts", "field": "zone",
 "categories": [{"value": "R", "label": "Residential", "color": "#fdbf6f"},
                {"value": "C", "label": "Commercial", "color": "#e31a1c"}]}
```

### `set_graduated_style`

Colour a vector layer by ranges of a numeric field.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `layer` | string | **required** | Layer ID or name |
| `field` | string | **required** | A numeric field |
| `mode` | enum | `"quantile"` | `quantile` (equal counts), `equal_interval`, `jenks` (natural breaks), `pretty`, `stddev` |
| `classes` | integer | `5` | 1 to 100 |
| `color_ramp` | string | `"Reds"` | |
| `invert_ramp` | boolean | `false` | |

Returns the resulting `classes` with their bounds and labels.

### `set_raster_style`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `layer` | string | **required** | Layer ID or name |
| `mode` | enum | `"singleband_pseudocolor"` | `singleband_pseudocolor`, `singleband_gray` or `multiband` |
| `band` | integer | `1` | Band for the single-band modes |
| `bands` | list of 3 integers | `[1, 2, 3]` | `[red, green, blue]` for `multiband` |
| `min`, `max` | number | band's actual range | Stretch range. Give both or neither. For `multiband` it applies to all three bands. |
| `color_ramp` | string | `"Spectral"` | For `singleband_pseudocolor` |
| `invert_ramp` | boolean | `false` | |

The layer's opacity is kept.

```json
{"layer": "dem", "mode": "singleband_pseudocolor", "color_ramp": "Viridis", "min": 500, "max": 900}
{"layer": "sentinel2", "mode": "multiband", "bands": [8, 4, 3]}
```

### `set_layer_labels`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `layer` | string | **required** | Layer ID or name |
| `enabled` | boolean | `true` | `false` hides the labels but keeps their settings |
| `field` | string | current | Field to label with |
| `expression` | string | current | QGIS expression instead of a field, e.g. `concat("name", ' - ', "type")` |
| `size` | number (pt) | current | Text size |
| `color` | colour | current | Text colour |
| `buffer_color` | colour | current | Halo colour |
| `buffer_size` | number (mm) | current | Halo width. `0` turns the halo off. |

Give `field` or `expression`, not both. The first time a layer gets labels, one of them is required. After that, settings you don't pass keep their current values.

### `save_layer_style`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `layer` | string | **required** | Layer ID or name |
| `path` | string | **required** | Ends in `.qml` (QGIS style, any layer) or `.sld` (OGC SLD, vector layers only) |

An existing file is overwritten.

### `load_layer_style`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `layer` | string | **required** | Layer ID or name |
| `path` | string | **required** | An existing `.qml` or `.sld` file |

Use this with `save_layer_style` to copy a style from one layer to others.

---

## Map

### `set_map_extent`

Move the map to a place. Give a box, or a centre with a scale or width.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `xmin`, `ymin`, `xmax`, `ymax` | number | none | A box. All four are needed, with `xmin < xmax` and `ymin < ymax`. |
| `center_x`, `center_y` | number | none | A centre point |
| `scale` | number | none | With a centre: the map scale denominator, e.g. `50000` for 1:50,000 |
| `width_km` | number | none | With a centre: the width of the view on the ground, in km |
| `crs` | string | `"EPSG:4326"` | CRS of the coordinates. In EPSG:4326, x is longitude and y is latitude. |

With a centre, give exactly one of `scale` or `width_km`. The coordinates are transformed to the map's CRS. `width_km` is measured on the ground, so it's correct at any latitude and in any map CRS.

Returns the resulting `extent` in the map's CRS, `canvas_crs` and `scale`.

```json
{"center_x": 46.67, "center_y": 24.71, "width_km": 30}
{"xmin": 46.3, "ymin": 24.3, "xmax": 47.4, "ymax": 25.1}
```

### `render_map`

Render the current map: visible layers, current extent and current styles.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `path` | string | none | Save the image to this file (`.png`, `.jpg`, …) instead of returning it |
| `width` | integer | `800` | Pixels |
| `height` | integer | `600` | Pixels |

Without `path`, the PNG is returned as an image the assistant can look at, which is useful for checking a style change.

---

## Scripting

### `execute_code`

Run Python inside QGIS. Prefer the specific tools above when one fits: they validate their input and cannot damage the project by accident. See the Security section of the [README](../README.md#security).

| Parameter | Type | Default | Description |
|---|---|---|---|
| `code` | string | **required** | Python source |

The code can use `iface`, `processing` and every name in `qgis.core` without importing them. Returns:

```json
{"success": true, "stdout": "…everything printed…", "result": "…the value of a variable named result…"}
```

On an exception, `success` is `false`, and `error` holds the traceback.
