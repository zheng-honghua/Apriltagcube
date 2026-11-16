"""Export the flush-inlaid cube for CAD or two-material slicing."""

import json
import math
import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from xml.etree import ElementTree as XML
from zipfile import ZIP_DEFLATED, ZipFile

from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakePrism
from OCP.gp import gp_Pnt, gp_Vec
from OCP.IFSelect import IFSelect_ReturnStatus
from OCP.Interface import Interface_Static
from OCP.TopLoc import TopLoc_Location
from OCP.Quantity import Quantity_Color, Quantity_TypeOfColor
from OCP.STEPCAFControl import STEPCAFControl_Writer
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDocStd import TDocStd_Document
from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED, TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS, TopoDS_Compound
from OCP.XCAFDoc import XCAFDoc_ColorType, XCAFDoc_DocumentTool
from OCP.collections import List_TopoDS_Shape

DATA = json.loads(Path(__file__).with_name("families.json").read_text(encoding="utf-8"))


@contextmanager
def export_destination(path):
    # A temporary file on the same volume lets the final replace be atomic.
    fd, temporary = tempfile.mkstemp(prefix=".apriltag-", suffix=path.suffix, dir=path.parent)
    os.close(fd)
    try:
        yield temporary
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def solids(shape):
    explorer = TopExp_Explorer(shape, TopAbs_SOLID)
    while explorer.More():
        yield explorer.Current()
        explorer.Next()


def shape_list(shapes):
    result = List_TopoDS_Shape()
    for shape in shapes:
        result.Append(shape)
    return result


def boolean(operation, base, tools):
    operation.SetArguments(shape_list([base]))
    operation.SetTools(shape_list(tools))
    operation.Build()
    if not operation.IsDone() or operation.Shape().IsNull():
        raise RuntimeError("CAD 布尔运算失败。")
    operation.SimplifyResult()
    return operation.Shape()


def inlay(face, rows, width, size, cube, depth):
    pitch = size / width
    chamfer = pitch / 100
    normal, right, up = (face[key] for key in ("normal", "right", "up"))

    def black(x, y):
        return 0 <= x < width and 0 <= y < width and bool(rows[y] & (1 << x))

    def point(x, y):
        u, v = x * pitch - size / 2, size / 2 - y * pitch
        return gp_Pnt(*(n * cube / 2 + r * u + t * v for n, r, t in zip(normal, right, up)))

    direction = gp_Vec(*(-depth * axis for axis in normal))
    cells = []
    for y in range(width):
        for x in range(width):
            if not black(x, y):
                continue
            polygon = BRepBuilderAPI_MakePolygon()
            # Clip only point contacts between diagonal black cells so the white
            # body and black inserts have manifold edges.
            corners = (
                (0, 0, -1, -1, (0, 1), (1, 0)),
                (1, 0, 1, -1, (-1, 0), (0, 1)),
                (1, 1, 1, 1, (0, -1), (-1, 0)),
                (0, 1, -1, 1, (1, 0), (0, -1)),
            )
            for cx, cy, dx, dy, incoming, outgoing in corners:
                clipped = black(x + dx, y + dy) and not (black(x + dx, y) or black(x, y + dy))
                offsets = (incoming, outgoing) if clipped else ((0, 0),)
                for ox, oy in offsets:
                    polygon.Add(point(x + cx + ox * chamfer / pitch, y + cy + oy * chamfer / pitch))
            polygon.Close()
            surface = BRepBuilderAPI_MakeFace(polygon.Wire()).Face()
            cells.append(BRepPrimAPI_MakePrism(surface, direction).Shape())

    shape = boolean(BRepAlgoAPI_Fuse(), cells[0], cells[1:]) if len(cells) > 1 else cells[0]
    return list(solids(shape))


