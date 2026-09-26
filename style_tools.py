# -*- coding: utf-8 -*-
"""
Styling, labelling and map view tools, so restyling a layer does not need
execute_code.

Colours are "#RRGGBB", "#RRGGBBAA" or "r,g,b[,a]" (a is 0-255, or 0-1 when
written with a decimal point, e.g. "255,0,0,0.5"). Every parameter is
validated before the layer is touched, so a rejected call changes nothing.
"""

import os
import re
from typing import Literal

from qgis.core import (QgsCategorizedSymbolRenderer, QgsClassificationEqualInterval,
                       QgsClassificationJenks, QgsClassificationPrettyBreaks,
                       QgsClassificationQuantile, QgsClassificationStandardDeviation,
                       QgsColorRampShader, QgsContrastEnhancement, QgsCoordinateReferenceSystem,
                       QgsCoordinateTransform, QgsFillSymbol, QgsGraduatedSymbolRenderer,
                       QgsLineSymbol, QgsMapLayer, QgsMarkerSymbol, QgsMultiBandColorRenderer,
                       QgsPalLayerSettings, QgsPointXY, QgsProject, QgsRasterBandStats,
                       QgsRectangle, QgsRendererCategory, QgsSimpleFillSymbolLayer,
                       QgsSimpleLineSymbolLayer, QgsSimpleMarkerSymbolLayer,
                       QgsSimpleMarkerSymbolLayerBase, QgsSingleBandGrayRenderer,
                       QgsSingleBandPseudoColorRenderer, QgsSingleSymbolRenderer, QgsStyle,
                       QgsSymbol, QgsSymbolLayerUtils, QgsTextBufferSettings, QgsTextFormat,
                       QgsVectorLayerSimpleLabeling, QgsWkbTypes)
from qgis.PyQt.QtGui import QColor

from .mcp_tools import _find_layer, _iface, _jsonable, _refresh_layer, mcp_server

FillStyle = Literal["solid", "no", "horizontal", "vertical", "cross", "b_diagonal",
                    "f_diagonal", "diagonal_x", "dense1", "dense2", "dense3", "dense4",
                    "dense5", "dense6", "dense7"]
LineStyle = Literal["solid", "no", "dash", "dot", "dash dot", "dash dot dot"]
MarkerShape = Literal["circle", "square", "diamond", "pentagon", "hexagon", "octagon",
                      "triangle", "equilateral_triangle", "star", "arrow", "cross", "cross2",
                      "line", "heart", "rounded_square"]

# Which set_layer_style parameters apply to which geometry type
_STYLE_PARAMETERS = {
    "Polygon": ("fill_color", "fill_style", "outline_color", "outline_width", "outline_style"),
    "Line": ("color", "width", "line_style"),
    "Point": ("color", "size", "shape", "outline_color", "outline_width"),
}

_CLASSIFICATIONS = {
    "quantile": QgsClassificationQuantile,
    "equal_interval": QgsClassificationEqualInterval,
    "jenks": QgsClassificationJenks,
    "pretty": QgsClassificationPrettyBreaks,
    "stddev": QgsClassificationStandardDeviation,
}

# Categorized renderers with more classes than this are unreadable; use graduated
MAX_CATEGORIES = 200


# ---------------------------------------------------------------------------
# Helpers


def _parse_color(value, parameter):
    """Parse "#RRGGBB", "#RRGGBBAA" or "r,g,b[,a]" into a QColor."""
    text = value.strip()
    match = re.fullmatch(r"#([0-9a-fA-F]{6})([0-9a-fA-F]{2})?", text)
    if match:
        color = QColor("#" + match.group(1))
        if match.group(2):
            color.setAlpha(int(match.group(2), 16))
        return color

    parts = [part.strip() for part in text.split(",")]
    if len(parts) in (3, 4):
        try:
            numbers = [float(part) for part in parts]
        except ValueError:
            numbers = None
        if numbers:
            if len(parts) == 4 and "." in parts[3]:
                numbers[3] *= 255
            if all(0 <= n <= 255 for n in numbers):
                return QColor(*[round(n) for n in numbers])
    raise ValueError('Invalid colour for {}: {!r}. Use "#RRGGBB", "#RRGGBBAA" or '
                     '"r,g,b,a" with values 0-255.'.format(parameter, value))


