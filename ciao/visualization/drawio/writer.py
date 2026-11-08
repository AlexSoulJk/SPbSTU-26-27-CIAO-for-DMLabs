"""Сериализация рассчитанной диаграммы в нативный XML draw.io."""

from __future__ import annotations

from xml.etree import ElementTree as ET

from .diagram_model import DiagramPage, EdgeCell, NodeCell


def _write_node(root: ET.Element, node: NodeCell) -> None:
    attributes = {
        "id": node.id,
        "value": node.label,
        "style": node.style,
        "vertex": "1",
        "parent": "1",
        "ciaoElement": node.kind,
    }
    attributes.update(dict(node.metadata))
    cell = ET.SubElement(root, "mxCell", attributes)
    ET.SubElement(
        cell,
        "mxGeometry",
        {
            "x": str(node.geometry.x),
            "y": str(node.geometry.y),
            "width": str(node.geometry.width),
            "height": str(node.geometry.height),
            "as": "geometry",
        },
    )


def _write_edge(root: ET.Element, edge: EdgeCell) -> None:
    attributes = {
        "id": edge.id,
        "value": edge.label,
        "style": edge.style,
        "edge": "1",
        "parent": "1",
        "source": edge.source_id,
        "target": edge.target_id,
        "ciaoElement": edge.kind,
    }
    attributes.update(dict(edge.metadata))
    cell = ET.SubElement(root, "mxCell", attributes)
    geometry_attributes = {"relative": "1", "as": "geometry"}
    if edge.label_x is not None:
        geometry_attributes["x"] = str(edge.label_x)
    if edge.label_y is not None:
        geometry_attributes["y"] = str(edge.label_y)
    geometry = ET.SubElement(cell, "mxGeometry", geometry_attributes)
    if edge.label_x is not None or edge.label_y is not None:
        ET.SubElement(geometry, "mxPoint", {"as": "offset"})
    if edge.points:
        points = ET.SubElement(geometry, "Array", {"as": "points"})
        for point in edge.points:
            ET.SubElement(points, "mxPoint", {"x": str(point.x), "y": str(point.y)})


def serialize_drawio(page: DiagramPage) -> bytes:
    """Создаёт детерминированный XML без файловых операций."""

    mxfile = ET.Element(
        "mxfile",
        {
            "host": "app.diagrams.net",
            "agent": "spbstu-ciao",
            "version": "1",
        },
    )
    diagram = ET.SubElement(mxfile, "diagram", {"id": "ciao-page", "name": "CIAO Program"})
    model = ET.SubElement(
        diagram,
        "mxGraphModel",
        {
            "dx": str(page.width),
            "dy": str(page.height),
            "grid": "1",
            "gridSize": "10",
            "page": "1",
            "pageScale": "1",
            "pageWidth": str(page.width),
            "pageHeight": str(page.height),
            "math": "0",
            "shadow": "0",
        },
    )
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", {"id": "0"})
    ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})

    for node in page.nodes:
        _write_node(root, node)
    for edge in page.edges:
        _write_edge(root, edge)

    ET.indent(mxfile, space="  ")
    return ET.tostring(mxfile, encoding="utf-8", xml_declaration=True)


__all__ = ["serialize_drawio"]
