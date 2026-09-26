# -*- coding: utf-8 -*-
"""
MCP tools exposed by QMCP.

Processing algorithms are not registered one tool per algorithm: several
hundred tool definitions with full help text overflow the client's context.
Instead the model finds algorithms with search_algorithms, reads their
parameters with get_algorithm_help and runs them with run_algorithm. All three
read the live processing registry, so every installed provider (native, GDAL,
GRASS, SAGA, plugins such as SCP) is covered.

Every tool runs on the QGIS main thread (see mcp_runtime.MainThreadFastMCP).
"""

import contextlib
import io
import os
import traceback

from mcp.server.fastmcp import Image
from qgis.core import (Qgis, QgsApplication, QgsCoordinateReferenceSystem, QgsMapLayer,
                       QgsMapRendererParallelJob, QgsProcessingFeedback,
                       QgsProcessingParameterDefinition, QgsProject, QgsRasterLayer,
                       QgsVectorLayer, QgsWkbTypes)
from qgis.PyQt.QtCore import QBuffer, QByteArray, QIODevice, QSize

from .mcp_runtime import MainThreadFastMCP

# Stateless JSON responses: clients (and mcp_bridge.py) keep working across
# server restarts because there is no session to lose
mcp_server = MainThreadFastMCP("QGIS MCP Server", log_level="WARNING",
                               stateless_http=True, json_response=True)

# Longest help text returned by get_algorithm_help, to keep responses small
MAX_HELP_CHARS = 3000


def _iface():
    # Looked up at call time: qgis.utils.iface is set by QGIS, not by this module
    from qgis.utils import iface
    return iface


def _jsonable(value):
    """Convert QGIS/Qt values into something JSON can carry."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, QgsMapLayer):
        return {"layer_id": value.id(), "name": value.name(), "source": value.source()}
    if hasattr(value, "isNull") and value.isNull():
        return None
    if hasattr(value, "toString"):
        return value.toString()
    return str(value)


def _layer_type(layer):
    if layer.type() == QgsMapLayer.VectorLayer:
        return "vector"
    if layer.type() == QgsMapLayer.RasterLayer:
        return "raster"
    return str(layer.type())


def _layer_info(layer):
    project = QgsProject.instance()
    node = project.layerTreeRoot().findLayer(layer.id())
    info = {
        "id": layer.id(),
        "name": layer.name(),
        "type": _layer_type(layer),
        "crs": layer.crs().authid(),
        "source": layer.source(),
        # Layers can be in the project without being in the layer tree
        "visible": node.isVisible() if node is not None else False,
    }
    if layer.type() == QgsMapLayer.VectorLayer:
        info.update({
            "geometry_type": QgsWkbTypes.geometryDisplayString(layer.geometryType()),
            "feature_count": layer.featureCount(),
            "fields": [field.name() for field in layer.fields()],
        })
    elif layer.type() == QgsMapLayer.RasterLayer:
        info.update({
            "width": layer.width(),
            "height": layer.height(),
            "band_count": layer.bandCount(),
        })
    return info


def _find_layer(layer):
    """Find a layer by ID, falling back to its name."""
    project = QgsProject.instance()
    found = project.mapLayer(layer)
    if found is not None:
        return found
    matches = project.mapLayersByName(layer)
    if not matches:
        raise ValueError("Layer not found: {}. Use get_layers to list layer IDs.".format(layer))
    if len(matches) > 1:
        raise ValueError("{} layers are named {!r}; use one of their IDs instead: {}".format(
            len(matches), layer, ", ".join(match.id() for match in matches)))
    return matches[0]


def _refresh_layer(layer):
    """Redraw a restyled layer and its legend entry."""
    layer.triggerRepaint()
    iface = _iface()
    if iface is not None and iface.layerTreeView() is not None:
        iface.layerTreeView().refreshLayerSymbology(layer.id())


def _algorithm_description(alg):
    """Short description, falling back to the start of the help (most algorithms lack one)."""
    text = alg.shortDescription() or alg.shortHelpString() or ""
    text = " ".join(text.split())
    return text if len(text) <= 160 else text[:157] + "..."


def _algorithm(algorithm_id):
    alg = QgsApplication.processingRegistry().algorithmById(algorithm_id)
    if alg is None:
        raise ValueError("Unknown algorithm: {}. Use search_algorithms to find "
                         "algorithm IDs.".format(algorithm_id))
    return alg


# ---------------------------------------------------------------------------
# General


@mcp_server.tool()
def ping() -> str:
    """Check that QGIS is reachable."""
    return "pong"


@mcp_server.tool()
def get_qgis_info() -> dict:
    """Get the QGIS version and the installed processing providers."""
    return {
        "qgis_version": Qgis.QGIS_VERSION,
        "providers": [
            {"id": provider.id(), "name": provider.name(),
             "algorithm_count": len(provider.algorithms())}
            for provider in QgsApplication.processingRegistry().providers()
        ],
    }


# ---------------------------------------------------------------------------
# Project


@mcp_server.tool()
def get_project_info() -> dict:
    """Get the current project's file, title, CRS and layers."""
    project = QgsProject.instance()
    layers = list(project.mapLayers().values())
    return {
        "filename": project.fileName(),
        "title": project.title(),
        "crs": project.crs().authid(),
        "layer_count": len(layers),
        # Keep the response small; get_layers has the full list
        "layers": [{"id": layer.id(), "name": layer.name(), "type": _layer_type(layer)}
                   for layer in layers[:20]],
    }