def build(settings):
    family = DATA["families"][settings["family"]]
    cube, size, depth = (float(settings[key]) for key in ("cube", "size", "depth"))
    ids = settings["ids"]
    if (
        not all(math.isfinite(value) for value in (cube, size, depth))
        or not 0.1 <= cube <= 100_000
        or not 0.1 <= size <= cube
        or depth < 0.001
        or len(ids) != len(DATA["faces"])
        or all(tag_id is None for tag_id in ids)
        or any(tag_id is not None and (type(tag_id) is not int or not 0 <= tag_id < len(family["patterns"])) for tag_id in ids)
    ):
        raise ValueError("模型尺寸或码 ID 无效。")

    width = family["width"]
    white_margin = size / width if settings["family"] == "tag36h11" else 0
    if depth + 0.001 > (cube - size) / 2 + white_margin:
        raise ValueError("嵌入深度过大，请减小码图或嵌入深度。")

    inserts = []
    for face, tag_id in zip(DATA["faces"], ids):
        if tag_id is None:
            continue
        rows = family["patterns"][tag_id]
        prefix = f'{face["key"]}_{settings["family"]}_{tag_id}'
        for index, shape in enumerate(inlay(face, rows, width, size, cube, depth), start=1):
            inserts.append((f"{prefix}_{index:02}", shape))

    blank = BRepPrimAPI_MakeBox(gp_Pnt(*([-cube / 2] * 3)), cube, cube, cube).Shape()
    base_solids = list(solids(boolean(BRepAlgoAPI_Cut(), blank, [shape for _, shape in inserts])))
    if len(base_solids) != 1 or not all(
        BRepCheck_Analyzer(shape).IsValid() for shape in [*base_solids, *(shape for _, shape in inserts)]
    ):
        raise RuntimeError("模型的实体检查失败。")
    return base_solids[0], inserts


def save(path, base, inserts):
    builder = BRep_Builder()
    assembly = TopoDS_Compound()
    builder.MakeCompound(assembly)
    parts = [("Cube_White", base, 0.98), *((name, shape, 0.025) for name, shape in inserts)]
    for _, shape, _ in parts:
        builder.Add(assembly, shape)

    doc = TDocStd_Document(TCollection_ExtendedString("BinXCAF"))
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    color_tool = XCAFDoc_DocumentTool.ColorTool_s(doc.Main())
    XCAFDoc_DocumentTool.SetLengthUnit_s(doc, 0.001)
    root = shape_tool.AddShape(assembly, True)
    TDataStd_Name.Set_s(root, TCollection_ExtendedString("AprilTag Cube"))
    for name, shape, shade in parts:
        label = shape_tool.FindShape(shape)
        if label.IsNull():
            raise RuntimeError("无法为 STEP 零件设置颜色。")
        TDataStd_Name.Set_s(label, TCollection_ExtendedString(name))
        color = Quantity_Color(shade, shade, shade, Quantity_TypeOfColor.Quantity_TOC_sRGB)
        color_tool.SetColor(label, color, XCAFDoc_ColorType.XCAFDoc_ColorGen)

    writer = STEPCAFControl_Writer()
    Interface_Static.SetCVal_s("write.step.schema", "AP242DIS")
    Interface_Static.SetCVal_s("write.step.unit", "MM")
    if not writer.Transfer(doc):
        raise RuntimeError("无法转换为 STEP。")

    with export_destination(path) as temporary:
        if writer.Write(temporary) != IFSelect_ReturnStatus.IFSelect_RetDone:
            raise RuntimeError("无法写入 STEP 文件。")


def triangulate(shapes):
    vertices, triangles = [], []
    for shape in shapes:
        mesher = BRepMesh_IncrementalMesh(shape, 0.001)
        if not mesher.IsDone():
            raise RuntimeError("无法为打印生成网格。")
        # Weld face seams within each solid. The separate solids stay independent.
        indices = {}
        faces = TopExp_Explorer(shape, TopAbs_FACE)
        while faces.More():
            face = TopoDS.Face(faces.Current())
            location = TopLoc_Location()
            mesh = BRep_Tool.Triangulation_s(face, location)
            if mesh is None or mesh.NbTriangles() == 0:
                raise RuntimeError("打印网格存在缺失的面。")
            transform = location.Transformation()
            node_ids = [None]
            for i in range(1, mesh.NbNodes() + 1):
                point = mesh.Node(i).Transformed(transform)
                xyz = tuple(round(value, 8) for value in (point.X(), point.Y(), point.Z()))
                if xyz not in indices:
                    indices[xyz] = len(vertices)
                    vertices.append(xyz)
                node_ids.append(indices[xyz])
            for i in range(1, mesh.NbTriangles() + 1):
                a, b, c = mesh.Triangle(i).Get()
                if face.Orientation() == TopAbs_REVERSED:
                    b, c = c, b
                triangle = (node_ids[a], node_ids[b], node_ids[c])
                if len(set(triangle)) != 3:
                    raise RuntimeError("打印网格存在退化的三角形。")
                triangles.append(triangle)
            faces.Next()
    return vertices, triangles