def _color_string(color):
    if color.alpha() == 255:
        return color.name()
    return "#{:02x}{:02x}{:02x}{:02x}".format(
        color.red(), color.green(), color.blue(), color.alpha())


def _check_opacity(value, parameter):
    if not 0 <= value <= 1:
        raise ValueError("{} must be between 0 and 1, got {}".format(parameter, value))


def _vector_layer(layer):
    found = _find_layer(layer)
    if found.type() != QgsMapLayer.VectorLayer:
        raise ValueError("{} is not a vector layer".format(found.name()))
    if not found.isSpatial():
        raise ValueError("{} has no geometry, so it has no symbology".format(found.name()))
    return found


def _raster_layer(layer):
    found = _find_layer(layer)
    if found.type() != QgsMapLayer.RasterLayer:
        raise ValueError("{} is not a raster layer".format(found.name()))
    return found


def _geometry_name(layer):
    return QgsWkbTypes.geometryDisplayString(layer.geometryType())


def _field(layer, field):
    index = layer.fields().indexOf(field)
    if index < 0:
        raise ValueError("{} has no field {!r}. Fields: {}".format(
            layer.name(), field, ", ".join(layer.fields().names())))
    return index


def _color_ramp(name, invert):
    style = QgsStyle.defaultStyle()
    ramp = style.colorRamp(name)
    if ramp is None:
        raise ValueError("Unknown color_ramp {!r}. Available: {}".format(
            name, ", ".join(sorted(style.colorRampNames()))))
    if invert:
        ramp.invert()
    return ramp


def _result(layer, applied, **extra):
    result = {"layer": layer.name(), "layer_id": layer.id(), "applied": _jsonable(applied)}
    result.update(extra)
    return result


def _symbol_summary(symbol):
    return {"type": type(symbol).__name__.replace("Qgs", "").replace("Symbol", "").lower(),
            "color": _color_string(symbol.color()),
            "opacity": symbol.opacity()}


# ---------------------------------------------------------------------------
# Vector symbology


