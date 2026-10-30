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
    source_face = _triangle().faces[0]
    face = scene.loose_mesh.add_face(source_face.vertices)
    face.attrs["ifc"] = {"id": 7, "class": "IfcWall", "name": "Gevel"}

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



def test_group_world_faces_applies_nested_placements_and_preserves_holes():
    from PySide6.QtGui import QMatrix4x4, QVector3D
    from core.group import Group
    from plugins.nen6068_brandoverslag import group_world_faces

    mesh = _triangle()
    group = Group(mesh, "Facade")
    placement = QMatrix4x4()
    placement.translate(QVector3D(4.0, 2.0, 1.0))
    group.xform = placement

    faces = group_world_faces(group)
    assert len(faces) == 1
    assert [tuple(round(v, 3) for v in
                  (faces[0]["vertices"][0].x(),
                   faces[0]["vertices"][0].y(),
                   faces[0]["vertices"][0].z()))] == [(4.0, 2.0, 1.0)]
    assert faces[0]["normal"] is not None
    assert abs(faces[0]["area"] - 0.5) < 1e-6
    assert faces[0]["holes"] == []


def test_windowizer_world_outline_uses_composed_child_and_parent_pose():
    from PySide6.QtGui import QMatrix4x4, QVector3D
    from core.group import Group
    from plugins.nen6068_brandoverslag import windowizer_world_outline

    window = Group(name="Window-001")
    part = Group(name="Frame")
    child_pose = QMatrix4x4()
    child_pose.translate(QVector3D(2.0, 3.0, 4.0))
    part.xform = child_pose
    window.adopt([part])

    parent_move = QMatrix4x4()
    parent_move.translate(QVector3D(10.0, 0.0, 0.0))
    window.xform = parent_move

    data = {"outline": [
        [0.0, 0.0, 0.0], [1.2, 0.0, 0.0],
        [1.2, 0.0, 1.0], [0.0, 0.0, 1.0],
    ]}
    outline = windowizer_world_outline(window, data)
    assert outline is not None
    assert (outline[0] - QVector3D(12.0, 3.0, 4.0)).length() < 1e-6
    assert (outline[2] - QVector3D(13.2, 3.0, 5.0)).length() < 1e-6



def test_opening_dimensions_are_independent_of_world_orientation():
    from PySide6.QtGui import QMatrix4x4, QVector3D
    from plugins.nen6068_brandoverslag import _outline_dimensions

    local = [
        QVector3D(0.0, 0.0, 0.0), QVector3D(1.2, 0.0, 0.0),
        QVector3D(1.2, 0.0, 1.0), QVector3D(0.0, 0.0, 1.0),
    ]
    pose = QMatrix4x4()
    pose.rotate(90.0, QVector3D(0.0, 0.0, 1.0))
    pose.translate(QVector3D(2.0, 3.0, 0.0))
    world = [pose.map(point) for point in local]

    width, height = _outline_dimensions(world)
    assert abs(width - 1.2) < 1e-5
    assert abs(height - 1.0) < 1e-5
