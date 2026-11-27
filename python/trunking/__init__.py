"""Parametric cable-trunking elbow families for Revit.

Modules
-------
spec        catalogue data (nine sizes), the six family definitions
expr        parser/evaluator for the Revit formula subset
lin         exact affine arithmetic used by the dimension planner
geometry    silhouette, chain strips, frames, prism checks
model       build_model(kind, wall_variant) -> parameters + solids + connectors
evaluate    flex a model to a W x H and measure it
dimplan     which sketch edge is labelled with which parameter
verify      41 acceptance checks per family across eleven sizes
adapter     Revit interface contract (one method per Revit call)
builder     eight-step build pipeline
fake_revit  in-memory document so the pipeline runs without Revit
revit_api   the real API implementation (probe based, degrades safely)
report      Markdown reports
pncanvas    dependency-free raster/PNG output for the previews
"""

__version__ = "1.0.0"