@mcp_server.tool()
def set_layer_style(layer: str,
                    fill_color: str = None, fill_style: FillStyle = None,
                    outline_color: str = None, outline_width: float = None,
                    outline_style: LineStyle = None,
                    color: str = None, width: float = None, line_style: LineStyle = None,
                    size: float = None, shape: MarkerShape = None) -> dict:
    """Give a vector layer a single-symbol style. Only the parameters given change.

    Polygon layers: fill_color, fill_style ("no" = transparent fill),
    outline_color, outline_width (mm), outline_style.
    Line layers: color, width (mm), line_style.
    Point layers: color, size (mm), shape, outline_color, outline_width (mm).
    Colours are "#RRGGBB", "#RRGGBBAA" or "r,g,b,a". A categorized or
    graduated style is replaced by a single symbol.
    """
    found = _vector_layer(layer)
    given = {name: value for name, value in (
        ("fill_color", fill_color), ("fill_style", fill_style),
        ("outline_color", outline_color), ("outline_width", outline_width),
        ("outline_style", outline_style), ("color", color), ("width", width),
        ("line_style", line_style), ("size", size), ("shape", shape)) if value is not None}
    geometry = _geometry_name(found)
    allowed = _STYLE_PARAMETERS[geometry]
    if not given:
        raise ValueError("Nothing to change; for a {} layer give any of: {}".format(
            geometry.lower(), ", ".join(allowed)))
    wrong = [name for name in given if name not in allowed]
    if wrong:
        raise ValueError("{} not valid for {} ({} layer); use: {}".format(
            ", ".join(wrong), found.name(), geometry.lower(), ", ".join(allowed)))

    colors = {name: _parse_color(given[name], name)
              for name in ("fill_color", "outline_color", "color") if name in given}
    for name in ("outline_width", "width", "size"):
        if given.get(name, 0) < 0:
            raise ValueError("{} must not be negative".format(name))

    renderer = found.renderer()
    replaced = None
    if isinstance(renderer, QgsSingleSymbolRenderer):
        symbol = renderer.symbol().clone()
    else:
        replaced = renderer.type()
        symbol = QgsSymbol.defaultSymbol(found.geometryType())

    simple_types = {"Polygon": (QgsSimpleFillSymbolLayer, QgsFillSymbol),
                    "Line": (QgsSimpleLineSymbolLayer, QgsLineSymbol),
                    "Point": (QgsSimpleMarkerSymbolLayer, QgsMarkerSymbol)}
    layer_class, symbol_class = simple_types[geometry]
    notes = []
    if symbol.symbolLayerCount() != 1 or not isinstance(symbol.symbolLayer(0), layer_class):
        # SVG markers, marker lines, gradient fills etc. have none of these settings
        previous_color = symbol.color()
        symbol = symbol_class.createSimple({})
        symbol.setColor(previous_color)
        notes.append("the previous symbol was not a simple {} symbol and was replaced"
                     .format(geometry.lower()))
    symbol_layer = symbol.symbolLayer(0)

    if geometry == "Polygon":
        if "fill_color" in colors:
            symbol_layer.setFillColor(colors["fill_color"])
        if "fill_style" in given:
            symbol_layer.setBrushStyle(QgsSymbolLayerUtils.decodeBrushStyle(fill_style))
        if "outline_color" in colors:
            symbol_layer.setStrokeColor(colors["outline_color"])
        if "outline_width" in given:
            symbol_layer.setStrokeWidth(outline_width)
        if "outline_style" in given:
            symbol_layer.setStrokeStyle(QgsSymbolLayerUtils.decodePenStyle(outline_style))
    elif geometry == "Line":
        if "color" in colors:
            symbol_layer.setColor(colors["color"])
        if "width" in given:
            symbol_layer.setWidth(width)
        if "line_style" in given:
            symbol_layer.setPenStyle(QgsSymbolLayerUtils.decodePenStyle(line_style))
    else:
        if "color" in colors:
            symbol_layer.setColor(colors["color"])
        if "size" in given:
            symbol_layer.setSize(size)
        if "shape" in given:
            decoded, ok = QgsSimpleMarkerSymbolLayerBase.decodeShape(shape)
            if not ok:
                raise ValueError("Unknown shape {!r}".format(shape))
            symbol_layer.setShape(decoded)
        if "outline_color" in colors:
            symbol_layer.setStrokeColor(colors["outline_color"])
        if "outline_width" in given:
            symbol_layer.setStrokeWidth(outline_width)

    if replaced is None:
        renderer.setSymbol(symbol)
    else:
        found.setRenderer(QgsSingleSymbolRenderer(symbol))
        notes.append("the {} renderer was replaced by a single symbol".format(replaced))
    _refresh_layer(found)
    result = _result(found, given)
    if notes:
        result["notes"] = notes
    return result


def _set_symbol_opacity(renderer, opacity):
    """Set the opacity of every symbol of a vector renderer."""
    if isinstance(renderer, QgsSingleSymbolRenderer):
        renderer.symbol().setOpacity(opacity)
    elif isinstance(renderer, QgsCategorizedSymbolRenderer):
        for index, category in enumerate(renderer.categories()):
            symbol = category.symbol().clone()
            symbol.setOpacity(opacity)
            renderer.updateCategorySymbol(index, symbol)
    elif isinstance(renderer, QgsGraduatedSymbolRenderer):
        for index, class_range in enumerate(renderer.ranges()):
            symbol = class_range.symbol().clone()
            symbol.setOpacity(opacity)
            renderer.updateRangeSymbol(index, symbol)
    else:
        raise ValueError("symbol_opacity is not supported for {} renderers".format(
            renderer.type()))
    if renderer.sourceSymbol() is not None:
        renderer.sourceSymbol().setOpacity(opacity)