@mcp_server.tool()
def load_project(path: str) -> dict:
    """Open a QGIS project file (.qgz or .qgs)."""
    project = QgsProject.instance()
    if not project.read(path):
        raise RuntimeError("Failed to load project from {}".format(path))
    _iface().mapCanvas().refresh()
    return {"loaded": path, "layer_count": len(project.mapLayers())}


@mcp_server.tool()
def create_new_project(path: str, crs: str = None) -> dict:
    """Clear the current project and save an empty one at path (e.g. /data/project.qgz).

    crs is optional, e.g. "EPSG:4326".
    """
    project = QgsProject.instance()
    project.clear()
    if crs:
        project.setCrs(QgsCoordinateReferenceSystem(crs))
    if not project.write(path):
        raise RuntimeError("Failed to save project to {}".format(path))
    _iface().mapCanvas().refresh()
    return {"created": path, "crs": project.crs().authid()}


@mcp_server.tool()
def save_project(path: str = None) -> dict:
    """Save the current project, to path if given, otherwise to its current file."""
    project = QgsProject.instance()
    save_path = path or project.fileName()
    if not save_path:
        raise ValueError("The project has never been saved; give a path")
    if not project.write(save_path):
        raise RuntimeError("Failed to save project to {}".format(save_path))
    return {"saved": save_path}


# ---------------------------------------------------------------------------
# Layers


@mcp_server.tool()
def get_layers() -> list:
    """List the project's layers with their IDs, types, CRS, fields and sizes."""
    return [_layer_info(layer) for layer in QgsProject.instance().mapLayers().values()]


@mcp_server.tool()
def add_vector_layer(path: str, name: str = None, provider: str = "ogr") -> dict:
    """Add a vector layer (shapefile, GeoPackage, GeoJSON, ...) to the project."""
    layer = QgsVectorLayer(path, name or os.path.basename(path), provider)
    if not layer.isValid():
        raise ValueError("Layer is not valid: {}".format(path))
    QgsProject.instance().addMapLayer(layer)
    return _layer_info(layer)


