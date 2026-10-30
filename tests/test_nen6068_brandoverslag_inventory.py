# SPDX-License-Identifier: GPL-3.0-or-later
"""Read-only scene inventory used by the NEN 6068 extension."""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from core.group import Group
from core.mesh import Mesh
from core.scene import Scene
from plugins.nen6068_brandoverslag import inspect_scene


def _triangle():
    mesh = Mesh()
    mesh.add_face([
        QVector3D(0, 0, 0),
        QVector3D(1, 0, 0),
        QVector3D(0, 0, 1),
    ])
    return mesh


def test_inventory_finds_nested_bim_groups_and_windowizer_metadata():
    scene = Scene()
    building = Group(_triangle(), "Building")
    building.ifc = {"class": "IfcBuilding", "name": "Building"}

    window = Group(name="Window-001")
    window.ifc = {"class": "IfcWindow", "name": "Window-001"}
    window.ext = {
        "windowizer": {
            "outline": [
                [0.0, 0.0, 0.0],
                [1.2, 0.0, 0.0],
                [1.2, 0.0, 1.0],
                [0.0, 0.0, 1.0],
            ],
            "pose": [],
        }
    }
    window.adopt([Group(_triangle(), "Frame")])
    building.adopt([window])
    scene.groups.append(building)

    result = inspect_scene(scene)
    by_name = {row["name"]: row for row in result["rows"]}

    assert by_name["Building"]["ifc"] == "IfcBuilding"
    assert by_name["Building"]["faces"] == 2
    assert by_name["Window-001"]["ifc"] == "IfcWindow"
    assert by_name["Window-001"]["note"] == "Windowizer-contour: 1.200 × 1.000 m"
    assert result["tagged_groups"] == 2
    assert result["windowizer_count"] == 1


def test_inventory_reports_loose_bim_faces_without_mutating_scene():
    scene = Scene()
    face = _triangle().faces[0]
    face.attrs["ifc"] = {"id": 7, "class": "IfcWall", "name": "Gevel"}
    scene.loose_mesh.add_face(face.vertices)

    before = scene.version
    result = inspect_scene(scene)

    assert result["loose_objects"] == 1
    row = next(row for row in result["rows"] if row["kind"] == "Losse vlakken")
    assert row["name"] == "Gevel"
    assert row["ifc"] == "IfcWall"
    assert row["faces"] == 1
    assert scene.version == before


def test_outline_size_rejects_invalid_or_degenerate_records():
    from plugins.nen6068_brandoverslag import _outline_size

    assert _outline_size([[0, 0, 0], [1, 0, 0]]) is None
    assert _outline_size([["bad", 0, 0], [1, 0, 1], [0, 0, 1]]) is None