@mcp_server.tool()
def set_layer_opacity(layer: str, opacity: float = None, symbol_opacity: float = None) -> dict:
    """Set a layer's opacity from 0 (invisible) to 1 (opaque).

    opacity applies to the whole layer (vector or raster). symbol_opacity
    (vector only) applies to the symbols themselves, fill and outline
    together. For a see-through fill with a solid outline, give set_layer_style
    a fill_color with alpha, e.g. "#ff000080".
    """
    found = _find_layer(layer)
    if opacity is None and symbol_opacity is None:
        raise ValueError("Give opacity and/or symbol_opacity")
    applied = {}
    for name, value in (("opacity", opacity), ("symbol_opacity", symbol_opacity)):
        if value is not None:
            _check_opacity(value, name)
            applied[name] = value

    if found.type() == QgsMapLayer.RasterLayer:
        if symbol_opacity is not None:
            raise ValueError("symbol_opacity only applies to vector layers; use opacity")
        found.renderer().setOpacity(opacity)
    elif found.type() == QgsMapLayer.VectorLayer:
        if symbol_opacity is not None:
            _set_symbol_opacity(found.renderer(), symbol_opacity)
        if opacity is not None:
            found.setOpacity(opacity)
    else:
        raise ValueError("{} does not support opacity".format(found.name()))
    _refresh_layer(found)
    return _result(found, applied)


@mcp_server.tool()
def set_categorized_style(layer: str, field: str, color_ramp: str = "Spectral",
                          invert_ramp: bool = False, categories: list[dict] = None) -> dict:
    """Colour a vector layer by the values of a field, one colour per value.

    By default every unique value of field gets a colour from color_ramp (any
    QGIS ramp name, e.g. "Spectral", "Viridis", "Turbo"). To choose the classes
    yourself, give categories as [{"value": ..., "label": ..., "color": ...}];
    label and color are optional there.
    """
    found = _vector_layer(layer)
    index = _field(found, field)
    ramp = _color_ramp(color_ramp, invert_ramp)

    if categories is None:
        values = sorted(found.uniqueValues(index), key=lambda v: (v is None, str(v)))
        if len(values) > MAX_CATEGORIES:
            raise ValueError("{} has {} unique values in {}; use set_graduated_style or give "
                             "categories explicitly".format(found.name(), len(values), field))
        categories = [{"value": value} for value in values]
    for category in categories:
        unknown = set(category) - {"value", "label", "color"}
        if "value" not in category or unknown:
            raise ValueError("Each category needs a value and may have label and color; got "
                             "{}".format(category))
        if category.get("color") is not None:
            _parse_color(category["color"], "category color")

    renderer_categories = []
    for number, category in enumerate(categories):
        symbol = QgsSymbol.defaultSymbol(found.geometryType())
        if category.get("color") is not None:
            symbol.setColor(_parse_color(category["color"], "category color"))
        else:
            symbol.setColor(ramp.color(number / max(len(categories) - 1, 1)))
        value = category["value"]
        label = category.get("label")
        renderer_categories.append(QgsRendererCategory(
            value, symbol, str(label if label is not None else value)))

    found.setRenderer(QgsCategorizedSymbolRenderer(field, renderer_categories))
    _refresh_layer(found)
    return _result(found, {"field": field, "color_ramp": color_ramp,
                           "categories": len(renderer_categories)})


@mcp_server.tool()
def set_graduated_style(layer: str, field: str,
                        mode: Literal["quantile", "equal_interval", "jenks", "pretty",
                                      "stddev"] = "quantile",
                        classes: int = 5, color_ramp: str = "Reds",
                        invert_ramp: bool = False) -> dict:
    """Colour a vector layer by ranges of a numeric field.

    mode is how the class breaks are chosen: quantile (equal counts),
    equal_interval, jenks (natural breaks), pretty or stddev.
    color_ramp is any QGIS ramp name, e.g. "Reds", "Viridis", "RdYlGn".
    """
    found = _vector_layer(layer)
    index = _field(found, field)
    if not found.fields().at(index).isNumeric():
        raise ValueError("{} is not numeric; use set_categorized_style".format(field))
    if not 1 <= classes <= 100:
        raise ValueError("classes must be between 1 and 100")
    ramp = _color_ramp(color_ramp, invert_ramp)

    renderer = QgsGraduatedSymbolRenderer(field)
    renderer.setSourceSymbol(QgsSymbol.defaultSymbol(found.geometryType()))
    renderer.setSourceColorRamp(ramp)
    renderer.setClassificationMethod(_CLASSIFICATIONS[mode]())
    renderer.updateClasses(found, classes)
    if not renderer.ranges():
        raise ValueError("{} has no values to classify in {}".format(found.name(), field))

    found.setRenderer(renderer)
    _refresh_layer(found)
    return _result(found, {"field": field, "mode": mode, "color_ramp": color_ramp},
                   classes=[{"lower": r.lowerValue(), "upper": r.upperValue(),
                             "label": r.label()} for r in renderer.ranges()])