@mcp_server.tool()
def add_raster_layer(path: str, name: str = None, provider: str = "gdal") -> dict:
    """Add a raster layer (GeoTIFF, ...) to the project."""
    layer = QgsRasterLayer(path, name or os.path.basename(path), provider)
    if not layer.isValid():
        raise ValueError("Layer is not valid: {}".format(path))
    QgsProject.instance().addMapLayer(layer)
    return _layer_info(layer)


@mcp_server.tool()
def remove_layer(layer: str) -> dict:
    """Remove a layer from the project, given its ID or name."""
    found = _find_layer(layer)
    layer_id = found.id()
    QgsProject.instance().removeMapLayer(layer_id)
    return {"removed": layer_id}


@mcp_server.tool()
def zoom_to_layer(layer: str) -> dict:
    """Zoom the map canvas to a layer's extent, given its ID or name."""
    found = _find_layer(layer)
    iface = _iface()
    iface.setActiveLayer(found)
    iface.zoomToActiveLayer()
    return {"zoomed_to": found.id()}


@mcp_server.tool()
def get_layer_features(layer: str, limit: int = 10) -> dict:
    """Get attributes and WKT geometries of the first features of a vector layer."""
    found = _find_layer(layer)
    if found.type() != QgsMapLayer.VectorLayer:
        raise ValueError("Layer is not a vector layer: {}".format(layer))

    field_names = [field.name() for field in found.fields()]
    features = []
    for feature in found.getFeatures():
        if len(features) >= limit:
            break
        geometry = feature.geometry().asWkt(precision=4) if feature.hasGeometry() else None
        features.append({
            "id": feature.id(),
            "attributes": {name: _jsonable(feature[name]) for name in field_names},
            "geometry": geometry,
        })
    return {
        "layer_id": found.id(),
        "feature_count": found.featureCount(),
        "fields": field_names,
        "features": features,
    }


# ---------------------------------------------------------------------------
# Processing


@mcp_server.tool()
def search_algorithms(query: str, provider: str = None, limit: int = 20) -> list:
    """Search the processing toolbox (native, GDAL, GRASS, SAGA and plugin providers).

    Every word of query must appear in the algorithm's ID, name, tags or
    description, e.g. "buffer", "clip raster", "zonal statistics".
    provider optionally restricts results, e.g. "native", "gdal", "grass7".
    Use get_algorithm_help on a result before running it.
    """
    words = query.lower().split()
    results = []
    for alg in QgsApplication.processingRegistry().algorithms():
        if provider and alg.provider() is not None and alg.provider().id() != provider:
            continue
        name = alg.displayName().lower()
        description = _algorithm_description(alg)
        text = " ".join([alg.id(), name, " ".join(alg.tags()), description]).lower()
        if not all(word in text for word in words):
            continue
        # Rank matches in the name first, then native algorithms
        score = sum(word in name for word in words) * 2 + (alg.id().startswith("native:"))
        results.append((score, {
            "id": alg.id(),
            "name": alg.displayName(),
            "group": alg.group(),
            "description": description,
        }))
    results.sort(key=lambda item: -item[0])
    return [item for _, item in results[:limit]]


@mcp_server.tool()
def get_algorithm_help(algorithm_id: str) -> dict:
    """Get an algorithm's parameters (names, types, defaults, enum options) and outputs.

    Layer parameters accept a layer ID, layer name or file path. Output
    parameters accept a file path or "TEMPORARY_OUTPUT".
    """
    alg = _algorithm(algorithm_id)
    parameters = []
    for definition in alg.parameterDefinitions():
        flags = definition.flags()
        info = {
            "name": definition.name(),
            "description": definition.description(),
            "type": definition.type(),
            "optional": bool(flags & QgsProcessingParameterDefinition.FlagOptional),
            "default": _jsonable(definition.defaultValue()),
        }
        if flags & QgsProcessingParameterDefinition.FlagAdvanced:
            info["advanced"] = True
        if definition.type() == "enum":
            info["options"] = {i: option for i, option in enumerate(definition.options())}
            if definition.allowMultiple():
                info["allow_multiple"] = True
        if definition.isDestination():
            info["destination"] = True
        parameters.append(info)

    help_text = alg.shortHelpString() or ""
    if len(help_text) > MAX_HELP_CHARS:
        help_text = help_text[:MAX_HELP_CHARS] + "..."
    return {
        "id": alg.id(),
        "name": alg.displayName(),
        "description": alg.shortDescription(),
        "help": help_text,
        "parameters": parameters,
        "outputs": [{"name": output.name(), "description": output.description(),
                     "type": output.type()} for output in alg.outputDefinitions()],
    }