def save_3mf(path, base, inserts, cube):
    core = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
    materials = "http://schemas.microsoft.com/3dmanufacturing/material/2015/02"
    model = XML.Element("model", {
        "xmlns": core, "xmlns:m": materials, "unit": "millimeter", "requiredextensions": "m",
    })
    XML.SubElement(model, "metadata", name="Application").text = "AprilTag Cube"
    resources = XML.SubElement(model, "resources")
    colors = XML.SubElement(resources, "m:colorgroup", id="4")
    XML.SubElement(colors, "m:color", color="#FFFFFF")
    XML.SubElement(colors, "m:color", color="#111111")

    config = XML.Element("config")
    object_config = XML.SubElement(config, "object", id="3")
    XML.SubElement(object_config, "metadata", key="name", value="AprilTag 方块")
    XML.SubElement(object_config, "metadata", key="extruder", value="1")
    parts = [
        ("白色方块", [base]),
        ("黑色 AprilTag", [shape for _, shape in inserts]),
    ]
    for filament, (name, shapes) in enumerate(parts, start=1):
        part_id = str(filament)
        part = XML.SubElement(resources, "object", id=part_id, name=name, type="model",
                              pid="4", pindex=str(filament - 1))
        mesh = XML.SubElement(part, "mesh")
        vertex_list = XML.SubElement(mesh, "vertices")
        triangle_list = XML.SubElement(mesh, "triangles")
        vertices, triangles = triangulate(shapes)
        for x, y, z in vertices:
            XML.SubElement(vertex_list, "vertex", x=str(x), y=str(y), z=str(z))
        for a, b, c in triangles:
            XML.SubElement(triangle_list, "triangle", v1=str(a), v2=str(b), v3=str(c))
        part_config = XML.SubElement(object_config, "part", id=part_id, subtype="normal_part")
        XML.SubElement(part_config, "metadata", key="name", value=name)
        XML.SubElement(part_config, "metadata", key="extruder", value=part_id)

    root = XML.SubElement(resources, "object", id="3", type="model", name="AprilTag 方块")
    components = XML.SubElement(root, "components")
    XML.SubElement(components, "component", objectid="1")
    XML.SubElement(components, "component", objectid="2")
    placement = XML.SubElement(model, "build")
    XML.SubElement(placement, "item", objectid="3", transform=f"1 0 0 0 1 0 0 0 1 0 0 {cube / 2}")

    content_types = XML.Element("Types", xmlns="http://schemas.openxmlformats.org/package/2006/content-types")
    XML.SubElement(content_types, "Default", Extension="rels",
                   ContentType="application/vnd.openxmlformats-package.relationships+xml")
    XML.SubElement(content_types, "Default", Extension="model",
                   ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml")
    XML.SubElement(content_types, "Default", Extension="config", ContentType="application/xml")
    relationships = XML.Element("Relationships", xmlns="http://schemas.openxmlformats.org/package/2006/relationships")
    XML.SubElement(relationships, "Relationship", Target="/3D/3dmodel.model", Id="rel-1",
                   Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel")
    with export_destination(path) as temporary:
        with ZipFile(temporary, "w", ZIP_DEFLATED) as archive:
            for filename, xml in (
                ("[Content_Types].xml", content_types),
                ("_rels/.rels", relationships),
                ("3D/3dmodel.model", model),
                ("Metadata/model_settings.config", config),
            ):
                archive.writestr(filename, XML.tostring(xml, encoding="utf-8", xml_declaration=True))


def export_model(settings, path):
    base, inserts = build(settings)
    if path.suffix.lower() == ".3mf":
        save_3mf(path, base, inserts, float(settings["cube"]))
    else:
        save(path, base, inserts)


if __name__ == "__main__":
    try:
        export_model(json.load(sys.stdin), Path(sys.argv[1]))
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as error:
        print(error, file=sys.stderr)
        sys.exit(1)