# ---------------------------------------------------------------------------
# Raster symbology


def _band_min_max(layer, band):
    stats = layer.dataProvider().bandStatistics(
        band, QgsRasterBandStats.Min | QgsRasterBandStats.Max)
    return stats.minimumValue, stats.maximumValue


def _contrast(layer, band, minimum, maximum):
    enhancement = QgsContrastEnhancement(layer.dataProvider().dataType(band))
    enhancement.setContrastEnhancementAlgorithm(QgsContrastEnhancement.StretchToMinimumMaximum)
    enhancement.setMinimumValue(minimum)
    enhancement.setMaximumValue(maximum)
    return enhancement


@mcp_server.tool()
def set_raster_style(layer: str,
                     mode: Literal["singleband_pseudocolor", "singleband_gray",
                                   "multiband"] = "singleband_pseudocolor",
                     band: int = 1, bands: list[int] = None,
                     min: float = None, max: float = None,
                     color_ramp: str = "Spectral", invert_ramp: bool = False) -> dict:
    """Style a raster layer.

    singleband_pseudocolor: colour band with color_ramp (e.g. "Spectral",
    "Viridis", "Greys") between min and max.
    singleband_gray: grey stretch of band between min and max.
    multiband: RGB composite of bands [red, green, blue] (default [1, 2, 3]).
    min and max default to the band's actual range.
    """
    found = _raster_layer(layer)
    provider = found.dataProvider()
    band_count = found.bandCount()
    if (min is None) != (max is None):
        raise ValueError("Give both min and max, or neither")
    if min is not None and min >= max:
        raise ValueError("min must be less than max")

    if mode == "multiband":
        bands = bands or [1, 2, 3]
        if len(bands) != 3:
            raise ValueError("multiband needs bands=[red, green, blue]")
        used = bands
    else:
        if bands is not None:
            raise ValueError("bands is only for multiband; use band for {}".format(mode))
        used = [band]
    for number in used:
        if not 1 <= number <= band_count:
            raise ValueError("{} has bands 1 to {}, not {}".format(
                found.name(), band_count, number))

    opacity = found.renderer().opacity() if found.renderer() else 1.0
    applied = {"mode": mode}
    if mode == "singleband_pseudocolor":
        ramp = _color_ramp(color_ramp, invert_ramp)
        minimum, maximum = (min, max) if min is not None else _band_min_max(found, band)
        renderer = QgsSingleBandPseudoColorRenderer(provider, band)
        renderer.setClassificationMin(minimum)
        renderer.setClassificationMax(maximum)
        renderer.createShader(ramp, QgsColorRampShader.Interpolated,
                              QgsColorRampShader.Continuous, 5)
        applied.update(band=band, min=minimum, max=maximum, color_ramp=color_ramp)
    elif mode == "singleband_gray":
        minimum, maximum = (min, max) if min is not None else _band_min_max(found, band)
        renderer = QgsSingleBandGrayRenderer(provider, band)
        renderer.setContrastEnhancement(_contrast(found, band, minimum, maximum))
        applied.update(band=band, min=minimum, max=maximum)
    else:
        renderer = QgsMultiBandColorRenderer(provider, *bands)
        setters = (renderer.setRedContrastEnhancement, renderer.setGreenContrastEnhancement,
                   renderer.setBlueContrastEnhancement)
        for setter, number in zip(setters, bands):
            minimum, maximum = (min, max) if min is not None else _band_min_max(found, number)
            setter(_contrast(found, number, minimum, maximum))
        applied.update(bands=bands)
        if min is not None:
            applied.update(min=min, max=max)

    renderer.setOpacity(opacity)
    found.setRenderer(renderer)
    _refresh_layer(found)
    return _result(found, applied)