class _CollectingFeedback(QgsProcessingFeedback):
    """Keeps the algorithm's log so errors can be returned to the model."""

    def __init__(self):
        super().__init__()
        self.messages = []

    def reportError(self, error, fatalError=False):
        self.messages.append("ERROR: " + error)
        super().reportError(error, fatalError)

    def pushWarning(self, warning):
        self.messages.append("WARNING: " + warning)
        super().pushWarning(warning)

    def pushInfo(self, info):
        self.messages.append(info)
        super().pushInfo(info)


@mcp_server.tool()
def run_algorithm(algorithm_id: str, parameters: dict, load_outputs: bool = True) -> dict:
    """Run a processing algorithm, e.g. run_algorithm("native:buffer",
    {"INPUT": "roads", "DISTANCE": 10, "OUTPUT": "TEMPORARY_OUTPUT"}).

    Call get_algorithm_help first for the parameter names. Output layers are
    added to the project so later calls can use them by ID; with
    load_outputs=False, TEMPORARY_OUTPUT layers are discarded after the run,
    so only file outputs remain.
    """
    import processing

    _algorithm(algorithm_id)
    feedback = _CollectingFeedback()
    try:
        if load_outputs:
            result = processing.runAndLoadResults(algorithm_id, parameters, feedback=feedback)
        else:
            result = processing.run(algorithm_id, parameters, feedback=feedback)
    except Exception as e:
        # The log usually says which parameter was wrong
        log = [m for m in feedback.messages[-20:] if str(e) not in m]
        raise RuntimeError("\n".join(["{} failed: {}".format(algorithm_id, e)] + log))
    return {"algorithm": algorithm_id, "result": _jsonable(result)}


# ---------------------------------------------------------------------------
# Map and scripting


@mcp_server.tool()
def render_map(path: str = None, width: int = 800, height: int = 600):
    """Render the current map canvas (visible layers, current extent and styles).

    Without path the image is returned so you can look at the map; with path
    it is saved to that file (PNG, JPG, ...) instead.
    """
    settings = _iface().mapCanvas().mapSettings()
    settings.setOutputSize(QSize(width, height))
    job = QgsMapRendererParallelJob(settings)
    job.start()
    job.waitForFinished()
    image = job.renderedImage()

    if path:
        if not image.save(path):
            raise RuntimeError("Failed to save rendered image to {}".format(path))
        return {"rendered": path, "width": width, "height": height}

    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return Image(data=bytes(data), format="png")


@mcp_server.tool()
def execute_code(code: str) -> dict:
    """Run PyQGIS code inside QGIS.

    iface, QgsProject, processing and everything in qgis.core are available.
    Anything printed is returned, as is the value of a variable named result.
    """
    import processing
    import qgis.core

    namespace = {name: getattr(qgis.core, name) for name in dir(qgis.core)
                 if not name.startswith("_")}
    namespace.update({"iface": _iface(), "processing": processing})
    stdout = io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout):
            exec(code, namespace)
    except Exception:
        return {"success": False, "stdout": stdout.getvalue(), "error": traceback.format_exc()}
    return {"success": True, "stdout": stdout.getvalue(),
            "result": _jsonable(namespace.get("result"))}


# Registers the styling and map view tools on mcp_server
from . import style_tools  # noqa: E402,F401