# ---------------------------------------------------------------------------
# Labels


@mcp_server.tool()
def set_layer_labels(layer: str, enabled: bool = True, field: str = None,
                     expression: str = None, size: float = None, color: str = None,
                     buffer_color: str = None, buffer_size: float = None) -> dict:
    """Turn a vector layer's labels on or off and set how they look.

    Label text comes from field, or from a QGIS expression such as
    concat("name", ' - ', "type"). size is in points, buffer_size (a halo
    around the text) in mm, 0 turns the halo off. Settings not given keep
    their current values.
    """
    found = _vector_layer(layer)
    if field is not None and expression is not None:
        raise ValueError("Give field or expression, not both")
    if field is not None:
        _field(found, field)
    parsed = {name: _parse_color(value, name)
              for name, value in (("color", color), ("buffer_color", buffer_color))
              if value is not None}
    for name, value in (("size", size), ("buffer_size", buffer_size)):
        if value is not None and value < 0:
            raise ValueError("{} must not be negative".format(name))

    labeling = found.labeling()
    has_labels = isinstance(labeling, QgsVectorLayerSimpleLabeling)
    if enabled and not has_labels and field is None and expression is None:
        raise ValueError("{} has no labels yet; give field or expression".format(found.name()))

    applied = {"enabled": enabled}
    if has_labels or field is not None or expression is not None:
        settings = QgsPalLayerSettings(labeling.settings()) if has_labels \
            else QgsPalLayerSettings()
        if field is not None:
            settings.fieldName = field
            settings.isExpression = False
            applied["field"] = field
        if expression is not None:
            settings.fieldName = expression
            settings.isExpression = True
            applied["expression"] = expression

        text_format = QgsTextFormat(settings.format())
        if size is not None:
            text_format.setSize(size)
            applied["size"] = size
        if "color" in parsed:
            text_format.setColor(parsed["color"])
            applied["color"] = color
        if buffer_color is not None or buffer_size is not None:
            buffer = QgsTextBufferSettings(text_format.buffer())
            buffer.setEnabled(buffer_size != 0)
            if "buffer_color" in parsed:
                buffer.setColor(parsed["buffer_color"])
                applied["buffer_color"] = buffer_color
            if buffer_size is not None:
                buffer.setSize(buffer_size)
                applied["buffer_size"] = buffer_size
            text_format.setBuffer(buffer)
        settings.setFormat(text_format)
        found.setLabeling(QgsVectorLayerSimpleLabeling(settings))

    found.setLabelsEnabled(enabled)
    _refresh_layer(found)
    return _result(found, applied)


# ---------------------------------------------------------------------------
# Inspecting and reusing styles


def _vector_style(layer):
    renderer = layer.renderer()
    style = {"renderer": renderer.type(), "opacity": layer.opacity()}
    if isinstance(renderer, QgsSingleSymbolRenderer):
        symbol = renderer.symbol()
        style["symbol"] = _symbol_summary(symbol)
        style["symbol"]["properties"] = _jsonable(symbol.symbolLayer(0).properties())
    elif isinstance(renderer, QgsCategorizedSymbolRenderer):
        style["field"] = renderer.classAttribute()
        style["categories"] = [
            {"value": _jsonable(category.value()), "label": category.label(),
             "color": _color_string(category.symbol().color()),
             "visible": category.renderState()}
            for category in renderer.categories()]
    elif isinstance(renderer, QgsGraduatedSymbolRenderer):
        style["field"] = renderer.classAttribute()
        method = renderer.classificationMethod()
        style["mode"] = method.id() if method else None
        style["classes"] = [
            {"lower": r.lowerValue(), "upper": r.upperValue(), "label": r.label(),
             "color": _color_string(r.symbol().color())}
            for r in renderer.ranges()]

    labels = {"enabled": layer.labelsEnabled()}
    if isinstance(layer.labeling(), QgsVectorLayerSimpleLabeling):
        settings = layer.labeling().settings()
        text_format = settings.format()
        labels.update({
            "expression" if settings.isExpression else "field": settings.fieldName,
            "size": text_format.size(),
            "color": _color_string(text_format.color()),
            "buffer_size": text_format.buffer().size() if text_format.buffer().enabled()
            else 0,
        })
    style["labels"] = labels
    return style


def _raster_style(layer):
    renderer = layer.renderer()
    style = {"renderer": renderer.type(), "opacity": renderer.opacity(),
             "band_count": layer.bandCount()}
    if isinstance(renderer, QgsSingleBandPseudoColorRenderer):
        style.update(band=renderer.band(), min=renderer.classificationMin(),
                     max=renderer.classificationMax())
        shader = renderer.shader()
        if shader is not None and shader.rasterShaderFunction() is not None:
            items = shader.rasterShaderFunction().colorRampItemList()
            style["color_stops"] = [{"value": item.value, "color": _color_string(item.color)}
                                    for item in items[:20]]
    elif isinstance(renderer, QgsSingleBandGrayRenderer):
        enhancement = renderer.contrastEnhancement()
        style["band"] = renderer.grayBand()
        if enhancement is not None:
            style.update(min=enhancement.minimumValue(), max=enhancement.maximumValue())
    elif isinstance(renderer, QgsMultiBandColorRenderer):
        style["bands"] = [renderer.redBand(), renderer.greenBand(), renderer.blueBand()]
    return style


@mcp_server.tool()
def get_layer_style(layer: str) -> dict:
    """Describe a layer's current style: renderer type, opacity, symbol colours,
    categorized or graduated classes, labels, and raster bands and ranges.
    Use it before changing a style.
    """
    found = _find_layer(layer)
    if found.type() == QgsMapLayer.VectorLayer and found.isSpatial():
        style = _vector_style(found)
    elif found.type() == QgsMapLayer.RasterLayer:
        style = _raster_style(found)
    else:
        raise ValueError("{} has no style to describe".format(found.name()))
    node = QgsProject.instance().layerTreeRoot().findLayer(found.id())
    style["visible"] = node.isVisible() if node is not None else False
    return {"layer": found.name(), "layer_id": found.id(), "style": style}


def _style_format(path):
    extension = os.path.splitext(path)[1].lower()
    if extension not in (".qml", ".sld"):
        raise ValueError("Style files must end in .qml or .sld, got {!r}".format(path))
    return extension


@mcp_server.tool()
def save_layer_style(layer: str, path: str) -> dict:
    """Save a layer's style to a .qml (QGIS) or .sld (OGC) file for reuse."""
    found = _find_layer(layer)
    extension = _style_format(path)
    if extension == ".sld":
        if found.type() != QgsMapLayer.VectorLayer:
            raise ValueError("SLD export is only supported for vector layers; use .qml")
        message, ok = found.saveSldStyle(path)
    else:
        message, ok = found.saveNamedStyle(path)
    if not ok:
        raise RuntimeError("Could not save style to {}: {}".format(path, message))
    return _result(found, {"saved": path})


@mcp_server.tool()
def load_layer_style(layer: str, path: str) -> dict:
    """Apply a style from a .qml or .sld file to a layer."""
    found = _find_layer(layer)
    extension = _style_format(path)
    if not os.path.isfile(path):
        raise ValueError("Style file not found: {}".format(path))
    if extension == ".sld":
        message, ok = found.loadSldStyle(path)
    else:
        message, ok = found.loadNamedStyle(path)
    if not ok:
        raise RuntimeError("Could not load style from {}: {}".format(path, message))
    _refresh_layer(found)
    return _result(found, {"loaded": path})


# ---------------------------------------------------------------------------
# Layer tree and map view


@mcp_server.tool()
def set_layer_visibility(layer: str, visible: bool) -> dict:
    """Show or hide a layer in the layer tree (its checkbox)."""
    found = _find_layer(layer)
    node = QgsProject.instance().layerTreeRoot().findLayer(found.id())
    if node is None:
        raise ValueError("{} is not in the layer tree".format(found.name()))
    node.setItemVisibilityChecked(visible)
    return _result(found, {"visible": visible})


@mcp_server.tool()
def rename_layer(layer: str, new_name: str) -> dict:
    """Rename a layer."""
    found = _find_layer(layer)
    if not new_name.strip():
        raise ValueError("new_name must not be empty")
    old_name = found.name()
    found.setName(new_name)
    return _result(found, {"old_name": old_name, "new_name": new_name})


@mcp_server.tool()
def set_map_extent(xmin: float = None, ymin: float = None, xmax: float = None,
                   ymax: float = None, center_x: float = None, center_y: float = None,
                   scale: float = None, width_km: float = None,
                   crs: str = "EPSG:4326") -> dict:
    """Move the map canvas to a place.

    Either give a box (xmin, ymin, xmax, ymax), or a centre (center_x,
    center_y) with scale (e.g. 50000 for 1:50,000) or width_km. Coordinates
    are in crs, by default EPSG:4326 (x = longitude, y = latitude).
    """
    box = (xmin, ymin, xmax, ymax)
    has_box = any(v is not None for v in box)
    has_center = center_x is not None or center_y is not None
    if has_box == has_center:
        raise ValueError("Give either xmin, ymin, xmax, ymax or center_x, center_y")
    if has_box and (None in box or xmin >= xmax or ymin >= ymax):
        raise ValueError("A box needs all of xmin < xmax and ymin < ymax")
    if has_center:
        if center_x is None or center_y is None:
            raise ValueError("Give both center_x and center_y")
        if (scale is None) == (width_km is None):
            raise ValueError("With a centre, give exactly one of scale or width_km")
        if (scale or width_km) <= 0:
            raise ValueError("scale and width_km must be positive")
    elif scale is not None or width_km is not None:
        raise ValueError("scale and width_km only apply with center_x and center_y")

    source_crs = QgsCoordinateReferenceSystem(crs)
    if not source_crs.isValid():
        raise ValueError("Unknown crs {!r}".format(crs))
    canvas = _iface().mapCanvas()
    canvas_crs = canvas.mapSettings().destinationCrs()
    transform = QgsCoordinateTransform(source_crs, canvas_crs, QgsProject.instance())

    if has_box:
        canvas.setExtent(transform.transformBoundingBox(QgsRectangle(xmin, ymin, xmax, ymax)))
        applied = {"box": [xmin, ymin, xmax, ymax], "crs": crs}
    else:
        center = transform.transform(QgsPointXY(center_x, center_y))
        if scale is not None:
            canvas.setCenter(center)
            canvas.zoomScale(scale)
            applied = {"center": [center_x, center_y], "scale": scale, "crs": crs}
        else:
            # Build the box in a local metric CRS so width_km is right at any latitude
            wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
            lon_lat = QgsCoordinateTransform(source_crs, wgs84, QgsProject.instance()) \
                .transform(QgsPointXY(center_x, center_y))
            local = QgsCoordinateReferenceSystem.fromProj(
                "+proj=aeqd +lat_0={} +lon_0={} +units=m".format(lon_lat.y(), lon_lat.x()))
            size = canvas.mapSettings().outputSize()
            half_width = width_km * 500
            aspect = size.height() / size.width() if size.width() > 0 and size.height() > 0 \
                else 1
            half_height = half_width * aspect
            to_canvas = QgsCoordinateTransform(local, canvas_crs, QgsProject.instance())
            canvas.setExtent(to_canvas.transformBoundingBox(
                QgsRectangle(-half_width, -half_height, half_width, half_height)))
            applied = {"center": [center_x, center_y], "width_km": width_km, "crs": crs}

    canvas.refresh()
    extent = canvas.extent()
    return {"applied": applied, "canvas_crs": canvas_crs.authid(),
            "extent": [extent.xMinimum(), extent.yMinimum(),
                       extent.xMaximum(), extent.yMaximum()],
            "scale": round(canvas.scale())}
